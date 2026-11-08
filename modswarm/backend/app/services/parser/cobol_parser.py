"""COBOL/JCL/BMS units and edges in GraphDev's ParsedUnit / ParsedEdge shape.

The extractors are the ported Builder. This module does not reimplement them.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from app.legacy.engine import Builder
from app.services.parser.types import ParsedEdge, ParsedUnit

LEGACY_EDGE_TYPES = {"COPY", "CALL", "LINK", "XCTL", "FILE", "JOB", "TRANS", "SCREEN"}


def parse_legacy_project(repo_root: str) -> tuple[list[ParsedUnit], list[ParsedEdge], Builder]:
    root = Path(repo_root)
    builder = Builder(root)
    builder.build_graph()
    builder.degrees_and_hubs()
    is_java = bool(builder.tree.get("java")) and not builder.tree.get("programs")
    units: list[ParsedUnit] = []
    for node in builder.nodes.values():
        file_path = node.get("file") or ""
        start = int(node.get("line") or 1)
        text = node.get("summary") or node.get("name") or ""
        lang = "java" if is_java or str(node.get("subtype") or "").startswith("java") else "cobol"
        units.append(ParsedUnit(
            file_path=file_path,
            symbol_name=node.get("name") or node["id"],
            qualname=node["id"],
            kind=node.get("kind") or "program",
            runtime="legacy",
            language=lang,
            start_line=start,
            end_line=start,
            code_hash=hashlib.sha256(f"{node['id']}:{text}".encode()).hexdigest()[:16],
            source_text=text,
        ))

    edges: list[ParsedEdge] = []
    for edge in builder.edges:
        etype = edge.get("type") or ""
        if etype not in LEGACY_EDGE_TYPES:
            continue
        edges.append(ParsedEdge(
            source_qualname=edge["source"],
            target_qualname=edge["target"],
            edge_type=etype,
            file_path=edge.get("file") or "",
            line=int(edge.get("line") or 0),
            snippet=edge.get("snippet") or "",
        ))
    return units, edges, builder
