"""Short Nemotron blurbs for why a node/edge exists — cached on the run."""

from __future__ import annotations

import asyncio
import hashlib
import json
import re


def _run_complete(role: str, prompt: str, code_hash: str, max_tokens: int = 160) -> dict:
    from app.services.agents.gateway import complete

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(complete(role, prompt, code_hash, max_tokens=max_tokens))
    # Already inside an event loop (rare for these sync routes) — skip LLM
    return {"status": "skip", "text": ""}


def _parse_why(text: str) -> str:
    text = (text or "").strip()
    if not text:
        return ""
    try:
        obj = json.loads(text)
        why = obj.get("why") or obj.get("explanation") or obj.get("summary") or ""
        if why:
            return str(why).strip()[:280]
    except Exception:
        pass
    why = re.sub(r"\s+", " ", text).strip().strip('"')
    return why[:280]


def template_node(node: dict, edges_by_type: dict[str, int]) -> str:
    name = node.get("name") or _short(node.get("id") or "")
    kind = node.get("kind") or "unit"
    summary = (node.get("summary") or "").strip()
    top = ", ".join(f"{k}×{v}" for k, v in sorted(edges_by_type.items(), key=lambda kv: -kv[1])[:3])
    if summary:
        return f"{name} is a {kind}: {summary[:160]}"
    if top:
        return f"{name} is a {kind} with measured deps ({top})."
    return f"{name} is a parsed {kind} in the legacy CardDemo graph."


def template_edge(edge: dict) -> str:
    et = edge.get("type") or "dep"
    src = _short(str(edge.get("source") or ""))
    tgt = _short(str(edge.get("target") or ""))
    snip = (edge.get("snippet") or "").strip()
    base = f"{et} links {src} → {tgt}"
    if snip:
        return f"{base} at the measured call site: {snip[:140]}"
    return f"{base} — parser-detected dependency with file:line evidence."


def _short(name: str) -> str:
    return name.split(":")[-1] if ":" in name else name


def ai_why_node(run: dict, node: dict, edges_by_type: dict[str, int]) -> str:
    nid = str(node.get("id") or "")
    cache = run.setdefault("ai_why", {})
    if nid in cache and cache[nid]:
        return cache[nid]
    fallback = template_node(node, edges_by_type)
    prompt = (
        "Explain in ONE sentence (max 35 words) why this legacy code unit exists in the CardDemo graph. "
        "Focus on business role + how neighbors use it. JSON {\"why\":\"...\"}.\n"
        f"name={node.get('name')} kind={node.get('kind')} cluster={node.get('cluster')}\n"
        f"summary={ (node.get('summary') or '')[:240] }\n"
        f"edge_types={edges_by_type}\n"
        f"file={node.get('file')}:{node.get('line')}"
    )
    code_hash = hashlib.sha256(f"node-why|{nid}|{node.get('file')}|{node.get('line')}".encode()).hexdigest()[:24]
    result = _run_complete("explainer", prompt, code_hash)
    why = _parse_why(result.get("text") or "") or fallback
    cache[nid] = why
    try:
        from app.services.migration import service
        service._save(run)
    except Exception:
        pass
    return why


def ai_why_edge(run: dict, edge: dict) -> str:
    eid = str(edge.get("id") or f"{edge.get('source')}::{edge.get('target')}::{edge.get('type')}")
    cache = run.setdefault("ai_why", {})
    if eid in cache and cache[eid]:
        return cache[eid]
    fallback = template_edge(edge)
    prompt = (
        "Explain in ONE sentence (max 35 words) why this dependency edge exists. "
        "Say what the source needs from the target. JSON {\"why\":\"...\"}.\n"
        f"type={edge.get('type')} source={edge.get('source')} target={edge.get('target')}\n"
        f"file={edge.get('file')}:{edge.get('line')}\n"
        f"snippet={(edge.get('snippet') or '')[:180]}"
    )
    code_hash = hashlib.sha256(f"edge-why|{eid}|{edge.get('file')}|{edge.get('line')}".encode()).hexdigest()[:24]
    result = _run_complete("explainer", prompt, code_hash)
    why = _parse_why(result.get("text") or "") or fallback
    cache[eid] = why
    try:
        from app.services.migration import service
        service._save(run)
    except Exception:
        pass
    return why
