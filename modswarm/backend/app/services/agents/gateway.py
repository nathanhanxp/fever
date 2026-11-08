"""Nemotron gateway: backend select, cache, semaphore, probe-based model choice."""

from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
import time
from pathlib import Path

import httpx

from app.core.config import DATA_DIR, NVIDIA_API_KEY, NVIDIA_BASE_URL, NVIDIA_MODEL, VULTR_API_KEY, VULTR_BASE_URL

PROMPT_VERSION = "ms-1"
_SEM = asyncio.Semaphore(4)
_PROBE = Path(__file__).resolve().parents[5] / "model_probe.json"
if not _PROBE.exists():
    _PROBE = Path(__file__).resolve().parents[4] / "model_probe.json"


def _cache_path() -> Path:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return DATA_DIR / "llm_cache.sqlite"


def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(_cache_path())
    conn.execute("CREATE TABLE IF NOT EXISTS cache (k TEXT PRIMARY KEY, v TEXT, created REAL)")
    conn.execute("CREATE TABLE IF NOT EXISTS traces (id INTEGER PRIMARY KEY AUTOINCREMENT, role TEXT, payload TEXT, created REAL)")
    return conn


def model_for(role: str, backend: str) -> tuple[str, str, str]:
    """Return (base_url, api_key, model). Empty key means not configured."""
    if backend == "vultr":
        base, key = VULTR_BASE_URL, VULTR_API_KEY
    else:
        base, key = NVIDIA_BASE_URL, NVIDIA_API_KEY
    chosen = NVIDIA_MODEL
    if _PROBE.exists():
        report = json.loads(_PROBE.read_text())
        for row in report.get("roles", {}).get(role) or []:
            if row.get("backend") == backend or backend == "nvidia":
                chosen = row.get("model") or chosen
                if row.get("backend") == "vultr":
                    base, key = VULTR_BASE_URL, VULTR_API_KEY
                break
        if backend == "nvidia":
            for row in report.get("roles", {}).get(role) or []:
                if row.get("backend") == "nvidia" and row.get("model"):
                    chosen = row["model"]
                    break
    return base, key, chosen


def vector_size() -> int:
    if _PROBE.exists():
        report = json.loads(_PROBE.read_text())
        rows = report.get("roles", {}).get("embeddings") or []
        if rows and rows[0].get("vector_size"):
            return int(rows[0]["vector_size"])
    return 2048


async def complete(role: str, prompt: str, code_hash: str, backend: str = "nvidia", json_mode: bool = True) -> dict:
    base, key, model = model_for(role, backend)
    if not key:
        return {"status": "not configured", "text": "", "model": model, "latency_s": None, "prompt_tokens": None, "completion_tokens": None}
    cache_key = hashlib.sha256(f"{PROMPT_VERSION}|{model}|{code_hash}|{prompt}".encode()).hexdigest()
    conn = _db()
    row = conn.execute("SELECT v FROM cache WHERE k=?", (cache_key,)).fetchone()
    if row:
        conn.close()
        cached = json.loads(row[0])
        cached["cache"] = "hit"
        return cached
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": "Reply with one JSON object and no markdown."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0,
        "max_tokens": 2500,
    }
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    started = time.perf_counter()
    async with _SEM:
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(base.rstrip("/") + "/chat/completions", headers={"Authorization": f"Bearer {key}"}, json=body)
    elapsed = round(time.perf_counter() - started, 3)
    if response.status_code >= 400:
        result = {"status": "error", "text": "", "error": response.text[:400], "model": model, "latency_s": elapsed, "prompt_tokens": None, "completion_tokens": None}
    else:
        payload = response.json()
        usage = payload.get("usage") or {}
        message = (payload.get("choices") or [{}])[0].get("message") or {}
        text = message.get("content") or ""
        if json_mode:
            start, end = text.find("{"), text.rfind("}")
            if start >= 0 and end > start:
                text = text[start:end + 1]
        result = {
            "status": "ok",
            "text": text,
            "model": model,
            "latency_s": elapsed,
            "prompt_tokens": usage.get("prompt_tokens"),
            "completion_tokens": usage.get("completion_tokens"),
            "cache": "miss",
        }
    conn = _db()
    conn.execute("INSERT OR REPLACE INTO cache (k, v, created) VALUES (?,?,?)", (cache_key, json.dumps(result), time.time()))
    conn.execute("INSERT INTO traces (role, payload, created) VALUES (?,?,?)", (role, json.dumps({"hash": code_hash, "status": result["status"]}), time.time()))
    conn.commit()
    conn.close()
    return result
