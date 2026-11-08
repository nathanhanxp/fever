"""Deterministic extractors for COBOL, copybooks, JCL, BMS, and CICS commands.

Facts come from these parsers. Agents later interpret them; they do not invent edges.
"""

from __future__ import annotations

import re
from pathlib import Path

from .source import logical_cobol, logical_jcl, read_text, snippet

COPY_RE = re.compile(r"\bCOPY\s+['\"]?([A-Z0-9-]+)['\"]?", re.I)
CALL_RE = re.compile(r"\bCALL\s+['\"]([A-Z0-9-]+)['\"]", re.I)
GOTO_RE = re.compile(r"\bGO\s+TO\s+([A-Z0-9-]+)", re.I)
ALTER_RE = re.compile(r"\bALTER\s+([A-Z0-9-]+)", re.I)
PERFORM_RE = re.compile(r"\bPERFORM\s+([A-Z0-9-]+)", re.I)
PARA_RE = re.compile(r"^([A-Z0-9][A-Z0-9-]{0,30})\.$", re.I)
VALUE_RE = re.compile(
    r"\b([A-Z0-9-]+)\s+PIC\b[^.]{0,80}?\bVALUE\s+['\"]([^'\"]*)['\"]",
    re.I,
)
LITERAL_RE = re.compile(r"'([^']{6,})'")
ASSIGN_RE = re.compile(r"\bASSIGN\s+TO\s+([A-Z0-9-]+)", re.I)
FILE_STATUS_RE = re.compile(r"\bFILE\s+STATUS\s+IS\s+([A-Z0-9-]+)", re.I)
SELECT_NAME_RE = re.compile(r"\bSELECT\s+([A-Z0-9-]+)", re.I)
QUOTED_RE = re.compile(r"\(\s*'([^']+)'\s*\)", re.I)
BARE_ARG_RE = re.compile(r"\(\s*([A-Z0-9-]+)\s*\)", re.I)
SQL_TABLE_RE = re.compile(r"\b(?:FROM|INTO|UPDATE|JOIN|TABLE)\s+([A-Z0-9_.]+)", re.I)
SENSITIVE_RE = re.compile(
    r"\b([A-Z0-9-]*(?:CARD-NUM|CARDNUM|PAN|CVV|SSN|PASSWORD|PASSWD|PWD)[A-Z0-9-]*)\b",
    re.I,
)
FIELD_RE = re.compile(r"^\d{0,2}\s+([A-Z0-9-]+)\s+PIC\b", re.I)
PGM_RE = re.compile(r"\bPROGRAM-ID\.\s*([A-Z0-9-]+)", re.I)
FUNC_RE = re.compile(r"Function\s*:\s*(.+)", re.I)
TYPE_RE = re.compile(r"Type\s*:\s*(.+)", re.I)

CICS_IO = {
    "READ", "WRITE", "REWRITE", "DELETE", "STARTBR", "READNEXT", "READPREV",
    "STARBR", "ENDBR", "UNLOCK",
}
CICS_XFER = {"XCTL", "LINK", "START"}
CICS_UI = {"SEND", "RECEIVE", "RETURN"}

SKIP_DIRS = {
    ".git", "node_modules", "__pycache__", "diagrams", "target", "build",
    ".gradle", "dist", "test", "tests", "generated-sources",
}


def iter_source_files(root: Path):
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        # Prefer main sources over test trees even when folder name isn't exactly "test"
        parts_l = {p.lower() for p in path.parts}
        if "src" in parts_l and "test" in parts_l and path.suffix.lower() == ".java":
            continue
        if path.suffix.lower() in {
            ".cbl", ".cob", ".cobol", ".cl2", ".cpy", ".copy", ".jcl", ".bms",
            ".prc", ".proc", ".mac", ".asm", ".csd", ".ctl", ".java", ".inc",
        }:
            yield path


def _header(raw_lines: list[str]) -> tuple[str, str]:
    function = ""
    kind = ""
    for line in raw_lines[:80]:
        m = FUNC_RE.search(line)
        if m and not function:
            function = m.group(1).strip(" *")
        m = TYPE_RE.search(line)
        if m and not kind:
            kind = m.group(1).strip(" *")
    return function, kind


def _arg(block: str, keyword: str) -> tuple[str, bool]:
    """Return (value, dynamic). dynamic=True when the argument is not a quoted literal."""
    m = re.search(rf"\b{keyword}\s*\(\s*'([^']+)'\s*\)", block, re.I)
    if m:
        return m.group(1).strip(), False
    m = re.search(rf"\b{keyword}\s*\(\s*([^)]+?)\s*\)", block, re.I)
    if m:
        return m.group(1).strip(), True
    return "", False


def parse_cobol(path: Path, root: Path) -> dict:
    rel = str(path.relative_to(root))
    raw_lines = read_text(path).splitlines()
    function, header_type = _header(raw_lines)
    logical: list[tuple[int, str]] = []
    for i, raw in enumerate(raw_lines, 1):
        code = logical_cobol(raw)
        if code:
            logical.append((i, code))

    name = path.stem.upper()
    for _, code in logical[:40]:
        m = PGM_RE.search(code)
        if m:
            name = m.group(1).upper()
            break

    values: dict[str, str] = {}
    for _, code in logical:
        for m in VALUE_RE.finditer(code):
            values[m.group(1).upper()] = m.group(2)

    copies = []
    calls = []
    gotos = []
    alters = []
    performs = []
    literals: dict[str, list[int]] = {}
    selects = []
    cics = []
    sql_tables = []
    sensitive = []
    paragraphs = []
    secret_compares = []
    in_proc = False
    counts = {"if": 0, "evaluate": 0, "goto": 0, "perform": 0, "cics": 0}

    i = 0
    while i < len(logical):
        lineno, code = logical[i]
        upper = code.upper()
        if "PROCEDURE DIVISION" in upper:
            in_proc = True
        if in_proc:
            pm = PARA_RE.match(code.strip())
            if pm and "DIVISION" not in upper and not upper.startswith("END "):
                paragraphs.append({"name": pm.group(1).upper(), "line": lineno})

        for m in COPY_RE.finditer(code):
            copies.append({"name": m.group(1).upper(), "line": lineno, "snippet": snippet(code)})
        for m in CALL_RE.finditer(code):
            calls.append({"name": m.group(1).upper(), "line": lineno, "snippet": snippet(code)})
        for m in GOTO_RE.finditer(code):
            counts["goto"] += 1
            gotos.append({"target": m.group(1).upper(), "line": lineno, "snippet": snippet(code)})
        for m in ALTER_RE.finditer(code):
            alters.append({"target": m.group(1).upper(), "line": lineno, "snippet": snippet(code)})
        for m in PERFORM_RE.finditer(code):
            counts["perform"] += 1
            performs.append({"target": m.group(1).upper(), "line": lineno})
        if re.search(r"\bIF\b", upper):
            counts["if"] += 1
        if "EVALUATE" in upper:
            counts["evaluate"] += 1
        for m in LITERAL_RE.finditer(code):
            lit = m.group(1).strip()
            if len(lit) >= 8 and lit.strip(" .-*") :
                literals.setdefault(lit, []).append(lineno)
        if "PIC" in upper:
            for m in SENSITIVE_RE.finditer(code):
                sensitive.append({"name": m.group(1).upper(), "line": lineno, "snippet": snippet(code)})
        if re.search(r"PWD|PASSWORD", code, re.I) and re.search(r"=|EQUAL", code, re.I):
            secret_compares.append({"line": lineno, "snippet": snippet(code)})

        if upper.startswith("SELECT ") or " SELECT " in f" {upper}" and "SELECT " in upper and "ASSIGN" in upper:
            block_lines = [(lineno, code)]
            block = code
            j = i
            while "." not in block and j + 1 < len(logical):
                j += 1
                block_lines.append(logical[j])
                block += " " + logical[j][1]
            sm = SELECT_NAME_RE.search(block)
            am = ASSIGN_RE.search(block)
            fm = FILE_STATUS_RE.search(block)
            if sm and am:
                selects.append({
                    "select": sm.group(1).upper(),
                    "assign": am.group(1).upper(),
                    "file_status": bool(fm),
                    "status_var": fm.group(1).upper() if fm else "",
                    "line": lineno,
                    "snippet": snippet(block),
                })
            i = j + 1
            continue

        if upper.startswith("EXEC CICS") or upper.startswith("EXEC SQL") or upper.startswith("EXEC DLI"):
            kind = "CICS" if "CICS" in upper else "SQL" if "SQL" in upper else "DLI"
            block_lines = [(lineno, code)]
            block = code
            j = i
            while "END-EXEC" not in block.upper() and j + 1 < len(logical):
                j += 1
                block_lines.append(logical[j])
                block += " " + logical[j][1]
            if kind == "CICS":
                counts["cics"] += 1
                verb = ""
                tokens = block.upper().replace("EXEC CICS", "", 1).strip().split()
                if tokens:
                    verb = tokens[0].strip(".,")
                has_resp = bool(re.search(r"\bRESP\s*\(", block, re.I)) or "NOHANDLE" in block.upper()
                prog, prog_dyn = _arg(block, "PROGRAM")
                dataset, ds_dyn = _arg(block, "DATASET")
                if not dataset:
                    dataset, ds_dyn = _arg(block, "FILE")
                map_name, _ = _arg(block, "MAP")
                mapset, mapset_dyn = _arg(block, "MAPSET")
                transid, tr_dyn = _arg(block, "TRANSID")
                cics.append({
                    "verb": verb,
                    "line": lineno,
                    "end_line": block_lines[-1][0],
                    "snippet": snippet(block),
                    "has_resp": has_resp,
                    "program": prog.upper() if prog else "",
                    "program_dynamic": prog_dyn,
                    "dataset": dataset.upper() if dataset else "",
                    "dataset_dynamic": ds_dyn,
                    "map": map_name.upper() if map_name else "",
                    "mapset": mapset.upper() if mapset else "",
                    "mapset_dynamic": mapset_dyn,
                    "transid": transid.upper() if transid else "",
                    "transid_dynamic": tr_dyn,
                })
            elif kind == "SQL":
                for m in SQL_TABLE_RE.finditer(block):
                    table = m.group(1).upper().strip(".")
                    if table not in {"SELECT", "WHERE", "SET"}:
                        sql_tables.append({"name": table, "line": lineno, "snippet": snippet(block)})
            else:
                pcb, _ = _arg(block, "PCB")
                cics.append({
                    "verb": "DLI",
                    "line": lineno,
                    "end_line": block_lines[-1][0],
                    "snippet": snippet(block),
                    "has_resp": True,
                    "program": "",
                    "program_dynamic": False,
                    "dataset": pcb.upper() if pcb else "IMS",
                    "dataset_dynamic": False,
                    "map": "",
                    "mapset": "",
                    "mapset_dynamic": False,
                    "transid": "",
                    "transid_dynamic": False,
                    "ims": True,
                })
            i = j + 1
            continue
        i += 1

    batchish = "BATCH" in header_type.upper() or path.stem.upper().startswith("CB")
    return {
        "name": name,
        "path": rel,
        "function": function or f"COBOL program {name}",
        "header_type": header_type,
        "batch": batchish and "CICS" not in header_type.upper(),
        "cics": counts["cics"] > 0 or "CICS" in header_type.upper(),
        "values": values,
        "copies": copies,
        "calls": calls,
        "gotos": gotos,
        "alters": alters,
        "performs": performs,
        "literals": {k: v for k, v in literals.items() if len(v) >= 3},
        "selects": selects,
        "cics_cmds": cics,
        "sql_tables": sql_tables,
        "sensitive": sensitive,
        "secret_compares": secret_compares,
        "paragraphs": paragraphs,
        "counts": counts,
        "line_count": len(raw_lines),
        "blob": "\n".join(code for _, code in logical),
    }


def parse_copybook(path: Path, root: Path) -> dict:
    rel = str(path.relative_to(root))
    raw_lines = read_text(path).splitlines()
    fields = []
    sensitive = []
    for i, raw in enumerate(raw_lines, 1):
        code = logical_cobol(raw)
        if not code:
            continue
        if SENSITIVE_RE.search(code) and "PIC" in code.upper():
            sensitive.append({"line": i, "snippet": snippet(code), "name": SENSITIVE_RE.search(code).group(1).upper()})
        m = re.search(r"\b([A-Z0-9-]+)\s+PIC\b", code, re.I)
        if m:
            fields.append(m.group(1).upper())
    return {
        "name": path.stem.upper(),
        "path": rel,
        "fields": fields,
        "sensitive": sensitive,
        "line_count": len(raw_lines),
    }


def parse_jcl(path: Path, root: Path) -> dict:
    rel = str(path.relative_to(root))
    raw_lines = read_text(path).splitlines()
    job_name = path.stem.upper()
    job_line = 1
    purpose = ""
    steps = []
    current = None
    instream = False
    instream_hits = []

    for i, raw in enumerate(raw_lines, 1):
        logical = logical_jcl(raw)
        if logical is None:
            if instream and raw.strip().startswith("//") and not raw.strip().startswith("//*"):
                instream = False
            elif instream and raw.strip() and not raw.strip().startswith("//"):
                if re.search(r"PASSWORD", raw, re.I):
                    instream_hits.append({"line": i, "snippet": "instream record contains a password literal (redacted)"})
            continue
        text = logical.strip()
        if text.startswith("//*") or text.startswith("*"):
            if "Process" in text or "CREATE" in text.upper() or "compute" in text.lower():
                cleaned = text.lstrip("/* ").strip()
                if cleaned and not purpose and not cleaned.lower().startswith("copyright"):
                    purpose = cleaned[:160]
            continue
        if instream and not text.startswith("//"):
            if re.search(r"PASSWORD", text, re.I) and not instream_hits:
                instream_hits.append({
                    "line": i,
                    "snippet": "instream record contains a password literal (redacted)",
                })
            continue
        if text.startswith("//"):
            instream = False
        if not text.startswith("//"):
            continue
        body = text[2:]
        m = re.match(r"(\S+)\s+JOB\b", body, re.I)
        if m:
            job_name = m.group(1).upper()
            job_line = i
            instream = False
            continue
        m = re.match(r"(\S+)\s+EXEC\b(.*)", body, re.I)
        if m:
            instream = False
            rest = m.group(2)
            pm = re.search(r"\bPGM=([A-Z0-9-]+)", rest, re.I)
            parm = ""
            parm_m = re.search(r"\bPARM='([^']*)'", rest, re.I)
            if parm_m:
                parm = parm_m.group(1)
            current = {
                "step": m.group(1).upper(),
                "pgm": pm.group(1).upper() if pm else "",
                "line": i,
                "parm": parm,
                "snippet": snippet(text),
                "dds": [],
            }
            steps.append(current)
            continue
        m = re.match(r"(\S+)\s+DD\b(.*)", body, re.I)
        if m and current is not None:
            dd = m.group(1).upper()
            rest = m.group(2)
            dsn_m = re.search(r"\bDSN=([^\s,]+)", rest, re.I)
            dsn = dsn_m.group(1).rstrip(",") if dsn_m else ""
            current["dds"].append({
                "dd": dd,
                "dsn": dsn.upper() if dsn else "",
                "line": i,
                "snippet": snippet(text),
            })
            instream = "DD *" in rest.upper() or rest.strip() == "*" or rest.strip().upper().startswith("*")
            continue
        if current and current["dds"] and re.match(r"\s+\S", body):
            dsn_m = re.search(r"\bDSN=([^\s,]+)", body, re.I)
            if dsn_m and not current["dds"][-1]["dsn"]:
                current["dds"][-1]["dsn"] = dsn_m.group(1).rstrip(",").upper()
                current["dds"][-1]["snippet"] = snippet(current["dds"][-1]["snippet"] + " " + text.strip())
            parm_m = re.search(r"\bPARM='([^']*)'", body, re.I)
            if parm_m and current and not current["parm"]:
                current["parm"] = parm_m.group(1)

    return {
        "name": job_name,
        "path": rel,
        "line": job_line,
        "purpose": purpose,
        "steps": steps,
        "instream_secrets": instream_hits,
        "line_count": len(raw_lines),
    }


def parse_bms(path: Path, root: Path) -> dict:
    rel = str(path.relative_to(root))
    raw_lines = read_text(path).splitlines()
    mapset = path.stem.upper()
    mapset_line = 1
    maps = []
    title = ""
    for i, raw in enumerate(raw_lines, 1):
        s = raw.strip()
        if s.startswith("*") and not title and "CardDemo" in raw:
            title = s.lstrip("* ").strip()
        m = re.match(r"([A-Z0-9]+)\s+DFHMSD\b", s, re.I)
        if m:
            mapset = m.group(1).upper()
            mapset_line = i
        m = re.match(r"([A-Z0-9]+)\s+DFHMDI\b", s, re.I)
        if m:
            maps.append({"name": m.group(1).upper(), "line": i, "snippet": snippet(s)})
    return {
        "name": mapset,
        "path": rel,
        "line": mapset_line,
        "title": title or f"BMS mapset {mapset}",
        "maps": maps,
        "line_count": len(raw_lines),
    }


def parse_java(path: Path, root: Path) -> dict:
    """Deterministic Java facts for VRaptor/Spring/JPA trees (e.g. jforum3).

    Extracts types, imports, extends/implements, constructor/field injection,
    controller forwards, and a few security/persistence annotations — no LLM.
    """
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    package = ""
    for line in lines[:40]:
        m = re.match(r"\s*package\s+([\w.]+)\s*;", line)
        if m:
            package = m.group(1)
            break

    classes: list[dict] = []
    imports: list[dict] = []
    extends: list[dict] = []
    implements: list[dict] = []
    injections: list[dict] = []
    forwards: list[dict] = []
    annotations: list[dict] = []
    entities: list[dict] = []

    # Simple name → fqcn from imports (for resolving Type.class / ctor params)
    import_map: dict[str, str] = {}
    for i, line in enumerate(lines, 1):
        im = re.match(r"\s*import\s+(?:static\s+)?([\w.]+)(\.\*)?\s*;", line)
        if im:
            fq = im.group(1)
            star = bool(im.group(2))
            imports.append({"name": fq, "line": i, "snippet": snippet(line), "star": star})
            if not star:
                import_map[fq.rsplit(".", 1)[-1]] = fq

    def resolve(simple: str) -> str:
        if "." in simple:
            return simple
        if simple in import_map:
            return import_map[simple]
        if package:
            return f"{package}.{simple}"
        return simple

    # Strip block comments lightly for annotation/class scans
    in_block = False
    ctor_buf = ""
    ctor_start = 0
    current_type: str | None = None
    pending_annos: list[tuple[str, int, str]] = []

    for i, line in enumerate(lines, 1):
        raw = line
        s = line.strip()
        if in_block:
            if "*/" in s:
                in_block = False
            continue
        if s.startswith("/*"):
            if "*/" not in s:
                in_block = True
            continue
        if s.startswith("//") or s.startswith("*"):
            continue

        for am in re.finditer(r"@(\w+)(?:\s*\(([^)]*)\))?", s):
            aname, args = am.group(1), (am.group(2) or "").strip()
            pending_annos.append((aname, i, snippet(raw)))
            annotations.append({"name": aname, "args": args, "line": i, "snippet": snippet(raw)})
            if aname in {"Entity", "Table", "MappedSuperclass"}:
                entities.append({"name": aname, "line": i, "snippet": snippet(raw)})

        cm = re.search(
            r"\b(?:public|protected|private|abstract|final|static|\s)*"
            r"(?:class|interface|enum)\s+(\w+)"
            r"(?:\s+extends\s+([\w.]+))?"
            r"(?:\s+implements\s+([\w.,\s]+))?",
            s,
        )
        if cm:
            name = cm.group(1)
            kind = "interface" if re.search(r"\binterface\s+" + re.escape(name), s) else (
                "enum" if re.search(r"\benum\s+" + re.escape(name), s) else "class"
            )
            roles = []
            for aname, _, _ in pending_annos:
                if aname in {"Resource", "Controller", "RestController", "Path"}:
                    roles.append("controller")
                elif aname in {"Repository", "Dao"}:
                    roles.append("repository")
                elif aname in {"Service", "Component"}:
                    roles.append("service")
                elif aname in {"Entity", "Table", "MappedSuperclass"}:
                    roles.append("entity")
            classes.append({
                "name": name,
                "kind": kind,
                "line": i,
                "snippet": snippet(raw),
                "roles": sorted(set(roles)),
                "annotations": [a[0] for a in pending_annos],
            })
            current_type = name
            if cm.group(2):
                parent = cm.group(2).strip()
                extends.append({
                    "name": resolve(parent),
                    "simple": parent.rsplit(".", 1)[-1],
                    "line": i,
                    "snippet": snippet(raw),
                    "owner": name,
                })
            if cm.group(3):
                for part in cm.group(3).split(","):
                    iface = part.strip()
                    if not iface:
                        continue
                    implements.append({
                        "name": resolve(iface),
                        "simple": iface.rsplit(".", 1)[-1],
                        "line": i,
                        "snippet": snippet(raw),
                        "owner": name,
                    })
            pending_annos = []

        # Field injection: Type name;  or final Type name;
        fm = re.match(
            r"\s*(?:private|protected|public)?\s*(?:final\s+)?([A-Z]\w*(?:<[^>;]+>)?)\s+(\w+)\s*;",
            s,
        )
        if fm and current_type and "(" not in s:
            typ = re.sub(r"<.*?>", "", fm.group(1)).strip()
            if typ not in {"String", "Integer", "Long", "Boolean", "Object", "int", "long", "boolean", "void"}:
                injections.append({
                    "type": resolve(typ),
                    "simple": typ,
                    "field": fm.group(2),
                    "line": i,
                    "snippet": snippet(raw),
                    "owner": current_type,
                    "via": "field",
                })

        # Constructor start — accumulate until closing paren for param types
        if current_type and re.search(rf"\b{re.escape(current_type)}\s*\(", s) and "new " not in s:
            ctor_buf = s
            ctor_start = i
            if ")" in s:
                # same-line ctor
                for pm in re.finditer(r"([A-Z]\w*(?:<[^>]+>)?)\s+(\w+)\s*(?:,|\))", ctor_buf):
                    typ = re.sub(r"<.*?>", "", pm.group(1)).strip()
                    if typ in {current_type, "String", "Integer", "Long", "Boolean", "Object"}:
                        continue
                    injections.append({
                        "type": resolve(typ),
                        "simple": typ,
                        "field": pm.group(2),
                        "line": ctor_start,
                        "snippet": snippet(raw),
                        "owner": current_type,
                        "via": "ctor",
                    })
                ctor_buf = ""
            continue
        if ctor_buf:
            ctor_buf += " " + s
            if ")" in s:
                for pm in re.finditer(r"([A-Z]\w*(?:<[^>]+>)?)\s+(\w+)\s*(?:,|\))", ctor_buf):
                    typ = re.sub(r"<.*?>", "", pm.group(1)).strip()
                    if typ in {current_type or "", "String", "Integer", "Long", "Boolean", "Object"}:
                        continue
                    injections.append({
                        "type": resolve(typ),
                        "simple": typ,
                        "field": pm.group(2),
                        "line": ctor_start,
                        "snippet": snippet(lines[ctor_start - 1] if ctor_start else raw),
                        "owner": current_type or "",
                        "via": "ctor",
                    })
                ctor_buf = ""

        # VRaptor / result.forwardTo(Foo.class)
        for fm2 in re.finditer(r"forwardTo\s*\(\s*([A-Z]\w*)\s*\.class\s*\)", s):
            forwards.append({
                "name": resolve(fm2.group(1)),
                "simple": fm2.group(1),
                "line": i,
                "snippet": snippet(raw),
                "owner": current_type or (classes[0]["name"] if classes else ""),
            })

    return {
        "path": str(path.relative_to(root)),
        "package": package,
        "classes": classes,
        "imports": imports,
        "extends": extends,
        "implements": implements,
        "injections": injections,
        "forwards": forwards,
        "annotations": annotations,
        "entities": entities,
    }


def parse_tree(root: Path) -> dict:
    programs = []
    copybooks = []
    jobs = []
    maps = []
    java = []
    others = []
    for path in sorted(iter_source_files(root), key=lambda p: str(p)):
        suf = path.suffix.lower()
        if suf in {".cbl", ".cob", ".cobol", ".cl2"}:
            programs.append(parse_cobol(path, root))
        elif suf in {".cpy", ".copy"}:
            copybooks.append(parse_copybook(path, root))
        elif suf in {".jcl", ".prc", ".proc"}:
            jobs.append(parse_jcl(path, root))
        elif suf == ".bms":
            maps.append(parse_bms(path, root))
        elif suf == ".java":
            java.append(parse_java(path, root))
        else:
            others.append({"name": path.stem.upper(), "path": str(path.relative_to(root)), "suffix": suf})
    return {
        "programs": programs,
        "copybooks": copybooks,
        "jobs": jobs,
        "maps": maps,
        "java": java,
        "others": others,
    }
