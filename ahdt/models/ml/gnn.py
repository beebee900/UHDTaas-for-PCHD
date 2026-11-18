"""GraphSAGE (PyG) support-availability model on the social network (NetworkX graph).

Transductive node classification: every person is a node, household and community ties
are edges, and the loss uses the training persons only. Validation on the test persons.
A logistic regression on the node's own features is reported as the no-graph baseline.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import networkx as nx
import numpy as np
import pandas as pd
from numpy.typing import NDArray
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score

from ahdt.models.ml.artifacts import Result, write_result
from ahdt.models.ml.common import split_masks
from evaluation.models.ahdt.fairness import ATTRIBUTES, ece, slice_report

MODEL_FILE = "model.pt"
META_FILE = "model.json"


def _net(n_in: int, hidden: int) -> Any:
    import torch
    from torch_geometric.nn import SAGEConv

    class Sage(torch.nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.c1 = SAGEConv(n_in, hidden)
            self.c2 = SAGEConv(hidden, 1)

        def forward(self, x: torch.Tensor, edge_index: torch.Tensor) -> torch.Tensor:
            h = torch.relu(self.c1(x, edge_index))
            out: torch.Tensor = self.c2(h, edge_index).squeeze(-1)
            return out

    return Sage()


def _tensors(df: pd.DataFrame, graph: nx.Graph, features: Sequence[str],
             mean: NDArray[np.float64], std: NDArray[np.float64]) -> tuple[Any, Any]:
    import torch

    index = {h: i for i, h in enumerate(df.hdt_id)}
    pairs = [(index[a], index[b]) for a, b in graph.edges() if a in index and b in index]
    ei = np.array(pairs + [(b, a) for a, b in pairs], dtype=np.int64).T.reshape(2, -1)
    x = (df[list(features)].to_numpy(dtype=np.float32) - mean) / std
    return torch.tensor(x, dtype=torch.float32), torch.tensor(ei)


def train(model_id: str, version: str, dataset: str, df: pd.DataFrame, graph: nx.Graph,
          features: Sequence[str], out: Path, *, epochs: int = 300, hidden: int = 32) -> Result:
    import torch

    torch.manual_seed(7)
    df = df.reset_index(drop=True)
    masks = split_masks(df.hdt_id.astype(str))
    x_raw = df[list(features)].to_numpy(dtype=np.float32)
    mean, std = x_raw[masks["train"]].mean(axis=0), x_raw[masks["train"]].std(axis=0) + 1e-6
    x, ei = _tensors(df, graph, features, mean, std)
    y = torch.tensor(df.label.to_numpy(dtype=np.float32))
    net = _net(len(features), hidden)
    opt = torch.optim.Adam(net.parameters(), lr=0.01, weight_decay=5e-4)
    tr = torch.tensor(masks["train"])
    for _ in range(epochs):
        opt.zero_grad()
        loss = torch.nn.functional.binary_cross_entropy_with_logits(net(x, ei)[tr], y[tr])
        loss.backward()
        opt.step()
    net.eval()
    with torch.no_grad():
        p = torch.sigmoid(net(x, ei)).numpy()
    te = masks["test"]
    yt = df.label.to_numpy()[te]
    auroc = float(roc_auc_score(yt, p[te]))
    base = LogisticRegression(max_iter=1000).fit(x.numpy()[masks["train"]],
                                                 df.label.to_numpy()[masks["train"]])
    base_auroc = float(roc_auc_score(yt, base.predict_proba(x.numpy()[te])[:, 1]))
    metrics = {"auroc": auroc, "baseline_auroc_no_graph": base_auroc, "ece": ece(yt, p[te]),
               "nodes": float(len(df)), "edges": float(ei.shape[1] // 2)}
    t = df[te]
    report = slice_report(model_id, "binary", yt, p[te],
                          {a: t[a].tolist() for a in ATTRIBUTES if a in t})
    out.mkdir(parents=True, exist_ok=True)
    torch.save(net.state_dict(), out / MODEL_FILE)
    (out / META_FILE).write_text(json.dumps({"features": list(features), "hidden": hidden,
                                             "mean": mean.tolist(), "std": std.tolist()},
                                            indent=1), encoding="utf-8")
    result = Result(model_id, version, dataset, "auroc", auroc, metrics, report.to_dict(),
                    split={k: int(v.sum()) for k, v in masks.items()} | {"unit": "person"})
    write_result(result, out, fairness_md=report.markdown())
    return result


class Predictor:
    """Support-availability probability of every node of a graph."""

    def __init__(self, directory: Path) -> None:
        import torch

        self.meta = json.loads((directory / META_FILE).read_text(encoding="utf-8"))
        self.net = _net(len(self.meta["features"]), int(self.meta["hidden"]))
        self.net.load_state_dict(torch.load(directory / MODEL_FILE, weights_only=True))
        self.net.eval()

    def probabilities(self, nodes: pd.DataFrame, graph: nx.Graph) -> dict[str, float]:
        import torch

        x, ei = _tensors(nodes.reset_index(drop=True), graph, self.meta["features"],
                         np.asarray(self.meta["mean"]), np.asarray(self.meta["std"]))
        with torch.no_grad():
            p = torch.sigmoid(self.net(x, ei)).numpy()
        return dict(zip(nodes.hdt_id.astype(str), map(float, p), strict=True))
