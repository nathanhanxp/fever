"""Question -> graph scope. Nemotron + measured graph decide nodes/edges — not the screenshot."""

from __future__ import annotations

import json
import re
from collections import deque

from sqlmodel import Session, select

from app.models import ClusterMember, CodeUnit, FeatureCluster, GraphEdge

# Spoken color → hue_name from the frontend palette (capture-graph.ts)
COLOR_ALIASES: list[tuple[str, str]] = [
    (r"\b(pink|magenta|fuchsia|hot[\s-]?pink)\b", "pink/magenta"),
    (r"\b(purple|violet|lilac)\b", "purple/violet"),
    (r"\b(yellow|gold|golden)\b", "yellow/gold"),
    (r"\b(cyan|teal|aqua)\b", "cyan"),
    (r"\b(orange|amber)\b", "orange"),
    (r"\b(green|lime|emerald)\b", "green"),
    (r"\b(blue|navy|indigo)\b", "blue"),
    (r"\bred\b", "red"),
]

# Tiny/conceptual cluster labels that must NOT hijack "what is API related?"
GENERIC_CLUSTER_LABELS = {
    "api", "data", "code", "batch", "security", "java", "util", "core",
    "other", "shared", "services", "service", "test", "tests", "main",
}

LENS_EDGES: dict[str, set[str]] = {
    "Data": {"FILE"},
    "API": {"TRANS", "SCREEN", "LINK", "XCTL"},
    "Batch": {"JOB"},
    "Code": {"CALL"},
    "Shared": {"COPY"},
    "Integration": {"LINK", "XCTL", "CALL"},
}

# Extra FeatureCluster labels that belong to a lens (Java + COBOL)
LENS_CLUSTERS: dict[str, set[str]] = {
    "API": {
        "api", "controllers", "controller", "actions", "action", "sso",
        "external", "rest", "servlet", "endpoints", "endpoint", "screens",
        "transactions", "online", "menus", "signon",
    },
    "Data": {"entities", "repository", "repositories", "datasets", "db2-types", "persistence", "jpa"},
    "Batch": {"jobs", "batch", "reports"},
    "Code": {"services", "core", "util", "support", "plugins", "extensions"},
    "Shared": {"copybooks", "formatters", "tags"},
    "Integration": {"external", "events", "plugins", "extensions", "sso"},
}

KEYWORDS: list[tuple[str, str]] = [
    (r"\b(data|dataset|datasets|file|files|vsam|db2|database|record|storage|ksds|jpa|entity|entities|repository)\b", "Data"),
    (r"\b(api|apis|rest|http|endpoint|endpoints|controller|controllers|servlet|screen|screens|transaction|transactions|cics|online|ui|bms|map|route|routes)\b", "API"),
    (r"\b(batch|job|jobs|jcl|schedule|nightly)\b", "Batch"),
    (r"\b(copybook|copybooks|shared layout|layout|copy)\b", "Shared"),
    (r"\b(call|calls|subprogram|service layer)\b", "Code"),
]
SECURITY_TERMS = ["PASSWORD", "PASSWD", "USRSEC", "SEC-USR", "SIGNON", "CARD-NUM", "CARDNUM", "CVV", "SSO", "AUTH"]
GENERIC_TERMS = {"FILE", "DATA", "READ", "WRITE", "MOVE", "CALL", "EXEC", "CICS", "COPY", "PROGRAM", "RECORD", "SECTION", "DISPLAY", "VALUE"}

COLOR_QUESTION = re.compile(
    r"\b(pink|magenta|fuchsia|purple|violet|yellow|gold|cyan|teal|orange|amber|green|lime|blue|navy|red|color|colour|hue)\b",
    re.I,
)


def is_color_question(question: str) -> bool:
    return bool(COLOR_QUESTION.search(question or ""))


def _keyword_scope(question: str) -> dict:
    q = question.lower()
    lens = next((name for pat, name in KEYWORDS if re.search(pat, q)), None)
    terms = SECURITY_TERMS if re.search(r"\b(security|secure|vuln|password|auth|pci|card number|pan|risk|sso)\b", q) else []
    symbols = re.findall(r"\b[A-Z][A-Z0-9]{3,}\b", question)
    return {"lens": lens, "symbols": symbols, "terms": terms, "direction": "both", "label": None}


async def _nemotron_scope(question: str, names: list[str], cluster_labels: list[str]) -> tuple[dict | None, str | None]:
    from app.services.agents.gateway import complete

    prompt = (
        "Map a question about a codebase dependency graph (COBOL/CICS OR Java/Spring/VRaptor) to a filter. "
        "Return JSON only: "
        '{"lens": "Data"|"API"|"Batch"|"Shared"|"Code"|"Integration"|null, '
        '"symbols": [names from the list ONLY if the question names them; else []], '
        '"terms": [identifiers for concept questions; else []], '
        '"clusters": [feature-cluster labels from the known list that belong to the answer], '
        '"direction": "dependents"|"dependencies"|"both", '
        '"label": "<=8 word title for what is shown"}. '
        "API = HTTP/controllers/screens/transactions/SSO/REST (not just a cluster literally named api). "
        "Data = persistence/entities/files. Code = services/calls. "
        f"Known cluster labels: {', '.join(cluster_labels[:80])}. "
        f"Sample symbols: {', '.join(names[:200])}. Question: {question}"
    )
    res = await complete("lens", prompt, f"scope-{question.strip().lower()[:80]}", backend="nvidia", json_mode=True)
    try:
        parsed = json.loads((res.get("text") or "").strip())
        return (parsed if isinstance(parsed, dict) else None), res.get("model")
    except json.JSONDecodeError:
        return None, res.get("model")


def match_palette_row(question: str, clusters: list[dict] | None) -> dict | None:
    """Map 'pink cluster' onto a ground-truth palette row — not conceptual words like 'api'."""
    if not clusters:
        return None
    q = (question or "").lower()

    # Explicit "the <label> cluster/region" — allow any label
    explicit = re.search(r"\b(?:the|cluster|region|group)\s+[\"']?([a-z0-9._/-]+)[\"']?\s*(?:cluster|region|group)?\b", q)
    if explicit:
        want = explicit.group(1).lower()
        for c in clusters:
            label = str(c.get("label") or "").strip().lower()
            if label == want:
                return c

    # Bare label match only for distinctive names (not api/data/code/…)
    if is_color_question(q) or re.search(r"\b(cluster|region|color|colour)\b", q):
        for c in sorted(clusters, key=lambda r: -(r.get("count") or 0)):
            label = str(c.get("label") or "").strip()
            if not label or label.lower() in GENERIC_CLUSTER_LABELS:
                continue
            if re.search(rf"\b{re.escape(label.lower())}\b", q):
                return c

    wanted: str | None = None
    for pat, hue_name in COLOR_ALIASES:
        if re.search(pat, q, flags=re.I):
            wanted = hue_name
            break
    if not wanted:
        return None
    hits = [
        c for c in clusters
        if wanted in str(c.get("hue_name") or c.get("color_name") or "").lower()
        or str(c.get("hue_name") or "").lower() == wanted
    ]
    if not hits and wanted == "pink/magenta":
        hits = [
            c for c in clusters
            if isinstance(c.get("hue"), (int, float)) and 300 <= float(c["hue"]) % 360 < 345
        ]
    if not hits and wanted == "red":
        hits = [
            c for c in clusters
            if isinstance(c.get("hue"), (int, float)) and (float(c["hue"]) % 360 < 15 or float(c["hue"]) % 360 >= 345)
        ]
    if not hits:
        return None
    return max(hits, key=lambda r: r.get("count") or 0)


def scope_cluster_label(session: Session, snapshot_id: str, label: str, *, hue_name: str | None = None) -> dict:
    """Isolate units that belong to a FeatureCluster label (color focus for Ask)."""
    units = list(session.exec(select(CodeUnit).where(CodeUnit.snapshot_id == snapshot_id)).all())
    edges = list(session.exec(select(GraphEdge).where(GraphEdge.snapshot_id == snapshot_id)).all())
    by_id = {u.id: u for u in units}

    clusters = list(session.exec(select(FeatureCluster).where(FeatureCluster.snapshot_id == snapshot_id)).all())
    target = next((c for c in clusters if (c.label or "").lower() == label.lower()), None)
    if not target:
        target = next((c for c in clusters if label.lower() in (c.label or "").lower()), None)
    if not target:
        return {"node_ids": [], "edge_keys": [], "count": 0, "lens": None, "label": None, "model": None}

    members = list(session.exec(select(ClusterMember).where(ClusterMember.cluster_id == target.id)).all())
    node_ids = {m.code_unit_id for m in members if m.code_unit_id in by_id}
    edge_rows = [
        e for e in edges
        if e.source_unit_id in node_ids and e.target_unit_id in node_ids
    ]
    if not edge_rows:
        edge_rows = [
            e for e in edges
            if e.source_unit_id in node_ids or e.target_unit_id in node_ids
        ]

    edge_keys = sorted({
        f"{e.source_unit_id}::{e.target_unit_id}::{e.edge_type}"
        for e in edge_rows
        if e.source_unit_id in node_ids and e.target_unit_id in node_ids
    })
    top = sorted(node_ids, key=lambda i: -(by_id[i].hub_score if i in by_id else 0))[:8]
    color_bit = f"{hue_name} · " if hue_name else ""
    return {
        "node_ids": sorted(node_ids),
        "edge_keys": edge_keys,
        "count": len(node_ids),
        "edge_count": len(edge_keys),
        "lens": None,
        "symbols": [],
        "terms": [],
        "label": f"{color_bit}{target.label}",
        "top": [by_id[i].symbol_name for i in top if i in by_id],
        "model": None,
        "cluster_label": target.label,
        "hue_name": hue_name,
        "cluster_labels": [target.label],
    }


def _cluster_member_ids(session: Session, snapshot_id: str, wanted: set[str]) -> tuple[set[str], list[str]]:
    """Resolve FeatureCluster labels → unit ids."""
    if not wanted:
        return set(), []
    clusters = list(session.exec(select(FeatureCluster).where(FeatureCluster.snapshot_id == snapshot_id)).all())
    matched: list[str] = []
    ids: set[str] = set()
    for c in clusters:
        lab = (c.label or "").strip().lower()
        if not lab:
            continue
        if lab in wanted or any(w in lab for w in wanted):
            matched.append(c.label or lab)
            for m in session.exec(select(ClusterMember).where(ClusterMember.cluster_id == c.id)).all():
                if m.code_unit_id:
                    ids.add(m.code_unit_id)
    return ids, matched


def _java_api_seeds(units: list[CodeUnit]) -> set[str]:
    """Controllers / actions / servlet-facing units for Java graphs."""
    out: set[str] = set()
    for u in units:
        blob = f"{u.symbol_name or ''} {u.qualname or ''} {u.kind or ''} {u.file_path or ''}".lower()
        if any(k in blob for k in (
            "controller", "servlet", "interceptor", "/actions/", ".actions.",
            "restcontroller", "requestmapping", "httpServlet",
        )):
            out.add(u.id)
        if (u.kind or "").lower() in {"screen", "transaction", "map"}:
            out.add(u.id)
    return out


def scope_facts(
    session: Session,
    snapshot_id: str,
    scope: dict,
    *,
    limit_nodes: int = 24,
) -> str:
    """Measured facts for the Ask agent — names, clusters, edge types (not image prose)."""
    if not scope.get("count"):
        return ""
    units = {
        u.id: u
        for u in session.exec(select(CodeUnit).where(CodeUnit.snapshot_id == snapshot_id)).all()
    }
    edges = list(session.exec(select(GraphEdge).where(GraphEdge.snapshot_id == snapshot_id)).all())
    node_ids = set(scope.get("node_ids") or [])
    edge_keys = set(scope.get("edge_keys") or [])

    from collections import Counter
    type_counts: Counter[str] = Counter()
    for e in edges:
        key = f"{e.source_unit_id}::{e.target_unit_id}::{e.edge_type}"
        if key in edge_keys or (
            e.source_unit_id in node_ids and e.target_unit_id in node_ids
        ):
            type_counts[e.edge_type or "?"] += 1

    # Cluster breakdown of scoped nodes
    clusters = list(session.exec(select(FeatureCluster).where(FeatureCluster.snapshot_id == snapshot_id)).all())
    unit_cluster: dict[str, str] = {}
    for c in clusters:
        for m in session.exec(select(ClusterMember).where(ClusterMember.cluster_id == c.id)).all():
            if m.code_unit_id:
                unit_cluster[m.code_unit_id] = c.label or "?"
    cluster_counts = Counter(unit_cluster[i] for i in node_ids if i in unit_cluster)

    top = sorted(
        [units[i] for i in node_ids if i in units],
        key=lambda u: -(u.hub_score or 0),
    )[:limit_nodes]
    lines = [
        "MEASURED GRAPH SCOPE (authoritative — answer from this, not the screenshot):",
        f"Lens/label: {scope.get('label') or scope.get('lens') or 'related'} · "
        f"{scope.get('count')} units · {scope.get('edge_count') or len(edge_keys)} edges",
    ]
    if scope.get("cluster_labels"):
        lines.append(f"Clusters included: {', '.join(scope['cluster_labels'])}")
    if cluster_counts:
        lines.append(
            "Units by cluster: "
            + ", ".join(f"{k} ({v})" for k, v in cluster_counts.most_common(12))
        )
    if type_counts:
        lines.append(
            "Edge types: "
            + ", ".join(f"{k}×{v}" for k, v in type_counts.most_common(8))
        )
    lines.append("Key units:")
    for u in top:
        cl = unit_cluster.get(u.id, "")
        lines.append(
            f"- {u.symbol_name} [{u.kind or '?'}{('/' + cl) if cl else ''}] "
            f"hub={round(u.hub_score or 0, 2)} · {(u.file_path or '')[:80]}"
        )
    lines.append(
        "Explain what these units do together in THIS repo. Name concrete symbols. "
        "Do not invent a single-node answer when many units are listed."
    )
    return "\n".join(lines)


async def scope_question(
    session: Session,
    snapshot_id: str,
    question: str,
    *,
    clusters: list[dict] | None = None,
) -> dict:
    # Color questions → palette cluster. Conceptual "API related" must NOT match label "api".
    if is_color_question(question):
        row = match_palette_row(question, clusters)
        if row and row.get("label"):
            scoped = scope_cluster_label(
                session,
                snapshot_id,
                str(row["label"]),
                hue_name=str(row.get("hue_name") or "") or None,
            )
            if scoped.get("count"):
                return scoped
    else:
        # Non-color: only explicit "the external cluster" style label hits
        row = match_palette_row(question, clusters)
        if row and row.get("label") and str(row["label"]).lower() not in GENERIC_CLUSTER_LABELS:
            # Only if question clearly names that region
            if re.search(rf"\b{re.escape(str(row['label']).lower())}\b", (question or "").lower()):
                if re.search(r"\b(cluster|region|group|named)\b", (question or "").lower()):
                    scoped = scope_cluster_label(
                        session,
                        snapshot_id,
                        str(row["label"]),
                        hue_name=str(row.get("hue_name") or "") or None,
                    )
                    if scoped.get("count"):
                        return scoped

    units = list(session.exec(select(CodeUnit).where(CodeUnit.snapshot_id == snapshot_id)).all())
    edges = list(session.exec(select(GraphEdge).where(GraphEdge.snapshot_id == snapshot_id)).all())
    names = sorted({u.symbol_name for u in units if u.symbol_name})
    feature_clusters = list(session.exec(select(FeatureCluster).where(FeatureCluster.snapshot_id == snapshot_id)).all())
    cluster_labels = [c.label for c in feature_clusters if c.label]

    model = None
    try:
        spec, model = await _nemotron_scope(question, names, cluster_labels)
    except Exception:  # noqa: BLE001
        spec = None
    fallback = _keyword_scope(question)
    if not spec:
        spec = fallback
    upper_names = {n.upper(): n for n in names}
    q_upper = question.upper()
    symbols = list(dict.fromkeys(
        upper_names[s.upper()] for s in (spec.get("symbols") or []) + fallback["symbols"]
        if isinstance(s, str) and s.upper() in upper_names and re.search(rf"\b{re.escape(s.upper())}\b", q_upper)
    ))
    terms = [
        t.upper() for t in (spec.get("terms") or []) + fallback["terms"]
        if isinstance(t, str) and len(t) >= 4 and t.upper() not in GENERIC_TERMS
    ]
    terms = list(dict.fromkeys(terms))[:12]

    lens = spec.get("lens") if spec.get("lens") in LENS_EDGES else fallback.get("lens")
    if symbols and not fallback.get("lens"):
        lens = None
    types = LENS_EDGES.get(lens or "", set())

    # Cluster names from Nemotron + defaults for the lens
    wanted_clusters = {
        str(x).lower() for x in (spec.get("clusters") or [])
        if isinstance(x, str) and x.strip()
    }
    wanted_clusters |= LENS_CLUSTERS.get(lens or "", set())
    cluster_ids, matched_clusters = _cluster_member_ids(session, snapshot_id, wanted_clusters)

    by_id = {u.id: u for u in units}
    lens_edges = [e for e in edges if not types or e.edge_type in types]
    node_ids: set[str] = set()
    edge_rows: list[GraphEdge] = []

    seeds = {u.id for u in units if u.symbol_name in symbols}
    if lens == "API":
        seeds |= _java_api_seeds(units)
    seeds |= cluster_ids

    if terms and not seeds:
        pattern = re.compile(r"(?<![A-Z0-9-])(" + "|".join(re.escape(t) for t in terms) + r")(?![A-Z0-9])")
        for u in units:
            if pattern.search(f"{u.symbol_name} {u.source_text or ''}".upper()):
                seeds.add(u.id)

    if seeds:
        direction = spec.get("direction") or "both"
        # For wide API seeds (many controllers), keep hops small but include all seeds
        node_ids = set(seeds)
        adj: dict[str, list[GraphEdge]] = {}
        use_edges = lens_edges if types else edges
        for e in use_edges:
            if direction in ("dependencies", "both"):
                adj.setdefault(e.source_unit_id, []).append(e)
            if direction in ("dependents", "both"):
                adj.setdefault(e.target_unit_id, []).append(e)
        hops = {s: 0 for s in seeds}
        queue = deque(seeds)
        max_hops = 1 if len(seeds) > 20 else 2
        while queue:
            cur = queue.popleft()
            if hops[cur] >= max_hops:
                continue
            for e in adj.get(cur, []):
                other = e.target_unit_id if e.source_unit_id == cur else e.source_unit_id
                edge_rows.append(e)
                if other not in hops:
                    hops[other] = hops[cur] + 1
                    queue.append(other)
        node_ids = set(hops)
    elif types:
        edge_rows = lens_edges
        for e in edge_rows:
            node_ids.update((e.source_unit_id, e.target_unit_id))

    # Always fold matched cluster members into the answer set for lens questions
    if cluster_ids and lens:
        node_ids |= cluster_ids
        for e in edges:
            if e.source_unit_id in cluster_ids and e.target_unit_id in cluster_ids:
                edge_rows.append(e)

    if not node_ids:
        return {"node_ids": [], "edge_keys": [], "count": 0, "lens": lens, "label": None, "model": model}

    # Cap enormous scopes for UI isolate, but keep top hubs + all direct seeds
    if len(node_ids) > 180:
        ranked = sorted(node_ids, key=lambda i: -(by_id[i].hub_score if i in by_id else 0))
        keep = set(ranked[:160]) | seeds | cluster_ids
        node_ids = keep
        edge_rows = [
            e for e in edge_rows
            if e.source_unit_id in node_ids and e.target_unit_id in node_ids
        ]

    edge_keys = sorted({f"{e.source_unit_id}::{e.target_unit_id}::{e.edge_type}" for e in edge_rows
                        if e.source_unit_id in node_ids and e.target_unit_id in node_ids})
    top = sorted(node_ids, key=lambda i: -(by_id[i].hub_score if i in by_id else 0))[:12]
    title = spec.get("label")
    if not title:
        if matched_clusters:
            title = f"API surface · {', '.join(matched_clusters[:4])}" if lens == "API" else f"{lens}: {', '.join(matched_clusters[:4])}"
        elif lens:
            title = f"{lens} dependencies"
        elif terms:
            title = f"Code touching {', '.join(terms[:3])}"
        elif symbols:
            title = f"Around {', '.join(symbols[:3])}"
        else:
            title = "Related units"

    return {
        "node_ids": sorted(node_ids),
        "edge_keys": edge_keys,
        "count": len(node_ids),
        "edge_count": len(edge_keys),
        "lens": lens,
        "symbols": symbols[:8],
        "terms": terms,
        "label": title,
        "top": [by_id[i].symbol_name for i in top if i in by_id],
        "model": model,
        "cluster_labels": matched_clusters,
    }
