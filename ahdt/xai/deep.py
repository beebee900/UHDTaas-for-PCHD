"""Explainers for waveform networks (design 04, 4.6.1, signal and image deep learning).

Integrated Gradients, occlusion and TCAV come from Captum. Grad-CAM comes from
pytorch-grad-cam, driven through a wrapper that presents the 1-D convolution as a
height-1 image. Attributions are summed into time segments so a clinician sees where in
the strip the evidence lies.
"""

from __future__ import annotations

import tempfile
import warnings
from collections.abc import Mapping, Sequence
from importlib.metadata import version

import numpy as np
import torch
from torch import nn

from ahdt.xai.subjects import SignalSubject
from ahdt.xai.types import Array, Result, driver
from atra import contracts as c

SEGMENTS = 20
IG_STEPS = 24


class _Target(nn.Module):
    """The probability of one class from a network that takes `[N, L]`."""

    def __init__(self, net: nn.Module, target: int) -> None:
        super().__init__()
        self.net, self.target = net, target

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.net(x)[:, self.target]


def _segments(a: Array, n: int) -> list[tuple[int, int]]:
    edges = np.linspace(0, len(a), n + 1).astype(int)
    return [(int(edges[i]), int(edges[i + 1])) for i in range(n)]


def _segment_drivers(s: SignalSubject, attribution: Array, n: int = SEGMENTS
                     ) -> list[c.Driver]:
    out = []
    for a, b in _segments(attribution, n):
        out.append(driver(f"{a / s.fs:.1f}-{b / s.fs:.1f} s", float(s.x[a:b].mean()),
                          float(attribution[a:b].sum())))
    return out


def integrated_gradients(s: SignalSubject, steps: int = IG_STEPS) -> Result:
    """Integrated Gradients (Sundararajan et al. 2017) from an all-zero strip."""
    from captum.attr import IntegratedGradients

    model = _Target(s.net, s.target).eval()
    x = torch.as_tensor(s.x[None, :], dtype=torch.float32, device="cpu")
    ig = IntegratedGradients(model)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        attr, delta = ig.attribute(x, baselines=torch.zeros_like(x), n_steps=steps,
                                   internal_batch_size=steps, return_convergence_delta=True)
    a = np.asarray(attr[0].detach().numpy(), dtype=float)
    return Result(f"captum.ig@{version('captum')}", "saliency", _segment_drivers(s, a),
                  output=s.output, base=float(s.proba(np.zeros((1, len(s.x))))[0, s.target]),
                  detail={"saliency": a.tolist(), "class": s.classes[s.target],
                          "convergence_delta": float(delta.abs().max()), "steps": steps})


def occlusion(s: SignalSubject, window: int | None = None) -> Result:
    """Fall of the class probability when a window of the strip is set to zero."""
    from captum.attr import Occlusion

    w = window or max(1, len(s.x) // SEGMENTS)
    model = _Target(s.net, s.target).eval()
    x = torch.as_tensor(s.x[None, :], dtype=torch.float32)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        attr = Occlusion(model).attribute(x, sliding_window_shapes=(w,), strides=(w,),
                                          baselines=0.0)
    a = np.asarray(attr[0].detach().numpy(), dtype=float)
    return Result(f"captum.occlusion@{version('captum')}", "saliency", _segment_drivers(s, a),
                  output=s.output, detail={"saliency": a.tolist(), "window": w,
                                           "class": s.classes[s.target]})


class _Image(nn.Module):
    """Logits of a `[N, 1, 1, L]` height-1 image, for pytorch-grad-cam."""

    def __init__(self, net: nn.Module) -> None:
        super().__init__()
        self.net = net

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.net(x[:, 0, 0, :])


def _last_conv(net: nn.Module) -> nn.Module:
    """The last convolution block before global pooling."""
    members = list(getattr(net, "members", []))
    holder = members[0] if members else getattr(net, "m", None) or getattr(net, "beat", net)
    return holder.conv[-2]


def grad_cam(s: SignalSubject) -> Result:
    """Grad-CAM (Selvaraju et al. 2017) on the last convolution block."""
    from pytorch_grad_cam import GradCAM
    from pytorch_grad_cam.utils.model_targets import ClassifierOutputTarget

    layer = _last_conv(s.net)
    wrapped = _Image(s.net).eval()

    def to_image(a: torch.Tensor) -> torch.Tensor:
        return a[:, :, None, :]

    x = torch.as_tensor(s.x[None, None, None, :], dtype=torch.float32)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        with GradCAM(model=wrapped, target_layers=[layer], reshape_transform=to_image) as cam:
            heat = cam(input_tensor=x, targets=[ClassifierOutputTarget(s.target)])
    a = np.asarray(heat[0], dtype=float).reshape(-1)
    if len(a) != len(s.x):
        a = np.interp(np.linspace(0, len(a) - 1, len(s.x)), np.arange(len(a)), a)
    return Result(f"gradcam.1d@{version('grad-cam')}", "saliency", _segment_drivers(s, a),
                  output=s.output, detail={"saliency": a.tolist(), "class": s.classes[s.target],
                                           "layer": "last convolution block"})


def tcav(s: SignalSubject, concepts: Mapping[str, Array], random: Sequence[Array],
         layer: str = "conv.5") -> Result:
    """TCAV scores (Kim et al. 2018): the share of examples of the class whose logit rises
    along each concept direction at `layer`. `concepts` and `random` are arrays of strips."""
    from captum.concept import TCAV, Concept
    from captum.concept._utils.data_iterator import dataset_to_dataloader

    class Examples(torch.utils.data.Dataset[torch.Tensor]):
        def __init__(self, data: Array) -> None:
            self.data = torch.as_tensor(np.asarray(data), dtype=torch.float32)

        def __len__(self) -> int:
            return len(self.data)

        def __getitem__(self, i: int) -> torch.Tensor:
            return self.data[i]

    def concept(cid: int, name: str, data: Array) -> Concept:
        return Concept(id=cid, name=name,
                       data_iter=dataset_to_dataloader(Examples(data), batch_size=8))

    made = [concept(i, name, arr) for i, (name, arr) in enumerate(concepts.items())]
    rand = concept(len(made), "random", np.asarray(random))
    model = _Target(s.net, s.target).eval()
    tmp = tempfile.mkdtemp(prefix="cav-")
    layers = [f"net.{layer}"] if hasattr(s.net, "conv") else [f"net.members.0.{layer}"]
    if not hasattr(s.net, "members") and not hasattr(s.net, "conv"):
        layers = [f"net.m.{layer}"]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        method = TCAV(model, layers=layers, save_path=tmp)
        x = torch.as_tensor(np.repeat(s.x[None, :], 6, axis=0)
                            + np.random.default_rng(0).normal(0, 0.01, (6, len(s.x))),
                            dtype=torch.float32)
        scores = method.interpret(inputs=x, experimental_sets=[[m, rand] for m in made],
                                  target=None)
    drivers = []
    for key, by_layer in scores.items():
        names = key.split("-")
        concept_name = concepts_names(made, names[0])
        val = float(by_layer[layers[0]]["sign_count"][0])
        drivers.append(driver(concept_name, val, val - 0.5))
    return Result(f"captum.tcav@{version('captum')}", "saliency", drivers, output=s.output,
                  detail={"layer": layers[0], "class": s.classes[s.target],
                          "reading": "sign_count above 0.5 means the concept raises the class"})


def concepts_names(made: Sequence[object], key: str) -> str:
    for m in made:
        if str(getattr(m, "id", "")) == key:
            return str(getattr(m, "name", key))
    return key
