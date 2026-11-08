"""Zip upload and the CardDemo preset."""

from __future__ import annotations

import os
import shutil
import zipfile
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile

from app.core.config import REPOS_DIR
from app.services.migration.service import open_tree

router = APIRouter(prefix="/api", tags=["upload"])

ALLOWED = {".cbl", ".cpy", ".jcl", ".bms", ".csd", ".md"}
MAX_FILES = 4000
MAX_BYTES = 40_000_000


def _license_name(text: str) -> str:
    head = text[:800].lower()
    if "mit license" in head:
        return "MIT"
    if "apache license" in head:
        return "Apache-2.0"
    if "gnu general public license" in head:
        return "GPL"
    return "unknown"


def _safe_extract(zf: zipfile.ZipFile, dest: Path) -> int:
    count = 0
    total = 0
    for info in zf.infolist():
        if info.is_dir():
            continue
        name = info.filename
        if name.startswith("/") or ".." in Path(name).parts:
            continue
        suffix = Path(name).suffix.lower()
        base = Path(name).name
        if suffix not in ALLOWED and base not in {"LICENSE", "NOTICE"}:
            continue
        total += info.file_size
        if total > MAX_BYTES or count >= MAX_FILES:
            raise HTTPException(413, "Upload exceeds the file or byte cap")
        target = dest / name
        target.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(info) as src, open(target, "wb") as out:
            shutil.copyfileobj(src, out)
        count += 1
    return count


@router.post("/upload")
async def upload_zip(file: UploadFile = File(...)):
    REPOS_DIR.mkdir(parents=True, exist_ok=True)
    dest = REPOS_DIR / "upload"
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    raw = await file.read()
    tmp = dest / "_in.zip"
    tmp.write_bytes(raw)
    try:
        with zipfile.ZipFile(tmp) as zf:
            kept = _safe_extract(zf, dest)
    except zipfile.BadZipFile as exc:
        raise HTTPException(400, "Not a zip file") from exc
    tmp.unlink(missing_ok=True)
    if kept == 0:
        raise HTTPException(400, "Zip had no COBOL, JCL, BMS, copybook, CSD, markdown, or LICENSE files")
    return open_tree(dest, display_name=file.filename or "upload")


@router.post("/preset/carddemo")
def preset_carddemo():
    root = os.environ.get("CARDDEMO_ROOT", "")
    path = Path(root)
    if not path.is_absolute():
        path = Path(__file__).resolve().parents[5] / root
    if not path.exists():
        guess = Path(__file__).resolve().parents[5] / "aws-mainframe-modernization-carddemo-main"
        path = guess
    if not path.exists():
        raise HTTPException(404, "CardDemo tree is not on disk")
    return open_tree(path, display_name=path.name)
