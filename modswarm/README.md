# Modernization Swarm

Adaptation of [GraphDev](https://gitlab.com) (MIT). Copyright (c) 2026-present GitLab Inc. Author Zelong Wang. See `LICENSE` and `NOTICE`.

GraphDev mapped a TypeScript repository into a semantic graph and answered questions with an OpenAI model. Modernization Swarm keeps that graph, hub scores, and the explore layout, and adds a second plane: proposed target components for a stack you can edit. The default stack is Java 21, Spring Boot, PostgreSQL, REST, containers, and a workflow scheduler.

## What changed from GraphDev

- OpenAI and the GitLab sample remote are not used. Calls go to NVIDIA's Nemotron endpoint. Vultr Serverless Inference is selectable at `https://api.vultrinference.com/v1` when its key is accepted.
- `POST /api/upload` accepts a zip (COBOL, copybooks, JCL, BMS, CSD, markdown, `LICENSE`) with path and size caps. `POST /api/preset/carddemo` opens the local CardDemo tree. The header shows the repository name and the license read from `LICENSE`.
- Legacy parsing is the ported `Builder` (`app/legacy/`, from this repo's `backend/app/parse.py` and `engine.py`). It emits GraphDev `ParsedUnit` / `ParsedEdge` rows for COPY, CALL, LINK, XCTL, FILE, JOB, TRANS, and SCREEN, with file, line, and snippet.
- Eight lens tasks propose target nodes and dashed migration edges. A prover drops any edge that lacks a snippet id from the prompt or a detector rule, and stores the rejection.
- The first screen is a cluster-by-lens matrix filled from a server-sent stream. A cell shows the count and the worst severity. The tooltip shows the model, latency, and token counts returned by the API.
- Waves come from the ported planner. Reordering through `POST /api/runs/{id}/waves/order` is refused when `validate_steps` finds a precondition that is out of order, and the response includes that reason.
- Preserve / Change / Retire decisions are appended to the work-order prompt. The PDF is one document with a page per block of lines, including each wave's removals.
- `model_probe.json` at the repository root chooses the model per role. A missing key is reported as `not configured`. Numbers on screen are the HTTP payload or an empty cell, not an estimate.

## Run

```bash
cd modswarm/backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --port 8090
```

Open `http://127.0.0.1:8090/swarm`.

The original GraphDev screens remain in `frontend/`. They still expect a TypeScript repository and the enrichment extras (`umap-learn`, `hdbscan`, `tree-sitter`).

## Probe

From the repository root, `python3 scripts/probe_models.py` rewrites `model_probe.json`. On the last run, NVIDIA `nemotron-3-nano-omni-30b-a3b-reasoning` completed plain text, JSON, and tool calls. Embeddings from `nemotron-3-embed-1b` were length 2048. The configured Vultr key returned HTTP 401, so Vultr roles are not feasible until that key is accepted.
