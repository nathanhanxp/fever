# Modernization Swarm

A swarm-style reader for AWS CardDemo. Deterministic parsers build COPY, CALL, LINK, XCTL, FILE, JOB, TRANS, and SCREEN edges. A prover drops findings that lack a source line and an authority. A planner turns the detected graph into ordered steps and rejects an illegal reordering. The 3D view is a new implementation of the instanced-node, typed-edge, lerp-to-target idea. It is not a copy of GraphDev.

CardDemo stays under its Apache-2.0 license in `aws-mainframe-modernization-carddemo-main`. The sample’s uneven style is intentional. Findings are detector output.

## Run

```bash
python3 -m venv backend/.venv
backend/.venv/bin/pip install -r backend/requirements.txt
backend/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000

cd frontend && npm install && npm run dev
```

Open http://127.0.0.1:5173. The API loads CardDemo on startup. Copy `.env.example` to `.env` if you want the optional NVIDIA benchmark. Do not commit `.env`.

## What is labeled

- **Measured** — a detector ran on source, or re-ran on a patched copy held in memory. The repo is not modified.
- **Predicted** — graph queries, ripple, roadmap risk, and optimizations. No speedup is claimed.
- **Candidate** — unused paragraphs and anything that could be reached from outside the repo.

## Limits

There is no CICS runtime here, so online programs are not executed. Dead code stays a candidate. Layout is by name and directory; the colored edges are the dependencies. Counts are detected edges, not effort or time. OSV, KEV, and EPSS are not used: they do not cover COBOL. Vultr serverless and a Vultr GPU are not called unless you set `VULTR_BASE_URL` and `VULTR_API_KEY`. The NeMo Agent Toolkit is not used.
