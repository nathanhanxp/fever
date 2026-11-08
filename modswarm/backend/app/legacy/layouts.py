"""Three real layouts. Similarity is UMAP on structural features, or absent if UMAP fails.

No coordinates are invented when a method fails. HDBSCAN labels are recorded and used
as capability groups only when the count lands between 10 and 30.
"""

from __future__ import annotations

import math
from collections import defaultdict

KIND_COL = {
    "transaction": 0,
    "job": 0,
    "program": 1,
    "screen": 2,
    "copybook": 2,
    "dataset": 3,
    "interface": 3,
}
EDGE_TYPES = ["COPY", "CALL", "LINK", "XCTL", "FILE", "JOB", "TRANS", "SCREEN"]
KINDS = ["program", "copybook", "dataset", "job", "transaction", "screen", "interface"]


def _features(nodes: list[dict], edges: list[dict]) -> list[list[float]]:
    index = {n["id"]: i for i, n in enumerate(nodes)}
    out_c = [defaultdict(int) for _ in nodes]
    in_c = [defaultdict(int) for _ in nodes]
    for e in edges:
        if e.get("predicted"):
            continue
        si = index.get(e["source"])
        ti = index.get(e["target"])
        if si is not None:
            out_c[si][e["type"]] += 1
        if ti is not None:
            in_c[ti][e["type"]] += 1
    rows = []
    for i, n in enumerate(nodes):
        deg = math.log1p(n.get("degree") or 0)
        kind = [1.0 if n.get("kind") == k else 0.0 for k in KINDS]
        outv = [math.log1p(out_c[i][t]) for t in EDGE_TYPES]
        inv = [math.log1p(in_c[i][t]) for t in EDGE_TYPES]
        rows.append(kind + outv + inv + [deg, 1.0 if n.get("hub") else 0.0])
    return rows


def _layered(nodes: list[dict]) -> dict[str, list[float]]:
    buckets: dict[int, list[dict]] = defaultdict(list)
    for n in nodes:
        buckets[KIND_COL.get(n.get("kind"), 1)].append(n)
    pos = {}
    for col, members in buckets.items():
        members = sorted(members, key=lambda n: (n.get("cluster") or "", n.get("name") or ""))
        height = 22.0
        for i, n in enumerate(members):
            t = 0.5 if len(members) == 1 else i / (len(members) - 1)
            y = (t - 0.5) * height
            z = ((hash(n.get("cluster") or "") % 9) - 4) * 0.45
            pos[n["id"]] = [round(col * 8.0, 4), round(y, 4), round(z, 4)]
    return pos


def _separate(points: dict[str, list[float]], min_dist: float = 4.5) -> None:
    ids = list(points)
    for _ in range(30):
        for i in range(len(ids)):
            for j in range(i + 1, len(ids)):
                a = points[ids[i]]
                b = points[ids[j]]
                dx, dz = a[0] - b[0], a[2] - b[2]
                dist = math.hypot(dx, dz) or 0.001
                if dist >= min_dist:
                    continue
                push = (min_dist - dist) / 2
                ux, uz = dx / dist, dz / dist
                a[0] += ux * push
                a[2] += uz * push
                b[0] -= ux * push
                b[2] -= uz * push


def attach_geometry(nodes: list[dict], edges: list[dict]) -> dict:
    layered = _layered(nodes)
    topdown = {i: [p[0], 0.0, p[1]] for i, p in layered.items()}
    meta: dict = {
        "similarity": None,
        "clustering": {"method": "name-and-directory", "used_for_view": True, "n_clusters": 0, "note": ""},
    }
    non_hubs = [n for n in nodes if not n.get("hub")]
    features = _features(nodes, edges)
    similarity: dict[str, list[float]] | None = None
    embedding = None
    try:
        import numpy as np
        import umap

        matrix = np.array(features, dtype=float)
        fit_idx = [i for i, n in enumerate(nodes) if not n.get("hub")]
        if len(fit_idx) >= 8:
            reducer = umap.UMAP(n_components=2, random_state=42, n_neighbors=min(15, len(fit_idx) - 1), min_dist=0.15)
            fitted = reducer.fit(matrix[fit_idx])
            all_xy = fitted.transform(matrix)
            span = float(np.max(np.abs(all_xy))) or 1.0
            scale = 18.0 / span
            similarity = {}
            for i, n in enumerate(nodes):
                similarity[n["id"]] = [round(float(all_xy[i, 0]) * scale, 4), 0.0, round(float(all_xy[i, 1]) * scale, 4)]
            embedding = all_xy
            meta["similarity"] = {
                "method": "UMAP",
                "random_state": 42,
                "fitted_on": "non-hub structural features (kind, edge-type profile, degree)",
                "n_fitted": len(fit_idx),
            }
        else:
            meta["similarity"] = {"error": f"Need at least 8 non-hub nodes to fit UMAP, found {len(fit_idx)}."}
    except Exception as exc:  # noqa: BLE001 — surface the real import or fit failure
        meta["similarity"] = {"error": str(exc)[:240]}

    capability = {n["id"]: n.get("cluster") or "other" for n in nodes}
    named = len(set(capability.values()))
    meta["clustering"] = {
        "method": "name-and-directory",
        "used_for_view": True,
        "n_clusters": named,
        "note": f"{named} capability groups from program prefix and directory.",
    }
    if embedding is not None:
        try:
            import numpy as np
            from sklearn.cluster import HDBSCAN

            fit_idx = [i for i, n in enumerate(nodes) if not n.get("hub")]
            clusterer = HDBSCAN(min_cluster_size=max(4, len(fit_idx) // 25))
            labels = clusterer.fit_predict(embedding[fit_idx])
            unique = sorted({int(x) for x in labels if int(x) >= 0})
            note = f"HDBSCAN produced {len(unique)} clusters and {int(np.sum(labels < 0))} noise points on the UMAP plane."
            if 10 <= len(unique) <= 30:
                for local, n in zip(labels, (nodes[i] for i in fit_idx)):
                    if int(local) >= 0:
                        capability[n["id"]] = f"hdbscan-{int(local)}"
                meta["clustering"] = {
                    "method": "sklearn.cluster.HDBSCAN",
                    "used_for_view": True,
                    "n_clusters": len(unique),
                    "noise": int(np.sum(labels < 0)),
                    "note": note + " Those clusters are the default view. Noise points keep their name group.",
                }
            else:
                meta["clustering"]["hdbscan_n"] = len(unique)
                meta["clustering"]["note"] += " " + note + " Outside 10–30, so the view keeps the named groups."
        except Exception as exc:  # noqa: BLE001
            meta["clustering"]["note"] += f" HDBSCAN was not used: {exc}."

    from collections import Counter

    names_by_cap: dict[str, list[str]] = defaultdict(list)
    for n in nodes:
        names_by_cap[capability[n["id"]]].append(n.get("cluster") or "other")
    majority = {cap: Counter(names).most_common(1)[0][0] for cap, names in names_by_cap.items()}
    repeats = Counter(majority.values())
    cap_label = {
        cap: name if repeats[name] == 1 else f"{name} {cap.rsplit('-', 1)[-1]}"
        for cap, name in majority.items()
    }
    for n in nodes:
        n["capability"] = capability[n["id"]]
        n["capability_label"] = cap_label[capability[n["id"]]]
        n["pos"] = {
            "layered": layered.get(n["id"], [0, 0, 0]),
            "topdown": topdown.get(n["id"], [0, 0, 0]),
            "similarity": None if similarity is None else similarity.get(n["id"]),
        }
        if similarity and similarity.get(n["id"]):
            sx, sy, sz = similarity[n["id"]]
            n["x"], n["y"], n["z"] = sx, sy, sz
        else:
            x, y, z = layered.get(n["id"], [n.get("x", 0), n.get("y", 0), n.get("z", 0)])
            n["x"], n["y"], n["z"] = x, y, z
    return meta
