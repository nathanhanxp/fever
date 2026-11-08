"""What-if reorder: simulate a bad plan order until the first fault."""

from __future__ import annotations

import re
from typing import Any


def _req_id(req: Any) -> str | None:
    if isinstance(req, dict):
        return req.get("step_id")
    return req if isinstance(req, str) else None


def parse_move(text: str, steps: list[dict]) -> list[str] | None:
    """Parse 'step 5 before 3' / 's5 before s3' / 'move 5 before 3' → new order of ids."""
    ids = [s["id"] for s in steps]
    n = len(ids)
    m = re.search(
        r"(?:step|s|wave)?\s*#?(\d{1,2})\s+(?:before|ahead of|prior to)\s+(?:step|s|wave)?\s*#?(\d{1,2})",
        text,
        re.I,
    )
    if not m:
        m = re.search(r"move\s+#?(\d{1,2})\s+(?:to\s+)?before\s+#?(\d{1,2})", text, re.I)
    if not m:
        return None
    a, b = int(m.group(1)), int(m.group(2))
    if a < 1 or b < 1 or a > n or b > n or a == b:
        return None
    move_id, before_id = ids[a - 1], ids[b - 1]
    order = [i for i in ids if i != move_id]
    at = order.index(before_id)
    order.insert(at, move_id)
    return order


def simulate(run: dict, order: list[str] | None = None, text: str | None = None) -> dict:
    steps = (run.get("plan") or {}).get("steps") or []
    by_id = {s["id"]: s for s in steps}
    if text and not order:
        order = parse_move(text, steps)
    if not order:
        order = [s["id"] for s in steps]

    ordered = [by_id[i] for i in order if i in by_id]
    frames: list[dict] = []
    completed: list[str] = []
    fault = None

    for idx, step in enumerate(ordered, 1):
        missing = []
        for req in step.get("requires") or []:
            rid = _req_id(req)
            if rid and rid not in completed and rid in by_id:
                missing.append(rid)
        title = step.get("stack_title") or step.get("title") or step["id"]
        retire = list(step.get("migrate") or [])
        for row in step.get("removals") or []:
            for nid in (row.get("source"), row.get("target")):
                if nid and nid not in retire:
                    retire.append(nid)
        removals = [
            {k: row.get(k) for k in ("source", "target", "type", "file", "line")}
            for row in (step.get("removals") or [])[:16]
            if row.get("source") and row.get("target")
        ]

        if missing:
            # Predicted modernization fault at this illegal order
            cyber = _fault_cyber(run, step, missing)
            cause_edges = _fault_edges(step, run)
            cause_nodes = _fault_nodes(step, cause_edges)
            fault = {
                "step_id": step["id"],
                "index": idx,
                "title": title,
                "missing": missing,
                "missing_titles": [
                    (by_id.get(m) or {}).get("stack_title")
                    or (by_id.get(m) or {}).get("title")
                    or m
                    for m in missing
                ],
                "explanation": _fault_explain(step, missing, by_id, cause_edges),
                "color": cyber[0]["color"] if cyber else "orange",
                "cyber": cyber,
                "nodes": cause_nodes,
                "edges": cause_edges,
                "why": (step.get("why_now") or step.get("why") or step.get("detail") or "").strip()[:320],
            }
            frames.append({
                "step_id": step["id"],
                "index": idx,
                "title": title,
                "ok": False,
                "fault": True,
                "retire_nodes": cause_nodes[:16] or retire[:12],
                "removed_edges": cause_edges or removals,
                "cyber": cyber,
                "explanation": fault["explanation"],
                "nodes": cause_nodes,
                "edges": cause_edges,
            })
            break

        frames.append({
            "step_id": step["id"],
            "index": idx,
            "title": title,
            "ok": True,
            "fault": False,
            "retire_nodes": retire[:12],
            "removed_edges": removals,
        })
        completed.append(step["id"])

    ok = fault is None
    # Legal reorder: don't make the client animate 40 steps — return a short note instead
    if ok:
        frames = []
    return {
        "order": [s["id"] for s in ordered],
        "order_titles": [
            {"id": s["id"], "index": i + 1, "title": s.get("stack_title") or s.get("title")}
            for i, s in enumerate(ordered)
        ],
        "frames": frames,
        "fault": fault,
        "ok": ok,
        "note": (
            None
            if fault
            else "Legal — preconditions still hold (e.g. 3 before 2 both only need step 1). No fault."
        ),
        "claim": "Predicted what-if against measured requires",
    }


def _fault_edges(step: dict, run: dict) -> list[dict]:
    """Concrete edges this illegal cut would touch — shown on the graph."""
    out: list[dict] = []
    seen: set[tuple] = set()
    for row in step.get("removals") or []:
        s, t = row.get("source"), row.get("target")
        if not s or not t:
            continue
        key = (s, t, row.get("type") or "")
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "source": s,
            "target": t,
            "type": row.get("type") or "CALL",
            "file": row.get("file"),
            "line": row.get("line"),
            "snippet": (row.get("snippet") or "")[:160],
            "cause": f"{row.get('type') or 'edge'} {s} → {t}"
            + (f" @ {row.get('file')}:{row.get('line')}" if row.get("file") else ""),
        })
        if len(out) >= 8:
            break
    if out:
        return out
    # Fall back to legacy edges that touch migrate units
    migrate = set(step.get("migrate") or [])
    for e in run.get("legacy_edges") or []:
        if e.get("source") in migrate or e.get("target") in migrate:
            s, t = e.get("source"), e.get("target")
            if not s or not t:
                continue
            key = (s, t, e.get("type") or "")
            if key in seen:
                continue
            seen.add(key)
            out.append({
                "source": s,
                "target": t,
                "type": e.get("type") or "CALL",
                "file": e.get("file"),
                "line": e.get("line"),
                "snippet": (e.get("snippet") or "")[:160],
                "cause": f"{e.get('type') or 'edge'} {s} → {t}"
                + (f" @ {e.get('file')}:{e.get('line')}" if e.get("file") else ""),
            })
            if len(out) >= 6:
                break
    return out


def _fault_nodes(step: dict, edges: list[dict]) -> list[str]:
    nodes: list[str] = []
    for nid in step.get("migrate") or []:
        if nid and nid not in nodes:
            nodes.append(nid)
    for e in edges:
        for nid in (e.get("source"), e.get("target")):
            if nid and nid not in nodes:
                nodes.append(nid)
    for row in step.get("removals") or []:
        for nid in (row.get("source"), row.get("target")):
            if nid and nid not in nodes:
                nodes.append(nid)
    return nodes[:16]


def _fault_explain(step: dict, missing: list[str], by_id: dict, edges: list[dict] | None = None) -> str:
    titles = [
        (by_id.get(m) or {}).get("stack_title") or (by_id.get(m) or {}).get("title") or m
        for m in missing
    ]
    why = (step.get("why_now") or step.get("why") or step.get("detail") or "").strip()
    base = (
        f"Broke at “{step.get('stack_title') or step.get('title')}” — missing prerequisite(s): "
        f"{', '.join(titles)}."
    )
    edge_bit = ""
    if edges:
        causes = [e.get("cause") for e in edges[:3] if e.get("cause")]
        if causes:
            edge_bit = " Fault edge(s): " + "; ".join(causes) + "."
    pitfall = (
        " Shipping this cut early skips the auth/TLS/precision gate those steps install, "
        "so the modernized surface inherits trust assumptions it should not."
    )
    return f"{base}{edge_bit}{pitfall}" + (f" Why: {why}" if why else "")


def _fault_cyber(run: dict, step: dict, missing: list[str]) -> list[dict]:
    """Pick orange/purple predicted nodes related to this illegal cut."""
    out = []
    retire = set(step.get("migrate") or [])
    for row in step.get("removals") or []:
        retire.update(filter(None, [row.get("source"), row.get("target")]))
    for r in run.get("cyber_risks") or []:
        if r.get("color") not in {"orange", "purple"}:
            continue
        if r.get("node_id") in retire:
            out.append({
                "node_id": r.get("node_id"),
                "color": r.get("color"),
                "title": r.get("title"),
                "detail": r.get("detail"),
            })
        if len(out) >= 4:
            break
    if not out:
        # fabricate predicted horizons on first migrate targets
        for nid in list(retire)[:3]:
            color = "orange" if str(nid).startswith("pgm:") or str(nid).startswith("java:") else "purple"
            out.append({
                "node_id": nid,
                "color": color,
                "title": "Predicted risk from illegal order",
                "detail": f"Prerequisite {', '.join(missing)} never wrapped this boundary before cutover.",
            })
    return out
