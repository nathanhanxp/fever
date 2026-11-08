"""Deterministic graph tools. Counts and lines come from stored rows."""

from __future__ import annotations

from collections import deque

from sqlmodel import Session, select

from app.models import CodeUnit, GraphEdge


def _units(session: Session, snapshot_id: str) -> list[CodeUnit]:
    return list(session.exec(select(CodeUnit).where(CodeUnit.snapshot_id == snapshot_id)).all())


def _edges(session: Session, snapshot_id: str) -> list[GraphEdge]:
    return list(session.exec(select(GraphEdge).where(GraphEdge.snapshot_id == snapshot_id)).all())


def _by_name(units: list[CodeUnit], text: str) -> list[CodeUnit]:
    needle = text.lower()
    hits = [u for u in units if needle in u.symbol_name.lower() or needle in u.qualname.lower() or needle in (u.file_path or "").lower()]
    return hits[:12]


def _row(unit: CodeUnit, hops: int) -> dict:
    return {
        "id": unit.id,
        "qualname": unit.qualname,
        "name": unit.symbol_name,
        "file": unit.file_path,
        "line": unit.start_line,
        "hops": hops,
        "label": "Measured",
    }


def dependents(session: Session, snapshot_id: str, focus: str) -> dict:
    units = _units(session, snapshot_id)
    edges = _edges(session, snapshot_id)
    seeds = _by_name(units, focus)
    by_id = {u.id: u for u in units}
    incoming: dict[str, list[str]] = {}
    for edge in edges:
        incoming.setdefault(edge.target_unit_id, []).append(edge.source_unit_id)
    found = []
    for seed in seeds:
        seen = {seed.id: 0}
        queue = deque([seed.id])
        while queue:
            cur = queue.popleft()
            for src in incoming.get(cur, []):
                if src not in seen and seen[cur] < 3:
                    seen[src] = seen[cur] + 1
                    queue.append(src)
        for uid, hops in seen.items():
            if hops == 0:
                continue
            found.append(_row(by_id[uid], hops))
    return {"focus": focus, "nodes": found, "count": len(found)}


def dependencies(session: Session, snapshot_id: str, focus: str) -> dict:
    units = _units(session, snapshot_id)
    edges = _edges(session, snapshot_id)
    seeds = _by_name(units, focus)
    by_id = {u.id: u for u in units}
    outgoing: dict[str, list[str]] = {}
    for edge in edges:
        outgoing.setdefault(edge.source_unit_id, []).append(edge.target_unit_id)
    found = []
    for seed in seeds:
        seen = {seed.id: 0}
        queue = deque([seed.id])
        while queue:
            cur = queue.popleft()
            for dst in outgoing.get(cur, []):
                if dst not in seen and seen[cur] < 3:
                    seen[dst] = seen[cur] + 1
                    queue.append(dst)
        for uid, hops in seen.items():
            if hops == 0:
                continue
            found.append(_row(by_id[uid], hops))
    return {"focus": focus, "nodes": found, "count": len(found)}


def path(session: Session, snapshot_id: str, source: str, target: str) -> dict:
    units = _units(session, snapshot_id)
    edges = _edges(session, snapshot_id)
    starts = _by_name(units, source)
    goals = {u.id for u in _by_name(units, target)}
    by_id = {u.id: u for u in units}
    outgoing: dict[str, list[str]] = {}
    for edge in edges:
        outgoing.setdefault(edge.source_unit_id, []).append(edge.target_unit_id)
    for seed in starts:
        prev = {seed.id: None}
        queue = deque([seed.id])
        while queue:
            cur = queue.popleft()
            if cur in goals and cur != seed.id:
                chain = []
                node = cur
                hops = 0
                while node is not None:
                    chain.append(_row(by_id[node], hops))
                    node = prev[node]
                    hops += 1
                chain.reverse()
                for i, row in enumerate(chain):
                    row["hops"] = i
                return {"nodes": chain, "count": len(chain), "label": "Measured"}
            for dst in outgoing.get(cur, []):
                if dst not in prev:
                    prev[dst] = cur
                    queue.append(dst)
    return {"nodes": [], "count": 0, "label": "Measured"}


def filter_by_lens(session: Session, snapshot_id: str, lens: str) -> dict:
    edges = _edges(session, snapshot_id)
    units = {u.id: u for u in _units(session, snapshot_id)}
    wanted = lens.lower()
    rows = []
    for edge in edges:
        if wanted in (edge.edge_type or "").lower():
            src = units.get(edge.source_unit_id)
            dst = units.get(edge.target_unit_id)
            if not src or not dst:
                continue
            rows.append({
                "edge_type": edge.edge_type,
                "source": src.qualname,
                "target": dst.qualname,
                "file": src.file_path,
                "line": src.start_line,
                "hops": 1,
            })
    return {"lens": lens, "edges": rows[:40], "count": len(rows), "label": "Measured"}


def findings_for(session: Session, snapshot_id: str, focus: str) -> dict:
    units = _by_name(_units(session, snapshot_id), focus)
    return {
        "nodes": [_row(u, 0) for u in units],
        "count": len(units),
        "label": "Measured",
    }
