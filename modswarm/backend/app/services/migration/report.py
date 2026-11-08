"""Single migration report PDF: every step with what, why, potential vulnerabilities, agent prompt."""

from __future__ import annotations

import io
import re
from typing import Callable
from xml.sax.saxutils import escape

from app.services.migration.sources import kev_for, sources_for, topics_for_step
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    KeepTogether,
    PageBreak,
    Paragraph,
    Preformatted,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

INK = colors.HexColor("#111827")
MUTED = colors.HexColor("#6b7280")
RULE = colors.HexColor("#e5e7eb")
RED = colors.HexColor("#b91c1c")
NV = colors.HexColor("#76b900")

EDGE_RISK = {
    "TRANS": ("CICS transaction becomes a network endpoint; RACF/region security does not carry over, so the new API can be called without authorization.", "Require authentication and per-record authorization on the new endpoint."),
    "SCREEN": ("BMS map field validation is lost when the screen becomes a web form/API, opening injection and over-posting.", "Validate every input field server-side with explicit length/type rules."),
    "LINK": ("COMMAREA passed between programs becomes a service payload; trust between callers is implicit today.", "Authenticate service-to-service calls and validate the payload schema."),
    "XCTL": ("Control transfer becomes an HTTP hop; session state that lived in CICS must be carried securely.", "Use signed, short-lived session tokens; never pass user ids in plain parameters."),
    "FILE": ("VSAM records move to a database reachable over the network; data that was only on-host is now in transit and at rest elsewhere.", "Encrypt in transit (TLS) and at rest; use least-privilege DB roles per service."),
    "COPY": ("Shared copybook becomes duplicated DTOs; field widths/packed decimals can drift and truncate or overflow.", "Generate DTOs from one schema and add round-trip tests for numeric precision."),
    "JOB": ("JCL job moves to a scheduler; dataset credentials and job parameters end up in config files.", "Store credentials in a secrets manager and restrict who can trigger the job."),
    "CALL": ("Static CALL becomes a library/service call; error codes that COBOL ignored may now propagate differently.", "Map every legacy return code to an explicit exception and test the failure paths."),
}


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    body = ParagraphStyle("body", parent=base["BodyText"], fontName="Helvetica", fontSize=9.5, leading=13, textColor=INK, alignment=TA_LEFT)
    return {
        "title": ParagraphStyle("title", parent=body, fontName="Helvetica-Bold", fontSize=20, leading=24, spaceAfter=6),
        "sub": ParagraphStyle("sub", parent=body, textColor=MUTED, fontSize=10, leading=14),
        "h2": ParagraphStyle("h2", parent=body, fontName="Helvetica-Bold", fontSize=13, leading=17, spaceBefore=4, spaceAfter=4),
        "label": ParagraphStyle("label", parent=body, fontName="Helvetica-Bold", fontSize=8, leading=11, textColor=MUTED, spaceBefore=6, spaceAfter=2),
        "body": body,
        "small": ParagraphStyle("small", parent=body, fontSize=8, leading=10.5, textColor=MUTED),
        "cell": ParagraphStyle("cell", parent=body, fontSize=8.5, leading=11),
        "code": ParagraphStyle("code", parent=body, fontName="Courier", fontSize=8, leading=10.5, textColor=INK),
    }


def _p(text: str, style: ParagraphStyle) -> Paragraph:
    return Paragraph(escape(str(text or "")), style)


def _clean_detail(text: str) -> str:
    return re.sub(r"\s*Target stack:.*$", "", text or "").strip()


def _fallback_vulns(step: dict, findings: list[str]) -> list[dict]:
    rows = []
    for f in findings[:2]:
        rows.append({"risk": f"Sensitive data exposed once this code leaves the mainframe: {f.split(' at ')[0]}", "evidence": f.split(" at ")[-1].split(" `")[0], "fix": "Mask or tokenize the field in the target model and in logs."})
    seen = set()
    for r in step.get("removals") or []:
        t = r.get("type")
        if t in EDGE_RISK and t not in seen:
            seen.add(t)
            risk, fix = EDGE_RISK[t]
            rows.append({"risk": risk, "evidence": f"{r.get('file')}:{r.get('line')}", "fix": fix})
        if len(rows) >= 3:
            break
    return rows


def _wrap_code(text: str, width: int = 98) -> str:
    out = []
    for para in (text or "").splitlines() or [""]:
        line = ""
        for word in para.split(" "):
            if len(line) + len(word) + 1 > width:
                out.append(line)
                line = word
            else:
                line = f"{line} {word}".strip()
        out.append(line)
    return "\n".join(out)


def build_report(run: dict, evidence_for: Callable[[dict, dict], dict]) -> bytes:
    st = _styles()
    stack = run.get("target_stack") or {}
    target = stack.get("description") or " · ".join(str(v) for v in [stack.get("language"), stack.get("framework"), stack.get("database"), stack.get("api")] if v) or "target not set"
    steps = (run.get("plan") or {}).get("steps") or []
    nem = run.get("stack_nemotron") or {}

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=LETTER, leftMargin=0.7 * inch, rightMargin=0.7 * inch, topMargin=0.7 * inch, bottomMargin=0.7 * inch,
                            title=f"Migration plan — {run.get('repo')}", author="ModSwarm")
    width = LETTER[0] - 1.4 * inch

    def footer(canvas, d):
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(MUTED)
        canvas.drawString(0.7 * inch, 0.45 * inch, f"{run.get('repo')} → {target}")
        canvas.drawRightString(LETTER[0] - 0.7 * inch, 0.45 * inch, f"Page {d.page}")
        canvas.restoreState()

    story: list = [
        _p("Migration Plan", st["title"]),
        _p(f"{run.get('repo')}  →  {target}", st["sub"]),
        Spacer(1, 10),
    ]
    legacy_edges = len(run.get("legacy_edges") or [])
    summary = Table(
        [[_p("Steps", st["small"]), _p("Legacy dependencies", st["small"]), _p("Planner model", st["small"])],
         [_p(str(len(steps)), st["h2"]), _p(f"{legacy_edges} → 0", st["h2"]), _p(nem.get("model") or "—", st["cell"])]],
        colWidths=[width * 0.2, width * 0.3, width * 0.5],
    )
    summary.setStyle(TableStyle([("LINEBELOW", (0, 1), (-1, 1), 0.5, RULE), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
    story += [summary, Spacer(1, 10)]
    if nem.get("guidance"):
        story += [_p("ORDERING", st["label"]), _p(nem["guidance"], st["body"])]
    kev = kev_for(stack, limit=5)
    if kev.get("items"):
        story += [_p("LIVE THREAT CONTEXT — CISA KNOWN EXPLOITED VULNERABILITIES", st["label"]),
                  _p(f"Catalog {kev.get('catalog_version')} (released {str(kev.get('date_released'))[:10]}): "
                     f"{kev.get('matched')} of {kev.get('total')} entries hit components of the target stack.", st["body"])]
        krows = [[_p("CVE", st["small"]), _p("Component", st["small"]), _p("Added", st["small"]), _p("Vulnerability", st["small"])]]
        for item in kev["items"]:
            krows.append([
                Paragraph(f'<link href="{escape(item["url"])}" color="#1d4ed8"><u>{escape(item["cve"])}</u></link>', st["cell"]),
                _p(item["product"], st["cell"]), _p(item["date_added"], st["small"]), _p(item["name"], st["cell"]),
            ])
        kt = Table(krows, colWidths=[width * 0.18, width * 0.22, width * 0.14, width * 0.46])
        kt.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, 0), 0.5, RED), ("LINEBELOW", (0, 1), (-1, -1), 0.25, RULE), ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 2)]))
        story += [kt, Spacer(1, 4), _p(kev["url"], st["small"])]
    story += [Spacer(1, 6), _p("Each step lists what is done, why it must happen at that point, the vulnerabilities the modernization "
                               "could introduce (with the legacy file:line it comes from), and a prompt you can hand to a coding agent.", st["small"])]
    story.append(PageBreak())

    for i, step in enumerate(steps, 1):
        ev = evidence_for(run, step)
        title = step.get("stack_title") or step.get("title")
        block: list = [
            Table([[_p(f"STEP {i}", ParagraphStyle("n", parent=st["label"], textColor=NV, spaceBefore=0)), _p(title, st["h2"])]],
                  colWidths=[0.7 * inch, width - 0.7 * inch],
                  style=TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE"), ("LEFTPADDING", (0, 0), (-1, -1), 0), ("LINEABOVE", (0, 0), (-1, 0), 1, INK)])),
        ]

        block.append(_p("1 · STEP PERFORMED", st["label"]))
        block.append(_p(_clean_detail(step.get("detail")) or step.get("title"), st["body"]))
        cuts = step.get("removals") or []
        if cuts:
            rows = [[_p(r.get("type"), st["cell"]), _p(f"{str(r.get('source')).split(':')[-1]} → {str(r.get('target')).split(':')[-1]}", st["cell"]),
                     _p(f"{r.get('file')}:{r.get('line')}", st["small"])] for r in cuts[:6]]
            if len(cuts) > 6:
                rows.append([_p("", st["cell"]), _p(f"+ {len(cuts) - 6} more", st["small"]), _p("", st["cell"])])
            t = Table(rows, colWidths=[0.6 * inch, width * 0.45, width - 0.6 * inch - width * 0.45])
            t.setStyle(TableStyle([("LINEBELOW", (0, 0), (-1, -1), 0.25, RULE), ("LEFTPADDING", (0, 0), (-1, -1), 2), ("TOPPADDING", (0, 0), (-1, -1), 2), ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]))
            block.append(t)

        block.append(_p("2 · WHY", st["label"]))
        why = step.get("why_now") or _clean_detail(step.get("detail"))
        reqs = ev.get("requires") or []
        if reqs:
            why += f"  Runs after: {', '.join(reqs)}."
        block.append(_p(why, st["body"]))

        block.append(_p("3 · POTENTIAL VULNERABILITIES", st["label"]))
        vulns = step.get("vulns") or _fallback_vulns(step, ev.get("findings") or [])
        if vulns:
            vrows = [[_p("Risk", st["small"]), _p("Evidence", st["small"]), _p("Control", st["small"])]]
            for v in vulns:
                vrows.append([_p(v.get("risk"), st["cell"]), _p(v.get("evidence"), st["small"]), _p(v.get("fix"), st["cell"])])
            vt = Table(vrows, colWidths=[width * 0.42, width * 0.22, width * 0.36])
            vt.setStyle(TableStyle([
                ("LINEBELOW", (0, 0), (-1, 0), 0.5, RED), ("LINEBELOW", (0, 1), (-1, -1), 0.25, RULE),
                ("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 2),
            ]))
            block.append(vt)
        else:
            block.append(_p("No new exposure: this step only restructures internal references.", st["small"]))

        block.append(_p("4 · EXAMPLE PROMPT FOR A CODING AGENT", st["label"]))
        prompt = step.get("engineer_prompt") or f"Implement '{title}' in {target}. Read {', '.join(step.get('files') or []) or 'the affected programs'}."
        code = Table([[Preformatted(_wrap_code(prompt), st["code"])]], colWidths=[width])
        code.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f3f4f6")), ("BOX", (0, 0), (-1, -1), 0.25, RULE),
                                  ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8), ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
        block.append(code)

        docs = sources_for(topics_for_step(step, ev.get("findings") or []), stack, limit=3)
        if docs:
            block.append(_p("5 · WHY THE AGENT CHOSE THIS — PRIMARY SOURCES", st["label"]))
            for d in docs:
                block.append(Paragraph(
                    f'<link href="{escape(d["url"])}" color="#1d4ed8"><u>{escape(d["title"])}</u></link>'
                    f'  <font color="#6b7280" size="7.5">{escape(d["source"])}</font>',
                    st["cell"],
                ))
                block.append(Paragraph(f'<i>“{escape(d["passage"])}”</i>', ParagraphStyle("q", parent=st["small"], leftIndent=8, textColor=INK, spaceAfter=2)))
                block.append(_p(d["url"], ParagraphStyle("u", parent=st["small"], leftIndent=8, fontSize=7, spaceAfter=4)))
        block.append(Spacer(1, 14))
        story.append(KeepTogether(block[:3]))
        story.extend(block[3:])

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buf.getvalue()
