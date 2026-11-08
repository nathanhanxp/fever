"""User-facing modernization brief — what you migrate to, what bites you, what it means."""

from __future__ import annotations

from collections import Counter, defaultdict


def build_brief(run: dict) -> dict:
    nodes = run.get("nodes") or []
    edges = run.get("legacy_edges") or []
    findings = run.get("findings") or []
    plan = run.get("plan") or {}
    steps = plan.get("steps") or []
    stack = run.get("target_stack") or {}
    targets = run.get("target_nodes") or []

    by_kind = Counter(n.get("kind") for n in nodes if n.get("status") != "modern")
    hubs = sorted(
        [n for n in nodes if n.get("kind") in {"copybook", "program"} and not n.get("external")],
        key=lambda n: -(n.get("degree") or 0),
    )[:8]

    dependents: dict[str, set[str]] = defaultdict(set)
    for e in edges:
        dependents[e["target"]].add(e["source"])
        dependents[e["source"]].add(e["target"])

    hub_cards = []
    for hub in hubs:
        blast = len(dependents.get(hub["id"], ()))
        hub_cards.append({
            "id": hub["id"],
            "name": hub.get("name") or hub["id"],
            "kind": hub.get("kind"),
            "file": hub.get("file") or "",
            "line": hub.get("line") or 1,
            "programs_touched": blast,
            "why_it_matters": (
                f"Shared {hub.get('kind')} — changing it without a contract breaks ~{blast} linked units."
                if hub.get("kind") == "copybook"
                else f"High-degree program — ~{blast} neighbors move when this moves."
            ),
        })

    def _sev(f: dict) -> int:
        s = (f.get("severity") or "").lower()
        return {"critical": 0, "high": 1, "medium": 2, "info": 3}.get(s, 4)

    accepted = [f for f in findings if f.get("verdict") != "rejected"]
    security = [f for f in accepted if (f.get("lens") or "") in {"platform-security", "security"} or "secret" in (f.get("type") or "").lower()]
    quality = [f for f in accepted if (f.get("lens") or "") == "quality" and f.get("claim") == "Measured"]
    predicted_opt = [f for f in accepted if f.get("claim") == "Predicted"]
    candidates = [f for f in accepted if f.get("claim") == "Candidate"]

    deficits = []
    for f in sorted(security + quality, key=_sev)[:12]:
        deficits.append({
            "id": f.get("id"),
            "title": f.get("title") or f.get("rule") or f.get("type"),
            "severity": f.get("severity") or "medium",
            "claim": f.get("claim") or "Measured",
            "file": f.get("file"),
            "line": f.get("line"),
            "snippet": (f.get("snippet") or "")[:160],
            "business": _business_line(f),
        })

    wave_cards = []
    for step in steps[:6]:
        removals = step.get("removals") or []
        before = sum((step.get("deps_before") or {}).values())
        after = sum((step.get("deps_after") or {}).values())
        wave_cards.append({
            "id": step.get("id"),
            "title": _plain_title(step),
            "removes": before - after if before and after is not None else len(removals),
            "risk_before": step.get("risk_before"),
            "risk_after": step.get("risk_after"),
            "unlocks": len(step.get("unblocks") or []),
            "business": _wave_business(step, before, after),
        })

    inventory = {
        "programs": by_kind.get("program", 0),
        "copybooks": by_kind.get("copybook", 0),
        "jobs": by_kind.get("job", 0),
        "screens": by_kind.get("map", 0) + by_kind.get("screen", 0),
        "files": by_kind.get("file", 0) + by_kind.get("dataset", 0),
        "legacy_edges": len(edges),
        "migration_edges": len(run.get("migration_edges") or []),
    }

    return {
        "repo": run.get("repo"),
        "run_id": run.get("id"),
        "migrating_to": {
            "language": stack.get("language") or "Java 21",
            "framework": stack.get("framework") or "Spring Boot",
            "database": stack.get("database") or "PostgreSQL",
            "api": stack.get("api") or "REST",
            "runtime": stack.get("runtime") or "containers",
            "scheduler": stack.get("scheduler") or "workflow scheduler",
            "components": [
                {"name": t.get("name"), "lens": t.get("lens"), "stack_hint": t.get("stack_hint") or ""}
                for t in targets[:12]
            ],
        },
        "inventory": inventory,
        "hidden_deficits": deficits,
        "hub_risks": hub_cards,
        "first_waves": wave_cards,
        "counts": {
            "security_issues": len(security),
            "quality_issues": len(quality),
            "predicted_opts": len(predicted_opt),
            "dead_code_candidates": len(candidates),
            "prover_rejected": len([f for f in findings if f.get("verdict") == "rejected"]),
        },
        "business_summary": _summary(inventory, hub_cards, deficits, wave_cards, stack),
        "label": "Measured inventory + deficits; roadmap waves are Predicted",
    }


def _business_line(f: dict) -> str:
    t = (f.get("type") or "").lower()
    title = (f.get("title") or "").lower()
    if "secret" in t or "password" in title or "hard-coded" in title:
        return "Credential or secret in source — blocks cloud cutover and audit."
    if "card" in title or "pan" in title or "sensitive" in title:
        return "Cardholder / PII field in a shared layout — every consumer inherits the exposure."
    if "file status" in title or "resp" in title or "nohandle" in title:
        return "Missing error handling — failures become silent data loss in production."
    if "go to" in title or "alter" in title:
        return "Control-flow smell — hard to retest after a rewrite."
    if "commarea" in title:
        return "Unbounded COMMAREA — buffer risk when you expose this as an API."
    if "racf" in title or "security" in title:
        return "Security config in the repo — must be remapped to IAM / IdP, not ignored."
    if f.get("claim") == "Predicted":
        return "Optimization candidate only — do not treat as a measured speedup."
    if f.get("claim") == "Candidate":
        return "May be dead — confirm no external scheduler or CICS entry before deleting."
    return "Fix before or during migration so the new system does not inherit the defect."


def _plain_title(step: dict) -> str:
    verb = step.get("verb") or ""
    title = step.get("title") or verb
    mapping = {
        "clean": "Clean defects before moving code",
        "wrap-dataset": "Put a service in front of a VSAM file",
        "migrate-program": "Rewrite a COBOL program",
        "retire-copybook": "Replace a shared record layout",
        "decommission": "Turn off a retired batch path",
    }
    return mapping.get(verb, title)


def _wave_business(step: dict, before: int, after: int) -> str:
    verb = step.get("verb") or ""
    dropped = max(0, (before or 0) - (after or 0))
    if verb == "clean":
        return "Stop shipping known defects into the new stack."
    if verb == "wrap-dataset":
        return f"Unblocks later data moves — {dropped or len(step.get('removals') or [])} direct file ties leave the programs."
    if verb == "migrate-program":
        return "One business capability moves to the target runtime; callers keep working via the plan order."
    if verb == "retire-copybook":
        return "Shared contract changes once — every consumer must agree or you fork data."
    if verb == "decommission":
        return "Removes batch cost and failure surface after replacements are live."
    return step.get("detail") or title_safe(step)


def title_safe(step: dict) -> str:
    return step.get("title") or "Planned change"


def _summary(inventory: dict, hubs: list, deficits: list, waves: list, stack: dict) -> str:
    top = hubs[0]["name"] if hubs else "shared modules"
    blast = hubs[0]["programs_touched"] if hubs else 0
    sev = deficits[0]["title"] if deficits else "no high deficits yet"
    target = f"{stack.get('language', 'Java')} / {stack.get('framework', 'Spring Boot')} / {stack.get('database', 'PostgreSQL')}"
    return (
        f"You are taking {inventory.get('programs', 0)} programs, {inventory.get('copybooks', 0)} copybooks, "
        f"and {inventory.get('jobs', 0)} jobs toward {target}. "
        f"Biggest coupling risk: {top} touches ~{blast} units. "
        f"Top deficit to clear: {sev}. "
        f"First wave: {(waves[0]['title'] if waves else 'clean findings')}."
    )
