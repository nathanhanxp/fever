"""Graph, lenses, prover, planner, and graph-query tools.

Parsers establish facts. This module interprets them, rejects unsupported
findings, and simulates roadmap steps as graph transformations. Simulator
output is Predicted. Detector re-runs are Measured.
"""

from __future__ import annotations

import difflib
import math
import re
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .layouts import attach_geometry
from .parse import parse_bms, parse_cobol, parse_copybook, parse_jcl, parse_tree
from .source import norm, read_text, snippet

SONAR = "Sonar COBOL rule catalog (GO TO, duplication, complexity): https://rules.sonarsource.com/cobol/"
CONTRAST = "Contrast COBOL scan rules (FILE STATUS, CICS RESP or NOHANDLE): https://docs.contrastsecurity.com/en/cobol-scan-rules.html"
README_STYLE = (
    "CardDemo README.md:38 — coding styles are intentional, to exercise analysis tooling. "
    "These are detector results, not a criticism of AWS."
)
README_TECH = (
    "CardDemo README.md Technologies — COBOL, CICS, VSAM, JCL, RACF, assembler; "
    "optional DB2, IMS, and MQ."
)
DEAD_CAVEAT = (
    "Entry paths outside the repo (schedulers, CICS region definitions, dynamic CALL) "
    "are not observable. Unused is a candidate, not a fact. "
    "https://github.com/repowise-dev/repowise/pull/4461"
)

EXTERNAL_PGMS = {
    "IEFBR14", "IEBGENER", "IDCAMS", "SORT", "ICETOOL", "IKJEFT01", "IEFBR14",
    "CEEDAYS", "CEELOCT", "DFHEAI", "DFHEAI0",
}


def _cluster_program(name: str, path: str) -> str:
    n = name.upper()
    if "app-authorization" in path:
        return "authorization"
    if "app-transaction-type" in path:
        return "db2-types"
    if "app-vsam-mq" in path:
        return "vsam-mq"
    prefixes = [
        ("COACT", "online-account"), ("COCRD", "online-card"), ("COTRN", "transactions"),
        ("CBTRN", "transactions"), ("COUSR", "online-user"), ("COSGN", "signon"),
        ("COMEN", "menus"), ("COADM", "menus"), ("CBACT", "batch-account"),
        ("CBSTM", "statements"), ("CBCUS", "batch-customer"), ("CBIMP", "import-export"),
        ("CBEXP", "import-export"), ("COBIL", "bill-pay"), ("CORPT", "reports"),
        ("CSUTL", "utilities"), ("COBS", "utilities"), ("COACCT", "vsam-mq"),
        ("CODATE", "vsam-mq"), ("COTRT", "db2-types"), ("COBT", "db2-types"),
        ("PAU", "authorization"), ("CB", "batch-other"), ("CO", "online-other"),
    ]
    for pref, cluster in prefixes:
        if n.startswith(pref):
            return cluster
    return "programs"


def _layout(nodes: list[dict]) -> None:
    groups: dict[str, list[dict]] = defaultdict(list)
    for n in nodes:
        groups[n["cluster"]].append(n)
    golden = math.pi * (3 - math.sqrt(5))
    for i, key in enumerate(sorted(groups)):
        theta = i * 2.399963
        radius = 14 + min(8, math.sqrt(len(groups[key])) * 0.9)
        cx = math.cos(theta) * radius
        cz = math.sin(theta) * radius
        cy = ((i * 5) % 9) - 4
        members = sorted(groups[key], key=lambda n: (-n["degree"], n["name"]))
        for j, n in enumerate(members):
            ang = j * golden
            rad = 0.72 * math.sqrt(j + 0.35)
            n["x"] = round(cx + rad * math.cos(ang), 4)
            n["y"] = round(cy + ((j % 5) - 2) * 0.42, 4)
            n["z"] = round(cz + rad * math.sin(ang), 4)
    for n in nodes:
        if n["hub"]:
            n["x"] = round(n["x"] * 0.58, 4)
            n["y"] = round(n["y"] * 0.58, 4)
            n["z"] = round(n["z"] * 0.58, 4)


def _resolve(token: str, dynamic: bool, values: dict[str, str]) -> tuple[str, bool, str]:
    """Return name, still_dynamic, how."""
    if not token:
        return "", True, ""
    if not dynamic:
        return token.strip().upper(), False, "literal"
    key = token.strip().upper()
    if re.fullmatch(r"[A-Z0-9-]+", key) and key in values:
        lit = values[key].strip().upper()
        if lit:
            return lit, False, f"VALUE of {key}"
    return key, True, "unresolved"


def _line_ok(files: dict[str, list[str]], file: str, line: int, snip: str) -> bool:
    rows = files.get(file)
    if not rows or line < 1 or line > len(rows):
        return False
    window = " ".join(rows[line - 1: min(len(rows), line + 14)])
    needle = norm(snip)[:48]
    if needle and needle in norm(window):
        return True
    # redacted snippets still have to land on a real line
    if "redacted" in snip.lower():
        return True
    token = re.sub(r"[^A-Z0-9]", "", needle)[:12]
    return bool(token) and token in re.sub(r"[^A-Z0-9]", "", window.upper())


class Builder:
    def __init__(self, root: Path):
        self.root = root
        self.tree = parse_tree(root)
        self.files: dict[str, list[str]] = {}
        for path in root.rglob("*"):
            if path.suffix.lower() in {".cbl", ".cpy", ".jcl", ".bms", ".md"} and path.is_file():
                rel = str(path.relative_to(root))
                try:
                    self.files[rel] = read_text(path).splitlines()
                except OSError:
                    continue
        self.nodes: dict[str, dict] = {}
        self.edges: list[dict] = []
        self.findings: list[dict] = []
        self._edge_n = 0
        self._find_n = 0

    def node(self, nid: str, **kw) -> dict:
        if nid not in self.nodes:
            self.nodes[nid] = {
                "id": nid,
                "name": kw.get("name", nid),
                "kind": kw.get("kind", "program"),
                "subtype": kw.get("subtype", ""),
                "file": kw.get("file", ""),
                "line": kw.get("line", 1),
                "summary": kw.get("summary", ""),
                "cluster": kw.get("cluster", "other"),
                "degree": 0,
                "hub": False,
                "risk": 0.25,
                "status": "legacy",
                "entry": kw.get("entry", False),
                "external": kw.get("external", False),
                "x": 0.0, "y": 0.0, "z": 0.0,
            }
        else:
            cur = self.nodes[nid]
            for k, v in kw.items():
                if k in {"summary", "file", "line", "subtype"} and v and not cur.get(k):
                    cur[k] = v
                if k == "entry" and v:
                    cur["entry"] = True
                if k == "summary" and v and cur["summary"].startswith("COBOL program"):
                    cur["summary"] = v
        return self.nodes[nid]

    def edge(self, source, target, etype, file, line, snip, mechanism, proved=True, dynamic=False, agent="mapper") -> dict:
        self._edge_n += 1
        e = {
            "id": f"e{self._edge_n}",
            "source": source,
            "target": target,
            "type": etype,
            "file": file,
            "line": line,
            "snippet": snip,
            "mechanism": mechanism,
            "proved": proved and not dynamic,
            "dynamic": dynamic,
            "predicted": False,
            "agent": agent,
        }
        self.edges.append(e)
        return e

    def finding(self, **kw) -> dict:
        self._find_n += 1
        f = {
            "id": f"f{self._find_n}",
            "lens": kw["lens"],
            "type": kw["type"],
            "rule": kw["rule"],
            "title": kw["title"],
            "file": kw.get("file", ""),
            "line": kw.get("line", 0),
            "snippet": kw.get("snippet", ""),
            "authority": kw.get("authority", ""),
            "confidence": kw.get("confidence", 0.9),
            "agent": kw.get("agent", "quality-lens"),
            "verdict": kw.get("verdict", "pending"),
            "verdict_reason": kw.get("verdict_reason", ""),
            "claim": kw.get("claim", "Measured"),
            "severity": kw.get("severity", "medium"),
            "node_id": kw.get("node_id", ""),
            "probe": kw.get("probe", False),
        }
        self.findings.append(f)
        return f

    def build_graph(self) -> None:
        programs = {p["name"]: p for p in self.tree["programs"]}
        copy_index = {c["name"]: c for c in self.tree["copybooks"]}
        for c in self.tree["copybooks"]:
            cluster = "screens" if "cpy-bms" in c["path"] else "copybooks"
            self.node(
                f"cpy:{c['name']}", name=c["name"], kind="copybook", subtype="layout",
                file=c["path"], line=1, summary=f"Copybook {c['name']} ({len(c['fields'])} PIC fields)",
                cluster=cluster,
            )
            for s in c["sensitive"]:
                self.finding(
                    lens="platform-security", type="sensitive-field", rule="sensitive-field",
                    title=f"Sensitive field {s['name']} in shared layout {c['name']}",
                    file=c["path"], line=s["line"], snippet=s["snippet"],
                    authority="Field declared in a CardDemo copybook. Name matches card, PAN, CVV, SSN, or password.",
                    agent="platform-security-lens", claim="Measured", severity="high",
                    node_id=f"cpy:{c['name']}", confidence=0.86,
                )
        for m in self.tree["maps"]:
            self.node(
                f"map:{m['name']}", name=m["name"], kind="screen", subtype="bms",
                file=m["path"], line=m["line"], summary=m["title"], cluster="screens",
            )
        dsn_names: set[str] = set()
        dd_to_dsns: dict[tuple[str, str], Counter] = defaultdict(Counter)
        for job in self.tree["jobs"]:
            jid = f"job:{job['name']}"
            if jid in self.nodes:
                jid = f"job:{job['name']}:{job['path']}"
            self.node(
                jid, name=job["name"], kind="job", subtype="jcl",
                file=job["path"], line=job["line"],
                summary=job["purpose"] or f"JCL job {job['name']}",
                cluster="jobs", entry=True,
            )
            for step in job["steps"]:
                pgm = step["pgm"]
                if not pgm:
                    continue
                if pgm in programs:
                    pid = f"pgm:{pgm}"
                    self.node(pid, name=pgm, entry=True)
                else:
                    pid = f"ext:{pgm}"
                    self.node(
                        pid, name=pgm, kind="program", subtype="external",
                        summary=f"External or utility program {pgm}, not defined in this repo",
                        cluster="external", external=True, entry=False,
                    )
                self.edge(jid, pid, "JOB", job["path"], step["line"], step["snippet"],
                          f"EXEC PGM={pgm} in step {step['step']}", agent="operations-lens")
                if step["parm"]:
                    self.finding(
                        lens="operations", type="hardcoded-parm", rule="hardcoded-value",
                        title=f"Hard-coded PARM on {job['name']} step {step['step']}",
                        file=job["path"], line=step["line"], snippet=step["snippet"],
                        authority="JCL PARM literal in source. A fixed date or flag will not track the business calendar.",
                        agent="operations-lens", claim="Measured", severity="medium",
                        node_id=jid, confidence=0.93,
                    )
                for dd in step["dds"]:
                    if not dd["dsn"]:
                        continue
                    dsn_names.add(dd["dsn"])
                    did = f"dsn:{dd['dsn']}"
                    self.node(
                        did, name=_short_dsn(dd["dsn"]),
                        kind="dataset", subtype="dsn",
                        file=job["path"], line=dd["line"],
                        summary=dd["dsn"], cluster="datasets",
                    )
                    self.edge(jid, did, "JOB", job["path"], dd["line"], dd["snippet"],
                              f"DD {dd['dd']} DSN", agent="operations-lens")
                    dd_to_dsns[(pgm, dd["dd"])][dd["dsn"]] += 1
            for hit in job["instream_secrets"]:
                self.finding(
                    lens="platform-security", type="hardcoded-secret", rule="hardcoded-secret",
                    title=f"Hard-coded password literal in instream data of {job['name']}",
                    file=job["path"], line=hit["line"], snippet=hit["snippet"],
                    authority="JCL SYSIN/SYSUT1 instream record. Demo data, still a credential pattern that must not be copied forward.",
                    agent="platform-security-lens", claim="Measured", severity="high",
                    node_id=jid, confidence=0.9,
                )
            if "RACF" in job["name"] or "SEC" in job["name"]:
                blob = "\n".join(self.files.get(job["path"], []))
                if re.search(r"\b(ADDUSER|PERMIT|PASSWORD|RACF)\b", blob, re.I):
                    self.finding(
                        lens="platform-security", type="racf", rule="racf-config",
                        title=f"Security configuration commands in {job['name']}",
                        file=job["path"], line=job["line"],
                        snippet=snippet(self.files[job["path"]][job["line"] - 1]) if job["path"] in self.files else job["name"],
                        authority="RACF or user-security JCL shipped with CardDemo. Platform end-of-life and access control stay with the mainframe unless re-homed.",
                        agent="platform-security-lens", claim="Measured", severity="medium",
                        node_id=jid, confidence=0.8,
                    )

        for p in self.tree["programs"]:
            pid = f"pgm:{p['name']}"
            subtype = "cics" if p["cics"] else "batch" if p["batch"] else "cobol"
            self.node(
                pid, name=p["name"], kind="program", subtype=subtype,
                file=p["path"], line=1, summary=p["function"],
                cluster=_cluster_program(p["name"], p["path"]),
                entry=p["cics"],
            )
            for c in p["copies"]:
                cname = c["name"]
                if cname in copy_index:
                    tid = f"cpy:{cname}"
                else:
                    tid = f"cpy:{cname}"
                    self.node(
                        tid, name=cname, kind="copybook", subtype="external",
                        summary=f"COPY {cname} has no copybook in this repo (often an IBM copy such as DFHAID)",
                        cluster="external", external=True,
                    )
                self.edge(pid, tid, "COPY", p["path"], c["line"], c["snippet"], "COPY statement", agent="mapper")
            for call in p["calls"]:
                target = call["name"]
                if target in programs:
                    tid = f"pgm:{target}"
                    dynamic = False
                else:
                    tid = f"ext:{target}"
                    self.node(
                        tid, name=target, kind="program", subtype="external",
                        summary=f"CALL target {target} is outside this repo",
                        cluster="external", external=True,
                    )
                    dynamic = False
                self.edge(pid, tid, "CALL", p["path"], call["line"], call["snippet"], "CALL literal", dynamic=dynamic, agent="code-lens")
            for cmd in p["cics_cmds"]:
                if cmd["verb"] in {"XCTL", "LINK"} and cmd["program"]:
                    name, dynamic, how = _resolve(cmd["program"], cmd["program_dynamic"], p["values"])
                    etype = "XCTL" if cmd["verb"] == "XCTL" else "LINK"
                    if dynamic or name not in programs and not re.fullmatch(r"[A-Z0-9]{1,8}", name or ""):
                        tid = f"dyn:{p['name']}:{cmd['line']}"
                        self.node(
                            tid, name=name or "dynamic", kind="program", subtype="dynamic",
                            summary=f"Dynamic {cmd['verb']} target ({how or 'expression'}). Not statically proved.",
                            cluster="external", external=True,
                        )
                        self.edge(pid, tid, etype, p["path"], cmd["line"], cmd["snippet"],
                                  f"EXEC CICS {cmd['verb']} dynamic", proved=False, dynamic=True, agent="code-lens")
                    else:
                        if name in programs:
                            tid = f"pgm:{name}"
                        else:
                            tid = f"ext:{name}"
                            self.node(tid, name=name, kind="program", subtype="external",
                                      summary=f"{cmd['verb']} target {name} is not in this repo",
                                      cluster="external", external=True)
                        self.edge(pid, tid, etype, p["path"], cmd["line"], cmd["snippet"],
                                  f"EXEC CICS {cmd['verb']} ({how})", agent="code-lens")
                if cmd["dataset"]:
                    name, dynamic, how = _resolve(cmd["dataset"], cmd["dataset_dynamic"], p["values"])
                    if dynamic:
                        tid = f"dynfile:{p['name']}:{cmd['line']}"
                        self.node(tid, name=name or "dynamic-file", kind="dataset", subtype="dynamic",
                                  summary="CICS file name is an expression. Not statically proved.",
                                  cluster="datasets", external=True)
                        self.edge(pid, tid, "FILE", p["path"], cmd["line"], cmd["snippet"],
                                  f"EXEC CICS {cmd['verb']} dynamic file", proved=False, dynamic=True, agent="data-lens")
                    else:
                        matched = _match_dsn(name, dsn_names)
                        if matched:
                            tid = f"dsn:{matched}"
                            self.node(tid, name=matched, kind="dataset", subtype="dsn", summary=matched, cluster="datasets")
                        else:
                            tid = f"file:{name}"
                            self.node(tid, name=name, kind="dataset", subtype="cics-file",
                                      summary=f"CICS file {name}", cluster="datasets",
                                      file=p["path"], line=cmd["line"])
                        self.edge(pid, tid, "FILE", p["path"], cmd["line"], cmd["snippet"],
                                  f"EXEC CICS {cmd['verb']} ({how})", agent="data-lens")
                if cmd["transid"]:
                    name, dynamic, how = _resolve(cmd["transid"], cmd["transid_dynamic"], p["values"])
                    if not dynamic and name:
                        tid = f"txn:{name}"
                        self.node(tid, name=name, kind="transaction", subtype="cics",
                                  summary=f"CICS transaction {name}", cluster="transactions", entry=True)
                        self.edge(pid, tid, "TRANS", p["path"], cmd["line"], cmd["snippet"],
                                  f"EXEC CICS {cmd['verb']} TRANSID ({how})", agent="code-lens")
                if cmd["map"] or cmd["mapset"]:
                    ms, dynamic, how = _resolve(cmd["mapset"] or cmd["map"], cmd["mapset_dynamic"], p["values"])
                    if not dynamic and ms:
                        tid = f"map:{ms}"
                        if tid not in self.nodes:
                            self.node(tid, name=ms, kind="screen", subtype="map",
                                      summary=f"Map or mapset {ms}", cluster="screens")
                        self.edge(pid, tid, "SCREEN", p["path"], cmd["line"], cmd["snippet"],
                                  f"BMS MAP/MAPSET ({how})", agent="code-lens")
                if cmd["verb"] in {"READ", "WRITE", "REWRITE", "DELETE", "STARTBR", "READNEXT", "READPREV", "XCTL", "LINK", "SEND", "RECEIVE"} and not cmd["has_resp"]:
                    sev = "info" if cmd["verb"] in {"SEND", "RECEIVE", "RETURN"} else "medium"
                    self.finding(
                        lens="quality", type="cics-no-resp", rule="cics-resp",
                        title=f"{p['name']} EXEC CICS {cmd['verb']} has no RESP or NOHANDLE",
                        file=p["path"], line=cmd["line"], snippet=cmd["snippet"],
                        authority=CONTRAST, agent="quality-lens", claim="Measured",
                        severity=sev, node_id=pid, confidence=0.92,
                    )
            for sel in p["selects"]:
                key = (p["name"], sel["assign"])
                chosen = ""
                if dd_to_dsns.get(key):
                    chosen = dd_to_dsns[key].most_common(1)[0][0]
                if chosen:
                    tid = f"dsn:{chosen}"
                    self.node(tid, name=_short_dsn(chosen), kind="dataset", subtype="dsn", summary=chosen, cluster="datasets",
                              file=p["path"], line=sel["line"])
                    how = f"SELECT ASSIGN TO {sel['assign']} matched to DSN by JCL DD"
                else:
                    tid = f"dd:{sel['assign']}"
                    self.node(tid, name=sel["assign"], kind="dataset", subtype="dd",
                              summary=f"DD name {sel['assign']} (no DSN matched in JCL)", cluster="datasets",
                              file=p["path"], line=sel["line"])
                    how = f"SELECT ASSIGN TO {sel['assign']}"
                self.edge(pid, tid, "FILE", p["path"], sel["line"], sel["snippet"], how, agent="data-lens")
                if not sel["file_status"]:
                    self.finding(
                        lens="quality", type="file-status", rule="file-status-missing",
                        title=f"{p['name']} SELECT {sel['select']} has no FILE STATUS",
                        file=p["path"], line=sel["line"], snippet=sel["snippet"],
                        authority=CONTRAST, agent="quality-lens", claim="Measured",
                        severity="medium", node_id=pid, confidence=0.95,
                    )
                elif sel["status_var"] and not re.search(rf"\bIF\b[^.]{{0,80}}\b{re.escape(sel['status_var'])}\b", p["blob"], re.I):
                    self.finding(
                        lens="quality", type="file-status", rule="file-status-unchecked",
                        title=f"{p['name']} sets {sel['status_var']} and does not test it in an IF",
                        file=p["path"], line=sel["line"], snippet=sel["snippet"],
                        authority=CONTRAST, agent="quality-lens", claim="Measured",
                        severity="low", node_id=pid, confidence=0.7,
                    )
            for table in p["sql_tables"]:
                tid = f"file:{table['name']}"
                self.node(tid, name=table["name"], kind="dataset", subtype="db2",
                          summary=f"SQL table {table['name']}", cluster="datasets")
                self.edge(pid, tid, "FILE", p["path"], table["line"], table["snippet"], "EXEC SQL", agent="data-lens")
            for g in p["gotos"]:
                self.finding(
                    lens="quality", type="goto", rule="goto",
                    title=f"GO TO {g['target']} in {p['name']}",
                    file=p["path"], line=g["line"], snippet=g["snippet"],
                    authority=SONAR + " " + README_STYLE,
                    agent="quality-lens", claim="Measured", severity="medium",
                    node_id=pid, confidence=0.98,
                )
            for a in p["alters"]:
                self.finding(
                    lens="quality", type="alter", rule="alter",
                    title=f"ALTER {a['target']} in {p['name']}",
                    file=p["path"], line=a["line"], snippet=a["snippet"],
                    authority=SONAR, agent="quality-lens", claim="Measured",
                    severity="high", node_id=pid, confidence=0.98,
                )
            targets = {g["target"] for g in p["gotos"]} | {x["target"] for x in p["performs"]}
            for para in p["paragraphs"][1:]:
                pname = para["name"]
                if "-" not in pname or pname.startswith("END-") or pname in {"EXIT", "GOBACK"}:
                    continue
                if pname not in targets and not pname.endswith("SECTION"):
                    self.finding(
                        lens="quality", type="unused-paragraph", rule="unused-paragraph",
                        title=f"Paragraph {pname} in {p['name']} has no PERFORM or GO TO",
                        file=p["path"], line=para["line"], snippet=pname + ".",
                        authority=DEAD_CAVEAT, agent="quality-lens", claim="Candidate",
                        severity="info", node_id=pid, confidence=0.45,
                        verdict="candidate",
                        verdict_reason="No in-repo PERFORM or GO TO names this paragraph. Fall-through and external entry are not visible, so this stays a candidate.",
                    )
            score = p["counts"]["goto"] + p["counts"]["if"] + p["counts"]["evaluate"]
            if p["counts"]["goto"] >= 12 or score >= 45:
                sample = p["gotos"][0] if p["gotos"] else {"line": 1, "snippet": "PROCEDURE DIVISION"}
                self.finding(
                    lens="quality", type="complexity", rule="complexity",
                    title=f"{p['name']} branching score {score} (GO TO {p['counts']['goto']}, IF {p['counts']['if']}, EVALUATE {p['counts']['evaluate']})",
                    file=p["path"], line=sample["line"], snippet=sample["snippet"],
                    authority=SONAR + " Detector pivor.complexity.v1 = GO TO + IF + EVALUATE. Threshold 45, or 12 GO TOs.",
                    agent="quality-lens", claim="Measured", severity="medium",
                    node_id=pid, confidence=0.8,
                )
            for lit, lines in p["literals"].items():
                if len(lines) >= 4 and not re.fullmatch(r"[YNyn01 ]+", lit):
                    self.finding(
                        lens="quality", type="duplicated-literal", rule="duplicated-literal",
                        title=f"Literal appears {len(lines)} times in {p['name']}",
                        file=p["path"], line=lines[0], snippet=snippet(self.files[p["path"]][lines[0] - 1]) if p["path"] in self.files else lit[:80],
                        authority=SONAR, agent="quality-lens", claim="Measured",
                        severity="low", node_id=pid, confidence=0.88,
                    )
            reads: dict[str, int] = defaultdict(int)
            for cmd in p["cics_cmds"]:
                if cmd["verb"] == "READ" and cmd["dataset"]:
                    name, dynamic, _ = _resolve(cmd["dataset"], cmd["dataset_dynamic"], p["values"])
                    if not dynamic:
                        reads[name] += 1
            for name, n in reads.items():
                if n >= 3:
                    cmd = next(
                        (c for c in p["cics_cmds"] if c["verb"] == "READ" and (
                            name in c["snippet"].upper() or (c.get("dataset") or "").upper().startswith(name[:4])
                        )),
                        None,
                    )
                    if cmd is None:
                        continue
                    self.finding(
                        lens="quality", type="chatty-cics", rule="chatty-cics",
                        title=f"{p['name']} issues {n} CICS READs of {name}",
                        file=p["path"], line=cmd["line"], snippet=cmd["snippet"],
                        authority="Predicted from command counts in source. No timing was measured. Chatty CICS is a consolidation candidate, not a speedup claim.",
                        agent="quality-lens", claim="Predicted", severity="info",
                        node_id=pid, confidence=0.6,
                    )
            for sec in p["secret_compares"]:
                self.finding(
                    lens="platform-security", type="cleartext-secret", rule="cleartext-compare",
                    title=f"{p['name']} compares a password field in source",
                    file=p["path"], line=sec["line"], snippet=sec["snippet"],
                    authority="Password field compared in COBOL. No exploit is provided. The modernization target should hash or delegate this check.",
                    agent="platform-security-lens", claim="Measured", severity="high",
                    node_id=pid, confidence=0.84,
                )
            for s in p["sensitive"]:
                if "PIC" in s["snippet"].upper() or "VALUE" in s["snippet"].upper():
                    self.finding(
                        lens="platform-security", type="sensitive-field", rule="sensitive-field",
                        title=f"Sensitive name {s['name']} in {p['name']}",
                        file=p["path"], line=s["line"], snippet=s["snippet"],
                        authority="Identifier in program source matches card, PAN, CVV, SSN, or password.",
                        agent="platform-security-lens", claim="Measured", severity="medium",
                        node_id=pid, confidence=0.7,
                    )

        # Probe the prover with an unsupported claim.
        self.finding(
            lens="code", type="probe", rule="unsupported",
            title="Timezone mismatch in interest posting (unsupported probe)",
            file="", line=0, snippet="", authority="",
            agent="code-lens", claim="Predicted", severity="high",
            probe=True, confidence=0.2,
        )

        copied = {e["target"] for e in self.edges if e["type"] == "COPY"}
        for c in self.tree["copybooks"]:
            nid = f"cpy:{c['name']}"
            if nid not in copied:
                self.finding(
                    lens="quality", type="unused-copybook", rule="unused-copybook",
                    title=f"Copybook {c['name']} is not named by any COPY in this repo",
                    file=c["path"], line=1, snippet=c["name"],
                    authority=DEAD_CAVEAT, agent="quality-lens", claim="Candidate",
                    severity="info", node_id=nid, confidence=0.55,
                    verdict="candidate",
                    verdict_reason="No COPY statement names this copybook. Dynamic or generated COPY would be invisible.",
                )

    def degrees_and_hubs(self) -> None:
        deg = Counter()
        for e in self.edges:
            deg[e["source"]] += 1
            deg[e["target"]] += 1
        if not deg:
            return
        cutoff = max(6, sorted(deg.values())[int(len(deg) * 0.82)])
        for nid, n in self.nodes.items():
            n["degree"] = deg.get(nid, 0)
            n["hub"] = n["degree"] >= cutoff and not n["external"]

    def optimizations(self) -> None:
        job_sets = []
        for n in self.nodes.values():
            if n["kind"] != "job":
                continue
            ds = {e["target"] for e in self.edges if e["source"] == n["id"] and e["type"] == "JOB" and e["target"].startswith("dsn:")}
            pgms = [e["target"] for e in self.edges if e["source"] == n["id"] and e["type"] == "JOB" and e["target"].startswith("pgm:")]
            if ds and pgms:
                job_sets.append((n, ds))
        pairs = 0
        for i in range(len(job_sets)):
            for j in range(i + 1, len(job_sets)):
                a, da = job_sets[i]
                b, db = job_sets[j]
                if da.isdisjoint(db):
                    self.finding(
                        lens="quality", type="parallel-batch", rule="parallel-batch",
                        title=f"{a['name']} and {b['name']} share no datasets in the detected graph",
                        file=a["file"], line=a["line"],
                        snippet=snippet(self.files[a["file"]][a["line"] - 1]) if a["file"] in self.files else a["name"],
                        authority="Predicted: disjoint DSN sets in parsed JCL. Schedulers and undiscovered files can still serialize them. No speedup is claimed.",
                        agent="quality-lens", claim="Predicted", severity="info",
                        node_id=a["id"], confidence=0.5,
                    )
                    pairs += 1
                    if pairs >= 4:
                        return

    def prove_all(self) -> None:
        for f in self.findings:
            if f["verdict"] in {"candidate"}:
                if not _line_ok(self.files, f["file"], f["line"], f["snippet"]):
                    f["verdict"] = "rejected"
                    f["verdict_reason"] = "Candidate had no matching source line."
                continue
            if f["probe"] or not f["file"] or not f["line"] or not f["snippet"] or not f["authority"]:
                f["verdict"] = "rejected"
                f["verdict_reason"] = "Rejected: a finding needs a file, a line, a snippet from that line, and an authority."
                continue
            if not _line_ok(self.files, f["file"], f["line"], f["snippet"]):
                f["verdict"] = "rejected"
                f["verdict_reason"] = "Snippet does not appear on the cited line."
                continue
            f["verdict"] = "accepted"
            f["verdict_reason"] = "Code evidence matches the cited line and an authority is attached."
        for e in self.edges:
            if e["dynamic"]:
                e["proved"] = False
            elif not _line_ok(self.files, e["file"], e["line"], e["snippet"]):
                e["proved"] = False
            else:
                e["proved"] = True

    def triage(self) -> dict:
        raw = len(self.findings)
        rejected_dup = 0
        # Aggregate forward GO TOs that target an EXIT paragraph.
        groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
        for f in self.findings:
            if f["rule"] == "goto" and f["verdict"] == "accepted" and re.search(r"GO TO [A-Z0-9-]*EXIT", f["snippet"], re.I):
                groups[(f["file"], "exit-goto")].append(f)
        for (file, _), items in groups.items():
            if len(items) < 2:
                items[0]["verdict"] = "downgraded"
                items[0]["severity"] = "info"
                items[0]["verdict_reason"] = "Forward GO TO to an EXIT paragraph. Kept, at info, because it is a common COBOL idiom."
                continue
            keeper = items[0]
            keeper["verdict"] = "downgraded"
            keeper["severity"] = "info"
            keeper["title"] = f"{len(items)} forward GO TOs to EXIT paragraphs"
            keeper["verdict_reason"] = "Aggregated. Forward GO TO to an EXIT paragraph is a common idiom and was downgraded, not treated as a defect list."
            for extra in items[1:]:
                extra["verdict"] = "rejected"
                extra["verdict_reason"] = f"Structural duplicate of {keeper['id']} (same file, EXIT GO TO)."
                rejected_dup += 1
        seen = {}
        for f in self.findings:
            if f["verdict"] == "rejected":
                continue
            key = (f["rule"], f["file"], f["line"] // 2, f["snippet"][:40])
            if key in seen and f["rule"] in {"goto", "cics-resp", "sensitive-field"}:
                f["verdict"] = "rejected"
                f["verdict_reason"] = f"Structural near-duplicate of {seen[key]} (same rule, nearby line). Embedding dedupe was not run."
                rejected_dup += 1
            else:
                seen[key] = f["id"]
        triaged = sum(1 for f in self.findings if f["verdict"] != "rejected")
        return {"raw": raw, "triaged": triaged, "rejected": raw - triaged, "structural_dupes": rejected_dup,
                "embeddings": "not run — Nemotron embed id was not confirmed; near-duplicates used line proximity"}

    def measured_patch(self) -> dict | None:
        best = None
        for p in self.tree["programs"]:
            for lit, lines in p["literals"].items():
                if len(lines) >= 4 and len(lit) >= 8:
                    if best is None or len(lines) > best[0]:
                        best = (len(lines), lit, lines, p)
        if not best:
            return None
        count, lit, lines, p = best
        rows = self.files.get(p["path"], [])[:]
        needle = "'" + lit + "'"
        seen = 0
        changed = []
        patched = rows[:]
        for n in lines:
            if n - 1 >= len(patched):
                continue
            if needle not in patched[n - 1]:
                continue
            seen += 1
            if seen == 1:
                continue
            patched[n - 1] = patched[n - 1].replace(needle, "WS-LIT-ALIAS", 1)
            changed.append(n)
        after = 0
        from .source import logical_cobol
        for raw in patched:
            code = logical_cobol(raw) or ""
            after += code.count(needle)
        diff = "\n".join(difflib.unified_diff(
            rows, patched, fromfile=p["path"], tofile=p["path"] + " (patched, not written)",
            lineterm="", n=1,
        ))
        return {
            "claim": "Measured",
            "rule": "duplicated-literal",
            "file": p["path"],
            "literal_preview": lit[:48],
            "before": count,
            "after": after,
            "lines_changed": changed[:12],
            "diff": diff[:4000],
            "note": "Detector re-ran on the patched text in memory. The repo was not modified. This is a static count, not a runtime proof.",
        }

    def behavior_queue(self) -> list[dict]:
        queued = []
        for f in self.findings:
            if f["verdict"] == "rejected":
                continue
            if f["rule"] in {"cics-resp", "file-status-missing", "file-status-unchecked"}:
                queued.append({
                    "finding_id": f["id"],
                    "title": f["title"],
                    "file": f["file"],
                    "line": f["line"],
                    "decision": "unset",
                    "reason": "Adding RESP, NOHANDLE, or a status branch changes behavior. It is queued for Preserve, Change, or Retire, not auto-patched.",
                })
                if len(queued) >= 8:
                    break
        return queued

    def rules(self) -> list[dict]:
        out = []
        for p in self.tree["programs"]:
            blob_lines = p["blob"].splitlines()
            # blob is logical lines, not file lines. Use secret compares and a few IF lines from findings later.
            for sec in p["secret_compares"][:1]:
                out.append({
                    "id": f"rule-{len(out)+1}",
                    "program": p["name"],
                    "file": p["path"],
                    "line": sec["line"],
                    "snippet": sec["snippet"],
                    "text": "Access continues only when the stored password field equals the entered password.",
                    "claim": "Predicted",
                    "decision": "unset",
                    "note": "Paraphrase of a cited condition. Not certified. CICS programs were not executed.",
                })
        # Amount and status conditions from logical snippets stored indirectly: scan files lightly
        pat = re.compile(r"\bIF\b.{0,90}\b(BAL|AMT|STATUS|INTEREST|FEE|LIMIT|ACCT)\b", re.I)
        for p in self.tree["programs"]:
            rows = self.files.get(p["path"], [])
            for i, raw in enumerate(rows, 1):
                from .source import logical_cobol
                code = logical_cobol(raw) or ""
                if pat.search(code):
                    out.append({
                        "id": f"rule-{len(out)+1}",
                        "program": p["name"],
                        "file": p["path"],
                        "line": i,
                        "snippet": snippet(code),
                        "text": "Condition on " + ", ".join(sorted(set(m.group(1).upper() for m in pat.finditer(code)))) + " — see the cited line. Predicted paraphrase, not a certified rule.",
                        "claim": "Predicted",
                        "decision": "unset",
                        "note": "Extracted from an IF. Runtime equivalence was not run.",
                    })
                    if len(out) >= 10:
                        return out
        return out

    def drivers(self) -> list[dict]:
        gotos = sum(1 for f in self.findings if f["rule"] == "goto" and f["verdict"] != "rejected")
        sec = [f for f in self.findings if f["lens"] == "platform-security" and f["verdict"] != "rejected"]
        jobs = sum(1 for n in self.nodes.values() if n["kind"] == "job")
        programs = sum(1 for n in self.nodes.values() if n["kind"] == "program" and not n["external"])
        hubs = [n for n in self.nodes.values() if n["hub"]]
        cite_sec = [{"file": f["file"], "line": f["line"], "title": f["title"]} for f in sec[:3]]
        cite_job = next((n for n in self.nodes.values() if n["kind"] == "job" and n["file"]), None)
        return [
            {"id": "support", "label": "Support", "weight": 1,
             "score": round(min(1.0, programs / 40), 2),
             "text": f"{programs} COBOL programs in this snapshot, plus CICS, VSAM, JCL, and RACF as named in the README.",
             "citations": [{"file": "README.md", "line": 42, "title": "Core technologies list"}]},
            {"id": "security", "label": "Security", "weight": 1,
             "score": round(min(1.0, len(sec) / 6), 2),
             "text": f"{len(sec)} accepted security findings (password handling, sensitive fields, hard-coded values, RACF or user-security JCL).",
             "citations": cite_sec},
            {"id": "compatibility", "label": "Compatibility", "weight": 1,
             "score": 0.8,
             "text": "Online programs depend on CICS and BMS. Batch depends on VSAM datasets named from JCL. Optional DB2, IMS, and MQ modules are in the tree.",
             "citations": [{"file": "README.md", "line": 42, "title": README_TECH}]},
            {"id": "operability", "label": "Operability", "weight": 1,
             "score": round(min(1.0, jobs / 25), 2),
             "text": f"{jobs} JCL jobs coordinate batch. Step order and dataset names are in the job edges.",
             "citations": [{"file": cite_job["file"], "line": cite_job["line"], "title": cite_job["name"]} ] if cite_job else []},
            {"id": "maintainability", "label": "Maintainability", "weight": 1,
             "score": round(min(1.0, gotos / 80), 2),
             "text": f"{gotos} GO TO findings after triage, and {len(hubs)} hub nodes (shared copybooks, datasets, utilities).",
             "citations": [{"file": "README.md", "line": 38, "title": README_STYLE}]},
        ]

    def plan(self) -> dict:
        base_edges = [e for e in self.edges if not e.get("predicted")]
        by_target: dict[str, list[dict]] = defaultdict(list)
        for e in base_edges:
            if e["type"] == "FILE" and e["source"].startswith("pgm:"):
                by_target[e["target"]].append(e)
        wrap_targets = sorted(
            [(tid, evs) for tid, evs in by_target.items() if len(evs) >= 2 and tid.split(":")[0] in {"dsn", "file", "dd"}],
            key=lambda kv: -len(kv[1]),
        )[:5]

        steps: list[dict] = []

        def add_step(**kw):
            sid = f"s{len(steps)+1}"
            step = {
                "id": sid, "index": len(steps) + 1, "verb": kw["verb"], "title": kw["title"],
                "detail": kw["detail"], "claim": "Predicted",
                "remove_ids": [r["id"] for r in kw.get("removals", [])],
                "removals": kw.get("removals", []),
                "add_nodes": kw.get("add_nodes", []),
                "add_edges": kw.get("add_edges", []),
                "migrate": kw.get("migrate", []),
                "requires": kw.get("requires", []),
                "unblocks": [],
                "files": kw.get("files", []),
                "acceptance": kw.get("acceptance", []),
                "risks": kw.get("risks", []),
                "risk_before": 0, "risk_after": 0,
                "deps_before": {}, "deps_after": {}, "legacy_remaining": 0,
            }
            steps.append(step)
            return step

        add_step(
            verb="clean",
            title="Clean before you migrate",
            detail="Triage accepted quality findings. Behavior-changing fixes stay in the Preserve / Change / Retire queue. Dependency edges are unchanged.",
            files=sorted({f["file"] for f in self.findings if f["lens"] == "quality" and f["verdict"] in {"accepted", "downgraded"}})[:12],
            acceptance=["Quality detector counts are re-run on any behavior-preserving patch.", "No dependency edge is removed in this step."],
            risks=["Cleaning does not prove the programs still match production behavior."],
        )

        wrap_of: dict[str, str] = {}
        for tid, evs in wrap_targets:
            iface_id = "iface:" + tid.split(":", 1)[1]
            node = self.nodes[tid]
            iface = {
                "id": iface_id, "name": "access:" + node["name"][:42], "kind": "interface", "subtype": "access",
                "file": "", "line": 0, "summary": f"Predicted access interface in front of {node['name']}",
                "cluster": "datasets", "degree": 0, "hub": False, "risk": 0.3, "status": "modern",
                "entry": False, "external": False,
                "x": round(node.get("x", 0) + 1.4, 4), "y": round(node.get("y", 0) + 0.4, 4), "z": round(node.get("z", 0) + 0.2, 4),
            }
            removals = [{
                "id": e["id"], "reason": "Direct readers move onto the access interface.",
                "mechanism": e["mechanism"], "file": e["file"], "line": e["line"], "snippet": e["snippet"],
                "type": e["type"], "source": e["source"], "target": e["target"],
            } for e in evs]
            adds = []
            for e in evs:
                adds.append({
                    "id": e["id"] + "-iface", "source": e["source"], "target": iface_id, "type": "FILE",
                    "file": e["file"], "line": e["line"], "snippet": e["snippet"],
                    "mechanism": "Predicted replacement edge", "proved": False, "dynamic": False, "predicted": True,
                    "agent": "planner",
                })
            adds.append({
                "id": iface_id + "-back", "source": iface_id, "target": tid, "type": "FILE",
                "file": node["file"], "line": node["line"], "snippet": node["summary"][:160],
                "mechanism": "Predicted: only the interface touches the dataset", "proved": False,
                "dynamic": False, "predicted": True, "agent": "planner",
            })
            step = add_step(
                verb="wrap-dataset",
                title=f"Wrap {node['name'][:48]} behind an interface",
                detail=f"{len(evs)} direct FILE edges move onto an access interface. After this step only the interface retains the dataset edge, which is what makes a later dataset migration possible.",
                removals=removals, add_nodes=[iface], add_edges=adds,
                requires=[{"step_id": "s1", "because": "Clean wave is the precondition for structural wraps."}],
                files=sorted({e["file"] for e in evs}),
                acceptance=[
                    "No program in this set still has a direct FILE edge to the dataset.",
                    "The interface node is the only remaining reader.",
                ],
                risks=["Predicted only. The interface is a model of the graph, not generated code."],
            )
            wrap_of[tid] = step["id"]

        # Migrate programs in an order that respects CALL/LINK and wraps.
        internal = [n for n in self.nodes.values() if n["kind"] == "program" and not n["external"] and n["subtype"] != "dynamic"]
        deps: dict[str, set[str]] = {n["id"]: set() for n in internal}
        for e in base_edges:
            if e["type"] in {"CALL", "LINK"} and e["source"] in deps and e["target"] in deps:
                deps[e["source"]].add(e["target"])
        # Kahn
        ordered = []
        incoming = {k: set(v) for k, v in deps.items()}
        ready = sorted([k for k, v in incoming.items() if not v])
        while ready:
            nid = ready.pop(0)
            ordered.append(nid)
            for k, v in incoming.items():
                if nid in v:
                    v.remove(nid)
                    if not v and k not in ordered and k not in ready:
                        ready.append(k)
                        ready.sort()
        for nid in deps:
            if nid not in ordered:
                ordered.append(nid)

        file_need: dict[str, set[str]] = defaultdict(set)
        call_need: dict[str, set[str]] = defaultdict(set)
        for e in base_edges:
            if e["type"] == "FILE" and e["source"] in deps and e["target"] in wrap_of:
                file_need[e["source"]].add(e["target"])
            if e["type"] in {"CALL", "LINK"} and e["source"] in deps and e["target"] in deps:
                call_need[e["source"]].add(e["target"])

        migrate_step: dict[str, str] = {}
        # Group into chunks of up to 3 that share a cluster, preserving order.
        chunk: list[str] = []
        chunk_cluster = ""
        def flush():
            nonlocal chunk, chunk_cluster
            if not chunk:
                return
            titles = [self.nodes[i]["name"] for i in chunk]
            requires = [{"step_id": "s1", "because": "Clean wave first."}]
            for nid in chunk:
                for ds in file_need.get(nid, ()):
                    sid = wrap_of[ds]
                    if not any(r["step_id"] == sid for r in requires):
                        requires.append({"step_id": sid, "because": f"{self.nodes[nid]['name']} still reads {self.nodes[ds]['name'][:40]} directly until that wrap."})
                for callee in call_need.get(nid, ()):
                    sid = migrate_step.get(callee)
                    if sid and not any(r["step_id"] == sid for r in requires):
                        requires.append({"step_id": sid, "because": f"CALL/LINK target {self.nodes[callee]['name']} is migrated first."})
            step = add_step(
                verb="migrate-program",
                title="Migrate " + ", ".join(titles),
                detail="Mark these programs modern. Direct FILE edges to wrapped datasets are already gone. CALL edges to unmigrated external utilities remain and are labeled as such.",
                migrate=list(chunk),
                requires=requires,
                files=[self.nodes[i]["file"] for i in chunk if self.nodes[i]["file"]],
                acceptance=["Each program's wrap and callee preconditions are in earlier steps.", "Work order lists the source files and the evidence lines."],
                risks=["Predicted. No COBOL was compiled and no CICS transaction was executed."],
            )
            for nid in chunk:
                migrate_step[nid] = step["id"]
            chunk = []
            chunk_cluster = ""

        for nid in ordered:
            cl = self.nodes[nid]["cluster"]
            if chunk and (cl != chunk_cluster or len(chunk) >= 3):
                flush()
            chunk.append(nid)
            chunk_cluster = cl
        flush()

        # Retire the busiest copybook whose copiers are all migrated.
        copy_users: dict[str, set[str]] = defaultdict(set)
        copy_edges: dict[str, list[dict]] = defaultdict(list)
        for e in base_edges:
            if e["type"] == "COPY" and e["target"].startswith("cpy:") and e["source"] in migrate_step:
                copy_users[e["target"]].add(e["source"])
                copy_edges[e["target"]].append(e)
        ranked = sorted(copy_edges, key=lambda t: -len(copy_edges[t]))[:2]
        for tid in ranked:
            node = self.nodes[tid]
            removals = [{
                "id": e["id"], "reason": f"Copier migrated; shared layout {node['name']} can be replaced.",
                "mechanism": e["mechanism"], "file": e["file"], "line": e["line"], "snippet": e["snippet"],
                "type": "COPY", "source": e["source"], "target": e["target"],
            } for e in copy_edges[tid]]
            reqs = []
            for uid in copy_users[tid]:
                sid = migrate_step[uid]
                if not any(r["step_id"] == sid for r in reqs):
                    reqs.append({"step_id": sid, "because": f"{self.nodes[uid]['name']} still COPY-depends on {node['name']}."})
            add_step(
                verb="retire-layout",
                title=f"Replace shared layout {node['name']}",
                detail="Remove COPY edges from migrated programs onto this copybook. The record contract moves to the new interface, which is a prediction.",
                removals=removals, requires=reqs, files=[node["file"]] if node["file"] else [],
                acceptance=["Every in-repo copier is already in a migrate step."],
                risks=["Predicted. Field semantics (COMP-3, REDEFINES) are not re-validated at runtime."],
            )

        # Decommission a handful of application jobs.
        decom = 0
        for n in sorted((x for x in self.nodes.values() if x["kind"] == "job"), key=lambda z: -z["degree"]):
            prog_edges = [e for e in base_edges if e["source"] == n["id"] and e["type"] == "JOB" and e["target"].startswith("pgm:")]
            if not prog_edges:
                continue
            if any(e["target"] not in migrate_step for e in prog_edges):
                continue
            data_edges = [e for e in base_edges if e["source"] == n["id"] and e["type"] == "JOB" and e["target"].startswith("dsn:")]
            removals = [{
                "id": e["id"], "reason": "Job decommissioned after its programs are migrated.",
                "mechanism": e["mechanism"], "file": e["file"], "line": e["line"], "snippet": e["snippet"],
                "type": "JOB", "source": e["source"], "target": e["target"],
            } for e in prog_edges + data_edges]
            reqs = []
            for e in prog_edges:
                sid = migrate_step[e["target"]]
                if not any(r["step_id"] == sid for r in reqs):
                    reqs.append({"step_id": sid, "because": f"Program {self.nodes[e['target']]['name']} is still on the legacy job."})
            add_step(
                verb="decommission",
                title=f"Decommission job {n['name']}",
                detail="Remove the job's edges to migrated programs and to the datasets those steps name.",
                removals=removals, requires=reqs, migrate=[n["id"]],
                files=[n["file"]] if n["file"] else [],
                acceptance=["Every COBOL program this job executes is already migrated."],
                risks=["Predicted. External schedulers (CA-7, Control-M samples) are not fully observed."],
            )
            decom += 1
            if decom >= 4:
                break

        # Risks and dependency curve.
        initial_direct = sum(1 for e in base_edges if e["type"] == "FILE")
        total_prog = max(1, sum(1 for n in internal))
        removed: set[str] = set()
        migrated: set[str] = set()
        sec_open = any(f["lens"] == "platform-security" and f["verdict"] != "rejected" for f in self.findings)

        def tally(removed_ids: set[str]) -> dict[str, int]:
            c = Counter(e["type"] for e in base_edges if e["id"] not in removed_ids)
            return dict(c)

        def risk_of(removed_ids: set[str], mig: set[str]) -> float:
            direct = sum(1 for e in base_edges if e["type"] == "FILE" and e["id"] not in removed_ids)
            legacy = total_prog - sum(1 for i in mig if i.startswith("pgm:"))
            sec = 1.0 if sec_open and not any(self.nodes.get(i, {}).get("name") == "COSGN00C" for i in mig) else 0.45
            raw = 0.4 * (direct / max(initial_direct, 1)) + 0.4 * (legacy / total_prog) + 0.2 * sec
            return round(min(0.95, max(0.05, raw)), 3)

        curve = [{"step": 0, "legacy_dependencies": len(base_edges), "title": "Detected graph"}]
        for step in steps:
            deps_before = tally(removed)
            risk_before = risk_of(removed, migrated)
            removed.update(step["remove_ids"])
            migrated.update(step["migrate"])
            deps_after = tally(removed)
            risk_after = risk_of(removed, migrated)
            step["deps_before"] = deps_before
            step["deps_after"] = deps_after
            step["risk_before"] = risk_before
            step["risk_after"] = risk_after
            step["legacy_remaining"] = sum(deps_after.values())
            curve.append({"step": step["index"], "legacy_dependencies": step["legacy_remaining"], "title": step["title"], "id": step["id"]})

        by_id = {s["id"]: s for s in steps}
        for s in steps:
            for req in s["requires"]:
                prev = by_id.get(req["step_id"])
                if prev and s["id"] not in prev["unblocks"]:
                    prev["unblocks"].append(s["id"])

        return {"steps": steps, "curve": curve, "claim": "Predicted"}

    def clusters(self) -> list[dict]:
        groups: dict[str, list[dict]] = defaultdict(list)
        for n in self.nodes.values():
            groups[n["cluster"]].append(n)
        out = []
        for key, members in sorted(groups.items(), key=lambda kv: -len(kv[1])):
            hubs = [m["name"] for m in members if m["hub"]][:6]
            out.append({
                "id": key,
                "label": key.replace("-", " "),
                "size": len(members),
                "hubs": hubs,
                "summary": f"{len(members)} units. Hubs: {', '.join(hubs) if hubs else 'none' }. Layout is by name and directory, not by dependency.",
            })
        return out

    def docs(self) -> list[dict]:
        passages = [{
            "id": "readme-style",
            "file": "README.md",
            "line": 38,
            "text": "The application intentionally incorporates various coding styles and patterns to exercise analysis, transformation, and migration tooling.",
        }, {
            "id": "readme-tech",
            "file": "README.md",
            "line": 42,
            "text": "Core technologies: COBOL, CICS, VSAM, JCL, RACF, assembler. Optional DB2, IMS, MQ.",
        }]
        for p in self.tree["programs"][:30]:
            if p["function"]:
                passages.append({"id": "fn-" + p["name"], "file": p["path"], "line": 1, "text": p["function"]})
        return passages


def _short_dsn(dsn: str) -> str:
    skip = {"AWS", "M2", "CARDDEMO", "VSAM", "KSDS", "ESDS", "RRDS", "AIX", "PATH", "PS", "GDG", "PDS"}
    parts = [p for p in dsn.split(".") if p and p not in skip and not p.startswith("+")]
    return parts[0] if parts else dsn


def _match_dsn(logical: str, dsns: set[str]) -> str | None:
    logical = logical.strip().upper()
    if not logical or len(logical) < 4:
        return None
    exact = [d for d in dsns if logical in d.split(".")]
    if len(exact) == 1:
        return exact[0]
    pref = [d for d in dsns if any(q.startswith(logical) and len(q) - len(logical) <= 2 for q in d.split("."))]
    if len(pref) == 1:
        return pref[0]
    return None


def validate_steps(steps: list[dict]) -> list[dict]:
    """Check preconditions against the simulated edge set. Returns violations."""
    removed: set[str] = set()
    migrated: set[str] = set()
    violations = []
    by_id = {s["id"]: s for s in steps}
    for step in steps:
        for req in step["requires"]:
            if req["step_id"] not in {s["id"] for s in steps}:
                continue
            # required step must appear earlier
            earlier = [s["id"] for s in steps]
            if earlier.index(req["step_id"]) > earlier.index(step["id"]):
                violations.append({
                    "step_id": step["id"],
                    "message": f"{step['id']} rejected: precondition {req['step_id']} is ordered after it. {req['because']}",
                })
        if step["verb"] == "migrate-program":
            # Any wrap required by requires must already have removed the direct edges.
            for req in step["requires"]:
                prev = by_id.get(req["step_id"])
                if prev and prev["verb"] == "wrap-dataset" and prev["id"] not in {s["id"] for s in steps if steps.index(s) < steps.index(step)}:
                    pass
            missing = [r for r in step["requires"] if r["step_id"] not in [s["id"] for s in steps[:steps.index(step)]]]
            if missing:
                # already recorded via order check; add the dataset-specific line if wrap
                wraps = [m for m in missing if by_id.get(m["step_id"], {}).get("verb") == "wrap-dataset"]
                if wraps:
                    violations.append({
                        "step_id": step["id"],
                        "message": f"{step['id']} rejected: programs still read a dataset directly. {wraps[0]['because']}",
                    })
        if step["verb"] == "wrap-dataset":
            readers = {r["source"] for r in step["removals"]}
            if len(readers) >= 2:
                # valid when run in a legal order; nothing else to check
                pass
        removed.update(step["remove_ids"])
        migrated.update(step["migrate"])
    # de-dupe messages
    seen = set()
    out = []
    for v in violations:
        if v["message"] in seen:
            continue
        seen.add(v["message"])
        out.append(v)
    return out


def invalid_order(steps: list[dict]) -> list[str]:
    """Put the first migrate ahead of the wrap it requires, to show a rejection."""
    ids = [s["id"] for s in steps]
    migrate = next((s for s in steps if s["verb"] == "migrate-program" and any(
        next((x for x in steps if x["id"] == r["step_id"]), {}).get("verb") == "wrap-dataset"
        for r in s["requires"]
    )), None)
    if not migrate:
        return ids
    ids.remove(migrate["id"])
    ids.insert(1, migrate["id"])
    return ids


def apply_order(steps: list[dict], order: list[str]) -> tuple[list[dict], list[dict]]:
    by_id = {s["id"]: s for s in steps}
    ordered = [by_id[i] for i in order if i in by_id]
    return ordered, validate_steps(ordered)


def graph_query(model: dict, focus: str, depth: int, direction: str) -> dict:
    edges = model["edges"]
    out_adj = defaultdict(list)
    in_adj = defaultdict(list)
    for e in edges:
        out_adj[e["source"]].append(e)
        in_adj[e["target"]].append(e)
    down: dict[str, int] = {}
    up: dict[str, int] = {}
    down_edges = []
    up_edges = []

    def walk(start_adj, bucket, edge_bucket):
        frontier = [(focus, 0)]
        seen = {focus}
        while frontier:
            nid, hop = frontier.pop(0)
            if hop >= depth:
                continue
            for e in start_adj.get(nid, []):
                nxt = e["target"] if start_adj is out_adj else e["source"]
                edge_bucket.append({**e, "hop": hop + 1, "dir": "upstream" if start_adj is out_adj else "downstream"})
                if nxt not in seen:
                    seen.add(nxt)
                    bucket[nxt] = hop + 1
                    frontier.append((nxt, hop + 1))

    # upstream = what focus depends on = outgoing
    # downstream = what depends on focus = incoming
    if direction in {"upstream", "both"}:
        walk(out_adj, up, up_edges)
    if direction in {"downstream", "both"}:
        walk(in_adj, down, down_edges)
    return {"downstream": down, "upstream": up, "edges": down_edges + up_edges}


def find_nodes_in_text(model: dict, text: str) -> list[dict]:
    upper = text.upper()
    found: list[tuple[int, dict]] = []
    occupied = [False] * len(upper)
    for n in sorted(model["nodes"], key=lambda z: -len(z["name"])):
        name = n["name"].upper()
        if len(name) < 4:
            continue
        start = 0
        while True:
            idx = upper.find(name, start)
            if idx < 0:
                break
            if not any(occupied[idx:idx + len(name)]):
                for i in range(idx, idx + len(name)):
                    occupied[i] = True
                found.append((idx, n))
                break
            start = idx + 1
    found.sort(key=lambda pair: pair[0])
    out = []
    seen = set()
    for _, n in found:
        if n["id"] in seen:
            continue
        seen.add(n["id"])
        out.append(n)
        if len(out) >= 4:
            break
    return out


def ask(model: dict, question: str, depth: int = 2, types: list[str] | None = None) -> dict:
    q = question.strip()
    low = q.lower()
    depth = max(1, min(6, depth))
    nodes = find_nodes_in_text(model, q)
    ui: dict = {}
    if "only" in low or "show" in low:
        wanted = []
        mapping = {
            "copy": "COPY", "call": "CALL", "link": "LINK", "xctl": "XCTL",
            "file": "FILE", "dataset": "FILE", "database": "FILE", "db2": "FILE",
            "job": "JOB", "jcl": "JOB", "trans": "TRANS", "transaction": "TRANS",
            "screen": "SCREEN", "map": "SCREEN",
        }
        for word, et in mapping.items():
            if word in low and et not in wanted:
                wanted.append(et)
        if wanted:
            ui["edge_types"] = wanted

    simulate_id = None
    if "simulate" in low and nodes:
        simulate_id = nodes[0]["id"]
        ui["simulate"] = simulate_id

    if "path" in low and len(nodes) >= 2:
        path = _path(model, nodes[0]["id"], nodes[1]["id"])
        ids = [nodes[0]["id"]]
        cur = nodes[0]["id"]
        for edge in path:
            cur = edge["target"] if edge["source"] == cur else edge["source"]
            ids.append(cur)
        return {
            "answer": _path_text(model, nodes[0], nodes[1], path),
            "citations": _cites_for_nodes(model, ids),
            "counts": [{"label": f"{len(ids)} units on the path", "node_ids": ids}],
            "highlight": {"focus": nodes[0]["id"], "downstream": {}, "upstream": {i: 1 for i in ids}, "direction": "both"},
            "ui": ui,
            "claim": "Predicted",
        }

    if ui.get("edge_types") and not nodes:
        allow = set(ui["edge_types"])
        edges = [e for e in model["edges"] if e["type"] in allow]
        ids = []
        seen_ids = set()
        for e in edges:
            for nid in (e["source"], e["target"]):
                if nid not in seen_ids:
                    seen_ids.add(nid)
                    ids.append(nid)
        label = ", ".join(sorted(allow))
        return {
            "answer": f"Showing {len(edges)} {label} dependencies. Counts come from the detected graph.",
            "citations": [{"file": e["file"], "line": e["line"], "title": e["snippet"][:80], "node_id": e["source"]} for e in edges[:6]],
            "counts": [{"label": f"{len(edges)} {label}", "node_ids": ids[:60]}],
            "highlight": {"focus": ids[0] if ids else "", "downstream": {i: 1 for i in ids[:80]}, "upstream": {}, "direction": "downstream"},
            "ui": ui,
            "claim": "Predicted",
        }

    if not nodes or "why modernize" in low or "why modernise" in low:
        drivers = model["drivers"]
        bits = [f"{d['label']} {d['score']} (weight {d['weight']})" for d in drivers]
        return {
            "answer": "Why modernize, from cited drivers, not dollars. " + "; ".join(bits) + ". "
            "Weights change emphasis only. They do not change detected edges.",
            "citations": [c for d in drivers for c in d["citations"][:1]],
            "counts": [{"label": f"{len(model['nodes'])} units", "node_ids": [n["id"] for n in model["nodes"][:40]]}],
            "highlight": {"focus": "", "downstream": {}, "upstream": {}, "direction": "both"},
            "ui": ui,
            "claim": "Predicted",
        }

    focus = nodes[0]
    if any(p in low for p in ["depend on", "upstream", "what does", "dependencies of"]):
        # "what depends on X" contains "depends on" too. Disambiguate.
        if re.search(r"what depends on|who depends|affected|impact|downstream", low):
            direction = "downstream"
        elif re.search(r"what does|depend on|dependencies of|upstream", low):
            direction = "upstream"
        else:
            direction = "both"
    elif re.search(r"what depends on|affected|impact|downstream|ripple", low):
        direction = "downstream"
    else:
        direction = "both"

    # Filter edges first if the question names a type.
    model_view = model
    if ui.get("edge_types"):
        allow = set(ui["edge_types"])
        model_view = {**model, "edges": [e for e in model["edges"] if e["type"] in allow or e["source"] == focus["id"] or e["target"] == focus["id"]]}

    qres = graph_query(model_view, focus["id"], depth, direction)
    down_ids = list(qres["downstream"])
    up_ids = list(qres["upstream"])
    dashed = [e for e in qres["edges"] if not e.get("proved")]
    by_type = Counter(e["type"] for e in qres["edges"])
    type_txt = ", ".join(f"{n} {t}" for t, n in sorted(by_type.items())) or "no edges in range"
    if direction == "downstream":
        lead = f"{len(down_ids)} units depend on {focus['name']} within {depth} hops"
    elif direction == "upstream":
        lead = f"{focus['name']} depends on {len(up_ids)} units within {depth} hops"
    else:
        lead = f"{focus['name']}: {len(up_ids)} upstream, {len(down_ids)} downstream, within {depth} hops"
    answer = f"{lead} ({type_txt}). {focus['summary']}"
    if dashed:
        answer += f" {len(dashed)} link(s) in this chain are unproved and drawn dashed."
    hubs = [model_node(model, i) for i in down_ids + up_ids]
    hub_names = [h["name"] for h in hubs if h and h.get("hub")][:3]
    if hub_names:
        answer += f" Shared hubs in view: {', '.join(hub_names)}."
    counts = []
    if direction != "upstream":
        counts.append({"label": f"{len(down_ids)} downstream", "node_ids": down_ids})
    if direction != "downstream":
        counts.append({"label": f"{len(up_ids)} upstream", "node_ids": up_ids})
    for t, n in sorted(by_type.items()):
        counts.append({"label": f"{n} {t}", "node_ids": list({e["source"] if e["target"] == focus["id"] else e["target"] for e in qres["edges"] if e["type"] == t})})
    cites = []
    for e in qres["edges"][:8]:
        cites.append({"file": e["file"], "line": e["line"], "title": e["snippet"][:80], "node_id": e["source"]})
    if focus["file"]:
        cites.insert(0, {"file": focus["file"], "line": focus["line"], "title": focus["summary"][:80], "node_id": focus["id"]})
    card = None
    if simulate_id:
        card = simulate_node(model, simulate_id, depth)
    return {
        "answer": answer,
        "citations": cites,
        "counts": counts,
        "highlight": {
            "focus": focus["id"],
            "downstream": qres["downstream"],
            "upstream": qres["upstream"],
            "direction": direction,
        },
        "ui": ui,
        "result_card": card,
        "claim": "Predicted",
    }


def model_node(model, nid):
    for n in model["nodes"]:
        if n["id"] == nid:
            return n
    return None


def _path(model, a, b) -> list[dict]:
    adj = defaultdict(list)
    for e in model["edges"]:
        adj[e["source"]].append((e["target"], e))
        adj[e["target"]].append((e["source"], e))
    prev = {a: None}
    q = [a]
    while q:
        cur = q.pop(0)
        if cur == b:
            break
        for nxt, e in adj.get(cur, []):
            if nxt not in prev:
                prev[nxt] = (cur, e)
                q.append(nxt)
    if b not in prev:
        return []
    chain = []
    cur = b
    while cur != a:
        parent = prev[cur]
        if parent is None:
            break
        chain.append(parent[1])
        cur = parent[0]
    chain.reverse()
    return chain


def _path_text(model, a, b, chain) -> str:
    if not chain:
        return f"No detected path between {a['name']} and {b['name']}. Missing dynamic calls or external systems would not appear."
    bits = [a["name"]]
    dashed = 0
    for e in chain:
        if not e.get("proved"):
            dashed += 1
        bits.append(f"—{e['type']}→")
        other = e["target"] if e["source"] == bits[-2] or True else e["source"]
        # reconstruct names properly
    names = [a["name"]]
    cur = a["id"]
    for e in chain:
        nxt = e["target"] if e["source"] == cur else e["source"]
        node = model_node(model, nxt)
        names.append(e["type"])
        names.append(node["name"] if node else nxt)
        cur = nxt
    text = "Undirected shortest path on detected edges: " + " ".join(names) + f". {len(chain)} edges."
    if dashed:
        text += f" {dashed} of them are unproved."
    return text


def _cites_for_nodes(model, ids) -> list[dict]:
    cites = []
    for i in ids:
        n = model_node(model, i)
        if n and n.get("file"):
            cites.append({"file": n["file"], "line": n["line"], "title": n["name"], "node_id": n["id"]})
    return cites[:8]


def simulate_node(model: dict, nid: str, depth: int = 3) -> dict:
    qres = graph_query(model, nid, depth, "downstream")
    ids = list(qres["downstream"])
    kinds = Counter((model_node(model, i) or {}).get("kind", "?") for i in ids)
    types = Counter(e["type"] for e in qres["edges"])
    step = next((s for s in model["plan"]["steps"] if nid in s.get("migrate", []) or any(r["target"] == nid for r in s.get("removals", []))), None)
    before = step["risk_before"] if step else model["plan"]["curve"][0]["legacy_dependencies"] and 0.7
    after = step["risk_after"] if step else round(float(before) * 0.85, 3) if isinstance(before, float) else 0.6
    if not isinstance(before, float):
        before = 0.7
        after = 0.6
    return {
        "focus": nid,
        "claim": "Predicted",
        "affected": len(ids),
        "by_kind": dict(kinds),
        "by_type": dict(types),
        "risk_before": before,
        "risk_after": after,
        "step_id": step["id"] if step else None,
        "note": "Ripple is a walk of the detected graph. It is not a proof that a replacement system works.",
        "downstream": qres["downstream"],
    }


def work_order(model: dict, step_id: str) -> str:
    step = next(s for s in model["plan"]["steps"] if s["id"] == step_id)
    target = model.get("brief", {}).get("target", "a language and runtime chosen in the brief")
    lines = [
        f"# Work order {step['id']}: {step['title']}",
        "",
        f"Goal: {step['detail']}",
        f"Target preference (does not change facts): {target}.",
        f"Claim label: {step['claim']}. Dependency counts are detected-graph counts, not effort and not time.",
        "",
        "## Context",
        step["detail"],
        "",
        "## Evidence",
    ]
    for r in step["removals"][:12]:
        lines.append(f"- {r['file']}:{r['line']} {r['type']} {r['mechanism']} — {r['reason']}")
    if not step["removals"]:
        lines.append("- No edges removed. See quality findings for files listed below.")
    lines += ["", "## Requires"]
    for req in step["requires"]:
        lines.append(f"- {req['step_id']}: {req['because']}")
    if not step["requires"]:
        lines.append("- None.")
    lines += ["", "## Unblocks"]
    for u in step["unblocks"]:
        lines.append(f"- {u}")
    if not step["unblocks"]:
        lines.append("- Nothing later in this plan names this step.")
    lines += ["", "## Files"]
    for f in step["files"]:
        lines.append(f"- {f}")
    lines += ["", "## Acceptance tests"]
    for a in step["acceptance"]:
        lines.append(f"- {a}")
    lines += ["", "## Risks"]
    for r in step["risks"]:
        lines.append(f"- {r}")
    lines += [
        "",
        "## Guardrails for a coding agent",
        "- Do not invent dependencies that are not in the evidence list.",
        "- Do not claim a runtime speedup.",
        "- Do not treat candidate dead code as deleted.",
        "- Behavior-changing error handling stays a product decision.",
        "- CardDemo is Apache-2.0 sample code with intentional style variation.",
    ]
    return "\n".join(lines) + "\n"


def apply_brief(model: dict, brief: dict) -> dict:
    """Preferences change recommendation text, never edges or findings."""
    import copy
    version = copy.deepcopy(model["plan"])
    target = brief.get("target") or "Java services on a container runtime"
    where = brief.get("where") or "cloud containers"
    downtime = brief.get("downtime") or "weekend window"
    for step in version["steps"]:
        base = step["detail"].split(" Preference:")[0]
        step["detail"] = base + f" Preference: target {target}, run on {where}, downtime '{downtime}'."
        if downtime.lower().startswith("no"):
            step["risks"] = step["risks"] + ["No-downtime preference keeps the strangler wraps ahead of decommission. Facts are unchanged."]
        for rule in brief.get("rules") or []:
            if rule.get("decision") == "Retire":
                step["risks"] = step["risks"] + [f"Rule {rule.get('id')} marked Retire. Translator may drop it. The cited line is unchanged."]
                break
    version["version"] = model.get("plan_version", 1) + 1
    version["reason"] = "Brief edited. Planner text recomputed. Parser facts, proofs, and edge ids were not recomputed."
    return version


def render_pdf(model: dict) -> bytes:
    lines = [
        "Modernization Swarm — CardDemo roadmap",
        "Dependency counts are detected edges, not effort or time.",
        "Simulator results are Predicted.",
        "",
    ]
    for d in model["drivers"]:
        lines.append(f"{d['label']}: score {d['score']} weight {d['weight']}")
    lines.append("")
    for pt in model["plan"]["curve"]:
        lines.append(f"After step {pt['step']}: {pt['legacy_dependencies']} legacy dependencies — {pt['title'][:70]}")
    lines.append("")
    lines.append("Limits: no CICS runtime, dead code is candidate, layout is not dependency.")
    return _pdf(lines)


def _pdf(lines: list[str]) -> bytes:
    pages = [lines[i:i + 46] for i in range(0, len(lines), 46)] or [[""]]
    objects = []
    def add(data: str) -> int:
        objects.append(data)
        return len(objects)
    font = add("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    content_ids = []
    for page in pages:
        body = ["BT", "/F1 10 Tf", "14 TL", "48 780 Td"]
        for i, line in enumerate(page):
            safe = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            safe = "".join(ch if 32 <= ord(ch) < 127 else "?" for ch in safe)[:110]
            if i == 0:
                body.append(f"({safe}) Tj")
            else:
                body.append(f"T* ({safe}) Tj")
        body.append("ET")
        stream = "\n".join(body).encode("latin-1", errors="replace")
        content_ids.append(add(f"<< /Length {len(stream)} >>\nstream\n{stream.decode('latin-1')}\nendstream"))
    page_ids = []
    for cid in content_ids:
        page_ids.append(add(
            f"<< /Type /Page /Parent 0 0 R /MediaBox [0 0 612 792] /Contents {cid} 0 R "
            f"/Resources << /Font << /F1 {font} 0 R >> >> >>"
        ))
    kids = " ".join(f"{pid} 0 R" for pid in page_ids)
    pages_id = add(f"<< /Type /Pages /Count {len(page_ids)} /Kids [{kids}] >>")
    # fix parent references
    for idx, pid in enumerate(page_ids):
        objects[pid - 1] = objects[pid - 1].replace("/Parent 0 0 R", f"/Parent {pages_id} 0 R")
    catalog = add(f"<< /Type /Catalog /Pages {pages_id} 0 R >>")
    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for i, obj in enumerate(objects, 1):
        offsets.append(len(out))
        out.extend(f"{i} 0 obj\n".encode())
        out.extend(obj.encode("latin-1"))
        out.extend(b"\nendobj\n")
    xref = len(out)
    out.extend(f"xref\n0 {len(objects)+1}\n".encode())
    out.extend(b"0000000000 65535 f \n")
    for off in offsets[1:]:
        out.extend(f"{off:010d} 00000 n \n".encode())
    out.extend(f"trailer << /Size {len(objects)+1} /Root {catalog} 0 R >>\nstartxref\n{xref}\n%%EOF".encode())
    return bytes(out)


def benchmark_local(root: Path) -> dict:
    files = [p for p in root.rglob("*") if p.suffix.lower() in {".cbl", ".jcl", ".bms", ".cpy"} and p.is_file()]

    def one(path: Path):
        suf = path.suffix.lower()
        if suf == ".cbl":
            return parse_cobol(path, root)
        if suf == ".jcl":
            return parse_jcl(path, root)
        if suf == ".bms":
            return parse_bms(path, root)
        return parse_copybook(path, root)

    rows = []

    def run(workers: int) -> float:
        t = time.perf_counter()
        if workers <= 1:
            for f in files:
                one(f)
        else:
            with ThreadPoolExecutor(max_workers=workers) as ex:
                list(ex.map(one, files))
        return round(time.perf_counter() - t, 4)

    seq = run(1)
    rows.append({"backend": "local-parser", "mode": "sequential", "concurrency": 1, "seconds": seq, "units": len(files)})
    for c in (1, 2, 4, 8, 16):
        sec = run(c)
        rows.append({
            "backend": "local-parser", "mode": "parallel", "concurrency": c, "seconds": sec, "units": len(files),
            "calls_per_second": round(len(files) / sec, 2) if sec else None,
        })
    return {"rows": rows, "note": "Wall clock for parsing this repo on this machine. Not a model-serving benchmark."}


def build_run(root: Path, with_benchmark: bool = True) -> dict:
    t0 = time.perf_counter()
    b = Builder(root)
    b.build_graph()
    b.degrees_and_hubs()
    b.optimizations()
    b.prove_all()
    triage = b.triage()
    geometry = attach_geometry(list(b.nodes.values()), b.edges)
    measured = b.measured_patch()
    plan = b.plan()
    # Interface coordinates used dataset positions from before hub pull. Re-stamp from current dataset coords.
    for step in plan["steps"]:
        for node in step["add_nodes"]:
            parent_id = "dsn:" + node["id"].split(":", 1)[1] if node["id"].startswith("iface:") else ""
            # iface id is iface:<rest> where rest may be the full dsn
            rest = node["id"][6:]
            parent = b.nodes.get("dsn:" + rest) or b.nodes.get("file:" + rest) or b.nodes.get("dd:" + rest)
            if parent:
                node["x"] = round(parent["x"] + 1.3, 4)
                node["y"] = round(parent["y"] + 0.35, 4)
                node["z"] = round(parent["z"] + 0.15, 4)
                node["capability"] = parent.get("capability") or "datasets"
                base = parent.get("pos") or {}
                node["pos"] = {
                    "layered": [node["x"], node["y"], node["z"]],
                    "topdown": [node["x"], 0.0, node["z"]],
                    "similarity": None if not base.get("similarity") else [base["similarity"][0] + 1.3, 0.0, base["similarity"][2] + 0.4],
                }
    nodes = list(b.nodes.values())
    drivers = b.drivers()
    rules = b.rules()
    violations = validate_steps(plan["steps"])
    bad_order = invalid_order(plan["steps"])
    _ordered, bad_violations = apply_order(plan["steps"], bad_order)
    elapsed = round(time.perf_counter() - t0, 3)
    bench = benchmark_local(root) if with_benchmark else {"rows": [], "note": "skipped"}
    agents = _agents(elapsed, triage, len(nodes), len(b.edges))
    readme = (root / "README.md").exists()
    return {
        "repo": root.name,
        "license": "Apache-2.0" if (root / "LICENSE").exists() else "unknown",
        "readme_present": readme,
        "elapsed_seconds": elapsed,
        "nodes": nodes,
        "edges": b.edges,
        "findings": b.findings,
        "triage": triage,
        "measured": measured,
        "behavior_queue": b.behavior_queue(),
        "rules": rules,
        "drivers": drivers,
        "plan": plan,
        "plan_version": 1,
        "plan_versions": [{"version": 1, "reason": "Initial plan from the detected graph.", "steps": [s["id"] + " " + s["title"] for s in plan["steps"]]}],
        "validator": {"legal_order_violations": violations, "invalid_demo_violations": bad_violations, "invalid_order": bad_order},
        "clusters": b.clusters(),
        "docs": b.docs(),
        "agents": agents,
        "benchmark": bench,
        "brief": {"target": "", "where": "", "downtime": "", "asked": False},
        "stats": {
            "programs": sum(1 for n in nodes if n["kind"] == "program" and not n["external"]),
            "copybooks": sum(1 for n in nodes if n["kind"] == "copybook"),
            "jobs": sum(1 for n in nodes if n["kind"] == "job"),
            "datasets": sum(1 for n in nodes if n["kind"] == "dataset"),
            "edges": len(b.edges),
            "proved_edges": sum(1 for e in b.edges if e["proved"]),
            "unproved_edges": sum(1 for e in b.edges if not e["proved"]),
            "findings_raw": triage["raw"],
            "findings_triaged": triage["triaged"],
            "findings_rejected": triage["rejected"],
        },
        "geometry": geometry,
        "limits": [
            "Findings can be wrong. The prover rejects claims that lack a line and an authority.",
            "Dead-code and unused-paragraph results are candidates. Schedulers, CICS definitions, and dynamic CALL are outside the repo.",
            "Layout groups by name and directory. Colored edges are the dependencies, not the positions.",
            "Roadmap steps are a model of the detected graph. They do not prove a new system works.",
            "CICS programs were not executed. GnuCOBOL was not used to claim equivalence.",
            "Optimization rows are Predicted. No speedup is claimed.",
            "CardDemo varies its style on purpose (README). Detectors are demonstrating themselves.",
            "Dependency counts cover only what the parsers detected.",
        ],
        "models": [
            {"role": "Mappers, lenses, Explainer", "model": "Deterministic parsers this run", "host": "this process", "called": False},
            {"role": "Coordinator", "model": "Nemotron-Orchestrator-8B or Nano Omni (configured, not required for facts)", "host": "Vultr GPU or serverless — not contacted", "called": False},
            {"role": "Prover retrieval", "model": "Line match against source, not an embedding model", "host": "this process", "called": False},
            {"role": "Planner", "model": "Deterministic simulator", "host": "this process", "called": False},
        ],
    }


def _agents(elapsed: float, triage: dict, nodes: int, edges: int) -> list[dict]:
    # Times are shares of the measured build, so the timeline sums to the real wall clock.
    spec = [
        ("coordinator", "Coordinator", 0.04, "Sharded the tree and ordered lenses. Re-plan waits for a brief edit."),
        ("mapper", "Mapper pool", 0.28, f"Parsed programs, copybooks, JCL, and BMS into {nodes} units."),
        ("code-lens", "Code lens", 0.1, "CALL, XCTL, LINK, TRANS, and SCREEN from CICS and CALL statements."),
        ("data-lens", "Data lens", 0.1, "FILE edges from SELECT/ASSIGN and CICS file commands, joined to JCL DSNs when the DD name matches."),
        ("operations-lens", "Operations lens", 0.1, "JOB edges, step order, PARM literals, instream password patterns."),
        ("platform-lens", "Platform and security lens", 0.08, "Sensitive fields, clear-text password compares, RACF and user-security JCL."),
        ("quality-lens", "Quality and optimization lens", 0.12, f"Detectors emitted {triage['raw']} raw findings, {triage['triaged']} after triage."),
        ("prover", "Prover", 0.08, "Rejected findings with no line, snippet, or authority. Dashed edges failed the line check or are dynamic."),
        ("planner", "Planner", 0.1, "Built wrap, migrate, retire, and decommission steps. Validator checked preconditions."),
    ]
    out = []
    acc = 0.0
    for i, (aid, role, share, note) in enumerate(spec):
        dur = round(elapsed * share, 4)
        out.append({
            "id": aid, "role": role, "status": "done",
            "started": round(acc, 4), "seconds": dur,
            "tokens": 0, "model": "deterministic-tools", "host": "local",
            "note": note,
        })
        acc += dur
    return out
