# Checklist

Evidence is a path. Screenshots from this session are the GraphDev file tree and graph counts at localhost:3000 (405 nodes, 971 edges).

- [x] C1 Model probe — `scripts/probe_models.py`, `model_probe.json`
- [x] C2 Gateway — `modswarm/backend/app/services/agents/gateway.py` (cache, semaphore, probe model)
- [x] C3 Evidence ids — prover in `services/migration/service.py` marks `rejected by prover`
- [x] C4 Trace table — `agent_tasks` in the gateway SQLite; `GET /api/repos/{id}/swarm`
- [x] C5 Agents wired through the gateway; chat and embeddings use Nemotron (`services/llm/nemotron.py`)
- [x] C6 Explorer tools — `services/agents/explorer.py`, called from `api/routes/chat.py`
- [ ] C7 Mock server pytest — not written this session
- [x] D Swarm page — `frontend/src/app/[repo]/swarm/page.tsx`
- [x] E Migration matrix page — `frontend/src/app/[repo]/migration/page.tsx`; lens badges in `graph-toggles.tsx`
- [ ] E Dashed migration edges on the 3D canvas — `graph-canvas.tsx` is frozen by `scripts/ui_guard.sh`, so the canvas cannot be taught a new edge style without failing the guard. Edges are still stored and listed on the Migration page.
- [x] F Waves and illegal order — ported planner via `GET /api/runs/{id}/waves` and `POST /api/runs/{id}/waves/order`
- [ ] F Each wave persisted as its own GraphDev snapshot and MR analysis — not done; one legacy snapshot is stored
- [x] G Ledger API — `POST /api/runs/{id}/ledger`
- [ ] G Issues list on the node card — node card is not in the allowlist
- [x] H PDF export button — `GET /api/repos/{id}/report.pdf` (ported PDF writer, not reportlab)
- [ ] H Work-order zip — work order text exists at `GET /api/runs/{id}/waves/{step}/work-order`; no zip endpoint
- [ ] I Vultr deploy — compose file exists; VM was not deployed. Probe recorded HTTP 401 for the Vultr key.
- [ ] I Benchmark table — page not added because a full 24×4×2 run was not executed, and empty numbers must not be invented
- [x] I Eval page — `frontend/src/app/[repo]/eval/page.tsx` shows graph-derived questions and “awaiting labels”
- [x] Chat empty answer — Nemotron reasoning consumed `max_tokens` and left `content` null (`finish_reason=length`). Calls now disable thinking and retry once without tools.
