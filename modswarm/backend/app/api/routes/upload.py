"""Zip upload and the CardDemo preset."""

from __future__ import annotations

import os
import shutil
import uuid
import zipfile
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile

from app.core.config import REPOS_DIR
from app.services.migration.service import open_tree

router = APIRouter(prefix="/api", tags=["upload"])

ALLOWED = {
    ".cbl", ".cob", ".cobol", ".cl2", ".cpy", ".copy", ".jcl", ".bms", ".csd",
    ".md", ".txt", ".inc", ".mac", ".proc", ".prc", ".ctl", ".sql", ".java",
}
FOLDER_EXT = {
    "cbl": ".cbl", "cobol": ".cbl", "src": ".cbl", "source": ".cbl",
    "cpy": ".cpy", "copy": ".cpy", "copybook": ".cpy", "copybooks": ".cpy", "cpy-bms": ".cpy",
    "jcl": ".jcl", "jobs": ".jcl", "proc": ".jcl",
    "bms": ".bms", "maps": ".bms", "map": ".bms",
    "csd": ".csd", "ctl": ".ctl",
}
MAX_FILES = 8000
MAX_BYTES = 80_000_000


def _keep_as(name: str) -> str | None:
    """Return the relative path to write, adding a suffix when the folder implies the type."""
    path = Path(name)
    if "__MACOSX" in path.parts or path.name.startswith("._"):
        return None
    if path.name in {"LICENSE", "NOTICE", "LICENSE.md", "README.md", "README"}:
        return name
    suffix = path.suffix.lower()
    if suffix in ALLOWED:
        return name
    # Extensionless mainframe trees: migrated_app/cbl/COACTUPC
    for part in reversed(path.parts[:-1]):
        key = part.lower()
        if key in FOLDER_EXT:
            if suffix:
                return None
            return str(path) + FOLDER_EXT[key]
    return None


def _safe_extract(zf: zipfile.ZipFile, dest: Path) -> int:
    count = 0
    total = 0
    for info in zf.infolist():
        if info.is_dir():
            continue
        kept = _keep_as(info.filename)
        if not kept:
            continue
        if kept.startswith("/") or ".." in Path(kept).parts:
            continue
        total += info.file_size
        if total > MAX_BYTES or count >= MAX_FILES:
            raise HTTPException(413, "Upload exceeds the file or byte cap")
        target = dest / kept
        target.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(info) as src, open(target, "wb") as out:
            shutil.copyfileobj(src, out)
        count += 1
    return count


@router.post("/upload")
async def upload_zip(file: UploadFile = File(...)):
    REPOS_DIR.mkdir(parents=True, exist_ok=True)
    dest = REPOS_DIR / f"upload-{uuid.uuid4().hex[:10]}"
    dest.mkdir(parents=True)
    raw = await file.read()
    if not raw:
        raise HTTPException(400, "Empty upload")
    tmp = dest / "_in.zip"
    tmp.write_bytes(raw)
    try:
        with zipfile.ZipFile(tmp) as zf:
            kept = _safe_extract(zf, dest)
    except zipfile.BadZipFile as exc:
        shutil.rmtree(dest, ignore_errors=True)
        raise HTTPException(400, "Not a zip file") from exc
    except HTTPException:
        shutil.rmtree(dest, ignore_errors=True)
        raise
    tmp.unlink(missing_ok=True)
    if kept == 0:
        shutil.rmtree(dest, ignore_errors=True)
        raise HTTPException(
            400,
            "Zip had no COBOL/JCL/BMS/copybook/Java files. "
            "Accepted: .cbl .cob .cpy .jcl .bms .csd .java, or extensionless files under cbl/ cpy/ jcl/ bms/ folders.",
        )
    try:
        return open_tree(dest, display_name=file.filename or dest.name)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"Parse failed: {exc}") from exc


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[5]


@router.post("/preset/carddemo")
def preset_carddemo():
    root = os.environ.get("CARDDEMO_ROOT", "")
    path = Path(root)
    if not path.is_absolute():
        path = _repo_root() / root
    if not path.exists():
        path = _repo_root() / "aws-mainframe-modernization-carddemo-main"
    if not path.exists():
        raise HTTPException(404, "CardDemo tree is not on disk")
    return open_tree(path, display_name=path.name)


@router.post("/preset/jforum3")
def preset_jforum3():
    """Deterministic Java parse of jforum3 → Quarkus modernization graph."""
    env = (os.environ.get("JFORUM_ROOT") or "").strip()
    path: Path | None = None
    if env:
        path = Path(env)
        if not path.is_absolute():
            path = _repo_root() / env
    if path is None or not path.exists():
        path = _repo_root() / "jforum3-master"
    if not path.exists():
        raise HTTPException(404, "jforum3-master tree is not on disk")
    return open_tree(path, display_name=path.name or "jforum3-master")

