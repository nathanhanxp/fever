# Fever

**Build agents and tools that accelerate legacy system modernization.**

The world runs on old software. Fever makes it easier to **understand**, **improve**, or **replace**.

Fever turns a COBOL/CICS mainframe sample (AWS CardDemo) or a Java forum zip (JForum) into a measured dependency graph, then runs a Nemotron agent swarm that plans cutovers, proves order constraints, projects post-migration cyber risk, and plays the migration on a live 3D graph.

HackUTD 2026 · Zero Day — targeting **8090 Solutions**, **NVIDIA (Nemotron)**, and **Vultr**.

---

## Purpose

Legacy systems are not “tech debt slides.” They are production graphs: copybooks, transactions, screens, batch jobs, controllers, and auth gates that nobody wants to cut in the wrong order.

Fever’s job:

1. **Parse** the legacy tree into Measured edges (COPY / CALL / LINK / XCTL / FILE / JOB / TRANS / SCREEN, plus Java equivalents).
2. **Plan** a dependency-safe migration into a target stack the user picks (Spring, Quarkus, ASP.NET + Azure SQL, …).
3. **Prove** illegal order before cutover (What-if / Prover).
4. **Show** risk that only appears *after* modernization (orange unauthenticated API boundaries, purple transit exposure) with primary-source citations — not vibe CVEs.

---

## 8090 track — novelties

[8090 Solutions](https://zeroday.hackutd.co/) asks for agents and tools that accelerate legacy modernization: make old software easier to understand, improve, or replace.

What Fever adds beyond a chat box on a repo:

| Novelty | What it means in the product |
| --- | --- |
| **Measured graph, not vibes** | Deterministic parsers build the edge set. UI labels **Measured** vs **Predicted** vs **Candidate** so judges can see what was detected vs projected. |
| **Cut-safe migration waves** | Planner emits ordered steps with requires / unblocks. Illegal order is rejected; What-if simulates “step 18 before 3” and flashes the fault. |
| **Play on the living graph** | Each Play step retires nodes/edges in the 3D view with glow — modernization you can watch, not a PDF checklist. |
| **Post-migration cyber horizon** | Orange = API/authz drift when TRANS/controllers become REST. Purple = FILE/JOB paths going real-time without TLS. Grounded in OWASP / stack docs, filtered to the *source* language (no COBOL links on JForum). |
| **Target-aware Plan** | Live web research for *this* target, then Nemotron rewrites step titles/whys/prompts for that stack. |
| **Ask grounded in the graph** | Scope tools resolve clusters/edges from the measured graph; vision is for colors/glow, not inventing a 1-node “api” cluster. |

---

## NVIDIA track — Nemotron beyond a chatbot

In addition to using **Nemotron**, the track requires more than prompt→reply:

### Beyond a chatbot
Fever is an operator console: upload → graph → Plan → Play → What-if → PDF. Chat/Ask is one surface; the swarm drives the graph and migration state.

### Multi-step workflows
Coordinator → Analyst → Prover loops on each wave. Planner chunks research + evidence into stack-specific steps. Scope agent expands a question into node/edge isolates before answering.

### Tool integration
- Graph + edge/node audit APIs  
- Live web research at Plan time  
- Primary-source page fetch + CISA KEV (context, not COBOL CVEs)  
- Explorer tools over the measured graph  
- Canvas capture → **Nemotron Omni VLM** (“NVIDIA sees”) for colors / clusters / Play glow  

### Real-world applicability
CardDemo (COBOL/CICS credit-card demo) and JForum (Java/VRaptor forum) are real legacy shapes: shared layouts, auth gates, persistence ports. The same plane plans a cut to Spring/Postgres, Quarkus, or C# / ASP.NET / Azure SQL.

Models are routed through `modswarm/backend/app/services/agents/gateway.py` (NVIDIA integrate API + optional Vultr), with probe results in `model_probe.json`.

---

## Vultr

Vultr is used as the **high-concurrency Nemotron host** for swarm fan-out — when infrastructure should not be the bottleneck.

- Gateway can target Vultr’s OpenAI-compatible endpoint (`VULTR_BASE_URL` / `VULTR_API_KEY` / `VULTR_MODEL`).
- Workflow / matrix paths fan agent tasks across threads; cache + semaphore keep the swarm honest under load.
- Benchmarks and probe scripts measure wall-clock as concurrency rises (see gateway bench helpers and `scripts/probe_models.py`).

Set keys in `.env` (never commit them). Prefer Vultr for parallel Planner / Play loops; NVIDIA for Omni VLM and fallback completions.

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

Load samples:

- `POST /api/preset/carddemo` — AWS CardDemo (COBOL/CICS)
- Upload a zip — e.g. JForum

Then: **Migrate → pick a target → Plan → Play**. Use **What-if** for illegal order. **Ask** for scoped graph questions. **NVIDIA sees** captures the canvas for Omni.

---

## Architecture (technical)

| Layer | Location |
| --- | --- |
| UI | `modswarm/frontend` — Next.js + R3F graph |
| API | `modswarm/backend` — FastAPI |
| Legacy parsers | `modswarm/backend/app/legacy` + `services/parser` |
| Migration plane | `modswarm/backend/app/services/migration/` (plan, cyber, what-if, web research, sources) |
| Agents / Nemotron | `modswarm/backend/app/services/agents/` + `services/llm/nemotron.py` |
| CardDemo tree | `aws-mainframe-modernization-carddemo-main/` (upstream license) |

Fever’s app tree is a GraphDev (MIT) fork extended with the migration / swarm plane.

### Claim labels

- **Measured** — detector hit or logged Nemotron call  
- **Predicted** — graph / What-if / cyber horizon (orange / purple)  
- **Candidate** — unused / external-only reachability  

### Limits

No CICS runtime. Dead code stays Candidate. Layout is geometric; edge colors are dependency types. Package CVE feeds do not “cover” COBOL — KEV is stack-adjacent context only. Source-language filters keep Java inspect cards on Spring/OWASP, not CardDemo READMEs.

---

## License / attribution

- Fever application code in this repo: see project license / hackathon submission.  
- GraphDev base: MIT (GitLab Inc. / Zelong Wang).  
- AWS CardDemo sample: upstream AWS Samples license in that directory.
