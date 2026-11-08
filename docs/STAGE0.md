# Stage 0 — GraphDev base, then model probe

GraphDev (MIT, GitLab Inc. / Zelong Wang) was the starting point. Its app lives in this repo as `modswarm/` (frontend + backend). The original `35368827-main` zip was removed after confirming every GraphDev path already existed under `modswarm/`.

`POST /api/repos` clones a git URL into `REPOS_DIR` and stores a `Repo`. `POST /api/repos/{id}/sync` walks commits, checks each SHA out, and calls `parse_project` (tree-sitter TypeScript) to snapshot `CodeUnit` and `GraphEdge` rows. `POST /api/repos/analyze-by-url` combines create, sync, and enrichment.

`POST /api/repos/{id}/analyze-mr` loads the latest snapshot on the target branch, diffs `.ts`/`.tsx` via git when `changed_files` is empty, and calls `analyze_mr`. The row stores `risk_level` and `report_json`. `GET /mrs` and `GET /mrs/{id}` list and fetch those reports.

`impact.py` rebuilds a temp tree of the changed files plus symlinks to unchanged sources, re-parses, and diffs qualnames into added, modified, and deleted. Direct callers and callees become the changed set; a bounded BFS marks amber ripple nodes. Hub nodes (`hub_score` above a threshold) raise risk. Cluster labels come from `ClusterMember`. New units can be described and embedded, then placed with the saved UMAP reducers. The overlay is red (changed), amber (ripple), and dim (the rest).

`POST /api/repos/{id}/chat` streams Server-Sent Events. Modernization Swarm routes those calls through the Nemotron gateway (NVIDIA / optional Vultr) instead of OpenAI.

`scripts/probe_models.py` calls each candidate on NVIDIA and Vultr for a plain completion, a JSON-schema object, and a tool call. Results are measured HTTP outcomes in `model_probe.json` at the repo root. The gateway reads that file when it assigns a model to a role.
