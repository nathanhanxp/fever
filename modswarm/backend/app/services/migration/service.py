"""Target layer, migration edges, matrix tasks, waves, ledger, PDF."""

from __future__ import annotations

import json
import random
import re
import time
import uuid
from pathlib import Path

from app.core.config import DATA_DIR
from app.legacy.engine import Builder, _layout, _pdf, apply_order, invalid_order, validate_steps, work_order
from app.services.agents.gateway import complete
from app.services.parser.cobol_parser import LEGACY_EDGE_TYPES, parse_legacy_project

LENSES = ["API", "Data", "Code", "Platform", "Batch", "Integration", "Security", "Compliance"]
EDGE_LENS = {
    "TRANS": "API", "SCREEN": "API", "LINK": "API", "XCTL": "API", "COPY": "API",
    "FILE": "Data", "CALL": "Code", "JOB": "Batch",
}
RUNS: dict[str, dict] = {}
PLAN_FIXTURES = Path(DATA_DIR) / "plan_fixtures"


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
    for name in ("LICENSE", "LICENSE.md", "license", "license.txt", "LICENSE.txt"):
        path = root / name
        if path.exists():
            text = path.read_text(errors="replace")[:1500]
            low = text.lower()
            kind = "Dream"
            if "lgpl" in low:
                kind = "LGPL"
            elif "apache" in low:
                kind = "Dream"
            elif "mit" in low:
                kind = "MIT"
            return kind, text
    return "unknown", ""


def open_tree(root: Path, display_name: str) -> dict:
    units, edges, builder = parse_legacy_project(str(root))
    builder.prove_all()
    _layout(list(builder.nodes.values()))
    plan = builder.plan()
    rules = builder.rules()
    violations = validate_steps(plan["steps"])
    bad = invalid_order(plan["steps"])
    _, bad_why = apply_order(plan["steps"], bad)
    license_kind, license_body = _license_text(root)
    is_java = bool(builder.tree.get("java")) and not builder.tree.get("programs")
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
    # Structural defaults for the Predicted migration layer only — user still must Plan.
    if is_java:
        target_stack = {
            "language": "Java 21",
            "framework": "Quarkus 3",
            "database": "PostgreSQL",
            "api": "JAX-RS",
            "runtime": "containers",
            "scheduler": "Quarkus Scheduler",
        }
    else:
        target_stack = {
            "language": "Java 21",
            "framework": "Spring Boot",
            "database": "PostgreSQL",
            "api": "REST",
            "runtime": "containers",
            "scheduler": "workflow scheduler",
        }
    run = {
        "id": run_id,
        "repo": display_name,
        "root": str(root),
        "license": license_kind,
        "license_excerpt": license_body[:400],
        "target_stack": target_stack,
        # Waves stay hidden until POST /stack (Plan) — avoids "steps before I chose Azure SQL"
        "user_planned": False,

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
    _seed_migration_layer(run)
    from app.services.migration.cyber import seed_cyber_risks
    seed_cyber_risks(run)
    repo_id, snapshot_id = _publish_graph(run)
    run["repo_id"] = repo_id
    run["snapshot_id"] = snapshot_id
    _save(run)
    return {
        "id": run_id,
        "repo_id": repo_id,
        "repo": display_name,
        "license": license_kind,
        "clusters": run["clusters"],
        "legacy_edges": len(legacy_edges),
        "migration_edges": len(run["migration_edges"]),
        "target_nodes": len(run["target_nodes"]),
        "units": len(units),
    }


def _seed_migration_layer(run: dict) -> None:
    """Predicted target plane + dashed migration edges from measured legacy facts.

    This is the visible novelty on Explore: legacy nodes stay left, targets sit on a
    second plane, and colored dashed lines connect them with evidence.
    """
    stack = run["target_stack"]
    by_id = {n["id"]: n for n in run["nodes"]}
    # Prefer high-degree hubs and contract edges so the overlay is readable.
    ranked = sorted(run["legacy_edges"], key=lambda e: -(by_id.get(e["source"], {}).get("degree", 0) + by_id.get(e["target"], {}).get("degree", 0)))
    seen_targets: dict[str, str] = {}
    per_lens: dict[str, int] = {}
    for edge in ranked:
        if len(run["migration_edges"]) >= 96:
            break
        lens = edge.get("lens") or EDGE_LENS.get(edge["type"], "Code")
        if per_lens.get(lens, 0) >= 16:
            continue
        legacy_id = edge["source"] if edge["source"].startswith("pgm:") else edge["target"]
        if not legacy_id.startswith(("pgm:", "job:", "txn:", "map:", "dsn:", "file:")):
            legacy_id = edge["source"]
        legacy = by_id.get(legacy_id) or by_id.get(edge["source"])
        if not legacy:
            continue
        kind_hint = {
            "API": f"REST {legacy.get('name', 'endpoint')}",
            "Data": f"table {legacy.get('name', 'dataset')}",
            "Code": f"module {legacy.get('name', 'service')}",
            "Batch": f"workflow {legacy.get('name', 'job')}",
            "Platform": f"runtime {legacy.get('name', 'service')}",
            "Integration": f"queue {legacy.get('name', 'channel')}",
            "Security": f"identity {legacy.get('name', 'principal')}",
            "Compliance": f"audit {legacy.get('name', 'field')}",
        }.get(lens, f"target {legacy.get('name', 'unit')}")
        key = f"{lens}:{kind_hint}"
        if key not in seen_targets:
            tid = "tgt:" + uuid.uuid4().hex[:8]
            # Second plane: push targets to +X so the graph reads as two layers.
            seen_targets[key] = tid
            run["target_nodes"].append({
                "id": tid,
                "name": kind_hint[:40],
                "kind": "target",
                "lens": lens,
                "cluster": legacy.get("cluster") or "other",
                "label": "Predicted",
                "stack_hint": f"{stack['language']} / {stack['framework']} / {stack['database']}",
                "x": float(legacy.get("x") or 0) + 16,
                "y": float(legacy.get("y") or 0),
                "z": float(legacy.get("z") or 0) + 4,
            })
        tid = seen_targets[key]
        run["migration_edges"].append({
            "id": "m" + uuid.uuid4().hex[:8],
            "lens": lens,
            "cluster": legacy.get("cluster") or "other",
            "legacy": legacy_id if legacy_id in by_id else edge["source"],
            "target": tid,
            "target_name": kind_hint[:40],
            "evidence": [{
                "id": "s0",
                "file": edge.get("file") or "",
                "line": edge.get("line") or 0,
                "snippet": (edge.get("snippet") or "")[:200],
            }],
            "risk": {
                "API": "API regression (field length/type, RESP → HTTP).",
                "Data": "Key semantics / packed-decimal / REDEFINES.",
                "Code": "Arithmetic, GO TO, or control-flow restructuring.",
                "Batch": "Step order, restart, file handoffs.",
                "Platform": "Unit-of-work and locking semantics.",
                "Integration": "External call or messaging contract.",
                "Security": "Sign-on / clear-text compare → IAM.",
                "Compliance": "Sensitive field handling (indicative only).",
            }.get(lens, "Migration risk from detected edge."),
            "action": f"Replace {edge['type']} with {stack['api'] if lens == 'API' else stack['database'] if lens == 'Data' else stack['language']} equivalent.",
            "confidence": 0.55,
            "rule": "detector",
            "severity": "amber",
            "label": "Predicted",
            "resolved": False,
        })
        per_lens[lens] = per_lens.get(lens, 0) + 1
    run["summary"] = (
        f"Predicted migration layer: {len(run['target_nodes'])} target components, "
        f"{len(run['migration_edges'])} dashed migration edges from measured COPY/CALL/FILE/JOB/TRANS facts. "
        f"Default stack {stack['language']} + {stack['framework']}."
    )
    run["welcome_extra"] = run["summary"]


def _publish_graph(run: dict) -> tuple[str, str]:
    """Write the legacy graph into GraphDev's Repo / CodeUnit / GraphEdge tables."""
    from datetime import datetime, timezone

    from sqlmodel import Session

    from app.core.database import engine
    from app.models import ClusterMember, CodeUnit, FeatureCluster, GraphEdge, ProjectGraphSnapshot, Repo

    max_deg = max((n.get("degree") or 0) for n in run["nodes"]) or 1
    with Session(engine) as session:
        repo = Repo(
            name=run["repo"],
            remote_url=None,
            source_root=run["root"],
            welcome_message=(
                f"{run.get('summary') or ''} "
                "License dream. Solid edges = measured legacy dependencies. "
                "Dashed colored edges = Predicted migration to the target plane. "
                "Use FILE/COPY/JOB or API/Data filters on the graph, or Simulate ripple on a selected node."
            ),
        )
        session.add(repo)
        session.commit()
        session.refresh(repo)
        snap = ProjectGraphSnapshot(
            repo_id=repo.id,
            commit_sha="legacy",
            commit_message=f"Parsed legacy graph (Dream)",
            commit_time=datetime.now(timezone.utc),
            branch_name="main",
            units_added=len(run["nodes"]),
        )
        session.add(snap)
        session.commit()
        session.refresh(snap)
        ids: dict[str, str] = {}
        clusters: dict[str, FeatureCluster] = {}
        for node in run["nodes"]:
            unit = CodeUnit(
                snapshot_id=snap.id,
                file_path=node.get("file") or node["id"],
                symbol_name=node.get("name") or node["id"],
                qualname=node["id"],
                kind=node.get("kind") or "program",
                runtime="legacy",
                language="cobol",
                start_line=int(node.get("line") or 1),
                end_line=int(node.get("line") or 1),
                code_hash=node["id"][:16],
                source_text=(node.get("summary") or "")[:4000],
                llm_description=node.get("summary") or None,
                hub_score=round((node.get("degree") or 0) / max_deg, 4),
                x2d=float(node.get("x") or 0),
                y2d=float(node.get("z") or 0),
                x3d=float(node.get("x") or 0),
                y3d=float(node.get("y") or 0),
                z3d=float(node.get("z") or 0),
            )
            session.add(unit)
            session.flush()
            ids[node["id"]] = unit.id
            label = node.get("cluster") or "other"
            if label not in clusters:
                clusters[label] = FeatureCluster(snapshot_id=snap.id, method="legacy-cluster", method_version="1", label=label)
                session.add(clusters[label])
                session.flush()
            session.add(ClusterMember(cluster_id=clusters[label].id, code_unit_id=unit.id))
        for edge in run["legacy_edges"]:
            if edge["source"] not in ids or edge["target"] not in ids:
                continue
            session.add(GraphEdge(
                snapshot_id=snap.id,
                source_unit_id=ids[edge["source"]],
                target_unit_id=ids[edge["target"]],
                edge_type=edge["type"],
            ))
        for index, node in enumerate(run.get("target_nodes") or []):
            unit = CodeUnit(
                snapshot_id=snap.id,
                file_path=f"target/{node['name']}",
                symbol_name=node["name"],
                qualname=node["id"],
                kind="target",
                runtime="target",
                language="java",
                start_line=1,
                end_line=1,
                code_hash=node["id"][:16],
                source_text=node.get("stack_hint") or node["name"],
                llm_description=f"Predicted {node.get('lens')} target · {node.get('stack_hint') or ''}",
                hub_score=0.0,
                x2d=float(node.get("x") or 18),
                y2d=float(node.get("z") or 6),
                x3d=float(node.get("x") or 18),
                y3d=float(node.get("y") or (index * 0.6 - 4)),
                z3d=float(node.get("z") or 6),
            )
            session.add(unit)
            session.flush()
            ids[node["id"]] = unit.id
            label = "target-" + (node.get("lens") or "API")
            if label not in clusters:
                clusters[label] = FeatureCluster(snapshot_id=snap.id, method="migration-target", method_version="1", label=label)
                session.add(clusters[label])
                session.flush()
            session.add(ClusterMember(cluster_id=clusters[label].id, code_unit_id=unit.id))
        for edge in run.get("migration_edges") or []:
            src = ids.get(edge["legacy"])
            dst = ids.get(edge["target"])
            if not src or not dst:
                continue
            session.add(GraphEdge(
                snapshot_id=snap.id,
                source_unit_id=src,
                target_unit_id=dst,
                edge_type="migration-" + edge["lens"],
            ))
        session.commit()
        run["unit_ids"] = ids
        return repo.id, snap.id


def get_run(run_id: str) -> dict:
    return _load(run_id)


def _step_evidence(run: dict, step: dict) -> dict:
    """Real code evidence for one step: cut edges with file:line/snippet and accepted findings on its files."""
    removals = step.get("removals") or []
    names = {str(x).split(":", 1)[-1] for r in removals for x in (r.get("source"), r.get("target")) if x}
    names |= {str(m).split(":", 1)[-1] for m in step.get("migrate") or []}
    files = set(step.get("files") or []) | {r.get("file") for r in removals if r.get("file")}
    findings = [
        f for f in run.get("findings") or []
        if f.get("verdict", "accepted") == "accepted"
        and (f.get("file") in files or any(n and n in (f.get("file") or "") for n in names))
    ]
    return {
        "id": step.get("id"),
        "title": step.get("title"),
        "verb": step.get("verb"),
        "requires": [(r.get("step_id") if isinstance(r, dict) else r) for r in step.get("requires") or []],
        "edge_types": sorted({r.get("type") for r in removals if r.get("type")}),
        "cuts": [
            f"{r.get('type')} {r.get('source')} -> {r.get('target')} at {r.get('file')}:{r.get('line')} "
            f"[{r.get('mechanism') or ''}] `{(r.get('snippet') or '')[:110]}`"
            for r in removals[:4]
        ],
        "findings": [f"{f.get('title')} at {f.get('file')}:{f.get('line')} `{(f.get('snippet') or '')[:80]}`" for f in findings[:3]],
    }


def stack_label(stack: dict) -> str:
    if stack.get("description"):
        return str(stack["description"])
    return " · ".join(str(stack[k]) for k in ("language", "framework", "database", "api") if stack.get(k))


def _infer_stack(stack: dict) -> dict:
    """Expand free-text Plan input (e.g. 'Azure SQL') into a concrete target stack."""
    out = {k: v for k, v in stack.items() if v}
    desc = str(out.get("description") or "").strip()
    blob = " ".join(str(out.get(k) or "") for k in ("description", "language", "framework", "database")).lower()

    def has(*words: str) -> bool:
        return any(w in blob for w in words)

    # Only fill missing fields — presets already send a full stack
    if not out.get("database"):
        if has("azure sql", "azure-sql", "mssql", "sql server"):
            out["database"] = "Azure SQL"
        elif has("cockroach"):
            out["database"] = "CockroachDB"
        elif has("postgres", "postgresql"):
            out["database"] = "PostgreSQL"
        elif has("mysql", "maria"):
            out["database"] = "MySQL"
        elif has("dynamo"):
            out["database"] = "DynamoDB"
        elif has("cosmos"):
            out["database"] = "Azure Cosmos DB"
        elif has("sql") and has("azure"):
            out["database"] = "Azure SQL"

    if not out.get("language"):
        # Order matters: "c++" before "c#"; avoid substring traps
        if re.search(r"\bc\+\+|cpp|cplusplus\b", blob):
            out["language"] = "C++"
        elif re.search(r"\bc#|csharp|\.net\b|dotnet|asp\.net", blob) or has("azure sql", "azure functions"):
            out["language"] = "C#"
        elif has("kotlin"):
            out["language"] = "Kotlin"
        elif re.search(r"\bgo\b|golang", blob):
            out["language"] = "Go"
        elif has("node", "typescript", "javascript"):
            out["language"] = "TypeScript"
        elif has("python"):
            out["language"] = "Python"
        elif has("rust"):
            out["language"] = "Rust"
        elif has("quarkus") or has("spring") or re.search(r"\bjava\b", blob):
            out["language"] = "Java 21"

    if not out.get("framework"):
        if out.get("language") == "C++":
            out["framework"] = "C++ services (REST/gRPC)"
        elif out.get("language") == "C#" or has("asp.net", ".net"):
            out["framework"] = "ASP.NET Core"
        elif has("quarkus"):
            out["framework"] = "Quarkus"
        elif has("spring") or (out.get("language") == "Java 21" and not has("quarkus")):
            out["framework"] = "Spring Boot"
        elif has("fastapi") or out.get("language") == "Python":
            out["framework"] = "FastAPI"
        elif has("express", "nestjs") or out.get("language") == "TypeScript":
            out["framework"] = "NestJS"
        elif out.get("language") == "Go":
            out["framework"] = "gRPC + Go"
        elif out.get("language") == "Rust":
            out["framework"] = "Axum / Actix"

    if not out.get("api"):
        out["api"] = "gRPC" if has("grpc") else "REST"
    if not out.get("runtime"):
        out["runtime"] = "Azure Container Apps" if has("azure") else "containers"
    if not out.get("scheduler"):
        out["scheduler"] = "Azure Functions" if has("azure") else "workflow scheduler"

    if desc and not out.get("description"):
        out["description"] = desc
    elif not out.get("description"):
        out["description"] = stack_label(out)
    return out


def _is_jforum(run: dict) -> bool:
    repo = str(run.get("repo") or "").lower()
    if "jforum" in repo:
        return True
    return any(
        str(n.get("id") or "").startswith("java:") or "jforum" in str(n.get("file") or "").lower()
        for n in (run.get("nodes") or [])[:40]
    )


def _is_csharp_azure_sql(stack: dict) -> bool:
    blob = " ".join(
        str(stack.get(k) or "")
        for k in ("description", "language", "framework", "database", "api")
    ).lower()
    has_net = any(x in blob for x in ("c#", "csharp", "asp.net", ".net", "dotnet"))
    has_azure = "azure sql" in blob or ("azure" in blob and "sql" in blob)
    # preset / typed "Azure SQL" alone expands to C# + ASP.NET + Azure SQL
    return (has_net and has_azure) or blob.strip() in {"azure sql", "c# · asp.net core · azure sql · rest"}


def _load_plan_fixture(name: str) -> dict | None:
    path = PLAN_FIXTURES / name
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def _scrub_java_stack_docs(docs: list[dict]) -> list[dict]:
    """Never let CardDemo / COBOL / CICS pages ride along on a Java plan."""
    out = []
    for d in docs or []:
        blob = f"{d.get('id') or ''} {d.get('title') or ''} {d.get('url') or ''} {d.get('passage') or ''} {d.get('source') or ''}".lower()
        if any(k in blob for k in ("carddemo", "cobol", "cics", "mainframe", "vsam", "aws-m2", "aws-mainframe")):
            continue
        out.append(d)
    return out


def _clear_step_plan_prose(run: dict) -> None:
    """Drop previous target's titles/whys so a new Plan cannot silently reuse them."""
    for step in (run.get("plan") or {}).get("steps") or []:
        for k in ("stack_title", "why_now", "engineer_prompt", "vulns", "target_stack"):
            step.pop(k, None)


def _stamp_step_titles(run: dict, label: str) -> int:
    """Guarantee every step title/why names THIS target so the UI visibly changes between Plans."""
    parts = [p.strip() for p in label.split("·") if p.strip()]
    # Prefer language · framework so Spring vs Quarkus vs .NET are obviously different
    short = " · ".join(parts[:2])[:36] if parts else "target"
    # Require the framework/db token (2nd part) when present — "Java" alone matches every jforum title
    must = parts[1] if len(parts) > 1 else (parts[0] if parts else "target")
    must_tok = re.sub(r"[^A-Za-z0-9+#.]", "", must).lower()
    stamped = 0
    for step in (run.get("plan") or {}).get("steps") or []:
        base = (step.get("stack_title") or step.get("title") or "Cut").strip()
        # Drop prior "→ OtherStack" suffix from a previous Plan
        base = re.sub(r"\s*→\s*.+$", "", base).strip()
        blob = re.sub(r"[^a-z0-9+#.]", "", base.lower())
        if must_tok and must_tok not in blob:
            step["stack_title"] = f"{base} → {short}"
            stamped += 1
        else:
            step["stack_title"] = base
        why = (step.get("why_now") or "").strip()
        if not why or must_tok and must_tok not in re.sub(r"[^a-z0-9+#.]", "", why.lower()):
            step["why_now"] = f"Apply this cut on {label}."
            stamped += 1
        step["target_stack"] = dict(run.get("target_stack") or {})
    return stamped


def _apply_plan_fixture(run: dict, fixture: dict, *, pretend_s: float) -> dict:
    """Apply a locally saved Plan response after a short fake load delay."""
    time.sleep(pretend_s)
    from app.services.migration.cyber import apply_stack_to_plan

    target = dict(fixture.get("target_stack") or run.get("target_stack") or {})
    run["target_stack"] = target
    run["user_planned"] = True
    _clear_step_plan_prose(run)
    apply_stack_to_plan(run)

    research = dict(fixture.get("plan_research") or {})
    research["latency_s"] = round(pretend_s, 2)
    research["claim"] = "Measured web fetch"
    run["plan_research"] = research

    by_id = {s.get("id"): s for s in (fixture.get("steps") or []) if s.get("id")}
    for step in (run.get("plan") or {}).get("steps") or []:
        row = by_id.get(step.get("id")) or {}
        if row.get("stack_title"):
            step["stack_title"] = row["stack_title"]
        if row.get("why_now"):
            step["why_now"] = row["why_now"]
        if row.get("engineer_prompt"):
            step["engineer_prompt"] = row["engineer_prompt"]
        if row.get("vulns"):
            step["vulns"] = row["vulns"]
        step["target_stack"] = dict(target)

    label = stack_label(run["target_stack"])
    rewritten = _stamp_step_titles(run, label)

    nemotron = dict(fixture.get("stack_nemotron") or {})
    nemotron["status"] = "ok"
    nemotron["fixture"] = True
    nemotron["research_sources"] = len(research.get("sources") or [])
    nemotron["research_queries"] = research.get("queries") or nemotron.get("research_queries") or []
    run["stack_nemotron"] = nemotron
    run["stack_docs"] = _scrub_java_stack_docs(list(fixture.get("stack_docs") or []))[:12]
    run["plan_revision"] = {
        "label": label,
        "at": time.time(),
        "fixture": True,
        "rewritten": rewritten,
    }
    run.pop("demo_steps", None)
    _save(run)

    all_steps = (run.get("plan") or {}).get("steps") or []
    prompts = {s["id"]: 1 for s in all_steps if s.get("engineer_prompt")}
    sample = [s.get("stack_title") or s.get("title") for s in all_steps[:3]]
    return {
        "target_stack": run["target_stack"],
        "stack_docs": run["stack_docs"],
        "nemotron": nemotron,
        "research": {
            "queries": research.get("queries") or [],
            "sources": research.get("sources") or [],
            "latency_s": research.get("latency_s"),
        },
        "steps_planned": len(all_steps),
        "prompts_written": len(prompts),
        "label": label,
        "fixture": True,
        "plan_revision": run["plan_revision"],
        "sample_titles": sample,
    }


def set_stack(run_id: str, stack: dict) -> dict:
    """Plan for an arbitrary target: web-search how to get there, then Nemotron writes steps from that research."""
    from app.services.migration.cyber import apply_stack_to_plan, stack_docs_for
    from app.services.migration.web_research import (
        is_banned_guidance,
        research_prompt_block,
        research_stack,
    )

    run = _load(run_id)
    run["target_stack"] = _infer_stack(stack)

    # Demo shortcut: jforum → C# / ASP.NET / Azure SQL uses a locally saved Plan
    # (other targets always re-research + re-call Nemotron — never reuse prior prose)
    if _is_jforum(run) and _is_csharp_azure_sql(run["target_stack"]):
        fixture = _load_plan_fixture("jforum3_csharp_azure_sql.json")
        if fixture:
            return _apply_plan_fixture(run, fixture, pretend_s=random.uniform(1.15, 1.85))

    run["user_planned"] = True
    _clear_step_plan_prose(run)
    apply_stack_to_plan(run)

    label = stack_label(run["target_stack"])
    all_steps = (run.get("plan") or {}).get("steps") or []
    run.pop("demo_steps", None)

    is_java = any(str(n.get("id") or "").startswith("java:") or str(n.get("subtype") or "").startswith("java")
                  for n in (run.get("nodes") or [])[:40])
    source_kind = "Java/VRaptor/JPA forum app" if is_java else "COBOL/CICS mainframe"

    # 1) Live web research for THIS target (not a static library)
    research = research_stack(
        source_kind=source_kind,
        target_label=label,
        repo=str(run.get("repo") or ""),
    )
    run["plan_research"] = research
    research_block = research_prompt_block(research)

    chunks = [all_steps[i:i + 5] for i in range(0, len(all_steps), 5)]
    nemotron: dict = {
        "status": "skipped",
        "model": None,
        "guidance": None,
        "top_risks": [],
        "calls": 0,
        "research_sources": len(research.get("sources") or []),
        "research_queries": research.get("queries") or [],
    }
    per_step: dict[str, dict] = {}
    try:
        import asyncio
        from app.services.agents.gateway import complete

        def _chunk_prompt(chunk: list[dict], first: bool) -> str:
            extra = (
                '"guidance": "2 sentences that NAME the target stack and cite at least one research URL or concrete API/'
                'DB feature from the research — never generic dependency-order filler", '
                if first else ""
            )
            return (
                f"You are the ModSwarm Planner. Source: {source_kind}. "
                f"TARGET (must appear by name in every title/why/fix): {label}. "
                f"Repo: {run.get('repo')}.\n"
                f"{research_block}\n"
                "Keep step ids and order. Rewrite prose for THIS target using research + evidence. "
                "Map each cut onto the target (e.g. VRaptor @Resource → C++ HTTP handler, JPA @Entity → "
                "C++ struct + SQL / EF Core / Quarkus Panache — whichever the target is). "
                "Ban phrases like 'dependency order ensures', 'repository boundary', 'cascading failures', "
                "'unauthorized access during the transition'.\n"
                "Return JSON: {" + extra + '"steps": {"<id>": {'
                '"title": "short title naming the target", '
                '"why": "grounded in evidence + research", '
                '"vulns": [{"risk":"...","evidence":"file:line","fix":"control from target/research"}] (1-3), '
                '"prompt": "coding-agent brief for the target stack"}}}. '
                f"Steps: {json.dumps([_step_evidence(run, s) for s in chunk])}"
            )

        async def _all():
            return await asyncio.gather(*[
                complete(
                    "planner",
                    _chunk_prompt(c, i == 0),
                    f"{run.get('id')}-{label}-webplan-{i}",
                    backend="nvidia",
                    json_mode=True,
                    max_tokens=3000,
                    use_cache=False,
                    temperature=0.4,
                )
                for i, c in enumerate(chunks)
            ])

        def _parse_planner(text: str) -> dict:
            raw = (text or "").strip()
            if not raw:
                return {}
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                pass
            fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.S)
            if fence:
                try:
                    return json.loads(fence.group(1))
                except json.JSONDecodeError:
                    pass
            start, end = raw.find("{"), raw.rfind("}")
            if start >= 0 and end > start:
                try:
                    return json.loads(raw[start : end + 1])
                except json.JSONDecodeError:
                    return {}
            return {}

        def _research_guidance() -> str:
            tops = research.get("sources") or []
            cite = tops[0] if tops else {}
            tip = (cite.get("passage") or cite.get("title") or "").strip()
            url = cite.get("url") or ""
            return (
                f"Modernize into {label} using live research"
                + (f" — {url}" if url else "")
                + (f". Key takeaway: {tip[:220]}" if tip else ".")
                + f" Source is {source_kind}; remap each measured cut onto that stack."
            )

        results = asyncio.run(_all())
        nemotron["calls"] = len(results)
        for i, result in enumerate(results):
            nemotron["status"] = result.get("status") if nemotron["status"] != "ok" else "ok"
            nemotron["model"] = result.get("model") or nemotron["model"]
            if result.get("error"):
                nemotron["error"] = result["error"]
            parsed = _parse_planner(result.get("text") or "")
            if not parsed:
                continue
            for sid, row in (parsed.get("steps") or {}).items():
                if isinstance(row, dict):
                    per_step[sid] = row
            g = parsed.get("guidance")
            if g and not is_banned_guidance(str(g)) and not nemotron.get("guidance"):
                nemotron["guidance"] = g
        if not nemotron.get("guidance") or is_banned_guidance(str(nemotron.get("guidance") or "")):
            nemotron["guidance"] = _research_guidance()
            nemotron["guidance_replaced"] = "banned-or-empty"
    except Exception as exc:  # noqa: BLE001
        tops = research.get("sources") or []
        cite = tops[0] if tops else {}
        nemotron = {
            "status": "error",
            "model": None,
            "guidance": (
                f"Modernize into {label} using live research"
                + (f" — {cite.get('url')}" if cite.get("url") else "")
                + f". Source is {source_kind}."
            ),
            "error": str(exc)[:240],
            "research_sources": len(research.get("sources") or []),
            "research_queries": research.get("queries") or [],
        }

    for step in all_steps:
        row = per_step.get(step.get("id")) or {}
        for src, dst in (("title", "stack_title"), ("prompt", "engineer_prompt"), ("why", "why_now")):
            val = row.get(src)
            if val and not (src == "why" and is_banned_guidance(str(val))):
                step[dst] = val
            elif src == "why" and (not val or is_banned_guidance(str(val or step.get(dst) or ""))):
                tops = research.get("sources") or []
                if tops:
                    step[dst] = (
                        f"Align this cut with {label} per {tops[0].get('title')}: "
                        f"{(tops[0].get('passage') or '')[:160]}"
                    )
        vulns = [v for v in (row.get("vulns") or []) if isinstance(v, dict) and v.get("risk")]
        for v in vulns:
            ref = re.search(
                r"[\w./-]+\.(?:cbl|cpy|jcl|bms|java|kt|cs|cpp|h|hpp|CBL|CPY|JCL|BMS|JAVA)(?::\d+)?",
                f"{v.get('evidence') or ''} {v.get('risk')}",
            )
            if ref:
                v["evidence"] = ref.group(0)
                v["risk"] = re.sub(
                    r"\s+at\s+[\w./-]+\.(?:cbl|cpy|jcl|bms|java|kt|cs|cpp|h|hpp)(?::\d+)?",
                    "",
                    str(v["risk"]),
                    flags=re.I,
                ).strip()
        if vulns:
            step["vulns"] = vulns[:3]
    rewritten = _stamp_step_titles(run, label)
    prompts = {s["id"]: 1 for s in all_steps if s.get("engineer_prompt")}
    run["stack_nemotron"] = nemotron
    run["plan_revision"] = {
        "label": label,
        "at": time.time(),
        "fixture": False,
        "rewritten": rewritten,
        "nemotron_status": nemotron.get("status"),
    }
    _save(run)
    docs = stack_docs_for(run["target_stack"])  # fresh for this target — don't keep prior Plan's docs
    # Merge live research URLs into stack_docs so Theater/PDF can show them
    live_docs = [
        {
            "id": f"web-{i}",
            "title": s.get("title"),
            "url": s.get("url"),
            "passage": s.get("passage"),
            "source": "web-research",
            "claim": "Measured",
        }
        for i, s in enumerate(research.get("sources") or [])
    ]
    merged_docs = live_docs + [d for d in (docs or []) if d.get("url") not in {x.get("url") for x in live_docs}]
    if _is_jforum(run) or any(str(n.get("id") or "").startswith("java:") for n in (run.get("nodes") or [])[:20]):
        merged_docs = _scrub_java_stack_docs(merged_docs)
    run["stack_docs"] = merged_docs[:12]
    _save(run)
    sample = [s.get("stack_title") or s.get("title") for s in all_steps[:3]]
    return {
        "target_stack": run["target_stack"],
        "stack_docs": run["stack_docs"],
        "nemotron": nemotron,
        "research": {
            "queries": research.get("queries") or [],
            "sources": research.get("sources") or [],
            "latency_s": research.get("latency_s"),
        },
        "steps_planned": len(all_steps),
        "prompts_written": len(prompts),
        "label": label,
        "fixture": False,
        "plan_revision": run["plan_revision"],
        "sample_titles": sample,
    }


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
    _publish_targets(run)
    _save(run)
    yield {"type": "summary", "text": run["summary"]}


def _publish_targets(run: dict) -> None:
    if not run.get("snapshot_id") or not run.get("migration_edges"):
        return
    from sqlmodel import Session

    from app.core.database import engine
    from app.models import CodeUnit, GraphEdge

    ids = dict(run.get("unit_ids") or {})
    with Session(engine) as session:
        for index, node in enumerate(run["target_nodes"]):
            if node["id"] in ids:
                continue
            unit = CodeUnit(
                snapshot_id=run["snapshot_id"],
                file_path=node["name"],
                symbol_name=node["name"],
                qualname=node["id"],
                kind="target",
                runtime="target",
                language="java",
                start_line=1,
                end_line=1,
                code_hash=node["id"][:16],
                source_text=node["name"],
                llm_description=f"Predicted {node['lens']} target",
                hub_score=0,
                x3d=18,
                y3d=float(index) * 0.8 - 4,
                z3d=6,
                x2d=18,
                y2d=6,
            )
            session.add(unit)
            session.flush()
            ids[node["id"]] = unit.id
        for edge in run["migration_edges"]:
            src = ids.get(edge["legacy"])
            dst = ids.get(edge["target"])
            if not src or not dst:
                continue
            session.add(GraphEdge(
                snapshot_id=run["snapshot_id"],
                source_unit_id=src,
                target_unit_id=dst,
                edge_type="migration-" + edge["lens"],
            ))
        session.commit()
    run["unit_ids"] = ids


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
    from app.services.migration.sources import sources_for, topics_for_step

    run = _load(run_id)
    plan = run.get("plan") or {}
    stack = run.get("target_stack") or {}
    planned = bool(run.get("user_planned"))
    if not planned:
        return {
            "steps": [],
            "curve": [],
            "planned": False,
            "target_stack": stack,
            "hint": "Enter a migration target and press Plan to generate dependency-safe steps.",
        }
    steps = []
    for step in plan.get("steps", []):
        removals = step.get("removals") or []
        findings = [str(v.get("risk") or "") for v in (step.get("vulns") or [])]
        docs = sources_for(topics_for_step(step, findings), stack, limit=2)
        steps.append({
            "id": step.get("id"),
            "index": step.get("index"),
            "verb": step.get("verb"),
            "title": step.get("stack_title") or step.get("title"),
            "detail": step.get("detail") or "",
            "claim": step.get("claim") or "Predicted",
            "retires": [row.get("id") for row in removals if row.get("id")],
            "removals": [
                {
                    "id": row.get("id"),
                    "type": row.get("type"),
                    "source": row.get("source"),
                    "target": row.get("target"),
                    "file": row.get("file"),
                    "line": row.get("line"),
                    "snippet": (row.get("snippet") or "")[:160],
                    "reason": row.get("reason") or "",
                }
                for row in removals[:24]
            ],
            "bridges": step.get("add_nodes") or [],
            "add_edges": step.get("add_edges") or [],
            "requires": step.get("requires") or [],
            "unblocks": step.get("unblocks") or [],
            "drivers": step.get("drivers") or [],
            "deps_before": step.get("deps_before") or {},
            "deps_after": step.get("deps_after") or {},
            "legacy_remaining": step.get("legacy_remaining"),
            "risk_before": step.get("risk_before"),
            "risk_after": step.get("risk_after"),
            "evidence_refs": [f"{row.get('file')}:{row.get('line')}" for row in removals[:8]],
            "why": step.get("why_now") or step.get("why") or step.get("detail") or step.get("title") or "",
            "acceptance": step.get("acceptance") or [],
            "risks": step.get("risks") or [],
            "stack_title": step.get("stack_title"),
            "engineer_prompt": step.get("engineer_prompt"),
            "why_now": step.get("why_now"),
            "vulns": step.get("vulns") or [],
            "docs": docs,
            "cut_count": len(removals),
        })
    return {
        "steps": steps,
        "curve": plan.get("curve") or [],
        "claim": plan.get("claim") or "Predicted",
        "planned": True,
        "illegal_order": run.get("illegal_order"),
        "illegal_reason": run.get("illegal_reason"),
        "violations": run.get("violations"),
        "target_stack": run.get("target_stack") or {},
        "plan_revision": run.get("plan_revision"),
    }


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
    from app.services.migration.report import build_report

    return build_report(_load(run_id), _step_evidence)


def impact_for_wave(run_id: str, step_id: str) -> dict:
    """GraphDev-style overlay without a git checkout: red changed, amber neighbors, dim rest."""
    run = _load(run_id)
    step = next((s for s in run["plan"].get("steps", []) if s.get("id") == step_id), None)
    if not step:
        return {"changed": [], "ripple": [], "removed_edges": [], "added_edges": [], "label": "Predicted"}
    changed = set()
    removed_edges = []
    for row in step.get("removals", []):
        if row.get("source"):
            changed.add(row["source"])
        if row.get("target"):
            changed.add(row["target"])
        if row.get("source") and row.get("target"):
            removed_edges.append({
                "source": row["source"],
                "target": row["target"],
                "type": row.get("type") or "FILE",
                "file": row.get("file"),
                "line": row.get("line"),
                "reason": row.get("reason") or "",
            })
    for nid in step.get("migrate") or []:
        changed.add(nid)
    for node in step.get("add_nodes") or []:
        if node.get("id"):
            changed.add(node["id"])
    ripple = set()
    for edge in run["legacy_edges"]:
        if edge["source"] in changed:
            ripple.add(edge["target"])
        if edge["target"] in changed:
            ripple.add(edge["source"])
    ripple -= changed
    added_edges = []
    for row in step.get("add_edges") or []:
        if row.get("source") and row.get("target"):
            added_edges.append({
                "source": row["source"],
                "target": row["target"],
                "type": row.get("type") or "FILE",
            })
            changed.add(row["source"])
            changed.add(row["target"])
    # Map legacy unit ids (pgm:FOO) onto GraphDev node ids when published as symbol names
    name_to_id = {}
    for node in run.get("nodes") or []:
        name_to_id[node.get("id")] = node.get("id")
        name_to_id[node.get("name")] = node.get("id")
    def map_id(raw: str) -> str:
        if raw in name_to_id:
            return name_to_id[raw]
        short = raw.split(":", 1)[-1] if ":" in raw else raw
        return name_to_id.get(short, raw)

    changed_mapped = sorted({map_id(x) for x in changed})
    ripple_mapped = sorted({map_id(x) for x in ripple} - set(changed_mapped))
    return {
        "step_id": step_id,
        "title": step.get("title"),
        "detail": step.get("detail") or "",
        "claim": step.get("claim") or "Predicted",
        "changed": changed_mapped,
        "ripple": ripple_mapped,
        "removed_edges": removed_edges,
        "added_edges": added_edges,
        "deps_before": step.get("deps_before") or {},
        "deps_after": step.get("deps_after") or {},
        "legacy_remaining": step.get("legacy_remaining"),
        "risk_before": step.get("risk_before"),
        "risk_after": step.get("risk_after"),
        "requires": step.get("requires") or [],
        "unblocks": step.get("unblocks") or [],
        "label": "Predicted",
    }


def findings_panel(run_id: str) -> dict:
    run = _load(run_id)
    findings = run.get("findings") or []
    measured = [f for f in findings if f.get("claim") == "Measured"]
    predicted = [f for f in findings if f.get("claim") == "Predicted"]
    candidate = [f for f in findings if f.get("claim") == "Candidate"]
    accepted = [f for f in findings if f.get("verdict") in {"accepted", "downgraded", None} and f.get("verdict") != "rejected"]
    rejected = [f for f in findings if f.get("verdict") == "rejected"]
    return {
        "counts": {
            "total": len(findings),
            "measured": len(measured),
            "predicted": len(predicted),
            "candidate": len(candidate),
            "accepted": len(accepted),
            "rejected": len(rejected),
        },
        "findings": [
            {
                "id": f.get("id"),
                "title": f.get("title") or f.get("rule") or f.get("type"),
                "type": f.get("type"),
                "lens": f.get("lens"),
                "claim": f.get("claim") or "Measured",
                "verdict": f.get("verdict") or "accepted",
                "file": f.get("file"),
                "line": f.get("line"),
                "snippet": (f.get("snippet") or "")[:180],
                "authority": f.get("authority") or "",
                "agent": f.get("agent") or "",
            }
            for f in findings[:80]
        ],
        "label": "Measured detectors + Predicted optimizations; Prover rejects lack evidence or authority.",
    }
