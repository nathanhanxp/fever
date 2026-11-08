"""OpenAI-Responses-shaped client that talks only to a Nemotron chat endpoint."""

from __future__ import annotations

import json
import os
import uuid
from types import SimpleNamespace

import httpx

from app.core.config import NVIDIA_API_KEY, NVIDIA_BASE_URL, NVIDIA_MODEL


def _ns(**kwargs):
    return SimpleNamespace(**kwargs)


class _Responses:
    def __init__(self, parent: "AsyncNemotron"):
        self.parent = parent
        self._threads: dict[str, list] = {}

    async def parse(self, *, model: str, instructions: str = "", input: list | None = None, text_format=None, **_kw):
        messages = []
        if instructions:
            messages.append({"role": "system", "content": instructions})
        for item in input or []:
            if isinstance(item, dict):
                messages.append({"role": item.get("role", "user"), "content": item.get("content", "")})
        schema_hint = ""
        if text_format is not None and hasattr(text_format, "model_json_schema"):
            schema_hint = "\nReply with JSON matching this schema:\n" + json.dumps(text_format.model_json_schema())
        if messages:
            messages[-1]["content"] = str(messages[-1]["content"]) + schema_hint
        raw = await self.parent.chat(model, messages, json_mode=True)
        parsed = None
        if text_format is not None:
            try:
                parsed = text_format.model_validate_json(raw["text"])
            except Exception:
                parsed = None
        content = _ns(parsed=parsed, text=raw["text"])
        message = _ns(type="message", content=[content])
        usage = _ns(input_tokens=raw["prompt_tokens"], output_tokens=raw["completion_tokens"])
        return _ns(output=[message], output_text=raw["text"], usage=usage)

    async def create(self, **kwargs):
        model = kwargs.get("model") or self.parent.model
        instructions = kwargs.get("instructions") or ""
        prev = kwargs.get("previous_response_id")
        incoming = kwargs.get("input") or []
        if prev and prev in self._threads:
            messages = list(self._threads[prev])
            for item in incoming:
                if isinstance(item, dict) and item.get("type") == "function_call_output":
                    messages.append({"role": "tool", "tool_call_id": item.get("call_id", ""), "content": item.get("output", "")})
                elif isinstance(item, dict):
                    messages.append({"role": item.get("role", "user"), "content": item.get("content", "")})
        else:
            messages = []
            if instructions:
                messages.append({"role": "system", "content": instructions})
            for item in incoming:
                if isinstance(item, dict) and "role" in item:
                    messages.append({"role": item["role"], "content": item.get("content", "")})
        tools = kwargs.get("tools")
        openai_tools = []
        for tool in tools or []:
            if tool.get("type") == "function" and "function" not in tool:
                openai_tools.append({
                    "type": "function",
                    "function": {
                        "name": tool["name"],
                        "description": tool.get("description", ""),
                        "parameters": tool.get("parameters", {"type": "object", "properties": {}}),
                    },
                })
        raw = await self.parent.chat(model, messages, tools=openai_tools or None)
        response_id = "resp_" + uuid.uuid4().hex[:12]
        stored = list(messages)
        if raw.get("tool_calls"):
            stored.append({
                "role": "assistant",
                "content": raw["text"] or "",
                "tool_calls": raw["tool_calls"],
            })
        else:
            stored.append({"role": "assistant", "content": raw["text"] or ""})
        self._threads[response_id] = stored
        usage = _ns(input_tokens=raw["prompt_tokens"], output_tokens=raw["completion_tokens"])
        if not kwargs.get("stream"):
            return _ns(id=response_id, output_text=raw["text"] or "", usage=usage, output=[])

        async def events():
            yield _ns(type="response.created", response=_ns(id=response_id), delta=None, item=None, item_id=None, arguments=None)
            if raw["text"]:
                yield _ns(type="response.output_text.delta", delta=raw["text"], response=None, item=None, item_id=None, arguments=None)
            for call in raw.get("tool_calls") or []:
                fn = call.get("function") or {}
                item_id = call.get("id") or uuid.uuid4().hex
                yield _ns(
                    type="response.output_item.added",
                    item=_ns(id=item_id, name=fn.get("name", ""), call_id=item_id),
                    delta=None, response=None, item_id=item_id, arguments=None,
                )
                yield _ns(
                    type="response.function_call_arguments.done",
                    item_id=item_id,
                    arguments=fn.get("arguments") or "{}",
                    delta=None, response=None, item=None,
                )

        return events()


class _Embeddings:
    def __init__(self, parent: "AsyncNemotron"):
        self.parent = parent

    async def create(self, *, input, model: str, dimensions: int | None = None, **_kw):
        texts = input if isinstance(input, list) else [input]
        payload = {"model": model, "input": texts, "input_type": "passage"}
        url = self.parent.base.rstrip("/") + "/embeddings"
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(url, headers=self.parent.headers, json=payload)
            response.raise_for_status()
            body = response.json()
        data = []
        for item in body.get("data") or []:
            vector = item.get("embedding") or []
            if dimensions and len(vector) > dimensions:
                vector = vector[:dimensions]
            data.append(_ns(index=item.get("index", len(data)), embedding=vector))
        usage = body.get("usage") or {}
        return _ns(data=data, usage=_ns(prompt_tokens=usage.get("prompt_tokens")))


class AsyncNemotron:
    def __init__(self, api_key: str | None = None, base_url: str | None = None, model: str | None = None):
        self.api_key = api_key if api_key is not None else (NVIDIA_API_KEY or os.environ.get("NVIDIA_API_KEY", ""))
        self.base = base_url or NVIDIA_BASE_URL or os.environ.get("NVIDIA_BASE_URL") or "https://integrate.api.nvidia.com/v1"
        self.model = model or NVIDIA_MODEL or "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning"
        self.responses = _Responses(self)
        self.embeddings = _Embeddings(self)

    @property
    def headers(self) -> dict:
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    async def chat(self, model: str, messages: list, tools: list | None = None, json_mode: bool = False) -> dict:
        if not self.api_key:
            return {"text": "", "tool_calls": [], "prompt_tokens": None, "completion_tokens": None, "error": "not configured"}
        body: dict = {"model": model or self.model, "messages": messages, "temperature": 0, "max_tokens": 800}
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        url = self.base.rstrip("/") + "/chat/completions"
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(url, headers=self.headers, json=body)
            response.raise_for_status()
            payload = response.json()
        choice = (payload.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        usage = payload.get("usage") or {}
        return {
            "text": message.get("content") or "",
            "tool_calls": message.get("tool_calls") or [],
            "prompt_tokens": usage.get("prompt_tokens"),
            "completion_tokens": usage.get("completion_tokens"),
        }


AsyncOpenAI = AsyncNemotron
