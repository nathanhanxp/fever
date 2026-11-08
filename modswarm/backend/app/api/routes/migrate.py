"""Migration graph, matrix stream, waves, ledger, PDF."""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel

from app.services.migration import service

router = APIRouter(prefix="/api/runs", tags=["migrate"])


@router.get("/by-repo/{repo_id}")
def by_repo(repo_id: str):
    for run_id in list(service.RUNS):
        if service.RUNS[run_id].get("repo_id") == repo_id:
            return {"id": run_id}
    from pathlib import Path
    from app.core.config import DATA_DIR
    folder = DATA_DIR / "runs"
    if folder.exists():
        for path in folder.glob("*.json"):
            import json
            data = json.loads(path.read_text())
            if data.get("repo_id") == repo_id:
                service.RUNS[data["id"]] = data
                return {"id": data["id"]}
    raise HTTPException(404, "No migration run for this repo")


class StackIn(BaseModel):
    language: str | None = None
    framework: str | None = None
    database: str | None = None
    api: str | None = None
    runtime: str | None = None
    scheduler: str | None = None


class OrderIn(BaseModel):
    order: list[str]


class DecisionIn(BaseModel):
    rule: str
    decision: str
    who: str = "reviewer"
    file: str | None = None
    line: int | None = None


def _run(run_id: str) -> dict:
    try:
        return service.get_run(run_id)
    except KeyError as exc:
        raise HTTPException(404, "Run not found") from exc


@router.get("/{run_id}")
def fetch(run_id: str):
    _run(run_id)
    return service.matrix(run_id)


@router.post("/{run_id}/stack")
def stack(run_id: str, body: StackIn):
    _run(run_id)
    return service.set_stack(run_id, body.model_dump())


@router.get("/{run_id}/graph")
def graph(run_id: str, lens: str = "All"):
    _run(run_id)
    return service.graph(run_id, lens)


@router.get("/{run_id}/file")
def code(run_id: str, file: str, line: int = 1):
    _run(run_id)
    return service.file_at(run_id, file, line)


@router.get("/{run_id}/matrix/stream")
async def stream(run_id: str, backend: str = "nvidia", max_tasks: int | None = None):
    _run(run_id)

    async def gen():
        async for event in service.run_matrix(run_id, backend=backend, max_tasks=max_tasks):
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream")


@router.get("/{run_id}/waves")
def wave_list(run_id: str):
    _run(run_id)
    return service.waves(run_id)


@router.post("/{run_id}/waves/order")
def wave_order(run_id: str, body: OrderIn):
    _run(run_id)
    return service.reorder(run_id, body.order)


@router.get("/{run_id}/waves/{step_id}/impact")
def impact(run_id: str, step_id: str):
    _run(run_id)
    return service.impact_for_wave(run_id, step_id)


@router.get("/{run_id}/waves/{step_id}/work-order")
def order(run_id: str, step_id: str):
    _run(run_id)
    return service.work(run_id, step_id)


@router.get("/{run_id}/ledger")
def ledger(run_id: str):
    _run(run_id)
    return {"cards": service.behavior_cards(run_id), "decisions": service.get_run(run_id)["ledger"]}


@router.post("/{run_id}/ledger")
def decide(run_id: str, body: DecisionIn):
    _run(run_id)
    if body.decision not in {"Preserve", "Change", "Retire"}:
        raise HTTPException(400, "Decision must be Preserve, Change, or Retire")
    return service.decide(run_id, body.model_dump())


@router.get("/{run_id}/pdf")
def pdf(run_id: str):
    _run(run_id)
    data = service.pdf(run_id)
    return Response(content=data, media_type="application/pdf")
