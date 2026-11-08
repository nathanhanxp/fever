"""Target layer, migration edges, matrix tasks, waves, ledger, PDF."""

from __future__ import annotations

import json
import uuid
from pathlib import Path

from app.core.config import DATA_DIR
from app.legacy.engine import Builder, _pdf, apply_order, invalid_order, validate_steps, work_order
from app.services.agents.gateway import complete
from app.services.parser.cobol_parser import LEGACY_EDGE_TYPES, parse_legacy_project

LENSES = ["API", "Data", "Code", "Platform", "Batch", "Integration", "Security", "Compliance"]
EDGE_LENS = {
    "TRANS": "API", "SCREEN": "API", "LINK": "API", "XCTL": "API", "COPY": "API",
    "FILE": "Data", "CALL": "Code", "JOB": "Batch",
}
RUNS: dict[str, dict] = {}


def _path(run_id: str) -> Path:
    folder = DATA_DIR / "runs"
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{run_id}.json"


def _save(run: dict) -> None:
    RUNS[run["id"]] = run
    _path(run["id"]).write_text(json.dumps(run))


def _load(run_id: str) -> dict:
    if run_id in RUNS:
        return RUNS[run_id]
    path = _path(run_id)
    if not path.exists():
        raise KeyError(run_id)
    run = json.loads(path.read_text())
    RUNS[run_id] = run
    return run


def _license_text(root: Path) -> tuple[str, str]:
    for name in ("LICENSE", "LICENSE.md", "license"):
        path = root / name
        if path.exists():
            text = path.read_text(errors="replace")[:1500]
            low = text.lower()
            kind = "MIT" if "mit license" in low else "Apache-2.0" if "apache" in low else "see LICENSE"
            return kind, text
    return "unknown", ""


def open_tree(root: Path, display_name: str) -> dict:
    units, edges, builder = parse_legacy_project(str(root))
    builder.prove_all()
    plan = builder.plan()
    rules = builder.rules()
    violations = validate_steps(plan["steps"])
    bad = invalid_order(plan["steps"])
    _, bad_why = apply_order(plan["steps"], bad)
    license_kind, license_body = _license_text(root)
    clusters: dict[str, list] = {}
    for node in builder.nodes.values():
        clusters.setdefault(node.get("cluster") or "other", []).append(node["id"])
    legacy_edges = []
    for edge in builder.edges:
        if edge.get("type") not in LEGACY_EDGE_TYPES:
            continue
        legacy_edges.append({
            "id": edge["id"],
            "source": edge["source"],
            "target": edge["target"],
            "type": edge["type"],
            "file": edge.get("file") or "",
            "line": edge.get("line") or 0,
            "snippet": (edge.get("snippet") or "")[:240],
            "lens": EDGE_LENS.get(edge["type"], "Code"),
        })
    run_id = uuid.uuid4().hex[:12]
    run = {
        "id": run_id,
        "repo": display_name,
        "root": str(root),
        "license": license_kind,
        "license_excerpt": license_body[:400],
        "target_stack": {
            "language": "Java 21",
            "framework": "Spring Boot",
            "database": "PostgreSQL",
            "api": "REST",
            "runtime": "containers",
            "scheduler": "workflow scheduler",
        },
        "nodes": list(builder.nodes.values()),
        "legacy_edges": legacy_edges,
        "units": len(units),
        "parsed_edges": len(edges),
        "clusters": sorted(clusters),
        "cluster_members": clusters,
        "rules": rules,
        "findings": builder.findings,
        "plan": plan,
        "violations": violations,
        "illegal_order": bad,
        "illegal_reason": bad_why,
        "target_nodes": [],
        "migration_edges": [],
        "rejections": [],
        "tasks": [],
        "ledger": [],
        "summary": "",
    }
    _save(run)
    return {"id": run_id, "repo": display_name, "license": license_kind, "clusters": run["clusters"], "legacy_edges": len(legacy_edges), "units": len(units)}


def get_run(run_id: str) -> dict:
    return _load(run_id)


def set_stack(run_id: str, stack: dict) -> dict:
    run = _load(run_id)
    run["target_stack"].update({k: v for k, v in stack.items() if v})
    _save(run)
    return run["target_stack"]


def _snippets_for(run: dict, cluster: str, lens: str) -> list[dict]:
    members = set(run["cluster_members"].get(cluster, []))
    rows = []
    for edge in run["legacy_edges"]:
        if edge["lens"] != lens and not (lens == "API" and edge["type"] in {"COPY", "LINK", "XCTL", "TRANS", "SCREEN"}):
            if edge["source"] not in members and edge["target"] not in members:
                continue
            if EDGE_LENS.get(edge["type"]) != lens:
                continue
        elif edge["source"] not in members and edge["target"] not in members:
            continue
        rows.append(edge)
        if len(rows) >= 8:
            break
    return rows


def _prove(edge: dict, allowed: set[str], rules: list[str]) -> str | None:
    if not edge.get("evidence_ids"):
        return "missing evidence lines"
    if not edge.get("rule"):
        return "missing rule or authority"
    unknown = [item for item in edge["evidence_ids"] if item not in allowed]
    if unknown:
        return "citation not in the provided snippets: " + ", ".join(unknown)
    if edge["rule"] not in rules and edge["rule"] not in {"detector", "source line"}:
        return "rule is not in the detector catalog"
    return None


async def run_matrix(run_id: str, backend: str = "nvidia", max_tasks: int | None = None):
    run = _load(run_id)
    rule_names = [r.get("rule") or r.get("id") or "detector" for r in run["rules"][:40]] or ["detector"]
    tasks = []
    for cluster in run["clusters"]:
        for lens in LENSES:
            tasks.append((cluster, lens))
    if max_tasks is not None:
        tasks = tasks[:max_tasks]
    run["tasks"] = [{"cluster": c, "lens": lens, "status": "queued"} for c, lens in tasks]
    _save(run)
    summaries = []
    for cluster, lens in tasks:
        snippets = _snippets_for(run, cluster, lens)
        task = next(t for t in run["tasks"] if t["cluster"] == cluster and t["lens"] == lens)
        if not snippets:
            task["status"] = "empty"
            task["count"] = 0
            task["severity"] = "empty"
            _save(run)
            yield {"type": "cell", **task}
            continue
        listing = "\n".join(
            f"s{i} {row['file']}:{row['line']} {row['type']} {row['source']} -> {row['target']} {row['snippet'][:120]}"
            for i, row in enumerate(snippets[:4])
        )
        allowed = {f"s{i}" for i in range(min(4, len(snippets)))}
        snippets = snippets[:4]
        prompt = (
            f"Lens {lens}. Stack {run['target_stack']['language']} {run['target_stack']['framework']}. "
            "Return one JSON object with keys targets, edges, summary. "
            "Each edge uses evidence_ids from the snippet ids below, rule detector, plus risk, action, and confidence. "
            "Cite only those ids.\n"
            + listing
        )
        code_hash = "|".join(allowed) + cluster + lens
        result = await complete("lens", prompt, code_hash, backend=backend, json_mode=True)
        task["model"] = result.get("model")
        task["latency_s"] = result.get("latency_s")
        task["prompt_tokens"] = result.get("prompt_tokens")
        task["completion_tokens"] = result.get("completion_tokens")
        task["status"] = result.get("status")
        if result.get("status") != "ok":
            task["count"] = 0
            task["severity"] = "empty"
            task["label"] = result.get("status")
            _save(run)
            yield {"type": "cell", **task}
            continue
        try:
            parsed = json.loads(result["text"])
        except json.JSONDecodeError:
            task["status"] = "rejected by prover"
            task["count"] = 0
            task["severity"] = "empty"
            run["rejections"].append({"cluster": cluster, "lens": lens, "reason": "response was not JSON"})
            _save(run)
            yield {"type": "cell", **task}
            continue
        accepted = 0
        worst = "green"
        for edge in parsed.get("edges") or []:
            if not edge.get("rule") and edge.get("rule_detector"):
                edge["rule"] = "detector"
            reason = _prove(edge, allowed, rule_names + ["detector", "source line"])
            if reason:
                run["rejections"].append({"cluster": cluster, "lens": lens, "reason": reason, "edge": edge})
                continue
            ids = edge["evidence_ids"]
            evidence = []
            for sid in ids:
                src = snippets[int(sid[1:])]
                evidence.append({"id": sid, "file": src["file"], "line": src["line"], "snippet": src["snippet"]})
            target_name = edge.get("target") or f"{lens.lower()}-target"
            if not any(n["name"] == target_name for n in run["target_nodes"]):
                run["target_nodes"].append({
                    "id": "tgt:" + uuid.uuid4().hex[:8],
                    "name": target_name,
                    "kind": "target",
                    "lens": lens,
                    "cluster": cluster,
                    "label": "Predicted",
                })
            target = next(n for n in run["target_nodes"] if n["name"] == target_name)
            conf = edge.get("confidence")
            try:
                conf = float(conf)
            except (TypeError, ValueError):
                conf = None
            severity = "amber"
            if conf is not None and conf < 0.45:
                severity = "red"
            elif conf is not None and conf >= 0.75:
                severity = "green"
            if severity == "red":
                worst = "red"
            elif severity == "amber" and worst != "red":
                worst = "amber"
            run["migration_edges"].append({
                "id": "m" + uuid.uuid4().hex[:8],
                "lens": lens,
                "cluster": cluster,
                "legacy": edge.get("legacy") or snippets[0]["source"],
                "target": target["id"],
                "target_name": target_name,
                "evidence": evidence,
                "risk": edge.get("risk") or "",
                "action": edge.get("action") or "",
                "confidence": conf,
                "rule": edge.get("rule"),
                "severity": severity,
                "label": "Predicted",
                "resolved": False,
            })
            accepted += 1
        task["count"] = accepted
        task["severity"] = worst if accepted else "empty"
        task["status"] = "measured-call" if accepted else "rejected by prover"
        if parsed.get("summary"):
            summaries.append(str(parsed["summary"])[:240])
        _save(run)
        yield {"type": "cell", **task}
    run["summary"] = summaries[0] if summaries else "No lens accepted a proposal with evidence."
    _save(run)
    yield {"type": "summary", "text": run["summary"]}


def matrix(run_id: str) -> dict:
    run = _load(run_id)
    return {
        "repo": run["repo"],
        "license": run["license"],
        "summary": run.get("summary") or "",
        "clusters": run["clusters"],
        "lenses": LENSES,
        "tasks": run.get("tasks") or [],
        "target_stack": run["target_stack"],
    }


def graph(run_id: str, lens: str | None = None) -> dict:
    run = _load(run_id)
    edges = run["migration_edges"]
    if lens and lens != "All":
        edges = [e for e in edges if e["lens"] == lens]
    return {
        "nodes": [{"id": n["id"], "name": n.get("name"), "kind": n.get("kind"), "cluster": n.get("cluster"), "hub_score": n.get("hub_score", n.get("degree", 0)), "file": n.get("file"), "line": n.get("line")} for n in run["nodes"]],
        "legacy_edges": run["legacy_edges"],
        "target_nodes": run["target_nodes"],
        "migration_edges": edges,
    }


def file_at(run_id: str, file: str, line: int) -> dict:
    run = _load(run_id)
    path = Path(run["root"]) / file
    if not path.exists() or not path.resolve().is_relative_to(Path(run["root"]).resolve()):
        return {"file": file, "line": line, "text": ""}
    rows = path.read_text(errors="replace").splitlines()
    start = max(1, line - 3)
    chunk = rows[start - 1: line + 3]
    return {"file": file, "line": line, "text": "\n".join(f"{start+i}: {row}" for i, row in enumerate(chunk))}


def waves(run_id: str) -> dict:
    run = _load(run_id)
    steps = []
    for step in run["plan"].get("steps", []):
        steps.append({
            "id": step.get("id"),
            "title": step.get("title"),
            "retires": [row.get("id") for row in step.get("removals", []) if row.get("id")],
            "resolves": [],
            "bridges": step.get("add_nodes") or [],
            "requires": step.get("requires") or [],
            "unblocks": step.get("unblocks") or [],
            "drivers": step.get("drivers") or [],
            "evidence_refs": [f"{row.get('file')}:{row.get('line')}" for row in step.get("removals", [])[:8]],
            "why": step.get("why") or step.get("title") or "",
        })
    return {"steps": steps, "illegal_order": run.get("illegal_order"), "illegal_reason": run.get("illegal_reason"), "violations": run.get("violations")}


def reorder(run_id: str, order: list[str]) -> dict:
    run = _load(run_id)
    _ordered, reasons = apply_order(run["plan"]["steps"], order)
    return {"accepted": not reasons, "reasons": reasons}


def work(run_id: str, step_id: str) -> dict:
    run = _load(run_id)
    stack = run["target_stack"]
    model = {
        "repo": run["repo"],
        "plan": run["plan"],
        "rules": run["rules"],
        "brief": {"target": ", ".join(f"{k} {v}" for k, v in stack.items())},
        "ledger": [row for row in run["ledger"] if row.get("decision") == "Preserve"],
    }
    text = work_order(model, step_id)
    preserved = [row for row in run["ledger"] if row.get("decision") == "Preserve"]
    if preserved:
        text += "\n\nAcceptance tests from Preserve decisions:\n"
        for row in preserved:
            text += f"- {row.get('rule')} must still hold ({row.get('who')} at {row.get('when')})\n"
    return {"step_id": step_id, "prompt": text, "label": "Predicted"}


def decide(run_id: str, body: dict) -> dict:
    run = _load(run_id)
    from datetime import datetime, timezone
    row = {
        "rule": body.get("rule"),
        "decision": body.get("decision"),
        "who": body.get("who") or "reviewer",
        "when": datetime.now(timezone.utc).isoformat(),
        "file": body.get("file"),
        "line": body.get("line"),
    }
    run["ledger"].append(row)
    _save(run)
    return row


def behavior_cards(run_id: str) -> list[dict]:
    run = _load(run_id)
    cards = []
    for finding in run["findings"]:
        lens = (finding.get("lens") or "").lower()
        if lens not in {"data", "code", "arithmetic"} and finding.get("type") not in {"rounded", "comp3", "redefines", "date"}:
            title = finding.get("title") or ""
            if not any(word in title.lower() for word in ("round", "decimal", "date", "redefine", "packed", "null", "space")):
                continue
        cards.append({
            "id": finding.get("id"),
            "rule": finding.get("rule") or finding.get("title"),
            "title": finding.get("title"),
            "file": finding.get("file"),
            "line": finding.get("line"),
            "snippet": finding.get("snippet"),
            "label": "Predicted",
            "example_in": finding.get("example_in") or "",
            "example_out": finding.get("example_out") or "",
        })
    return cards[:40]


def pdf(run_id: str) -> bytes:
    run = _load(run_id)
    lines = [
        f"Modernization Swarm — {run['repo']}",
        "Labels: Predicted from the model, Measured from a detector re-run, Candidate when unproven.",
        "Indicative only. This is not a compliance determination.",
        run.get("summary") or "",
        "",
        "Matrix lenses: " + ", ".join(LENSES),
    ]
    for step in run["plan"].get("steps", []):
        lines += ["", f"Wave {step['id']}: {step['title']}", step.get("detail") or ""]
        for row in step.get("removals", [])[:8]:
            lines.append(f"retire {row.get('file')}:{row.get('line')} {row.get('type')}")
    lines.append("")
    lines.append("Ledger")
    for row in run["ledger"]:
        lines.append(f"{row.get('decision')} {row.get('rule')} by {row.get('who')} at {row.get('when')}")
    if not run["ledger"]:
        lines.append("No Preserve / Change / Retire decisions yet.")
    lines.append("")
    lines.append("Limits: no live CICS region. Dead code stays Candidate. Vultr chat returned 401 in the probe.")
    return _pdf(lines)


def impact_for_wave(run_id: str, step_id: str) -> dict:
    """GraphDev-style overlay without a git checkout: red changed, amber neighbors, dim rest."""
    run = _load(run_id)
    step = next((s for s in run["plan"].get("steps", []) if s.get("id") == step_id), None)
    if not step:
        return {"changed": [], "ripple": [], "resolved": []}
    changed = set()
    for row in step.get("removals", []):
        if row.get("source"):
            changed.add(row["source"])
        if row.get("target"):
            changed.add(row["target"])
    ripple = set()
    for edge in run["legacy_edges"]:
        if edge["source"] in changed:
            ripple.add(edge["target"])
        if edge["target"] in changed:
            ripple.add(edge["source"])
    ripple -= changed
    resolved = [e["id"] for e in run["migration_edges"] if e.get("cluster") and step.get("title")]
    return {"changed": sorted(changed), "ripple": sorted(ripple), "resolved_migration_ids": resolved[:20], "label": "Predicted"}
