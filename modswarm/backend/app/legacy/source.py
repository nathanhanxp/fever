"""COBOL/JCL line decoding. CardDemo mixes free-form source and sequence-numbered copybooks."""

from __future__ import annotations

import re

SOURCE_SUFFIXES = {
    ".cbl", ".cpy", ".jcl", ".bms", ".prc", ".mac", ".asm", ".csd", ".txt", ".md",
}


def read_text(path) -> str:
    data = path.read_bytes()
    return data.decode("utf-8", errors="replace")


def logical_cobol(raw: str) -> str | None:
    """Return the code area, or None for blanks and comments."""
    if raw.endswith("\n"):
        raw = raw[:-1]
    if raw.endswith("\r"):
        raw = raw[:-1]
    if not raw.strip():
        return None
    if len(raw) >= 7 and raw[:6].isdigit() and raw[6] in " */":
        indicator = raw[6]
        body = raw[7:72]
        if indicator in "*/":
            return None
        text = body.strip()
        return text or None
    if len(raw) > 72 and raw[72:].strip().isdigit():
        raw = raw[:72]
    text = raw.strip()
    if not text or text[0] in "*/":
        return None
    return text


def logical_jcl(raw: str) -> str | None:
    if raw.endswith("\n"):
        raw = raw[:-1]
    if raw.endswith("\r"):
        raw = raw[:-1]
    s = raw.strip()
    if not s or s.startswith("//*"):
        return None
    return raw.rstrip()


def snippet(text: str, limit: int = 180) -> str:
    one = re.sub(r"\s+", " ", text.strip())
    return one[:limit]


def norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().upper()
