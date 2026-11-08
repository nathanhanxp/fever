# Fever

The world runs on old software. Fever makes it easier to **understand**, **improve**, or **replace**.

Fever turns a legacy codebase or an uploaded zip into a **measured** dependency graph, then runs a Nemotron agent swarm that plans cutovers, proves order, projects post-migration cyber risk, and **plays** the migration on a live 3D graph.

---

## Purpose

Legacy systems are production graphs, not slideware: copybooks, transactions, screens, batch jobs, controllers, auth gates. Cutting them in the wrong order is how migrations die.

Fever’s loop:

1. **Parse** → Measured edges (COPY / CALL / LINK / XCTL / FILE / JOB / TRANS / SCREEN, plus Java controller / interceptor / JPA shapes).
2. **Plan** → Dependency-safe waves aimed at a user-chosen target stack (Spring, Quarkus, ASP.NET + Azure SQL, …).
3. **Prove** → Illegal order blocked; What-if simulates “step 18 before 3” and shows the fault on the graph.
4. **Play** → Each wave retires nodes/edges in the 3D view with glow so cutover is visible, not a checklist.
5. **Cite** → Predicted cyber horizons (orange API/authz drift, purple transit) attach primary docs filtered to the *source* language.

---

## What’s novel

Most “AI modernization” tools chat over files. Fever treats modernization as a **graph surgery** problem with explicit claim types.

**Measured vs Predicted vs Candidate.** Detectors own Measured edges. The swarm and cyber horizon own Predicted claims. Reachability leftovers stay Candidate. The UI never collapses those into one confidence bar.

**The graph is the runtime.** Plan steps are not prose — they carry `requires` / `unblocks`, removals, and bridges. Play mutates the same graph the parsers built. What-if reorders waves and animates which edges would break.

**Post-migration cyber, not “scan the zip for CVEs.”** Orange risks appear when TRANS / controllers become public REST without re-applying authz. Purple risks appear when FILE/JOB paths go real-time without TLS. Wording and sources follow the source language (VRaptor / Spring / OWASP on JForum — never CardDemo/CICS paste on a Java repo).

**Target-conditioned planning.** Plan does live web research for *this* target, then Nemotron rewrites step titles, whys, vulns, and coding-agent prompts so a Quarkus plan does not silently reuse an ASP.NET one.

**Ask is scoped, not vision-only.** A screenshot can tell Nemotron Omni what colors/glow are on screen. Cluster membership and “API-related” isolates come from graph tools over Measured edges — so Ask cannot invent a one-node `api` cluster from pixels.

---

## Nemotron

We chose Nemotron because the workload is **agentic and multimodal**, not a single chat completion:

| Role | Model / path | Why that call exists |
| --- | --- | --- |
| **Planner** | Nemotron (JSON mode, chunked) | Rewrite waves for a concrete target using live research + step evidence — not generic “dependency order” filler. |
| **Coordinator / Analyst / Prover** | Nemotron on each Play step | Sequencing, risk delta, and gatekeeping illegal cuts with file:line evidence. |
| **Scope** | Nemotron + graph tools | Turn a natural-language question into a node/edge isolate before answering. |
| **Explain** | Short Nemotron blurbs | Why this node/edge exists, cached on the run. |
| **Omni VLM** | Nemotron 3 Nano Omni | “NVIDIA sees”: read a live canvas capture (colors, clusters, Play glow) when the question is visual. |
| **Embed / rerank** | Nemotron embed endpoints | Ground Prover-style claims against fetched doc passages where configured. |

**Why not “one big prompt”?** Legacy cutover has irreversible order constraints. We keep parsers deterministic, put LLMs on *rewrite / judge / scope / see*, and label every claim. Gateway code (`modswarm/backend/app/services/agents/gateway.py`) selects backend + model from probe results (`model_probe.json`), caches completions, and semaphores concurrency so the swarm stays measurable.

Tooling the models actually call: graph + edge/node audit APIs, explorer search, live web research at Plan time, primary-source page fetch, CISA KEV as stack-adjacent context (not a COBOL CVE substitute).

---

## How we use Vultr (and why)

Swarm fan-out is the bottleneck if every Planner chunk and Play loop serializes on one key. Vultr’s OpenAI-compatible GPU/serverless endpoint is the **parallel Nemotron host**.

- Configure `VULTR_BASE_URL` / `VULTR_API_KEY` / `VULTR_MODEL` in `.env`.
- Gateway routes high-concurrency roles (mapper / planner chunks / Play loops) to Vultr when configured; NVIDIA remains the path for Omni VLM and fallback.
- `parallel_benchmark` in the gateway measures wall-clock for the same Nemotron ping at concurrency 1→8 with unique cache keys — so we can show that parallelism actually drops wall time instead of inventing a “scale story.”
- `scripts/probe_models.py` records measured HTTP outcomes (completion, JSON schema, tool call) per host so role→model assignment is evidence-backed.

**Why Vultr specifically:** OpenAI-compatible drop-in for the same Nemotron prompts we already write for NVIDIA, without rewriting the swarm, while giving us a second throttle domain for fan-out.

---

## Run

```bash
# API
cd modswarm/backend
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --port 8090

# UI (separate terminal)
cd modswarm/frontend
npm install
npm run dev
```

Open the Next app (usually http://localhost:3000).

Copy `.env.example` → `.env` at the repo root for NVIDIA / Vultr keys. **Do not commit `.env`.**

Load samples: `POST /api/preset/carddemo`, or upload a zip (e.g. JForum). Then **Migrate → Plan → Play**. Use **What-if** for illegal order, **Ask** for scoped graph questions, **NVIDIA sees** for Omni on a canvas capture.

---

## Architecture

| Layer | Path |
| --- | --- |
| UI | `modswarm/frontend` — Next.js + React Three Fiber |
| API | `modswarm/backend` — FastAPI |
| Parsers | `modswarm/backend/app/legacy`, `services/parser` |
| Migration plane | `services/migration/` — plan, cyber, what-if, web research, sources, report |
| Agents | `services/agents/` — gateway, scope, explorer |
| LLM | `services/llm/nemotron.py` |
| CardDemo sample | `aws-mainframe-modernization-carddemo-main/` (upstream license) |

App shell is a GraphDev (MIT) fork; Fever is the migration / swarm plane on top.

### Claim labels

- **Measured** — detector or logged Nemotron call  
- **Predicted** — graph / What-if / cyber horizon (orange / purple)  
- **Candidate** — unused / external-only reachability  

### Limits

No CICS runtime. Dead code stays Candidate. Layout is geometric; edge colors are dependency types. Package CVE feeds do not cover COBOL. Source-language filters keep Java inspect cards on Spring/OWASP, not mainframe READMEs.


