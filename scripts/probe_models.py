"""Probe Nemotron-compatible backends. Writes model_probe.json from real HTTP results.

No fabricated timings or token counts: missing usage fields stay null.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "model_probe.json"

SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "probe_answer",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {"ok": {"type": "boolean"}, "note": {"type": "string"}},
            "required": ["ok", "note"],
            "additionalProperties": False,
        },
    },
}

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "ping",
            "description": "Return a short status token.",
            "parameters": {
                "type": "object",
                "properties": {"token": {"type": "string"}},
                "required": ["token"],
            },
        },
    }
]


def _env(name: str) -> str:
    val = os.environ.get(name, "")
    if val:
        return val
    path = ROOT / ".env"
    if path.exists():
        for line in path.read_text().splitlines():
            if line.startswith(name + "="):
                return line.split("=", 1)[1].strip()
    return ""


def _post(base: str, key: str, path: str, body: dict, timeout: int = 90) -> dict:
    url = base.rstrip("/") + path
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            elapsed = time.perf_counter() - started
            parsed = json.loads(raw) if raw else {}
            usage = parsed.get("usage") or {}
            vector_size = None
            data = parsed.get("data") or []
            if data and isinstance(data[0], dict) and isinstance(data[0].get("embedding"), list):
                vector_size = len(data[0]["embedding"])
            return {
                "ok": True,
                "status": resp.status,
                "seconds": round(elapsed, 3),
                "prompt_tokens": usage.get("prompt_tokens"),
                "completion_tokens": usage.get("completion_tokens"),
                "total_tokens": usage.get("total_tokens"),
                "vector_size": vector_size,
                "snippet": raw[:500],
            }
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        return {
            "ok": False,
            "status": exc.code,
            "seconds": round(time.perf_counter() - started, 3),
            "prompt_tokens": None,
            "completion_tokens": None,
            "total_tokens": None,
            "error": raw[:800],
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "status": None,
            "seconds": round(time.perf_counter() - started, 3),
            "prompt_tokens": None,
            "completion_tokens": None,
            "total_tokens": None,
            "error": str(exc)[:800],
        }


def probe_model(base: str, key: str, model: str) -> dict:
    completion = _post(
        base,
        key,
        "/chat/completions",
        {
            "model": model,
            "messages": [{"role": "user", "content": "Reply with the single word pong."}],
            "max_tokens": 32,
            "temperature": 0,
        },
    )
    schema = _post(
        base,
        key,
        "/chat/completions",
        {
            "model": model,
            "messages": [{"role": "user", "content": 'Return JSON {"ok": true, "note": "probe"}.'}],
            "max_tokens": 80,
            "temperature": 0,
            "response_format": SCHEMA,
        },
    )
    if not schema["ok"]:
        schema_fallback = _post(
            base,
            key,
            "/chat/completions",
            {
                "model": model,
                "messages": [{"role": "user", "content": 'Return JSON {"ok": true, "note": "probe"}.'}],
                "max_tokens": 80,
                "temperature": 0,
                "response_format": {"type": "json_object"},
            },
        )
        schema = {**schema_fallback, "strict_schema_error": schema.get("error")}
    tools = _post(
        base,
        key,
        "/chat/completions",
        {
            "model": model,
            "messages": [{"role": "user", "content": "Call the ping tool with token probe."}],
            "max_tokens": 80,
            "temperature": 0,
            "tools": TOOLS,
            "tool_choice": "auto",
        },
    )
    return {"model": model, "completion": completion, "json_schema": schema, "tools": tools}


def main() -> None:
    backends = []
    nv_key = _env("NVIDIA_API_KEY") or _env("NEMOTRON_API_KEY")
    nv_base = _env("NVIDIA_BASE_URL") or "https://integrate.api.nvidia.com/v1"
    nv_model = _env("NVIDIA_MODEL") or "nvidia/nemotron-3-nano-30b-a3b"
    if nv_key:
        nv_models = []
        for candidate in (
            nv_model,
            "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning",
            "nvidia/nemotron-nano-3-30b-a3b",
            "nvidia/nemotron-3.5-bolt-e4b",
        ):
            if candidate and candidate not in nv_models:
                nv_models.append(candidate)
        backends.append(("nvidia", nv_base, nv_key, nv_models))
    else:
        backends.append(("nvidia", nv_base, "", []))

    vultr_key = _env("VULTR_API_KEY")
    vultr_base = _env("VULTR_BASE_URL") or "https://api.vultrinference.com/v1"
    vultr_model = _env("VULTR_MODEL")
    vultr_models = []
    for candidate in (vultr_model, "nemotron-3-nano-omni-30b-a3b-reasoning"):
        if candidate and candidate not in vultr_models:
            vultr_models.append(candidate)
    if vultr_key and vultr_models:
        backends.append(("vultr", vultr_base, vultr_key, vultr_models))
    else:
        backends.append(("vultr", vultr_base, "", []))

    report = {"backends": [], "roles": {}}
    for name, base, key, models in backends:
        entry = {"name": name, "base": base, "configured": bool(key), "models": []}
        if not key:
            entry["note"] = "not configured"
        for model in models:
            entry["models"].append(probe_model(base, key, model))
        report["backends"].append(entry)

    def feasible(kind: str) -> list[dict]:
        found = []
        for backend in report["backends"]:
            for row in backend["models"]:
                block = row.get(kind) or {}
                if block.get("ok"):
                    found.append({"backend": backend["name"], "model": row["model"], "seconds": block.get("seconds")})
        return found

    completion_ok = feasible("completion")
    schema_ok = feasible("json_schema")
    tools_ok = feasible("tools")
    report["roles"] = {
        "coordinator": completion_ok[:1],
        "describer": schema_ok[:1] or completion_ok[:1],
        "namer": schema_ok[:1] or completion_ok[:1],
        "lens": schema_ok[:1] or completion_ok[:1],
        "skeptic": schema_ok[:1] or completion_ok[:1],
        "planner": schema_ok[:1] or completion_ok[:1],
        "analyst": completion_ok[:1],
        "explorer": tools_ok[:1] or completion_ok[:1],
        "embeddings": [],
    }
    # Embedding probe is separate and optional.
    if nv_key:
        embed = _post(
            nv_base,
            nv_key,
            "/embeddings",
            {"model": "nvidia/nemotron-3-embed-1b", "input": ["probe"], "input_type": "query"},
        )
        report["embeddings_probe"] = {
            k: embed[k] for k in ("ok", "status", "seconds", "error", "vector_size") if k in embed
        }
        if embed.get("ok"):
            report["roles"]["embeddings"] = [{
                "backend": "nvidia",
                "model": "nvidia/nemotron-3-embed-1b",
                "vector_size": embed.get("vector_size"),
                "seconds": embed.get("seconds"),
            }]

    OUT.write_text(json.dumps(report, indent=2))
    print(OUT)
    for role, rows in report["roles"].items():
        print(role, "feasible" if rows else "not feasible", rows)


if __name__ == "__main__":
    main()
