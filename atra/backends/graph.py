"""In-process graph backend: NetworkX with a fixed Cypher subset (design 03, section 3.12).

Supported statement shapes (`$name` are parameters; literals may be quoted strings or
numbers):

    MATCH (a:L {p: $x})-[:R*1..n]->(b:L) WHERE b.p IN $list RETURN a, b
    MATCH (a)-[r:R]->(b) WHERE a.id = $id RETURN type(r), b
    MATCH (a:L {p: $x}) WHERE a.q = $y RETURN a
    MERGE (a:L {id: $id}) SET a += $props
    MATCH (a:L {id: $x}), (b:L {id: $y}) MERGE (a)-[:R]->(b)

`WHERE` takes `=` and `IN` comparisons joined by `AND`. `RETURN` items are variables,
`var.prop`, or `type(r)`, each with an optional `AS alias`. A node is returned as a dict
of its properties. Anything else raises `UnsupportedQuery`, and must run on Neo4j.
"""

from __future__ import annotations

import re
import threading
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import networkx as nx

from atra.backends.base import GraphBackend


class UnsupportedQuery(ValueError):
    pass


_NODE = r"\(\s*(?P<{v}>\w+)?\s*(?::\s*(?P<{l}>\w+))?\s*(?P<{p}>\{{[^}}]*\}})?\s*\)"
_REL = (r"-\[\s*(?P<rv>\w+)?\s*(?::\s*(?P<rt>\w+))?\s*"
        r"(?P<star>\*\s*(?P<lo>\d+)?\s*\.\.\s*(?P<hi>\d+))?\s*\]->")

_PATH_RE = re.compile(r"^MATCH\s+" + _NODE.format(v="av", l="al", p="ap") + r"\s*" + _REL
                      + r"\s*" + _NODE.format(v="bv", l="bl", p="bp")
                      + r"(?:\s+WHERE\s+(?P<where>.+?))?\s+RETURN\s+(?P<ret>.+)$",
                      re.IGNORECASE | re.DOTALL)
_SINGLE_RE = re.compile(r"^MATCH\s+" + _NODE.format(v="av", l="al", p="ap")
                        + r"(?:\s+WHERE\s+(?P<where>.+?))?\s+RETURN\s+(?P<ret>.+)$",
                        re.IGNORECASE | re.DOTALL)
_MERGE_NODE_RE = re.compile(r"^MERGE\s+" + _NODE.format(v="av", l="al", p="ap")
                            + r"(?:\s+SET\s+(?P<sv>\w+)\s*\+=\s*\$(?P<props>\w+))?$",
                            re.IGNORECASE | re.DOTALL)
_MERGE_EDGE_RE = re.compile(r"^MATCH\s+" + _NODE.format(v="av", l="al", p="ap") + r"\s*,\s*"
                            + _NODE.format(v="bv", l="bl", p="bp")
                            + r"\s+MERGE\s+\(\s*(?P<a2>\w+)\s*\)\s*-\[\s*:\s*(?P<rt>\w+)\s*\]->"
                            r"\s*\(\s*(?P<b2>\w+)\s*\)$", re.IGNORECASE | re.DOTALL)
_COND_RE = re.compile(r"^(?P<var>\w+)\.(?P<prop>\w+)\s*(?P<op>=|IN)\s*(?P<val>.+)$",
                      re.IGNORECASE)
_RET_RE = re.compile(r"^(?:(?P<fn>type)\(\s*(?P<fv>\w+)\s*\)|(?P<var>\w+)(?:\.(?P<prop>\w+))?)"
                     r"(?:\s+AS\s+(?P<alias>\w+))?$", re.IGNORECASE)


def _value(token: str, params: Mapping[str, Any]) -> Any:
    token = token.strip()
    if token.startswith("$"):
        name = token[1:]
        if name not in params:
            raise UnsupportedQuery(f"missing parameter ${name}")
        return params[name]
    if len(token) >= 2 and token[0] == token[-1] and token[0] in "'\"":
        return token[1:-1]
    try:
        return float(token) if "." in token else int(token)
    except ValueError:
        raise UnsupportedQuery(f"cannot read value '{token}'") from None


def _props(text: str | None, params: Mapping[str, Any]) -> dict[str, Any]:
    if not text:
        return {}
    body = text.strip()[1:-1].strip()
    out: dict[str, Any] = {}
    for item in filter(None, (s.strip() for s in body.split(","))):
        key, _, val = item.partition(":")
        out[key.strip()] = _value(val, params)
    return out


@dataclass(frozen=True)
class _Cond:
    var: str
    prop: str
    op: str
    value: Any

    def holds(self, props: Mapping[str, Any]) -> bool:
        actual = props.get(self.prop)
        if self.op == "IN":
            return actual in self.value
        return bool(actual == self.value)


def _where(text: str | None, params: Mapping[str, Any]) -> list[_Cond]:
    if not text:
        return []
    conds = []
    for part in re.split(r"\s+AND\s+", text.strip(), flags=re.IGNORECASE):
        m = _COND_RE.match(part.strip())
        if not m:
            raise UnsupportedQuery(f"unsupported WHERE clause '{part}'")
        conds.append(_Cond(m["var"], m["prop"], m["op"].upper(), _value(m["val"], params)))
    return conds


class NetworkXGraph(GraphBackend):
    """Property graph in a NetworkX MultiDiGraph. Nodes are keyed by their `id` property."""

    def __init__(self) -> None:
        self.g: nx.MultiDiGraph = nx.MultiDiGraph()
        self._lock = threading.Lock()

    async def run(self, query: str, params: Mapping[str, Any] | None = None
                  ) -> list[dict[str, Any]]:
        q = " ".join(query.split())
        p = dict(params or {})
        with self._lock:
            for regex, handler in ((_MERGE_EDGE_RE, self._merge_edge),
                                   (_MERGE_NODE_RE, self._merge_node),
                                   (_PATH_RE, self._match_path),
                                   (_SINGLE_RE, self._match_single)):
                m = regex.match(q)
                if m:
                    return handler(m, p)
        raise UnsupportedQuery(f"not in the in-process Cypher subset: {q}")

    async def close(self) -> None:
        return None

    def _node_ok(self, node: str, label: str | None, props: Mapping[str, Any]) -> bool:
        data = self.g.nodes[node]
        if label and label not in data["labels"]:
            return False
        return all(data["props"].get(k) == v for k, v in props.items())

    def _nodes(self, label: str | None, props: Mapping[str, Any]) -> list[str]:
        if "id" in props:
            nid = str(props["id"])
            return [nid] if nid in self.g and self._node_ok(nid, label, props) else []
        return [n for n in self.g.nodes if self._node_ok(n, label, props)]

    def _merge_node(self, m: re.Match[str], params: Mapping[str, Any]) -> list[dict[str, Any]]:
        props = _props(m["ap"], params)
        if "id" not in props:
            raise UnsupportedQuery("MERGE needs an id property")
        nid = str(props["id"])
        if nid not in self.g:
            self.g.add_node(nid, labels=set(), props={})
        data = self.g.nodes[nid]
        if m["al"]:
            data["labels"].add(m["al"])
        data["props"].update(props)
        if m["props"]:
            if m["sv"] != m["av"]:
                raise UnsupportedQuery("SET must update the merged variable")
            data["props"].update(dict(params[m["props"]]))
        return [{m["av"] or "n": dict(data["props"])}]

    def _merge_edge(self, m: re.Match[str], params: Mapping[str, Any]) -> list[dict[str, Any]]:
        if {m["a2"], m["b2"]} != {m["av"], m["bv"]} or m["a2"] != m["av"]:
            raise UnsupportedQuery("MERGE must connect the two matched variables in order")
        sources = self._nodes(m["al"], _props(m["ap"], params))
        targets = self._nodes(m["bl"], _props(m["bp"], params))
        created = 0
        for a in sources:
            for b in targets:
                if not self.g.has_edge(a, b, key=m["rt"]):
                    self.g.add_edge(a, b, key=m["rt"])
                    created += 1
        return [{"created": created, "matched": len(sources) * len(targets)}]

    def _match_single(self, m: re.Match[str], params: Mapping[str, Any]) -> list[dict[str, Any]]:
        var = m["av"]
        conds = _where(m["where"], params)
        rows = []
        for n in self._nodes(m["al"], _props(m["ap"], params)):
            props = self.g.nodes[n]["props"]
            if all(c.holds(props) for c in conds if c.var == var):
                rows.append({var: n})
        return [self._project(m["ret"], row, {}) for row in rows]

    def _match_path(self, m: re.Match[str], params: Mapping[str, Any]) -> list[dict[str, Any]]:
        av, bv, rv, rtype = m["av"], m["bv"], m["rv"], m["rt"]
        conds = _where(m["where"], params)
        lo = int(m["lo"] or 1) if m["star"] else 1
        hi = int(m["hi"]) if m["star"] else 1
        if m["star"] and rv:
            raise UnsupportedQuery("a variable-length relationship cannot be bound")
        rows: list[tuple[dict[str, str], dict[str, str]]] = []
        seen: set[tuple[str, str, str]] = set()
        for a in self._nodes(m["al"], _props(m["ap"], params)):
            for b, rel in self._reach(a, rtype, lo, hi):
                if not self._node_ok(b, m["bl"], _props(m["bp"], params)):
                    continue
                key = (a, b, rel if rv else "")
                if key in seen:
                    continue
                seen.add(key)
                rows.append(({av: a, bv: b} if av else {bv: b}, {rv: rel} if rv else {}))
        out = []
        for nodes, rels in rows:
            props = {var: self.g.nodes[n]["props"] for var, n in nodes.items()}
            if all(c.holds(props.get(c.var, {})) for c in conds):
                out.append(self._project(m["ret"], nodes, rels))
        return out

    def _reach(self, start: str, rtype: str | None, lo: int, hi: int) -> list[tuple[str, str]]:
        found: list[tuple[str, str]] = []
        frontier = [(start, "")]
        visited = {start}
        for depth in range(1, hi + 1):
            nxt = []
            for node, _ in frontier:
                for _, b, key in self.g.out_edges(node, keys=True):
                    if rtype and key != rtype:
                        continue
                    if depth >= lo:
                        found.append((b, key))
                    if b not in visited:
                        visited.add(b)
                        nxt.append((b, key))
            frontier = nxt
        return found

    def _project(self, ret: str, nodes: Mapping[str, str],
                 rels: Mapping[str, str]) -> dict[str, Any]:
        row: dict[str, Any] = {}
        for item in (s.strip() for s in ret.split(",")):
            m = _RET_RE.match(item)
            if not m:
                raise UnsupportedQuery(f"unsupported RETURN item '{item}'")
            if m["fn"]:
                if m["fv"] not in rels:
                    raise UnsupportedQuery(f"type() of unbound relationship '{m['fv']}'")
                row[m["alias"] or f"type({m['fv']})"] = rels[m["fv"]]
            elif m["var"] in nodes:
                props = self.g.nodes[nodes[m["var"]]]["props"]
                value = props.get(m["prop"]) if m["prop"] else dict(props)
                row[m["alias"] or item] = value
            else:
                raise UnsupportedQuery(f"unknown variable '{m['var']}'")
        return row


class Neo4jGraph(GraphBackend):
    """Neo4j over the async Bolt driver. A node is returned as a dict of its properties and
    a relationship type as its name, the same shapes as `NetworkXGraph`."""

    def __init__(self, url: str, user: str = "neo4j", password: str = "") -> None:
        from neo4j import AsyncGraphDatabase

        self.driver = AsyncGraphDatabase.driver(url, auth=(user, password))

    @staticmethod
    def _plain(value: Any) -> Any:
        from neo4j.graph import Node, Relationship

        if isinstance(value, Node):
            return dict(value)
        if isinstance(value, Relationship):
            return value.type
        return value

    async def run(self, query: str, params: Mapping[str, Any] | None = None
                  ) -> list[dict[str, Any]]:
        result = await self.driver.execute_query(query, dict(params or {}))
        records: list[Any] = list(result.records)
        return [{k: self._plain(v) for k, v in record.items()} for record in records]

    async def close(self) -> None:
        await self.driver.close()
