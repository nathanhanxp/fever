"""HTTP API for the modernization swarm. Facts are computed locally; model calls are optional."""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import time
import uuid
import zipfile
from io import BytesIO
from pathlib import Path

import httpx
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse, Response, StreamingResponse
from pydantic import BaseModel

from .engine import apply_brief, apply_order, ask, build_run, simulate_node, work_order
from .swarm import run_tasks

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")
CARDDEMO = Path(os.environ.get("CARDDEMO_ROOT", ROOT / "aws-mainframe-modernization-carddemo-main"))
if not CARDDEMO.is_absolute():
    CARDDEMO = (ROOT / CARDDEMO).resolve()
ACTIVE = {"root": Path(os.environ.get("SOURCE_ROOT", ROOT / "jforum3-master"))}
if not ACTIVE["root"].is_absolute():
    ACTIVE["root"] = (ROOT / ACTIVE["root"]).resolve()
WORKSPACES = ROOT / "backend" / ".workspaces"
KEEP_SUFFIXES = {".cbl", ".cpy", ".jcl", ".bms", ".csd", ".md", ".java"}

app = FastAPI(title="Modernization Swarm")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

STATE: dict = {"status": "idle", "model": None, "error": "", "events": []}


class AskBody(BaseModel):
    question: str
    depth: int = 2
    types: list[str] | None = None


class BriefBody(BaseModel):
    target: str = ""
    where: str = ""
    downtime: str = ""
    rules: list[dict] = []


class OrderBody(BaseModel):
    order: list[str]


class WeightsBody(BaseModel):
    weights: dict[str, float]


def _events_from(model: dict) -> list[dict]:
    events = [{"type": "status", "status": "running", "message": f"Swarm started on {model.get('repo', 'repository')}"}]
    for agent in model["agents"]:
        events.append({"type": "agent", "phase": "start", **agent})
        events.append({"type": "agent", "phase": "done", **agent})
    events.append({
        "type": "graph",
        "nodes": model["stats"]["programs"],
        "edges": model["stats"]["edges"],
        "message": "Detected graph ready",
    })
    events.append({"type": "status", "status": "done", "message": "Discover finished"})
    return events


def _rebuild() -> None:
    STATE["status"] = "running"
    STATE["error"] = ""
    try:
        model = build_run(ACTIVE["root"], with_benchmark=True)
        STATE["model"] = model
        STATE["events"] = _events_from(model)

        def on_row(row: dict) -> None:
            current = STATE.get("model")
            if not current:
                return
            agents = current["agents"]
            for i, existing in enumerate(agents):
                if existing["id"] == row["id"]:
                    agents[i] = row
                    break
            else:
                agents.append(row)
            STATE["events"].append({"type": "agent", "phase": "done", **{k: v for k, v in row.items() if k != "output"}, "output": row.get("output", "")})

        rows = asyncio.run(run_tasks(model, on_row))
        model["agents"] = [a for a in model["agents"] if a.get("group") != "nemotron"] + rows
        STATE["model"] = model
        STATE["status"] = "done"
    except Exception as exc:  # noqa: BLE001 — surface the message to the UI
        STATE["status"] = "error"
        STATE["error"] = str(exc)


@app.on_event("startup")
async def startup() -> None:
    asyncio.get_event_loop().run_in_executor(None, _rebuild)


@app.get("/api/health")
def health():
    return {
        "ok": True,
        "status": STATE["status"],
        "carddemo": str(CARDDEMO),
        "carddemo_exists": CARDDEMO.exists(),
        "root": str(ACTIVE["root"]),
        "repo": ACTIVE["root"].name,
        "nvidia_configured": bool(os.environ.get("NVIDIA_API_KEY") or os.environ.get("NEMOTRON_API_KEY")),
        "vultr_configured": bool(os.environ.get("VULTR_BASE_URL") and os.environ.get("VULTR_API_KEY")),
    }


@app.get("/api/run")
def get_run():
    if STATE["status"] == "error":
        raise HTTPException(500, STATE["error"])
    if STATE["model"] is None:
        return {"status": STATE["status"]}
    return {"status": STATE["status"], **STATE["model"]}


@app.post("/api/upload")
async def upload(request: Request):
    raw = await request.body()
    if len(raw) > 200 * 1024 * 1024:
        raise HTTPException(413, "zip exceeds 200 MB")
    try:
        zf = zipfile.ZipFile(BytesIO(raw))
    except zipfile.BadZipFile as exc:
        raise HTTPException(400, "not a zip") from exc
    wid = uuid.uuid4().hex[:12]
    dest = WORKSPACES / wid
    dest.mkdir(parents=True, exist_ok=True)
    kept = 0
    total = 0
    for info in zf.infolist():
        if info.is_dir():
            continue
        name = info.filename.replace("\\", "/")
        parts = Path(name).parts
        if not name or name.startswith("/") or ".." in parts:
            shutil.rmtree(dest, ignore_errors=True)
            raise HTTPException(400, "zip path rejected")
        mode = (info.external_attr >> 16) & 0o170000
        if mode == 0o120000:
            continue
        suffix = Path(name).suffix.lower()
        if suffix not in KEEP_SUFFIXES and Path(name).name not in {"LICENSE", "license.txt"}:
            continue
        if kept >= 8000:
            break
        data = zf.read(info)
        if total + len(data) > 200 * 1024 * 1024:
            break
        total += len(data)
        target = dest / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        kept += 1
    if kept == 0:
        shutil.rmtree(dest, ignore_errors=True)
        raise HTTPException(400, "This analyzer reads COBOL, JCL, BMS and copybooks")
    for child in WORKSPACES.iterdir() if WORKSPACES.exists() else []:
        if child.resolve() != dest.resolve():
            shutil.rmtree(child, ignore_errors=True)
    ACTIVE["root"] = dest
    asyncio.get_event_loop().run_in_executor(None, _rebuild)
    return {"message": f"Rebuilding. Kept {kept} source files.", "files": kept}


@app.post("/api/reset")
async def reset():
    ACTIVE["root"] = CARDDEMO
    if WORKSPACES.exists():
        shutil.rmtree(WORKSPACES, ignore_errors=True)
    asyncio.get_event_loop().run_in_executor(None, _rebuild)
    return {"message": "Reset to CardDemo. Rebuilding."}


@app.post("/api/analyze")
async def analyze():
    if STATE["status"] == "running":
        return {"status": "running"}
    asyncio.get_event_loop().run_in_executor(None, _rebuild)
    return {"status": "running"}


@app.get("/api/events")
async def events():
    async def gen():
        cursor = 0
        while True:
            batch = STATE["events"]
            while cursor < len(batch):
                yield f"data: {json.dumps(batch[cursor])}\n\n"
                cursor += 1
            if STATE["status"] in {"done", "error"} and cursor >= len(STATE["events"]):
                yield f"data: {json.dumps({'type': 'end', 'status': STATE['status']})}\n\n"
                break
            await asyncio.sleep(0.2)

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.get("/api/file")
def file(path: str):
    root = ACTIVE["root"].resolve()
    target = (root / path).resolve()
    if not str(target).startswith(str(root)) or not target.is_file():
        raise HTTPException(404, "file not in the active tree")
    text = target.read_text(encoding="utf-8", errors="replace")
    return {"path": path, "text": text}


@app.get("/api/files")
def files():
    model = STATE["model"]
    if not model:
        return {"files": []}
    paths = sorted({n["file"] for n in model["nodes"] if n.get("file")})
    return {"files": paths}


@app.post("/api/ask")
def post_ask(body: AskBody):
    model = STATE["model"]
    if not model:
        raise HTTPException(409, "analysis not ready")
    return ask(model, body.question, body.depth, body.types)


@app.post("/api/simulate/{node_id:path}")
def post_simulate(node_id: str, depth: int = 3):
    model = STATE["model"]
    if not model:
        raise HTTPException(409, "analysis not ready")
    if not any(n["id"] == node_id for n in model["nodes"]):
        raise HTTPException(404, "node not found")
    return simulate_node(model, node_id, depth)


@app.post("/api/brief")
def post_brief(body: BriefBody):
    model = STATE["model"]
    if not model:
        raise HTTPException(409, "analysis not ready")
    for rule in model["rules"]:
        match = next((r for r in body.rules if r.get("id") == rule["id"]), None)
        if match and match.get("decision") in {"Preserve", "Change", "Retire"}:
            rule["decision"] = match["decision"]
    model["brief"] = {"target": body.target, "where": body.where, "downtime": body.downtime, "asked": True}
    version = apply_brief(model, {"target": body.target, "where": body.where, "downtime": body.downtime, "rules": model["rules"]})
    model["plan_version"] = version["version"]
    model["plan_versions"].append({
        "version": version["version"],
        "reason": version["reason"],
        "steps": [s["id"] + " " + s["title"] for s in version["steps"]],
    })
    # Recommendations change. Edge facts on the base graph stay.
    model["plan"] = {**model["plan"], "steps": version["steps"], "version": version["version"], "reason": version["reason"]}
    return {"version": version["version"], "reason": version["reason"], "plan": model["plan"], "rules": model["rules"]}


@app.post("/api/weights")
def post_weights(body: WeightsBody):
    model = STATE["model"]
    if not model:
        raise HTTPException(409, "analysis not ready")
    for driver in model["drivers"]:
        if driver["id"] in body.weights:
            driver["weight"] = max(0.0, min(5.0, float(body.weights[driver["id"]])))
    total = sum(d["weight"] for d in model["drivers"]) or 1
    score = round(sum(d["weight"] * d["score"] for d in model["drivers"]) / total, 3)
    return {"drivers": model["drivers"], "weighted_score": score, "note": "Weights change emphasis only. Detected edges are unchanged."}


@app.post("/api/validate")
def post_validate(body: OrderBody):
    model = STATE["model"]
    if not model:
        raise HTTPException(409, "analysis not ready")
    ordered, violations = apply_order(model["plan"]["steps"], body.order)
    return {"violations": violations, "order": [s["id"] for s in ordered]}


@app.get("/api/work-order/{step_id}")
def get_work_order(step_id: str):
    model = STATE["model"]
    if not model:
        raise HTTPException(409, "analysis not ready")
    if not any(s["id"] == step_id for s in model["plan"]["steps"]):
        raise HTTPException(404, "step not found")
    return PlainTextResponse(work_order(model, step_id), media_type="text/markdown")


@app.get("/api/roadmap.pdf")
def roadmap_pdf():
    model = STATE["model"]
    if not model:
        raise HTTPException(409, "analysis not ready")
    from .engine import render_pdf
    return Response(render_pdf(model), media_type="application/pdf")


@app.post("/api/benchmark/model")
async def model_benchmark():
    """One short completion per configured backend. Records tokens and wall clock. No COBOL is sent."""
    key = os.environ.get("NVIDIA_API_KEY") or os.environ.get("NEMOTRON_API_KEY")
    base = os.environ.get("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1").rstrip("/")
    candidates = [
        os.environ.get("NVIDIA_MODEL", ""),
        "nvidia/nemotron-3-nano-30b-a3b",
        "nvidia/llama-3.1-nemotron-nano-8b-v1",
        "nvidia/nvidia-nemotron-nano-9b-v2",
    ]
    rows = []
    if not key:
        rows.append({"backend": "nvidia", "status": "not configured", "seconds": None, "tokens": 0})
    else:
        async with httpx.AsyncClient(timeout=40) as client:
            working = None
            for model_id in [c for c in candidates if c]:
                started = time.perf_counter()
                try:
                    res = await client.post(
                        base + "/chat/completions",
                        headers={"Authorization": f"Bearer {key}"},
                        json={
                            "model": model_id,
                            "messages": [{"role": "user", "content": "Reply with the single word OK."}],
                            "max_tokens": 8,
                            "temperature": 0,
                        },
                    )
                    elapsed = round(time.perf_counter() - started, 3)
                    if res.status_code >= 400:
                        rows.append({"backend": "nvidia", "model": model_id, "status": f"http {res.status_code}", "seconds": elapsed, "tokens": 0})
                        continue
                    data = res.json()
                    usage = data.get("usage") or {}
                    tokens = int(usage.get("total_tokens") or 0)
                    rows.append({
                        "backend": "nvidia", "model": model_id, "status": "ok",
                        "seconds": elapsed, "tokens": tokens,
                        "calls_per_second": round(1 / elapsed, 3) if elapsed else None,
                    })
                    working = model_id
                    break
                except Exception as exc:  # noqa: BLE001
                    rows.append({"backend": "nvidia", "model": model_id, "status": str(exc)[:160], "seconds": None, "tokens": 0})
            if working:
                # concurrency 1, 2, 4 of the same tiny call
                for n in (1, 2, 4):
                    started = time.perf_counter()
                    async def one(client=client):
                        res = await client.post(
                            base + "/chat/completions",
                            headers={"Authorization": f"Bearer {key}"},
                            json={
                                "model": working,
                                "messages": [{"role": "user", "content": "Reply with the single word OK."}],
                                "max_tokens": 8,
                                "temperature": 0,
                            },
                        )
                        res.raise_for_status()
                        return res.json().get("usage") or {}
                    try:
                        usages = await asyncio.gather(*[one() for _ in range(n)])
                        elapsed = round(time.perf_counter() - started, 3)
                        tokens = sum(int(u.get("total_tokens") or 0) for u in usages)
                        rows.append({
                            "backend": "nvidia", "model": working, "mode": "parallel",
                            "concurrency": n, "status": "ok", "seconds": elapsed, "tokens": tokens,
                            "calls_per_second": round(n / elapsed, 3) if elapsed else None,
                        })
                    except Exception as exc:  # noqa: BLE001
                        rows.append({"backend": "nvidia", "model": working, "concurrency": n, "status": str(exc)[:160], "tokens": 0})
    vultr = os.environ.get("VULTR_BASE_URL")
    if not vultr:
        rows.append({"backend": "vultr-serverless", "status": "not configured", "note": "Set VULTR_BASE_URL and VULTR_API_KEY. Nano Omni was confirmed on Vultr by the brief; this process has not called it."})
    rows.append({"backend": "vultr-gpu", "status": "not configured", "note": "Level 3 stretch. No GPU endpoint is set."})
    if STATE["model"] is not None:
        STATE["model"].setdefault("model_benchmark", {"rows": []})
        STATE["model"]["model_benchmark"] = {"rows": rows, "at": time.time()}
    return {"rows": rows}
