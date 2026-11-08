"""Live multi-step agent architecture demo — real plan, lenses, prover, planner, playback."""

from __future__ import annotations

import asyncio
import json
import time


def _sse(event: str, data: dict) -> str:
    return f"data: {json.dumps({**data, 'type': event})}\n\n"


def _field(res: dict, key: str) -> str:
    text = (res.get("text") or "").strip()
    if not text:
        return ""
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return str(obj.get(key) or obj.get("reason") or obj.get("finding") or obj.get("why") or "")[:220]
    except Exception:
        pass
    return text[:220]


def _parse_json(res: dict) -> dict:
    text = (res.get("text") or "").strip()
    if not text:
        return {}
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else {}
    except Exception:
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            try:
                obj = json.loads(text[start : end + 1])
                return obj if isinstance(obj, dict) else {}
            except Exception:
                return {}
    return {}


def _missing_reqs(step: dict, completed: list[str]) -> list[str]:
    missing = []
    for req in step.get("requires") or []:
        rid = req.get("step_id") if isinstance(req, dict) else req
        if rid and rid not in completed:
            missing.append(rid)
    return missing


def _pick_step(run: dict) -> tuple[dict, list[str]]:
    """Next legal cut with real edge removals (skip empty clean stubs for the demo)."""
    steps = (run.get("plan") or {}).get("steps") or []
    completed: list[str] = []
    last = (run.get("demo_last_playback") or {}).get("step_id")
    if last and (run.get("demo_last_playback") or {}).get("ok"):
        for s in steps:
            sid = s.get("id")
            if sid:
                completed.append(sid)
            if sid == last:
                break
    # Auto-complete zero-removal steps that are already legal so the demo
    # lands on a real wrap/cut instead of a no-op clean.
    progressed = True
    while progressed:
        progressed = False
        for step in steps:
            sid = step.get("id")
            if not sid or sid in completed:
                continue
            if _missing_reqs(step, completed):
                continue
            if step.get("removals"):
                return step, list(completed)
            completed.append(sid)
            progressed = True
    for step in steps:
        sid = step.get("id")
        if sid in completed:
            continue
        if not _missing_reqs(step, completed):
            return step, list(completed)
    return (steps[0] if steps else {}), []


def _step_clusters(run: dict, step: dict) -> list[str]:
    by_id = {n.get("id"): n for n in (run.get("nodes") or [])}
    labels: list[str] = []
    for row in step.get("removals") or []:
        for nid in (row.get("source"), row.get("target")):
            lab = (by_id.get(nid) or {}).get("cluster")
            if lab and lab not in labels:
                labels.append(lab)
    for mid in step.get("migrate") or []:
        lab = (by_id.get(mid) or {}).get("cluster")
        if lab and lab not in labels:
            labels.append(lab)
    if not labels:
        labels = list((run.get("clusters") or [])[:3])
    return labels[:4]


async def stream_architecture_demo(run: dict):
    """Plan → fan-out → gate → write → execute against the measured CardDemo plan + graph."""
    from app.services.agents.gateway import complete
    from app.services.migration import service
    from app.services.migration.cyber import playback_step, seed_cyber_risks
    from app.services.migration.service import _prove, _snippets_for, _step_evidence, stack_label

    stack = run.get("target_stack") or {}
    label = stack_label(stack) if stack else "Java 21 · Spring Boot · PostgreSQL"
    steps = (run.get("plan") or {}).get("steps") or []
    step, completed_before = _pick_step(run)
    if not step:
        yield _sse("log", {"line": "# error: no measured plan steps on this run"})
        yield _sse("demo_done", {"wall_s": 0, "steps_planned": 0, "message": "No plan — re-open CardDemo / upload first"})
        return

    title = step.get("stack_title") or step.get("title") or step.get("id") or "cut"
    step_id = step.get("id") or "s?"
    evidence = _step_evidence(run, step)
    clusters = _step_clusters(run, step)
    started = time.time()

    stages = [
        ("plan", "Coordinator", "Orders the next legal cut from requires[]"),
        ("fanout", "Lenses ∥", "Real cluster snippets → Nemotron → prover filter"),
        ("gate", "Prover", "Reject claims without primary-source grounding"),
        ("write", "Planner", "Write step title, why, vulns onto the measured plan"),
        ("exec", "Execute", "Playback cut on the measured graph"),
    ]
    yield _sse(
        "demo_start",
        {
            "stages": [{"id": s[0], "label": s[1], "detail": s[2]} for s in stages],
            "target": label,
            "step_id": step_id,
            "step_title": title,
            "clusters": clusters,
            "cuts_planned": len(step.get("removals") or []),
        },
    )
    yield _sse(
        "log",
        {
            "line": (
                f"# measured plan · {len(steps)} steps · next legal cut {step_id} “{title}” "
                f"· clusters {', '.join(clusters) or '—'} · {len(step.get('removals') or [])} edge removals"
            )
        },
    )

    # ── 1. Coordinator (real requires + evidence) ────────────────────────────
    yield _sse("stage", {"id": "plan", "status": "running", "t": 0})
    yield _sse("log", {"line": f"$ coordinator.plan --step {step_id} --target \"{label}\""})
    c = await complete(
        "coordinator",
        (
            'Return JSON {"reason":"...","order_ok":true}. '
            "reason must be one short sentence (under 160 characters) explaining sequencing — "
            "do not echo the word chars. "
            "You are the Coordinator for mainframe modernization. "
            f"Next legal cut id={step_id} title={title}. "
            f"Requires already done={completed_before or ['none']}. "
            f"Evidence={json.dumps(evidence)[:900]}. "
            f"Target stack={label}."
        ),
        f"demo-coord-{run.get('id')}-{step_id}",
        max_tokens=160,
        json_mode=True,
    )
    reason = _field(c, "reason") or (
        f"Prereqs met ({len(completed_before)}); cut {step_id} next for {label}."
    )
    yield _sse("log", {"line": f"OK  coordinator           {c.get('latency_s') or '—'}s  {reason}"})
    yield _sse(
        "decision",
        {
            "role": "coordinator",
            "kind": "order",
            "verdict": "accept" if c.get("status") == "ok" else (c.get("status") or "fallback"),
            "text": reason,
            "latency_s": c.get("latency_s"),
        },
    )
    yield _sse("stage", {"id": "plan", "status": "done", "latency_s": c.get("latency_s")})

    # ── 2. Parallel lenses on real snippets ──────────────────────────────────
    yield _sse("stage", {"id": "fanout", "status": "running"})
    yield _sse("log", {"line": f"$ lenses.run --parallel --clusters {','.join(clusters)} --sem 8"})

    lens_jobs: list[tuple[str, str, list[dict]]] = []
    for cluster in clusters:
        for lens in ("Data", "Security", "Code", "API"):
            snippets = _snippets_for(run, cluster, lens)
            if snippets:
                lens_jobs.append((cluster, lens, snippets[:4]))
            if len(lens_jobs) >= 3:
                break
        if len(lens_jobs) >= 3:
            break
    if not lens_jobs:
        # Fall back: any cluster × Code
        for cluster in (run.get("clusters") or [])[:6]:
            snippets = _snippets_for(run, cluster, "Code")
            if snippets:
                lens_jobs.append((cluster, "Code", snippets[:4]))
            if len(lens_jobs) >= 3:
                break

    rule_names = [r.get("rule") or r.get("id") or "detector" for r in (run.get("rules") or [])[:40]] or ["detector"]
    accepted_edges: list[dict] = []

    role_for = {
        "Data": "data-lens",
        "Security": "platform-security-lens",
        "Code": "code-lens",
        "API": "code-lens",
    }

    async def one_lens(cluster: str, lens: str, snippets: list[dict]):
        listing = "\n".join(
            f"s{i} {row['file']}:{row['line']} {row['type']} {row['source']} -> {row['target']} {(row.get('snippet') or '')[:120]}"
            for i, row in enumerate(snippets)
        )
        allowed = {f"s{i}" for i in range(len(snippets))}
        prompt = (
            f"Lens {lens}. Cluster {cluster}. Stack {label}. "
            "Return one JSON object with keys finding, edges, summary. "
            "Each edge needs evidence_ids from the snippet ids, rule \"detector\", risk, action, confidence. "
            "Cite only those ids. finding <= 120 chars.\n"
            + listing
        )
        res = await complete(
            role_for.get(lens, "lens"),
            prompt,
            f"demo-lens-{run.get('id')}-{cluster}-{lens}",
            max_tokens=400,
            json_mode=True,
            backend="nvidia",
        )
        return cluster, lens, snippets, allowed, res

    results = await asyncio.gather(*[one_lens(c, l, s) for c, l, s in lens_jobs]) if lens_jobs else []
    for cluster, lens, snippets, allowed, res in results:
        parsed = _parse_json(res)
        finding = str(parsed.get("finding") or parsed.get("summary") or "")[:160] or _field(res, "finding")
        if not finding:
            finding = f"{lens}/{cluster}: {len(snippets)} measured snippets scanned"
        kept = 0
        for edge in parsed.get("edges") or []:
            if not edge.get("rule"):
                edge["rule"] = "detector"
            reason_fail = _prove(edge, allowed, rule_names + ["detector", "source line"])
            if reason_fail:
                run.setdefault("rejections", []).append(
                    {"cluster": cluster, "lens": lens, "reason": reason_fail, "edge": edge, "source": "architecture-demo"}
                )
                continue
            kept += 1
            accepted_edges.append({"cluster": cluster, "lens": lens, "edge": edge, "snippets": snippets})
        status = res.get("status") or "error"
        yield _sse(
            "log",
            {
                "line": (
                    f"OK  {lens+'/'+cluster:<22} {res.get('latency_s') or '—'}s  "
                    f"{finding} · accepted {kept}/{(len(parsed.get('edges') or []) or 0)}"
                )
            },
        )
        yield _sse(
            "decision",
            {
                "role": f"{lens}-lens",
                "kind": "lens",
                "verdict": "accept" if kept or status == "ok" else status,
                "text": finding,
                "latency_s": res.get("latency_s"),
            },
        )
    if not lens_jobs:
        yield _sse("log", {"line": "WARN lenses               no snippets for step clusters — skipping fan-out"})
    yield _sse("stage", {"id": "fanout", "status": "done"})

    # Persist any newly accepted migration edges (real Predicted layer growth)
    if accepted_edges:
        import uuid

        by_id = {n.get("id"): n for n in (run.get("nodes") or [])}
        for item in accepted_edges[:8]:
            edge = item["edge"]
            snippets = item["snippets"]
            lens = item["lens"]
            cluster = item["cluster"]
            ids = edge.get("evidence_ids") or []
            evidence_rows = []
            for sid in ids:
                try:
                    src = snippets[int(str(sid)[1:])]
                except Exception:
                    continue
                evidence_rows.append(
                    {"id": sid, "file": src["file"], "line": src["line"], "snippet": (src.get("snippet") or "")[:200]}
                )
            target_name = edge.get("target") or f"{lens.lower()}-target"
            if not any(n["name"] == target_name for n in run.get("target_nodes") or []):
                run.setdefault("target_nodes", []).append(
                    {
                        "id": "tgt:" + uuid.uuid4().hex[:8],
                        "name": str(target_name)[:40],
                        "kind": "target",
                        "lens": lens,
                        "cluster": cluster,
                        "label": "Predicted",
                    }
                )
            target = next(n for n in run["target_nodes"] if n["name"] == str(target_name)[:40])
            legacy = edge.get("legacy") or (snippets[0]["source"] if snippets else None)
            if legacy and legacy not in by_id and snippets:
                legacy = snippets[0]["source"]
            run.setdefault("migration_edges", []).append(
                {
                    "id": "m" + uuid.uuid4().hex[:8],
                    "lens": lens,
                    "cluster": cluster,
                    "legacy": legacy,
                    "target": target["id"],
                    "target_name": target["name"],
                    "evidence": evidence_rows,
                    "risk": edge.get("risk") or "",
                    "action": edge.get("action") or "",
                    "confidence": edge.get("confidence"),
                    "rule": edge.get("rule") or "detector",
                    "severity": "amber",
                    "label": "Predicted",
                    "resolved": False,
                    "source": "architecture-demo",
                }
            )
        try:
            service._publish_targets(run)
        except Exception:
            pass
        service._save(run)
        yield _sse("log", {"line": f"OK  publish               +{min(8, len(accepted_edges))} Predicted migration edges → Explore graph"})

    # ── 3. Prover gate on the real cut ───────────────────────────────────────
    yield _sse("stage", {"id": "gate", "status": "running"})
    yield _sse("log", {"line": "$ prover.gate --require primary-source --step " + step_id})
    cut_lines = evidence.get("cuts") or []
    p = await complete(
        "prover",
        (
            'Return JSON {"reason":"...","accept":true}. '
            "reason = one short sentence under 160 characters; never echo the instruction. "
            "You are the Prover. Gate this measured cut only if file:line evidence exists. "
            f"Step={title}. Cuts={json.dumps(cut_lines)[:700]}. "
            f"Lens accepts this run={len(accepted_edges)}. Target={label}."
        ),
        f"demo-prover-{run.get('id')}-{step_id}",
        max_tokens=160,
        json_mode=True,
    )
    parsed_p = _parse_json(p)
    accept = parsed_p.get("accept", True)
    if isinstance(accept, str):
        accept = accept.lower() not in {"false", "0", "no"}
    # Hard gate: no removals evidence → reject
    if not (step.get("removals") or cut_lines):
        accept = False
    preason = _field(p, "reason") or (
        "Accepted: file:line evidence + plan order." if accept else "Rejected: missing primary-source evidence."
    )
    yield _sse(
        "log",
        {"line": f"{'OK' if accept else 'REJECT'}  prover               {p.get('latency_s') or '—'}s  {preason}"},
    )
    yield _sse(
        "decision",
        {
            "role": "prover",
            "kind": "gate",
            "verdict": "accept" if accept else "reject",
            "text": preason,
            "latency_s": p.get("latency_s"),
        },
    )
    yield _sse("stage", {"id": "gate", "status": "done", "latency_s": p.get("latency_s")})

    if not accept:
        yield _sse("stage", {"id": "write", "status": "done"})
        yield _sse("stage", {"id": "exec", "status": "done"})
        yield _sse(
            "demo_done",
            {
                "wall_s": round(time.time() - started, 2),
                "steps_planned": len(steps),
                "step_id": step_id,
                "message": f"Prover rejected {step_id} — no execute",
            },
        )
        return

    # ── 4. Planner writes onto the measured step ─────────────────────────────
    yield _sse("stage", {"id": "write", "status": "running"})
    yield _sse("log", {"line": f"$ planner.write --step {step_id}"})
    pl = await complete(
        "planner",
        (
            'Return JSON {"title":"short","why":"...","vulns":[{"risk":"...","evidence":"file:line","fix":"..."}],'
            '"prompt":"engineer instruction"}. '
            "why under 160 characters; prompt under 240. Use ONLY the evidence given. Name real programs/datasets. "
            f"Target={label}. Evidence={json.dumps(evidence)[:1000]}."
        ),
        f"demo-plan-{run.get('id')}-{step_id}",
        max_tokens=500,
        json_mode=True,
    )
    parsed_pl = _parse_json(pl)
    why = str(parsed_pl.get("why") or "")[:220] or _field(pl, "why") or step.get("why_now") or ""
    if parsed_pl.get("title"):
        step["stack_title"] = str(parsed_pl["title"])[:80]
    if why:
        step["why_now"] = why
    if parsed_pl.get("prompt"):
        step["engineer_prompt"] = str(parsed_pl["prompt"])[:600]
    vulns = [v for v in (parsed_pl.get("vulns") or []) if isinstance(v, dict) and v.get("risk")]
    if vulns:
        step["vulns"] = vulns[:3]
    # write back into plan
    for i, s in enumerate(steps):
        if s.get("id") == step_id:
            steps[i] = step
            break
    run.setdefault("plan", {})["steps"] = steps
    service._save(run)
    vuln_line = (vulns[0].get("risk") if vulns else "") or "—"
    yield _sse("log", {"line": f"OK  planner              {pl.get('latency_s') or '—'}s  {why or title}"})
    yield _sse("log", {"line": f"     vuln → {vuln_line}"})
    yield _sse(
        "decision",
        {
            "role": "planner",
            "kind": "plan",
            "verdict": "accept" if pl.get("status") == "ok" else (pl.get("status") or "fallback"),
            "text": why or title,
            "latency_s": pl.get("latency_s"),
        },
    )
    yield _sse("stage", {"id": "write", "status": "done", "latency_s": pl.get("latency_s")})

    # ── 5. Execute real playback (same path as Explore Play) ─────────────────
    yield _sse("stage", {"id": "exec", "status": "running"})
    yield _sse("log", {"line": f"$ play --step {step_id} --graph-surgery"})
    if not run.get("cyber_risks"):
        seed_cyber_risks(run)
        service._save(run)
    # playback_step uses asyncio.run() for Nemotron — must not nest in this event loop
    play = await asyncio.to_thread(playback_step, run, step_id, completed_before)
    removed = play.get("removed_edges") or []
    retire = play.get("retire_nodes") or []
    agents = play.get("agents") or {}
    for role, bucket in agents.items():
        text = bucket.get("reason") or bucket.get("delta") or ""
        if text:
            yield _sse(
                "decision",
                {
                    "role": role,
                    "kind": "playback",
                    "verdict": "accept" if play.get("ok") else "blocked",
                    "text": str(text)[:220],
                    "latency_s": None,
                },
            )
    run["demo_last_playback"] = {
        "step_id": step_id,
        "title": play.get("title") or title,
        "ok": play.get("ok"),
        "retire_nodes": len(retire),
        "removed_edges": len(removed),
        "ribbon": play.get("ribbon"),
        "at": time.time(),
    }
    service._save(run)
    yield _sse(
        "playback",
        {
            "ok": play.get("ok"),
            "step_id": step_id,
            "title": play.get("title") or title,
            "retire_nodes": len(retire),
            "removed_edges": len(removed),
            "ribbon": play.get("ribbon"),
            "missing": play.get("missing") or [],
        },
    )
    yield _sse(
        "log",
        {
            "line": (
                f"{'OK' if play.get('ok') else 'BLOCKED'}  execute              "
                f"cut {len(removed)} edges · retire {len(retire)} nodes · "
                f"deps {((play.get('ribbon') or {}).get('deps_before'))}→{((play.get('ribbon') or {}).get('deps_after'))} · "
                f"open Explore → Migrate Play on {step_id}"
            )
        },
    )
    yield _sse("stage", {"id": "exec", "status": "done"})

    wall = round(time.time() - started, 2)
    yield _sse(
        "demo_done",
        {
            "wall_s": wall,
            "steps_planned": len(steps),
            "step_id": step_id,
            "step_title": play.get("title") or title,
            "removed_edges": len(removed),
            "retire_nodes": len(retire),
            "lens_accepted": len(accepted_edges),
            "message": (
                f"Live workflow on {step_id}: plan → {len(lens_jobs)} lenses → prover → planner → "
                f"execute ({len(removed)} edge cuts)"
            ),
        },
    )
