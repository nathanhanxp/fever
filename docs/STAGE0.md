# Stage 0 — GraphDev unchanged, then model probe

GraphDev (`35368827-main/graphdev`, MIT, GitLab Inc. / Zelong Wang) was read as shipped. It was not modified.

`POST /api/repos` clones a git URL into `REPOS_DIR` and stores a `Repo`. `POST /api/repos/{id}/sync` walks commits, checks each SHA out, and calls `parse_project` (tree-sitter TypeScript) to snapshot `CodeUnit` and `GraphEdge` rows. `POST /api/repos/analyze-by-url` combines create, sync, and enrichment.

`POST /api/repos/{id}/analyze-mr` loads the latest snapshot on the target branch, diffs `.ts`/`.tsx` via git when `changed_files` is empty, and calls `analyze_mr`. The row stores `risk_level` and `report_json`. `GET /mrs` and `GET /mrs/{id}` list and fetch those reports.

`impact.py` rebuilds a temp tree of the changed files plus symlinks to unchanged sources, re-parses, and diffs qualnames into added, modified, and deleted. Direct callers and callees become the changed set; a bounded BFS marks amber ripple nodes. Hub nodes (`hub_score` above a threshold) raise risk. Cluster labels come from `ClusterMember`. New units can be described and embedded, then placed with the saved UMAP reducers. The overlay is red (changed), amber (ripple), and dim (the rest).

`POST /api/repos/{id}/chat` streams Server-Sent Events from the OpenAI Responses API (`gpt-5.4-mini`) with `vector_search` and `graph_traverse`. The system prompt is built from unit counts, edge counts, and cluster labels. `:::flow` blocks are rewritten from `#N` indexes to stored ids.

`scripts/probe_models.py` calls each candidate on NVIDIA and Vultr for a plain completion, a JSON-schema object, and a tool call. Results are measured HTTP outcomes in `model_probe.json`. The gateway reads that file when it assigns a model to a role. Roles are marked feasible only when that probe returned a successful response.

Measured on this machine: `nvidia/nemotron-3-nano-30b-a3b` returns HTTP 410 (end of life). `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning` and `nvidia/nemotron-3.5-bolt-e4b` succeed at completion, JSON schema, and tool calling, so coordinator, describer, namer, lens, skeptic, planner, analyst, and explorer are feasible on NVIDIA. `nvidia/nemotron-3-embed-1b` returns vectors of size 2048. The configured Vultr key returns HTTP 401 on chat completions, so Vultr roles are not feasible until that key is accepted. GraphDev’s process was not started here because `sqlmodel` is not installed in the system Python; the source was read in place.
