"""Swarm summary, benchmark trigger, waves, findings, and eval seeds."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from sqlmodel import Session, select

from app.core.database import get_session
from app.models import Repo
from app.services.agents.gateway import complete_vision, load_thread_matrix, parallel_benchmark, swarm_payload
from app.services.migration import service

router = APIRouter(prefix="/api/repos/{repo_id}", tags=["swarm"])


class VisionIn(BaseModel):
    image: str  # data:image/...;base64,... or raw base64
    note: str | None = None
    question: str | None = None
    step_id: str | None = None
    # Ground-truth cluster palette from the live graph (fixes VLM color mixups)
    clusters: list[dict] | None = None


def _run_for(repo_id: str) -> dict | None:
    for run in service.RUNS.values():
        if run.get("repo_id") == repo_id:
            return run
    from app.core.config import DATA_DIR
    folder = DATA_DIR / "runs"
    if not folder.exists():
        return None
    for path in folder.glob("*.json"):
        data = json.loads(path.read_text())
        if data.get("repo_id") == repo_id:
            service.RUNS[data["id"]] = data
            return data
    return None


def _require_run(repo_id: str) -> dict:
    run = _run_for(repo_id)
    if not run:
        raise HTTPException(404, "No migration run for this repo — open CardDemo or upload a zip first")
    if run["id"] not in service.RUNS:
        service.RUNS[run["id"]] = run
    return service.get_run(run["id"]) if run["id"] in service.RUNS else run


@router.get("/swarm")
def swarm(repo_id: str, session: Session = Depends(get_session)):
    if not session.get(Repo, repo_id):
        raise HTTPException(404, "Repo not found")
    payload = swarm_payload()
    run = _run_for(repo_id)
    payload["summary"] = (run or {}).get("summary") or ""
    payload["rejections"] = (run or {}).get("rejections") or []
    payload["run_id"] = (run or {}).get("id")
    payload["plan_steps"] = len(((run or {}).get("plan") or {}).get("steps") or [])
    payload["demo_last_playback"] = (run or {}).get("demo_last_playback")
    payload["finding_counts"] = {
        "total": len((run or {}).get("findings") or []),
        "rejected": len([f for f in ((run or {}).get("findings") or []) if f.get("verdict") == "rejected"]),
    }
    payload["limits"] = [
        "Indicative only. No compliance claim.",
        "Dead code stays Candidate.",
        "Predicted = graph/simulator. Measured = detector re-run or logged Nemotron call.",
        "Thinking mode is disabled so answers land in message content.",
    ]
    cached = load_thread_matrix()
    payload["vultr_thread_matrix"] = (cached or {}).get("vultr_thread_matrix")
    payload["benchmark_measured_at"] = (cached or {}).get("measured_at")
    return payload


@router.post("/swarm/benchmark")
async def swarm_benchmark(repo_id: str, session: Session = Depends(get_session), focus: str = "both"):
    if not session.get(Repo, repo_id):
        raise HTTPException(404, "Repo not found")
    backends = ["vultr"] if focus == "vultr" else ["nvidia"] if focus == "nvidia" else ["nvidia", "vultr"]
    return await parallel_benchmark(backends=backends, concurrencies=[1, 2, 4, 8])


@router.post("/swarm/demo")
async def swarm_demo(repo_id: str, session: Session = Depends(get_session)):
    """Judge demo: run a live multi-step agent workflow and stream stage events."""
    if not session.get(Repo, repo_id):
        raise HTTPException(404, "Repo not found")
    run = _require_run(repo_id)
    from fastapi.responses import StreamingResponse
    from app.services.migration.demo import stream_architecture_demo

    async def gen():
        async for chunk in stream_architecture_demo(run):
            yield chunk

    return StreamingResponse(gen(), media_type="text/event-stream")


@router.post("/vision/graph")
async def vision_graph(repo_id: str, body: VisionIn, session: Session = Depends(get_session)):
    """Nemotron Omni VLM reads a live graph screenshot (colors, clusters, Play glow)."""
    if not session.get(Repo, repo_id):
        raise HTTPException(404, "Repo not found")
    image = (body.image or "").strip()
    if not image:
        raise HTTPException(400, "image required")
    if not image.startswith("data:"):
        image = f"data:image/png;base64,{image}"
    # Cap ~1.8MB data URL to stay under typical gateway limits
    if len(image) > 1_800_000:
        raise HTTPException(400, "screenshot too large — zoom out or lower quality")

    clusters = body.clusters or []
    palette_lines = []
    for c in clusters[:24]:
        label = str(c.get("label") or "?")
        hue_name = str(c.get("hue_name") or c.get("color_name") or "colored")
        css = str(c.get("color") or "")
        count = c.get("count")
        palette_lines.append(f"- {hue_name} cluster → label “{label}” ({count} units) css={css}")

    legend = (
        "OVERLAY legend (glow on top of cluster colors — do not confuse with clusters):\n"
        "- Soft sky / cyan glow = current Play step cut.\n"
        "- Orange glow = predicted API / authz risk.\n"
        "- Purple/violet glow = predicted transit / TLS risk.\n"
        "- Red = measured legacy finding.\n"
        "- Cluster body colors are the palette below — NOT the overlay glow.\n"
        "Color naming rules (important):\n"
        "- pink / magenta / fuchsia / hot-pink ≈ hue 300–340 — NEVER call these green.\n"
        "- green / lime ≈ hue 90–150.\n"
        "- yellow / gold ≈ hue 40–70.\n"
        "- blue / cyan ≈ hue 180–240.\n"
        "- When the operator names a color, answer with the matching palette row.\n"
    )
    prompt = (
        "You are looking at a live 3D code-dependency graph for mainframe modernization.\n"
        f"{legend}\n"
    )
    if palette_lines:
        prompt += "GROUND-TRUTH cluster palette from the renderer (authoritative):\n"
        prompt += "\n".join(palette_lines) + "\n\n"
    q = (body.question or body.note or "").strip()
    if q:
        prompt += (
            f"Operator question: {q[:500]}\n"
            "Answer that question first using the ground-truth palette. "
            "If they ask about pink/magenta, pick the pink/magenta palette row — do not substitute green.\n"
            "Then add at most 3 short supporting observations from the image.\n"
        )
    else:
        prompt += (
            "Describe briefly (5–8 sentences):\n"
            "1) Clusters by palette color name + label.\n"
            "2) Any Play/risk glow (sky/orange/purple) separate from cluster colors.\n"
            "3) One modernization pitfall visible in the structure.\n"
            "Do not invent CVE IDs. Prefer Measured vs Predicted language.\n"
        )
    if body.step_id:
        prompt += f"\nCurrent playback step id: {body.step_id}\n"

    result = await complete_vision(prompt, image, backend="nvidia")
    return {
        "ok": result.get("status") == "ok",
        "text": result.get("text") or "",
        "error": result.get("error"),
        "model": result.get("model"),
        "latency_s": result.get("latency_s"),
        "claim": "Measured",
        "prompt_tokens": result.get("prompt_tokens"),
        "completion_tokens": result.get("completion_tokens"),
        "palette": clusters[:24],
    }


@router.get("/waves")
def repo_waves(repo_id: str, session: Session = Depends(get_session)):
    if not session.get(Repo, repo_id):
        raise HTTPException(404, "Repo not found")
    run = _require_run(repo_id)
    return service.waves(run["id"]) | {"run_id": run["id"]}


@router.get("/waves/{step_id}/impact")
def repo_wave_impact(repo_id: str, step_id: str, session: Session = Depends(get_session)):
    if not session.get(Repo, repo_id):
        raise HTTPException(404, "Repo not found")
    run = _require_run(repo_id)
    return service.impact_for_wave(run["id"], step_id)


@router.get("/findings")
def repo_findings(repo_id: str, session: Session = Depends(get_session)):
    if not session.get(Repo, repo_id):
        raise HTTPException(404, "Repo not found")
    run = _require_run(repo_id)
    return service.findings_panel(run["id"]) | {"run_id": run["id"]}


@router.get("/brief")
def repo_brief(repo_id: str, session: Session = Depends(get_session)):
    """What you're migrating to, what will bite you, what it means for the business."""
    if not session.get(Repo, repo_id):
        raise HTTPException(404, "Repo not found")
    run = _require_run(repo_id)
    from app.services.migration.brief import build_brief
    from app.services.migration.cyber import _is_java_run, cyber_map_for_ui, seed_cyber_risks, stack_docs_for
    # Refresh so Java runs never keep stale mainframe-worded predictions
    seed_cyber_risks(run)
    service._save(run)
    brief = build_brief(run)
    brief["cyber_map"] = cyber_map_for_ui(run)
    brief["cyber_risks"] = (run.get("cyber_risks") or [])[:24]
    brief["target_stack"] = run.get("target_stack") or {}
    docs = run.get("stack_docs") or stack_docs_for(run.get("target_stack") or {})
    if _is_java_run(run):
        from app.services.migration.service import _scrub_java_stack_docs
        docs = _scrub_java_stack_docs(docs)
        # Before Plan: also hide target-stack ASP.NET/Azure pages
        if not run.get("user_planned"):
            docs = [
                d for d in docs
                if not any(
                    k in (d.get("url") or "").lower()
                    for k in ("aspnet", "azure-sql", "/dotnet/")
                )
            ]
    brief["stack_docs"] = docs
    brief["stack_nemotron"] = run.get("stack_nemotron")
    brief["user_planned"] = bool(run.get("user_planned"))
    return brief


class StackBody(BaseModel):
    description: str | None = None
    language: str | None = None
    framework: str | None = None
    database: str | None = None
    api: str | None = None
    runtime: str | None = None
    scheduler: str | None = None


@router.post("/stack")
def repo_stack(repo_id: str, body: StackBody, session: Session = Depends(get_session)):
    """Save Migrating-to stack, rewrite plan text, return stack-specific docs + Nemotron guidance."""
    if not session.get(Repo, repo_id):
        raise HTTPException(404, "Repo not found")
    run = _require_run(repo_id)
    return service.set_stack(run["id"], {k: v for k, v in body.model_dump().items() if v})


class PlayBody(BaseModel):
    completed: list[str] = []


@router.post("/waves/{step_id}/play")
def play_wave(repo_id: str, step_id: str, body: PlayBody | None = None, session: Session = Depends(get_session)):
    """Play one migration step: Coordinator + Analyst + Prover loops, return dim/retire sets."""
    if not session.get(Repo, repo_id):
        raise HTTPException(404, "Repo not found")
    run = _require_run(repo_id)
    from app.services.migration.cyber import playback_step, seed_cyber_risks
    if not run.get("cyber_risks"):
        seed_cyber_risks(run)
        service._save(run)
    completed = (body.completed if body else []) or []
    return playback_step(run, step_id, completed)


class WhatIfBody(BaseModel):
    text: str | None = None
    order: list[str] | None = None


@router.post("/what-if")
def what_if(repo_id: str, body: WhatIfBody, session: Session = Depends(get_session)):
    """Simulate a reordered plan until the first precondition fault — for the graph What-if panel."""
    if not session.get(Repo, repo_id):
        raise HTTPException(404, "Repo not found")
    run = _require_run(repo_id)
    from app.services.migration.what_if import simulate
    return simulate(run, order=body.order, text=body.text)


@router.get("/edges/audit")
def edge_audit_card(repo_id: str, key: str, session: Session = Depends(get_session)):
    """Primary-source verification card for a clicked edge."""
    if not session.get(Repo, repo_id):
        raise HTTPException(404, "Repo not found")
    run = _require_run(repo_id)
    from app.services.migration.cyber import edge_audit, seed_cyber_risks
    if not run.get("cyber_risks"):
        seed_cyber_risks(run)
        service._save(run)
    return edge_audit(run, key)


@router.get("/nodes/audit")
def node_audit_card(repo_id: str, key: str, session: Session = Depends(get_session)):
    """Info card for a clicked node: edges, predicted cyber risk, plan steps, sources, live KEV."""
    if not session.get(Repo, repo_id):
        raise HTTPException(404, "Repo not found")
    run = _require_run(repo_id)
    from app.services.migration.cyber import node_audit, seed_cyber_risks
    if not run.get("cyber_risks"):
        seed_cyber_risks(run)
        service._save(run)
    return node_audit(run, key)


@router.get("/migration")
def migration(repo_id: str, session: Session = Depends(get_session)):
    if not session.get(Repo, repo_id):
        raise HTTPException(404, "Repo not found")
    run = _run_for(repo_id)
    if not run:
        raise HTTPException(404, "No migration run")
    loaded = service.get_run(run["id"]) if run["id"] not in service.RUNS else run
    if run["id"] not in service.RUNS:
        service.RUNS[run["id"]] = loaded
    return service.matrix(run["id"]) | {"run_id": run["id"], "rejections": loaded.get("rejections", [])}


@router.get("/report.pdf")
def report(repo_id: str, session: Session = Depends(get_session)):
    if not session.get(Repo, repo_id):
        raise HTTPException(404, "Repo not found")
    run = _run_for(repo_id)
    if not run:
        raise HTTPException(404, "No migration run")
    data = service.pdf(run["id"])
    return Response(content=data, media_type="application/pdf")


@router.get("/eval")
def eval_page(repo_id: str, session: Session = Depends(get_session)):
    if not session.get(Repo, repo_id):
        raise HTTPException(404, "Repo not found")
    from app.models import CodeUnit, ProjectGraphSnapshot
    snap = session.exec(
        select(ProjectGraphSnapshot).where(ProjectGraphSnapshot.repo_id == repo_id).order_by(ProjectGraphSnapshot.created_at.desc())
    ).first()
    names = []
    if snap:
        rows = session.exec(select(CodeUnit).where(CodeUnit.snapshot_id == snap.id).limit(10)).all()
        names = [u.symbol_name for u in rows]
    questions = [
        {"id": i + 1, "question": f"Where is {name} defined?", "expected": [name], "label": "Measured"}
        for i, name in enumerate(names)
    ]
    labels = Path(__file__).resolve().parents[5] / "docs" / "labels.csv"
    return {
        "questions": questions,
        "prover": "awaiting labels" if not labels.exists() else "labels file present",
        "labels_path": "docs/labels.csv",
    }

