"""Migration awareness for the Ask agent — step digests + source packets."""

from __future__ import annotations

import re

from app.services.migration.sources import sources_for, topics_for_step


def detect_step_index(message: str) -> int | None:
    """Parse 'step 5', 's5', '#5', 'wave 5' → 1-based index."""
    m = re.search(r"\b(?:step|wave|s)\s*#?\s*(\d{1,2})\b", message, re.I)
    if m:
        return int(m.group(1))
    m = re.search(r"#(\d{1,2})\b", message)
    if m and int(m.group(1)) <= 40:
        return int(m.group(1))
    return None


def _sum(d: dict | None) -> int:
    return sum(int(v or 0) for v in (d or {}).values())


def migration_digest(run: dict | None) -> str:
    if not run:
        return "No migration plan loaded yet."
    stack = run.get("target_stack") or {}
    label = stack.get("description") or " · ".join(
        str(stack[k]) for k in ("language", "framework", "database") if stack.get(k)
    ) or "unset target"
    steps = (run.get("plan") or {}).get("steps") or []
    lines = [f"Target: {label}", f"Plan: {len(steps)} steps (legacy edges must reach 0)."]
    for i, s in enumerate(steps, 1):
        title = s.get("stack_title") or s.get("title") or s.get("id")
        cuts = len(s.get("removals") or [])
        deps = f"{_sum(s.get('deps_before'))}→{_sum(s.get('deps_after'))}"
        why = (s.get("why_now") or s.get("why") or "")[:110]
        vulns = "; ".join((v.get("risk") or "")[:60] for v in (s.get("vulns") or [])[:2])
        lines.append(f"{i}. [{s.get('id')}] {title} · cut {cuts} · deps {deps}")
        if why:
            lines.append(f"   why: {why}")
        if vulns:
            lines.append(f"   vulns: {vulns}")
    return "\n".join(lines)


def step_packet(run: dict, index: int) -> dict | None:
    steps = (run.get("plan") or {}).get("steps") or []
    if index < 1 or index > len(steps):
        return None
    step = steps[index - 1]
    stack = run.get("target_stack") or {}
    findings = [str(v.get("risk") or "") for v in (step.get("vulns") or [])]
    docs = sources_for(topics_for_step(step, findings), stack, limit=3)
    removals = [
        {
            "type": r.get("type"),
            "source": r.get("source"),
            "target": r.get("target"),
            "file": r.get("file"),
            "line": r.get("line"),
            "snippet": (r.get("snippet") or "")[:120],
        }
        for r in (step.get("removals") or [])[:12]
    ]
    requires = []
    for req in step.get("requires") or []:
        rid = req.get("step_id") if isinstance(req, dict) else req
        if rid:
            requires.append(rid)
    unblocks = step.get("unblocks") or []
    return {
        "index": index,
        "id": step.get("id"),
        "title": step.get("stack_title") or step.get("title"),
        "why": step.get("why_now") or step.get("why") or step.get("detail"),
        "verb": step.get("verb"),
        "requires": requires,
        "unblocks": unblocks,
        "deps_before": _sum(step.get("deps_before")),
        "deps_after": _sum(step.get("deps_after")),
        "vulns": step.get("vulns") or [],
        "removals": removals,
        "docs": docs,
        "prompt": step.get("engineer_prompt"),
    }


def format_step_for_prompt(packet: dict) -> str:
    docs = "\n".join(
        f"- {d.get('title')}: \"{(d.get('passage') or '')[:160]}\" ({d.get('url')})"
        for d in (packet.get("docs") or [])
    ) or "- (no cached guide passages)"
    vulns = "\n".join(
        f"- {v.get('risk')} · evidence {v.get('evidence')} · fix: {v.get('fix')}"
        for v in (packet.get("vulns") or [])[:5]
    ) or "- none listed"
    cuts = "\n".join(
        f"- −{r.get('type')} {r.get('source')}→{r.get('target')} @ {r.get('file')}:{r.get('line')}"
        for r in (packet.get("removals") or [])[:8]
    ) or "- (cuts computed at play time from retire set)"
    return (
        f"[Migration step {packet['index']} · {packet.get('id')} · {packet.get('title')}]\n"
        f"Why now: {packet.get('why')}\n"
        f"Requires: {packet.get('requires') or 'none'} · Unblocks: {packet.get('unblocks') or 'none'}\n"
        f"Deps {packet.get('deps_before')}→{packet.get('deps_after')}\n"
        f"Measured cuts:\n{cuts}\n"
        f"Potential modernization vulnerabilities:\n{vulns}\n"
        f"Primary sources (cite these URLs in your answer):\n{docs}\n"
        "Answer the user about THIS step. Lead with side effects / risks, then cite sources with links."
    )
