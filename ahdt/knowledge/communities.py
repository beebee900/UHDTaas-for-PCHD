"""Community summaries for GraphRAG (design 04, 4.4.3).

The person's subgraph is clustered with Louvain (`networkx.community.louvain_communities`,
fixed seed). Each community is stored as a `Community` node with its summary, linked from
its members by `IN_COMMUNITY`. The summary comes from the summariser passed in; the
default lists the members by kind, and the LLM summariser of the cognitive services
replaces it there.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

import networkx as nx

from ahdt.knowledge import queries as q
from ahdt.knowledge.phkg import PHKG

type Summariser = Callable[[Sequence[dict[str, Any]]], Awaitable[str]]
SEED = 7


async def extractive_summary(members: Sequence[dict[str, Any]]) -> str:
    by_kind: dict[str, list[str]] = defaultdict(list)
    for m in members:
        kind = m["labels"][0]
        name = m.get("name") or m.get("field") or m.get("label") or m.get("kind") or m["id"]
        by_kind[kind].append(str(name))
    return "; ".join(f"{kind}: {', '.join(sorted(set(names)))}"
                     for kind, names in sorted(by_kind.items()))


async def build(phkg: PHKG, hdt_id: str, summarise: Summariser = extractive_summary,
                *, method: str = "extractive") -> list[dict[str, Any]]:
    nodes, edges = await phkg.subgraph(hdt_id)
    g = nx.Graph()
    g.add_nodes_from(n["id"] for n in nodes if n["id"] != hdt_id)
    g.add_edges_from((a, b) for a, _, b in edges if hdt_id not in (a, b))
    by_id = {n["id"]: n for n in nodes}
    out = []
    groups = nx.community.louvain_communities(g, seed=SEED) if g.number_of_nodes() else []
    for i, members in enumerate(sorted(groups, key=lambda s: sorted(s)[0])):
        cid = f"community:{hdt_id}:{i}"
        member_nodes = [by_id[m] for m in sorted(members)]
        summary = await summarise(member_nodes)
        props = {"hdt_id": hdt_id, "summary": summary, "size": len(members), "method": method}
        await phkg.graph.run(q.MERGE_COMMUNITY, {"id": cid, "props": {**props, "id": cid}})
        for m in members:
            await phkg.graph.run(q.IN_COMMUNITY, {"a": m, "b": cid})
        out.append({"id": cid, **props, "members": sorted(members)})
    return out
