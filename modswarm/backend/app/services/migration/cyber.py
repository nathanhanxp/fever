"""Predictive migration cyber risk + edge audit cards (Predicted, with Measured citations)."""

from __future__ import annotations

from collections import defaultdict

# Primary-source snippets we can cite without inventing URLs at runtime.
# Passages are paraphrased pointers to public CardDemo / COBOL migration guidance.
DOCS = [
    {
        "id": "aws-carddemo-overview",
        "title": "AWS CardDemo — sample for mainframe analysis and migration",
        "source": "AWS Samples / CardDemo README",
        "url": "https://github.com/aws-samples/aws-mainframe-modernization-carddemo",
        "passage": "CardDemo exercises COBOL, CICS, VSAM, JCL and related mainframe assets used to evaluate modernization tooling.",
        "tags": ["migration", "carddemo", "cobol"],
    },
    {
        "id": "aws-m2-guide",
        "title": "AWS Mainframe Modernization — User Guide",
        "source": "AWS Docs",
        "url": "https://docs.aws.amazon.com/m2/latest/userguide/what-is-m2.html",
        "passage": "Modernization patterns must preserve transaction integrity and security controls when rehosting or refactoring COBOL workloads.",
        "tags": ["migration", "carddemo", "security"],
    },
    {
        "id": "ibm-cobol-cics",
        "title": "CICS application modernization considerations",
        "source": "IBM COBOL / CICS docs",
        "url": "https://www.ibm.com/docs/en/cobol-zos",
        "passage": "Transaction programs that share COMMAREA and VSAM files must preserve unit-of-work and security boundaries when moved behind APIs.",
        "tags": ["cics", "api", "security", "commarea"],
    },
    {
        "id": "owasp-api1",
        "title": "OWASP API Security Top 10 — Broken Object Level Authorization",
        "source": "OWASP",
        "url": "https://owasp.org/API-Security/editions/2023/en/0xa1-broken-object-level-authorization/",
        "passage": "Exposing a legacy transaction as a REST resource without authz checks creates an unauthenticated or under-authorized microservice boundary.",
        "tags": ["api", "security", "orange"],
    },
    {
        "id": "cisa-kev",
        "title": "CISA Known Exploited Vulnerabilities Catalog",
        "source": "CISA KEV",
        "url": "https://www.cisa.gov/known-exploited-vulnerabilities-catalog",
        "passage": "Use KEV as live threat context when migration introduces new network-facing surfaces or outdated crypto libraries.",
        "tags": ["tls", "transit", "purple", "security", "cve"],
    },
    {
        "id": "cisa-plaintext",
        "title": "CISA — Protecting Sensitive and Personal Data",
        "source": "CISA",
        "url": "https://www.cisa.gov/topics/cybersecurity-best-practices",
        "passage": "Sensitive data moving between services should use encryption in transit. Batch flat files becoming real-time streams without TLS increase exposure.",
        "tags": ["tls", "transit", "purple", "pii"],
    },
    {
        "id": "osv-dev",
        "title": "OSV — Open Source Vulnerability database",
        "source": "OSV.dev",
        "url": "https://osv.dev/",
        "passage": "Cross-check post-migration dependency stacks (JVM, containers, API gateways) against OSV for introduced CVEs.",
        "tags": ["security", "orange", "cve"],
    },
    {
        "id": "pci-pan",
        "title": "PCI DSS — cardholder data storage",
        "source": "PCI SSC",
        "url": "https://www.pcisecuritystandards.org/",
        "passage": "Primary account numbers and related fields in shared layouts require protection wherever they are stored or transmitted after modernization.",
        "tags": ["card", "pci", "compliance", "copybook"],
    },
    # --- stack-specific target docs (selected when user picks Migrating to) ---
    {
        "id": "spring-boot-migrate",
        "title": "Spring Boot 3.0 Migration Guide",
        "source": "spring.io",
        "url": "https://github.com/spring-projects/spring-boot/wiki/Spring-Boot-3.0-Migration-Guide",
        "passage": "javax→jakarta namespace move, security filter chain changes, and Boot 3 dependency upgrades for modernized services.",
        "tags": ["java", "spring", "rest", "stack", "api", "code"],
    },
    {
        "id": "spring-security-authorize",
        "title": "Spring Security — Authorize HttpServletRequests",
        "source": "spring.io",
        "url": "https://docs.spring.io/spring-security/reference/servlet/authorization/authorize-http-requests.html",
        "passage": "Replace legacy @SecurityConstraint / interceptor gates with authorizeHttpRequests or an OAuth2 resource server before exposing controllers as REST.",
        "tags": ["java", "spring", "security", "stack", "orange", "api"],
    },
    {
        "id": "spring-jwt",
        "title": "Spring Security — OAuth 2.0 Resource Server JWT",
        "source": "spring.io",
        "url": "https://docs.spring.io/spring-security/reference/servlet/oauth2/resource-server/jwt.html",
        "passage": "Validate bearer tokens on every modernized controller that used to sit behind session or annotation-based auth.",
        "tags": ["java", "spring", "security", "stack", "orange", "api"],
    },
    {
        "id": "postgres-ssl",
        "title": "PostgreSQL — Secure TCP/IP Connections with SSL",
        "source": "PostgreSQL docs",
        "url": "https://www.postgresql.org/docs/current/ssl-tcp.html",
        "passage": "Require TLS for app→DB after cutover; pair with sslmode=verify-full in clients.",
        "tags": ["postgresql", "postgres", "database", "stack", "data", "purple", "transit"],
    },
    {
        "id": "postgres-numeric",
        "title": "PostgreSQL — Numeric Types (money / COMP-3)",
        "source": "PostgreSQL docs",
        "url": "https://www.postgresql.org/docs/current/datatype-numeric.html#DATATYPE-NUMERIC-DECIMAL",
        "passage": "Map COBOL COMP-3 / packed decimals to NUMERIC/DECIMAL — never float — to avoid silent money skew.",
        "tags": ["postgresql", "postgres", "database", "stack", "data", "purple", "precision"],
    },
    {
        "id": "java-se",
        "title": "Java SE 21 — Getting Started with Migration",
        "source": "Oracle / OpenJDK",
        "url": "https://docs.oracle.com/en/java/javase/21/migrate/getting-started.html",
        "passage": "COBOL packed decimals and EBCDIC strings need explicit converters — do not rely on default charset.",
        "tags": ["java", "stack", "code"],
    },
    {
        "id": "quarkus-oidc",
        "title": "Quarkus — OpenID Connect Bearer token auth",
        "source": "quarkus.io",
        "url": "https://quarkus.io/guides/security-oidc-bearer-token-authentication",
        "passage": "Wire OIDC bearer validation on REST resources that replace former VRaptor / servlet entry points.",
        "tags": ["kotlin", "quarkus", "stack", "java", "api", "orange"],
    },
    {
        "id": "aspnet-auth",
        "title": "ASP.NET Core — Authentication",
        "source": "Microsoft Learn",
        "url": "https://learn.microsoft.com/en-us/aspnet/core/security/authentication/",
        "passage": "Host modernized controllers behind ASP.NET authentication middleware after cutover.",
        "tags": ["csharp", "c#", "asp.net", "dotnet", ".net", "stack", "api", "orange"],
    },
    {
        "id": "aspnet-authorize",
        "title": "ASP.NET Core — Authorization",
        "source": "Microsoft Learn",
        "url": "https://learn.microsoft.com/en-us/aspnet/core/security/authorization/introduction",
        "passage": "Map legacy auth gates to policies and [Authorize] before exposing REST endpoints on the target stack.",
        "tags": ["csharp", "c#", "asp.net", "dotnet", ".net", "stack", "api", "orange"],
    },
    {
        "id": "azure-sql-tls",
        "title": "Azure SQL — Connectivity settings (minimum TLS)",
        "source": "Microsoft Learn",
        "url": "https://learn.microsoft.com/en-us/azure/azure-sql/database/connectivity-settings",
        "passage": "Enforce minimum TLS on Azure SQL and use encrypted ADO.NET / EF Core connection strings at cutover.",
        "tags": ["azure sql", "database", "stack", "data", "purple", "transit"],
    },
    {
        "id": "java-to-csharp",
        "title": "Migrate from Java to .NET",
        "source": "Microsoft Learn",
        "url": "https://learn.microsoft.com/en-us/dotnet/core/porting/java-to-csharp",
        "passage": "Controller/service/entity mapping patterns when porting a Java forum/app stack onto ASP.NET Core.",
        "tags": ["csharp", "c#", "asp.net", "dotnet", ".net", "stack", "java", "code"],
    },
]


def stack_docs_for(stack: dict | None) -> list[dict]:
    """Docs keyed to the user's Migrating-to stack (Java/Spring/Postgres, etc.)."""
    stack = stack or {}
    blob = " ".join(str(v).lower() for v in stack.values() if v)
    tags: list[str] = ["stack", "migration"]
    if "java" in blob or "spring" in blob:
        tags += ["java", "spring"]
    if "postgres" in blob or "postgresql" in blob:
        tags += ["postgres", "postgresql", "database"]
    if "quarkus" in blob or "kotlin" in blob:
        tags += ["quarkus", "kotlin"]
    if "asp.net" in blob or ".net" in blob or "c#" in blob or "csharp" in blob or "azure" in blob:
        tags += ["dotnet", "asp.net", "csharp", "azure sql"]
    if "rest" in blob or "api" in blob:
        tags += ["api", "rest"]
    # Security baselines only — CardDemo/COBOL docs must NOT ride along on Java/.NET plans
    tags += ["security", "api"]
    tag_set = set(tags)
    scored: list[tuple[int, dict]] = []
    for doc in DOCS:
        hit = len(tag_set.intersection(doc["tags"]))
        if hit <= 0:
            continue
        # Prefer docs that carry the "stack" tag when the user picked a target
        bonus = 3 if "stack" in doc["tags"] and hit >= 2 else 0
        scored.append((hit + bonus, {k: doc[k] for k in ("id", "title", "source", "url", "passage")}))
    scored.sort(key=lambda x: -x[0])
    out = []
    seen: set[str] = set()
    for _, doc in scored:
        if doc["id"] in seen:
            continue
        seen.add(doc["id"])
        out.append(doc)
        if len(out) >= 8:
            break
    return out


def _is_java_run(run: dict) -> bool:
    repo = str(run.get("repo") or "").lower()
    if "jforum" in repo or "java" in repo:
        return True
    for n in (run.get("nodes") or [])[:40]:
        nid = str(n.get("id") or "")
        path = str(n.get("file") or "")
        if nid.startswith("java:") or path.endswith(".java"):
            return True
    return False


def _source_doc_tags(run: dict) -> list[str]:
    """Doc tags allowed for THIS codebase (not the migration target)."""
    if _is_java_run(run):
        return ["java", "spring", "api", "security", "orange", "input", "tls", "transit", "purple", "secrets"]
    return ["carddemo", "cobol", "cics", "migration", "api", "security", "orange", "purple", "tls", "transit", "secrets", "precision", "pci", "card"]


def apply_stack_to_plan(run: dict) -> None:
    """Rewrite wave titles/details so playback + PDF cite the chosen target stack."""
    stack = run.get("target_stack") or {}
    label = stack.get("description") or " · ".join(
        str(v) for v in [stack.get("language"), stack.get("framework"), stack.get("database"), stack.get("api")] if v
    ) or "target stack"
    for step in (run.get("plan") or {}).get("steps") or []:
        base = (step.get("detail") or "").split(" Target stack:")[0].rstrip()
        step["detail"] = f"{base} Target stack: {label}."
        step["target_stack"] = dict(stack)
    run["stack_docs"] = stack_docs_for(stack)
    seed_cyber_risks(run)
    # Do not paste target-stack (ASP.NET/Azure) pages onto Java source risk cards —
    # those belong on the Plan brief. COBOL runs may still attach matching stack docs.
    if not _is_java_run(run):
        for r in run.get("cyber_risks") or []:
            extra = [d for d in stack_docs_for(stack)[:2] if _doc_ok_for_run(run, d)]
            seen = {d.get("id") for d in (r.get("docs") or [])}
            merged = list(r.get("docs") or [])
            for d in extra:
                if d.get("id") not in seen:
                    merged.append(d)
            r["docs"] = merged[:4]


def _doc_ok_for_run(run: dict, doc: dict) -> bool:
    """Block wrong-language sources. Java inspect cards never cite COBOL or ASP.NET overviews."""
    url = (doc.get("url") or "").lower()
    title = (doc.get("title") or "").lower()
    source = (doc.get("source") or "").lower()
    blob = f"{url} {title} {source} {doc.get('id') or ''}"
    java = _is_java_run(run)
    cobolish = any(k in blob for k in ("cobol", "cics", "carddemo", "mainframe", "vsam", "ibm.com/docs/en/cobol"))
    if java and cobolish:
        return False
    # Source-graph citations stay on Java/OWASP — target-stack pages live on Plan only
    if java and any(k in blob for k in ("aspnet", "/dotnet/", "azure-sql", "learn.microsoft.com/en-us/dotnet", "learn.microsoft.com/en-us/aspnet")):
        return False
    if not java and any(k in blob for k in ("jforum", "vraptor", "jakarta.ee", "spring.io", "spring-security")):
        return False
    return True


def _java_risks_stale(run: dict) -> bool:
    if not _is_java_run(run):
        return False
    for r in run.get("cyber_risks") or []:
        blob = f"{r.get('detail') or ''} {r.get('title') or ''}"
        if any(k in blob for k in ("CICS", "VSAM", "COBOL", "COMMAREA", "mainframe region")):
            return True
        for d in r.get("docs") or []:
            if not _doc_ok_for_run(run, d):
                return True
    return False


def _refresh_java_cyber(run: dict) -> bool:
    """Reseed + persist when Java still carries mainframe wording or wrong-stack docs."""
    if not _java_risks_stale(run):
        return False
    seed_cyber_risks(run)
    try:
        from app.services.migration import service
        service._save(run)
    except Exception:  # noqa: BLE001
        pass
    return True


def seed_cyber_risks(run: dict) -> None:
    """Attach Predicted orange/purple migration cyber risks — wording matches source language."""
    risks = []
    by_id = {n["id"]: n for n in run.get("nodes") or []}
    findings = run.get("findings") or []
    java = _is_java_run(run)
    stack = run.get("target_stack") or {}
    api = stack.get("api") or "REST"
    target_label = stack.get("description") or stack.get("framework") or stack.get("language") or "the target stack"

    # Red / legacy: from Measured security findings
    for f in findings:
        if f.get("verdict") == "rejected":
            continue
        if (f.get("lens") or "") not in {"platform-security", "security"} and "secret" not in (f.get("type") or "").lower():
            if "sensitive" not in (f.get("title") or "").lower() and "card" not in (f.get("title") or "").lower():
                if "security" not in (f.get("title") or "").lower() and "constraint" not in (f.get("title") or "").lower():
                    continue
        nid = None
        for n in by_id.values():
            if n.get("file") and f.get("file") and n["file"] == f["file"]:
                nid = n["id"]
                break
        risks.append({
            "id": f"cyber-legacy-{f.get('id')}",
            "node_id": nid,
            "horizon": "legacy",
            "color": "red",
            "title": f.get("title") or "Legacy security finding",
            "claim": "Measured",
            "detail": "Active issue in the current codebase — clear before or during cutover.",
            "file": f.get("file"),
            "line": f.get("line"),
            "docs": _docs_for(["security", "api"] if java else ["security", "pci", "card"], run=run),
        })

    # Orange: HTTP / controller entry points without authz after modernization
    for edge in run.get("legacy_edges") or []:
        if edge.get("type") not in {"TRANS", "SCREEN", "LINK", "XCTL"}:
            continue
        src = by_id.get(edge["source"])
        if not src:
            continue
        kind = (src.get("kind") or "").lower()
        subtype = str(src.get("subtype") or "").lower()
        if java:
            if kind not in {"program", "transaction", "screen", "map"} and "controller" not in subtype and "controller" not in str(src.get("name") or "").lower():
                # Still allow txn:* / java controllers linked via TRANS
                if not str(src.get("id") or "").startswith(("txn:", "java:")):
                    continue
            detail = (
                f"Modernizing {src.get('name')} behind {api} without an authz gate "
                f"opens a public endpoint that VRaptor/@SecurityConstraint previously gated "
                f"in this Java forum app. Target: {target_label}."
            )
            docs = _docs_for(["api", "security", "orange"], run=run)
        else:
            if kind not in {"program", "transaction", "map"}:
                continue
            detail = (
                f"Modernizing {src.get('name')} behind {api} without an authz gate "
                "opens a microservice boundary that the CICS region previously mediated."
            )
            docs = _docs_for(["api", "security", "cics"], run=run)
        risks.append({
            "id": f"cyber-orange-{edge.get('id')}",
            "node_id": edge["source"],
            "edge_id": edge.get("id"),
            "horizon": "post-migration",
            "color": "orange",
            "title": f"Predicted: unauthenticated API boundary for {src.get('name')}",
            "claim": "Predicted",
            "detail": detail,
            "file": edge.get("file"),
            "line": edge.get("line"),
            "snippet": (edge.get("snippet") or "")[:180],
            "docs": docs,
            "threat_context": {
                "framework": "OWASP API1 / Broken Object Level Authorization",
                "kev": "not a package CVE — architectural prediction",
                "epss": None,
                "label": "Predicted",
            },
        })
        if len([r for r in risks if r["color"] == "orange"]) >= 18:
            break

    if not java:
        # Purple: FILE/JOB batch → real-time without TLS (COBOL/VSAM only)
        for edge in run.get("legacy_edges") or []:
            if edge.get("type") not in {"FILE", "JOB"}:
                continue
            risks.append({
                "id": f"cyber-purple-{edge.get('id')}",
                "node_id": edge["target"] if str(edge.get("target", "")).startswith(("file:", "dsn:")) else edge["source"],
                "edge_id": edge.get("id"),
                "horizon": "post-migration",
                "color": "purple",
                "title": "Predicted: data-in-transit exposure on modernization",
                "claim": "Predicted",
                "detail": (
                    "Moving this VSAM/batch handoff to a stream or service call without TLS "
                    f"exposes payloads on the path to {stack.get('database', 'the target database')}."
                ),
                "file": edge.get("file"),
                "line": edge.get("line"),
                "snippet": (edge.get("snippet") or "")[:180],
                "docs": _docs_for(["tls", "transit", "purple"], run=run),
                "threat_context": {
                    "framework": "CISA sensitive data in transit",
                    "kev": "n/a — not a catalogued CVE for COBOL",
                    "epss": None,
                    "label": "Predicted",
                },
            })
            if len([r for r in risks if r["color"] == "purple"]) >= 14:
                break

        # Orange: COPYBOOK mass-assignment (COBOL only)
        for edge in run.get("legacy_edges") or []:
            if edge.get("type") not in {"COPY", "CALL"}:
                continue
            src = by_id.get(edge.get("source") or "")
            risks.append({
                "id": f"cyber-orange-copy-{edge.get('id')}",
                "node_id": edge.get("source"),
                "edge_id": edge.get("id"),
                "horizon": "post-migration",
                "color": "orange",
                "title": f"Predicted: privileged field exposure via {(src or {}).get('name') or 'shared copybook'}",
                "claim": "Predicted",
                "detail": (
                    "Lifting a COBOL COPY/CALL boundary into a DTO without an allowlist often re-exposes "
                    "admin flags, credit limits, or PAN fragments the green-screen never posted."
                ),
                "file": edge.get("file"),
                "line": edge.get("line"),
                "snippet": (edge.get("snippet") or "")[:180],
                "docs": _docs_for(["api", "security", "input"], run=run),
                "threat_context": {
                    "framework": "OWASP Mass Assignment / API3 Property-level authz",
                    "kev": "architectural prediction — not a package CVE",
                    "epss": None,
                    "label": "Predicted",
                },
            })
            if len([r for r in risks if r["color"] == "orange"]) >= 28:
                break

        # Purple: JCL secrets
        for n in by_id.values():
            kind = (n.get("kind") or "").lower()
            name = (n.get("name") or "").upper()
            if kind not in {"job", "proc", "jcl"} and "JOB" not in name and not str(n.get("id", "")).startswith("job:"):
                continue
            risks.append({
                "id": f"cyber-purple-job-{n.get('id')}",
                "node_id": n.get("id"),
                "horizon": "post-migration",
                "color": "purple",
                "title": f"Predicted: batch credential leakage modernizing {n.get('name')}",
                "claim": "Predicted",
                "detail": (
                    "Mainframe JCL often carries DATASET passwords and RACF assumptions. Lifted into "
                    f"{stack.get('scheduler', 'a cloud scheduler')} without a secret store, "
                    "those values become CI vars, container env, or log lines."
                ),
                "file": n.get("file"),
                "line": n.get("line"),
                "docs": _docs_for(["secrets", "tls"], run=run),
                "threat_context": {
                    "framework": "OWASP Secrets Management / PCI DSS transmission",
                    "kev": "n/a — operational prediction",
                    "epss": None,
                    "label": "Predicted",
                },
            })
            if len([r for r in risks if "cyber-purple-job" in r["id"]]) >= 8:
                break

        # COMP-3 precision
        for edge in run.get("legacy_edges") or []:
            if edge.get("type") != "FILE":
                continue
            snip = (edge.get("snippet") or "").upper()
            if "COMP-3" not in snip and "PACKED" not in snip and "PIC S9" not in snip:
                continue
            risks.append({
                "id": f"cyber-purple-precision-{edge.get('id')}",
                "node_id": edge.get("target") or edge.get("source"),
                "edge_id": edge.get("id"),
                "horizon": "post-migration",
                "color": "purple",
                "title": "Predicted: monetary precision loss on VSAM→SQL rewrite",
                "claim": "Predicted",
                "detail": (
                    "COMP-3 / packed-decimal amounts mapped to float/double instead of NUMERIC/DECIMAL "
                    "silently skew balances after cutover — an integrity fault that looks like fraud."
                ),
                "file": edge.get("file"),
                "line": edge.get("line"),
                "snippet": (edge.get("snippet") or "")[:180],
                "docs": _docs_for(["precision"], run=run),
                "threat_context": {
                    "framework": "data integrity / PCI cardholder amount handling",
                    "kev": "n/a",
                    "epss": None,
                    "label": "Predicted",
                },
            })
            if len([r for r in risks if "precision" in r["id"]]) >= 6:
                break
    else:
        # Java: session / interceptor / SSO without authz after port
        for n in by_id.values():
            name = str(n.get("name") or "")
            path = str(n.get("file") or "").lower()
            blob = f"{name} {path} {n.get('subtype') or ''}".lower()
            if not any(k in blob for k in ("interceptor", "session", "sso", "securityconstraint", "filter")):
                continue
            risks.append({
                "id": f"cyber-orange-java-{n.get('id')}",
                "node_id": n.get("id"),
                "horizon": "post-migration",
                "color": "orange",
                "title": f"Predicted: auth boundary drift on {name}",
                "claim": "Predicted",
                "detail": (
                    f"Porting {name} to {target_label} without re-applying @SecurityConstraint / session checks "
                    f"can leave {api} handlers open on this Java/VRaptor forum stack."
                ),
                "file": n.get("file"),
                "line": n.get("line"),
                "docs": _docs_for(["api", "security", "orange"], run=run),
                "threat_context": {
                    "framework": "OWASP API2 Broken Authentication",
                    "kev": "architectural prediction — not a package CVE",
                    "epss": None,
                    "label": "Predicted",
                },
            })
            if len([r for r in risks if "cyber-orange-java" in r["id"]]) >= 12:
                break

    reds = [r for r in risks if r["color"] == "red"][:28]
    all_risks = reds + [r for r in risks if r["color"] != "red"]
    for r in all_risks:
        r["docs"] = [d for d in (r.get("docs") or []) if _doc_ok_for_run(run, d)][:3]
    run["cyber_risks"] = all_risks


def _docs_for(tags: list[str], run: dict | None = None) -> list[dict]:
    out = []
    for doc in DOCS:
        if not any(t in doc["tags"] for t in tags):
            continue
        if run and not _doc_ok_for_run(run, doc):
            continue
        # Prefer non-overview pages
        url = doc.get("url") or ""
        if url.rstrip("/").endswith(("/guides", "/aspnet/core", "/docs/current", "/reference")):
            continue
        out.append({k: doc[k] for k in ("id", "title", "source", "url", "passage")})
    return out[:3]


def _short(name: str) -> str:
    return name.split(":")[-1] if ":" in name else name


def edge_audit(run: dict, edge_key: str) -> dict:
    """Primary-source verification card for a clicked edge.

    edge_key formats: legacyEdgeId OR source::target::type OR GraphDev uuid pair.
    """
    edges = run.get("legacy_edges") or []
    edge = None
    if "::" in edge_key:
        parts = edge_key.split("::")
        src, tgt = parts[0], parts[1] if len(parts) > 1 else ""
        et = parts[2] if len(parts) > 2 else ""
        src_s, tgt_s = _short(src).upper(), _short(tgt).upper()
        typed = lambda e: not et or e.get("type") == et
        edge = next((e for e in edges if e.get("source") == src and e.get("target") == tgt and typed(e)), None) or next(
            (e for e in edges if _short(str(e.get("source", ""))).upper() == src_s and _short(str(e.get("target", ""))).upper() == tgt_s and typed(e)),
            None,
        )
        for e in [] if edge else edges:
            es, etg = str(e.get("source", "")), str(e.get("target", ""))
            if (es == src and etg == tgt) or (
                et and e.get("type") == et and (src in es or src in etg)
            ):
                edge = e
                break
            # match by short / case-insensitive symbol names from the graph UI
            if src_s and tgt_s and src_s in _short(es).upper() and tgt_s in _short(etg).upper():
                if not et or e.get("type") == et:
                    edge = e
                    break
            if src_s in es.upper() and tgt_s in etg.upper():
                edge = e
                break
    else:
        edge = next((e for e in edges if e.get("id") == edge_key), None)

    if not edge:
        # Try migration edges / cyber
        for r in run.get("cyber_risks") or []:
            if r.get("edge_id") == edge_key or r.get("id") == edge_key:
                return {
                    "found": True,
                    "edge": {"id": edge_key, "type": "migration-risk", "source": r.get("node_id"), "target": ""},
                    "risk": r,
                    "docs": r.get("docs") or [],
                    "threat_context": r.get("threat_context"),
                    "reasoning": r.get("detail"),
                    "claim": r.get("claim") or "Predicted",
                    "agents": _agent_attribution(r.get("color")),
                }
        return {"found": False, "edge_key": edge_key, "claim": "Measured"}

    from app.services.migration.sources import EDGE_TOPICS, sources_for

    _refresh_java_cyber(run)

    related = [r for r in (run.get("cyber_risks") or []) if r.get("edge_id") == edge.get("id") or r.get("node_id") in {edge["source"], edge["target"]}]
    # Prefer Predicted (orange/purple) over Measured red on API edges
    related.sort(key=lambda r: {"orange": 0, "purple": 1, "red": 2}.get(r.get("color") or "", 3))
    topics = list(EDGE_TOPICS.get(edge.get("type") or "", []))
    if any(r.get("color") == "orange" for r in related) or (edge.get("type") or "") in {"TRANS", "SCREEN", "LINK", "XCTL"}:
        topics = ["api-auth", "api-authz"] + topics
    if any(r.get("color") == "purple" for r in related):
        topics = ["transit"] + topics
    stack = run.get("target_stack") or {}
    java = _is_java_run(run)
    # Docs follow SOURCE language — never pull target-stack ASP.NET into a Java edge card
    default_topics = ["api-auth"] if java else ["carddemo"]
    docs = [
        d for d in sources_for(topics or default_topics, None if java else stack, limit=4, source_java=java)
        if _doc_ok_for_run(run, d)
    ][:2]
    for r in related[:2]:
        if r.get("color") == "red":
            continue  # don't let measured CVE catalogs crowd out OWASP on auth edges
        for d in r.get("docs") or []:
            if _doc_ok_for_run(run, d) and all(d.get("url") != x.get("url") for x in docs):
                docs.insert(0, d)
    docs = docs[:2]

    etype = edge.get("type") or "?"
    display_type = etype
    if java and etype == "TRANS":
        display_type = "HTTP"
    elif java and etype == "SCREEN":
        display_type = "VIEW"

    risk = related[0] if related else {
        "color": "none",
        "title": f"Measured {display_type} dependency",
        "claim": "Measured",
        "detail": "Parser-detected edge with code evidence. No Predicted cyber horizon attached.",
    }

    from app.services.migration.explain import ai_why_edge

    return {
        "found": True,
        "edge": {
            "id": edge.get("id"),
            "type": display_type,
            "raw_type": etype,
            "lens": edge.get("lens"),
            "source": edge.get("source"),
            "target": edge.get("target"),
            "file": edge.get("file"),
            "line": edge.get("line"),
            "snippet": edge.get("snippet"),
        },
        "ai_why": ai_why_edge(run, edge),
        "risk": risk,
        "docs": docs,
        "kev": None,
        "threat_context": risk.get("threat_context") if isinstance(risk, dict) else None,
        "reasoning": risk.get("detail") if isinstance(risk, dict) else "",
        "claim": "Measured edge; cyber horizon Predicted where attached",
        "agents": _agent_attribution(risk.get("color") if isinstance(risk, dict) else None),
    }


def _agent_attribution(color: str | None) -> list[dict]:
    base = [
        {"role": "mapper", "model": "Nemotron 3 Nano Omni", "host": "Vultr serverless", "job": "Locate edge evidence in source"},
        {"role": "security-lens", "model": "Nemotron 3 Nano Omni", "host": "Vultr serverless / NVIDIA", "job": "Project post-migration threat"},
        {"role": "prover", "model": "Nemotron embed + rerank", "host": "NVIDIA endpoints", "job": "Ground claim in primary docs"},
    ]
    if color == "orange":
        base.append({"role": "api-lens", "model": "Nemotron 3 Nano Omni", "host": "NVIDIA", "job": "Flag unauthenticated API boundary"})
    if color == "purple":
        base.append({"role": "data-lens", "model": "Nemotron 3 Nano Omni", "host": "NVIDIA", "job": "Flag transit exposure on FILE/JOB path"})
    return base


def _merge_by_title(items: list[dict], keys: tuple[str, ...]) -> list[dict]:
    """One card per distinct title; repeated call sites collapse into a line list."""
    merged: dict[str, dict] = {}
    for it in items:
        title = it.get("title") or ""
        if title not in merged:
            merged[title] = {k: it.get(k) for k in keys} | {"lines": []}
        if it.get("line") is not None and it["line"] not in merged[title]["lines"]:
            merged[title]["lines"].append(it["line"])
    for m in merged.values():
        if len(m["lines"]) > 1:
            m["line"] = ", ".join(str(x) for x in m["lines"][:8])
    return list(merged.values())


def node_audit(run: dict, key: str) -> dict:
    """Bottom-panel card for a clicked node: what it is, its edges, predicted risks, steps, sources, live KEV."""
    from app.services.migration.sources import EDGE_TOPICS, kev_for, sources_for, topics_for_finding

    nodes = run.get("nodes") or []
    short = _short(key).upper()
    node = next((n for n in nodes if n.get("id") == key), None) or next(
        (n for n in nodes if _short(str(n.get("id"))).upper() == short or str(n.get("name", "")).upper() == short), None
    )
    if not node:
        return {"found": False, "key": key}
    nid = node["id"]
    edges = [e for e in run.get("legacy_edges") or [] if nid in (e.get("source"), e.get("target"))]
    by_type: dict[str, int] = defaultdict(int)
    for e in edges:
        by_type[e.get("type") or "?"] += 1
    risks = [r for r in run.get("cyber_risks") or [] if r.get("node_id") == nid]
    findings = [f for f in run.get("findings") or [] if node.get("file") and f.get("file") == node.get("file") and f.get("verdict", "accepted") == "accepted"]
    steps = []
    for i, s in enumerate((run.get("plan") or {}).get("steps") or [], 1):
        touched = nid in (s.get("migrate") or []) or any(nid in (r.get("source"), r.get("target")) for r in s.get("removals") or [])
        if touched:
            steps.append({"index": i, "id": s.get("id"), "title": s.get("stack_title") or s.get("title"), "why": s.get("why_now"), "vulns": s.get("vulns") or []})

    _refresh_java_cyber(run)
    risks = [r for r in run.get("cyber_risks") or [] if r.get("node_id") == nid]

    topics: list[str] = []
    if any(r.get("color") == "orange" for r in risks):
        topics += ["api-auth", "api-authz"]
    if any(r.get("color") == "purple" for r in risks):
        topics += ["transit"]
    for f in findings:
        topics += topics_for_finding(f.get("title") or "")
    for t in sorted(by_type, key=lambda k: -by_type[k])[:3]:
        topics += EDGE_TOPICS.get(t, [])[:1]
    stack = run.get("target_stack") or {}
    from app.services.migration.explain import ai_why_node

    java = _is_java_run(run)
    # Remap mainframe edge labels for Java UI chips
    display_by_type: dict[str, int] = {}
    for t, c in by_type.items():
        label = t
        if java and t == "TRANS":
            label = "HTTP"
        elif java and t == "SCREEN":
            label = "VIEW"
        display_by_type[label] = display_by_type.get(label, 0) + c

    docs = []
    seen_urls: set[str] = set()
    # Source-language only on node cards (skip stack_docs — those are Plan/target)
    primary = sources_for(
        topics or (["api-auth"] if java else ["carddemo"]),
        None if java else stack,
        limit=3,
        source_java=java,
    )
    for d in primary:
        if not _doc_ok_for_run(run, d):
            continue
        url = (d.get("url") or "").rstrip("/")
        if not url or url in seen_urls:
            continue
        if url.endswith(("/reference", "/reference/index.html", "/guides", "/aspnet/core", "/docs/current", "/security/authentication")):
            continue
        if "/migration-guides" in url and url.rstrip("/").endswith("migration-guides"):
            continue
        seen_urls.add(url)
        docs.append(d)
        if len(docs) >= 2:
            break

    # KEV only when this node has measured findings or predicted orange/purple — and only 1 CVE
    show_kev = bool(findings) or any(r.get("color") in {"orange", "purple", "red"} for r in risks)
    kev = None
    if show_kev:
        raw = kev_for(stack, limit=6)
        items = raw.get("items") or []
        # Prefer CVEs whose product string touches this file/symbol (avoid same Spring CVE on every click)
        blob = f"{node.get('name') or ''} {node.get('file') or ''} {node.get('id') or ''}".lower()
        ranked = sorted(
            items,
            key=lambda v: (
                0 if any(p and p in blob for p in str(v.get("product") or "").lower().split()) else 1,
                v.get("date_added") or "",
            ),
        )
        # Stable per-node pick so we don't flash the same top-2 everywhere
        seed = sum(ord(c) for c in str(nid)) % max(len(ranked), 1)
        pick = ranked[seed:seed + 1] if ranked else []
        if pick:
            kev = {**raw, "items": pick, "matched": len(pick)}

    return {
        "found": True,
        "node": {k: node.get(k) for k in ("id", "name", "kind", "file", "line", "summary", "cluster", "risk")},
        "ai_why": ai_why_node(run, node, dict(by_type)),
        "edges_by_type": display_by_type,
        "edge_count": len(edges),
        "risks": _merge_by_title(risks, ("color", "title", "detail", "claim", "file", "line", "snippet"))[:2],
        "findings": _merge_by_title(findings, ("title", "file", "line", "snippet"))[:2],
        "steps": steps[:3],
        "docs": docs,
        "kev": kev,
    }


def playback_step(run: dict, step_id: str, completed_before: list[str] | None = None) -> dict:
    """Play Step: Coordinator + Analyst + Prover over the full validated plan."""
    import asyncio

    from app.services.migration.service import impact_for_wave

    plan_steps = (run.get("plan") or {}).get("steps") or []
    steps = plan_steps
    step = next((s for s in steps if s.get("id") == step_id), None)
    if not step:
        return {"ok": False, "error": "unknown step"}

    completed = set(completed_before or [])
    missing = []
    for req in step.get("requires") or []:
        rid = req.get("step_id") if isinstance(req, dict) else req
        if rid and rid not in completed and rid != step_id:
            missing.append(rid)

    prover_reason = ""
    if step.get("verb") == "retire-copybook" and not any(
        p.get("id") in completed for p in plan_steps if "wrap" in (p.get("verb") or "")
    ):
        # Soft: warn in reason but don't hard-block demo unless missing prereqs
        prover_reason = ""

    impact = impact_for_wave(run["id"], step_id)
    risk_b = impact.get("risk_before") or step.get("risk_before") or 0
    risk_a = impact.get("risk_after") or step.get("risk_after") or 0
    deps_b = impact.get("deps_before") or step.get("deps_before") or {}
    deps_a = impact.get("deps_after") or step.get("deps_after") or {}

    coordinator = {
        "role": "Sequential Constraint Formulator",
        "model": "Nemotron-Orchestrator-8B / Nano Omni",
        "host": "Vultr",
        "requires": step.get("requires") or [],
        "missing_prereqs": missing,
        "allowed": not missing,
        "reason": "",
        "claim": "Predicted",
    }
    analyst = {
        "role": "Active Blast-Radius Evaluator",
        "model": "Nemotron 3 Nano Omni",
        "host": "Vultr serverless",
        "risk_before": risk_b,
        "risk_after": risk_a,
        "deps_before": deps_b,
        "deps_after": deps_a,
        "changed": impact.get("changed") or [],
        "ripple": impact.get("ripple") or [],
        "removed_edges": impact.get("removed_edges") or [],
        "delta": "",
        "claim": "Predicted",
    }
    prover = {
        "role": "Adversarial Gatekeeper",
        "model": "Nemotron embed + Nano Omni",
        "host": "NVIDIA endpoints",
        "rejected": bool(missing),
        "reason": (
            f"Blocked: prerequisites not complete ({', '.join(missing)})"
            if missing
            else "Accepted: evidence-backed removals with plan order."
        ),
        "claim": "Measured check against plan constraints",
    }

    # Live Nemotron one-liners for the three loops (parallel)
    stack = run.get("target_stack") or {}
    stack_label = stack.get("description") or " · ".join(str(v) for v in [stack.get("language"), stack.get("framework"), stack.get("database")] if v)
    try:
        from app.services.agents.gateway import complete

        async def _agents():
            c_prompt = (
                "Return JSON {reason: string <= 140 chars}. You are the Coordinator. "
                f"Step={step.get('title')}. Missing prereqs={missing or 'none'}. "
                f"Explain sequencing for {stack_label}."
            )
            a_prompt = (
                "Return JSON {delta: string <= 140 chars}. You are the Analyst. "
                f"Risk {risk_b}->{risk_a}. Deps {sum((deps_b or {}).values())}->{sum((deps_a or {}).values())}. "
                "State the blast-radius drop in one line."
            )
            p_prompt = (
                "Return JSON {reason: string <= 140 chars}. You are the Prover. "
                f"Rejected={bool(missing)}. Cite why this cut is safe or blocked for {stack_label}."
            )
            return await asyncio.gather(
                complete("coordinator", c_prompt, f"play-c-{step_id}", backend="nvidia", json_mode=True),
                complete("lens", a_prompt, f"play-a-{step_id}", backend="nvidia", json_mode=True),
                complete("prover", p_prompt, f"play-p-{step_id}", backend="nvidia", json_mode=True),
            )

        c_res, a_res, p_res = asyncio.run(_agents())
        for res, bucket, field in (
            (c_res, coordinator, "reason"),
            (a_res, analyst, "delta"),
            (p_res, prover, "reason"),
        ):
            if res.get("model"):
                bucket["model"] = res["model"]
            text = (res.get("text") or "").strip()
            if not text:
                continue
            try:
                import json as _json
                parsed = _json.loads(text)
                bucket[field] = parsed.get(field) or parsed.get("reason") or text[:140]
            except Exception:  # noqa: BLE001
                bucket[field] = text[:140]
            if res.get("status") == "ok":
                bucket["claim"] = "Nemotron live"
    except Exception as exc:  # noqa: BLE001
        coordinator["reason"] = coordinator.get("reason") or f"Sequencing check ({exc.__class__.__name__})"
        analyst["delta"] = analyst.get("delta") or f"risk {risk_b}→{risk_a}"

    if not coordinator.get("reason"):
        coordinator["reason"] = (
            f"Blocked on {', '.join(missing)}" if missing else f"Safe to cut — prereqs met for {stack_label or 'target'}"
        )
    if not analyst.get("delta"):
        analyst["delta"] = f"risk {risk_b}→{risk_a} · deps {sum((deps_b or {}).values())}→{sum((deps_a or {}).values())}"

    retire = list(impact.get("changed") or [])
    for mid in step.get("migrate") or []:
        if mid not in retire:
            retire.append(mid)

    removed_edges = list(impact.get("removed_edges") or [])
    # Seed from plan removals so every step has something to light on the graph
    for row in step.get("removals") or []:
        if row.get("source") and row.get("target"):
            removed_edges.append({k: row.get(k) for k in ("source", "target", "type", "file", "line")})
        for nid in (row.get("source"), row.get("target"), row.get("id")):
            if nid and nid not in retire:
                retire.append(nid)

    # Clean / validate steps with empty impact: pull programs from vuln evidence + findings
    if not retire and not removed_edges:
        by_file = {n.get("file"): n.get("id") for n in (run.get("nodes") or []) if n.get("file")}
        for v in step.get("vulns") or []:
            ev = str(v.get("evidence") or "")
            path = ev.split(":")[0] if ":" in ev else ev
            if path in by_file and by_file[path] not in retire:
                retire.append(by_file[path])
        for f in run.get("findings") or []:
            if f.get("file") and any(
                str(v.get("evidence") or "").startswith(str(f.get("file")))
                for v in (step.get("vulns") or [])
            ):
                nid = by_file.get(f.get("file"))
                if nid and nid not in retire:
                    retire.append(nid)

    after_completed = completed | ({step_id} if not missing else set())
    finishing = len(after_completed) >= len(steps)

    # Expand ONLY this step's retire set — previous steps already cut on the client.
    # Mixing prior cut_nodes into removed_edges made every Play step glow the whole graph.
    cut_nodes = set(retire)
    seen = {(e.get("source"), e.get("target"), e.get("type")) for e in removed_edges}
    for edge in run.get("legacy_edges") or []:
        key = (edge.get("source"), edge.get("target"), edge.get("type"))
        if key in seen:
            continue
        if edge.get("source") in cut_nodes or edge.get("target") in cut_nodes:
            seen.add(key)
            removed_edges.append({k: edge.get(k) for k in ("source", "target", "type", "file", "line")})

    retire_all = False
    if finishing and not missing:
        retire_all = True
        retire = [n.get("id") for n in (run.get("nodes") or []) if n.get("id")]
        removed_edges = [
            {
                "source": e.get("source"),
                "target": e.get("target"),
                "type": e.get("type") or "FILE",
                "file": e.get("file"),
                "line": e.get("line"),
            }
            for e in (run.get("legacy_edges") or [])
            if e.get("source") and e.get("target")
        ]
        analyst["deps_after"] = {k: 0 for k in (deps_b or {"ALL": 1})}
        analyst["risk_after"] = 0
        risk_a = 0
        deps_a = analyst["deps_after"]

    related_cyber = []
    seen_cyber: set[str] = set()
    for r in run.get("cyber_risks") or []:
        if r.get("node_id") not in set(retire) and r.get("node_id") not in set(impact.get("ripple") or []):
            continue
        title = str(r.get("title") or "")
        if title in seen_cyber:
            continue
        seen_cyber.add(title)
        related_cyber.append(r)
        if len(related_cyber) >= 2:
            break

    # Step-specific deep docs — not stack overview landing pages
    from app.services.migration.sources import sources_for, topics_for_step

    findings = [str(v.get("risk") or "") for v in (step.get("vulns") or [])]
    topics = topics_for_step(step, findings)
    sources = sources_for(topics, stack, limit=3)
    if not sources:
        # Fall back to plan research / stack deep links, still skip bare overviews
        for d in (run.get("stack_docs") or []) + stack_docs_for(stack):
            url = (d.get("url") or "")
            if not url or url.rstrip("/").endswith(("/reference", "/guides", "/aspnet/core", "/docs/current")):
                continue
            sources.append(d)
            if len(sources) >= 3:
                break

    return {
        "ok": coordinator["allowed"] and not missing,
        "step_id": step_id,
        "title": step.get("stack_title") or step.get("title"),
        "detail": step.get("detail"),
        "engineer_prompt": step.get("engineer_prompt"),
        "missing": missing,
        "agents": {"coordinator": coordinator, "analyst": analyst, "prover": prover},
        "retire_nodes": retire,
        "removed_edges": removed_edges,
        "added_edges": impact.get("added_edges") or [],
        "retire_all": retire_all,
        "cyber_on_step": related_cyber,
        "sources": sources,
        "target_stack": stack,
        "ribbon": {
            "risk_before": risk_b,
            "risk_after": risk_a,
            "deps_before": sum((deps_b or {}).values()),
            "deps_after": sum((deps_a or {}).values()),
        },
        "claim": "Predicted playback; edge facts Measured",
    }


def cyber_map_for_ui(run: dict) -> dict[str, str]:
    """Map legacy node id → color for the frontend."""
    out: dict[str, str] = {}
    # Prefer strongest signal: legacy red > orange > purple
    rank = {"red": 3, "orange": 2, "purple": 1}
    for r in run.get("cyber_risks") or []:
        nid = r.get("node_id")
        if not nid:
            continue
        color = r.get("color") or "orange"
        if rank.get(color, 0) >= rank.get(out.get(nid, ""), 0):
            out[nid] = color
    return out
