"""Nemotron tasks grounded in evidence the deterministic extractors already produced.

With no API key the rows stay status "not configured" and carry no invented text.
"""

from __future__ import annotations

import asyncio
import os
import re
import time
from typing import Callable

import httpx

LINE_ID = re.compile(r"[\w./_-]+:\d+")
FALLBACK_MODELS = [
    "nvidia/nemotron-3-nano-30b-a3b",
    "nvidia/llama-3.1-nemotron-nano-8b-v1",
    "nvidia/nvidia-nemotron-nano-9b-v2",
    "nvidia/nemotron-3.5-bolt-e4b",
]


def _key() -> str:
    return os.environ.get("NVIDIA_API_KEY") or os.environ.get("NEMOTRON_API_KEY") or ""


def _models() -> list[str]:
    chosen = os.environ.get("NVIDIA_MODEL", "").strip()
    out = [chosen] if chosen else []
    for name in FALLBACK_MODELS:
        if name not in out:
            out.append(name)
    return out


def task_specs(model: dict) -> list[dict]:
    specs: list[dict] = []
    for step in model.get("plan", {}).get("steps", []):
        allowed = []
        bits = []
        for row in step.get("removals", [])[:6]:
            line_id = f"{row.get('file', '')}:{row.get('line', '')}"
            allowed.append(line_id)
            bits.append(f"{line_id} {row.get('snippet', '')[:160]}")
        specs.append({
            "id": f"rationale-{step['id']}",
            "role": "step-rationale",
            "input_ref": ", ".join(allowed),
            "allowed": allowed,
            "prompt": (
                "Explain in 2 or 3 sentences why this step is in the plan. "
                "Cite only these line ids, and no others: "
                + (", ".join(allowed) if allowed else "(none were extracted)")
                + ". Step: "
                + step.get("title", "")
                + ". "
                + " ".join(bits)
            ),
        })
    for rule in model.get("rules", [])[:24]:
        line_id = f"{rule.get('file', '')}:{rule.get('line', '')}"
        specs.append({
            "id": f"rule-{rule.get('id', line_id)}",
            "role": "rule-explainer",
            "input_ref": line_id,
            "allowed": [line_id] if rule.get("file") else [],
            "prompt": (
                "Explain this extracted rule in plain English. Cite only "
                + (line_id if rule.get("file") else "no line id")
                + ". Snippet: "
                + str(rule.get("snippet", ""))[:200]
            ),
        })
    borderline = [
        f for f in model.get("findings", [])
        if f.get("verdict") in {"downgraded", "candidate"} or (f.get("confidence") or 1) < 0.7
    ][:8]
    for finding in borderline:
        line_id = f"{finding.get('file', '')}:{finding.get('line', '')}"
        specs.append({
            "id": f"skeptic-{finding.get('id')}",
            "role": "skeptic",
            "input_ref": line_id,
            "allowed": [line_id] if finding.get("file") else [],
            "prompt": (
                "This finding is borderline. Confirm it or downgrade it, and give the reason. "
                "Cite only " + (line_id if finding.get("file") else "no line id") + ". "
                + finding.get("title", "") + " " + str(finding.get("snippet", ""))[:180]
            ),
        })
    specs.append({
        "id": "report-summary",
        "role": "report-summary",
        "input_ref": model.get("repo", ""),
        "allowed": [],
        "prompt": (
            "Write a short executive summary from these computed counts only. Do not cite line numbers. "
            f"Repo {model.get('repo')}. Edges {model.get('stats', {}).get('edges', 0)}. "
            f"Proved {model.get('stats', {}).get('proved_edges', 0)}. "
            f"Steps {len(model.get('plan', {}).get('steps', []))}."
        ),
    })
    return specs


def _row(spec: dict, **kw) -> dict:
    prompt = kw.get("prompt_tokens") or 0
    completion = kw.get("completion_tokens") or 0
    return {
        "id": spec["id"],
        "role": spec["role"],
        "status": kw.get("status", "not configured"),
        "started": round(kw.get("started", 0), 4),
        "seconds": round(kw.get("seconds", 0), 4),
        "tokens": prompt + completion,
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "model": kw.get("model", ""),
        "host": kw.get("host", ""),
        "group": "nemotron",
        "note": "",
        "output": kw.get("output", ""),
        "input_ref": spec.get("input_ref", ""),
    }


def _check(output: str, allowed: list[str]) -> str:
    cited = LINE_ID.findall(output or "")
    allowed_set = set(allowed)
    extra = [item for item in cited if item not in allowed_set]
    if extra:
        return "rejected by prover"
    return "done"


async def _chat(client: httpx.AsyncClient, base: str, key: str, model: str, prompt: str) -> tuple[str, int, int]:
    res = await client.post(
        base.rstrip("/") + "/chat/completions",
        headers={"Authorization": f"Bearer {key}"},
        json={
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.2,
            "max_tokens": 280,
        },
        timeout=40,
    )
    res.raise_for_status()
    data = res.json()
    message = data["choices"][0]["message"]
    text = message.get("content") or message.get("reasoning_content") or ""
    usage = data.get("usage") or {}
    return text, int(usage.get("prompt_tokens") or 0), int(usage.get("completion_tokens") or 0)


async def run_tasks(model: dict, on_row: Callable[[dict], None] | None = None) -> list[dict]:
    specs = task_specs(model)
    origin = time.perf_counter()
    key = _key()
    if not key:
        rows = [_row(spec, started=0, host="", model="") for spec in specs]
        for row in rows:
            if on_row:
                on_row(row)
        return rows

    base = os.environ.get("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1")
    host = base.split("/")[2] if "://" in base else base
    vultr_base = os.environ.get("VULTR_BASE_URL", "")
    vultr_key = os.environ.get("VULTR_API_KEY", "")
    vultr_model = os.environ.get("VULTR_MODEL", "")
    names = _models()
    if vultr_base and vultr_key and vultr_model:
        names.append(vultr_model)
    sem = asyncio.Semaphore(3)
    rows: list[dict] = []

    async with httpx.AsyncClient() as client:
        async def one(spec: dict) -> dict:
            async with sem:
                started = time.perf_counter() - origin
                last_error = "not configured"
                for name in names:
                    use_base, use_key, use_host = base, key, host
                    if vultr_model and name == vultr_model:
                        use_base, use_key, use_host = vultr_base, vultr_key, vultr_base.split("/")[2]
                    try:
                        t1 = time.perf_counter()
                        text, prompt_tokens, completion_tokens = await _chat(client, use_base, use_key, name, spec["prompt"])
                        status = _check(text, spec["allowed"])
                        output = text if status == "rejected by prover" else "Nemotron-written, grounded in cited lines. " + text
                        row = _row(
                            spec, status=status, started=started, seconds=time.perf_counter() - t1,
                            prompt_tokens=prompt_tokens, completion_tokens=completion_tokens,
                            model=name, host=use_host, output=output,
                        )
                        if on_row:
                            on_row(row)
                        return row
                    except httpx.HTTPStatusError as exc:
                        last_error = f"http {exc.response.status_code}"
                        continue
                    except Exception as exc:  # noqa: BLE001 — next model, never log the key
                        last_error = type(exc).__name__
                        continue
                row = _row(spec, status="error", started=started, seconds=0, model=names[0] if names else "", host=host, output=last_error)
                if on_row:
                    on_row(row)
                return row

        rows = await asyncio.gather(*(one(spec) for spec in specs))
    return list(rows)
