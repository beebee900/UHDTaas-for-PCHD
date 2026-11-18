"""Explainers for graph models (design 04, 4.6.1, graph models).

GNNExplainer and PGExplainer come from PyTorch Geometric. Both return importance scores
for the edges around the person; GNNExplainer also scores the person's and neighbours'
features. `phkg_paths` adds the person's recorded facts from the personal health
knowledge graph.
"""

from __future__ import annotations

import warnings
from importlib.metadata import version
from typing import TYPE_CHECKING, Any

import numpy as np

from ahdt.knowledge.phkg import PHKG
from ahdt.xai.subjects import GraphSubject
from ahdt.xai.types import Result, driver

GNN_EPOCHS = 40
PG_EPOCHS = 12
PG_TRAIN_NODES = 24
TOP_EDGES = 5

if TYPE_CHECKING:
    import torch


def _config() -> Any:
    from torch_geometric.explain.config import ModelConfig

    return ModelConfig(mode="binary_classification", task_level="node", return_type="raw")


def _edges(s: GraphSubject, mask: torch.Tensor, top: int) -> list[dict[str, float | int]]:
    ei = s.edge_index
    touch = ((ei[0] == s.node) | (ei[1] == s.node)).nonzero().reshape(-1)
    scored = sorted(((float(mask[i]), int(i)) for i in range(len(mask))),
                    key=lambda p: -p[0])
    near = [(w, i) for w, i in scored if i in set(touch.tolist())] or scored
    return [{"source": int(ei[0, i]), "target": int(ei[1, i]), "importance": w}
            for w, i in near[:top]]


def gnn_explainer(s: GraphSubject, epochs: int = GNN_EPOCHS) -> Result:
    """GNNExplainer (Ying et al. 2019): soft masks over the node features and the edges
    that preserve the model's prediction for the person."""
    from torch_geometric.explain import Explainer, GNNExplainer

    explainer = Explainer(model=s.net, algorithm=GNNExplainer(epochs=epochs),
                          explanation_type="model", node_mask_type="attributes",
                          edge_mask_type="object", model_config=_config())
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        exp = explainer(s.x, s.edge_index, index=s.node)
    feature = exp.node_mask.sum(dim=0)
    own = exp.node_mask[s.node]
    drivers = [driver(f, float(s.x[s.node, i]), float(feature[i]))
               for i, f in enumerate(s.features)]
    return Result(f"gnnexplainer@{version('torch-geometric')}", "graph", drivers,
                  output=s.output,
                  detail={"edges": _edges(s, exp.edge_mask, TOP_EDGES),
                          "own_feature_importance": {f: float(own[i])
                                                     for i, f in enumerate(s.features)},
                          "epochs": epochs})


def pg_explainer(s: GraphSubject, epochs: int = PG_EPOCHS) -> Result:
    """PGExplainer (Luo et al. 2020): a small network trained to score edges, then applied
    to the person. It explains the model's own decision as the target."""
    import torch
    from torch_geometric.explain import Explainer, PGExplainer

    algorithm = PGExplainer(epochs=epochs, lr=0.01)
    explainer = Explainer(model=s.net, algorithm=algorithm, explanation_type="phenomenon",
                          edge_mask_type="object", model_config=_config())
    with torch.no_grad():
        target = (torch.sigmoid(s.net(s.x, s.edge_index)) >= 0.5).float()
    n = s.x.shape[0]
    nodes = sorted({s.node, *np.linspace(0, n - 1, min(PG_TRAIN_NODES, n)).astype(int).tolist()})
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for epoch in range(epochs):
            for idx in nodes:
                algorithm.train(epoch, s.net, s.x, s.edge_index, target=target, index=idx)
        exp = explainer(s.x, s.edge_index, target=target, index=s.node)
    edges = _edges(s, exp.edge_mask, TOP_EDGES)
    drivers = [driver(f"edge {e['source']}->{e['target']}", None, float(e["importance"]))
               for e in edges]
    return Result(f"pgexplainer@{version('torch-geometric')}", "graph", drivers,
                  output=s.output, detail={"edges": edges, "epochs": epochs,
                                           "trained_on_nodes": len(nodes)})


async def phkg_paths(phkg: PHKG, hdt_id: str) -> Result:
    """The person's recorded conditions, medications and phenotypes as one-edge paths
    from the person, the facts a clinician can check against the network explanation."""
    paths: list[dict[str, str]] = []
    for query, label in (("person.conditions", "HAS_CONDITION"),
                         ("person.medications", "TAKES"),
                         ("person.phenotypes", "HAS_PHENOTYPE")):
        for row in await phkg.read(query, hdt_id):
            node = row["b"]
            paths.append({"from": hdt_id, "edge": label, "to": str(node["id"]),
                          "name": str(node.get("name") or node.get("label") or node["id"])})
    return Result("phkg.paths@own", "graph", [driver(p["name"], p["edge"], 1.0)
                                                for p in paths],
                  detail={"paths": paths})
