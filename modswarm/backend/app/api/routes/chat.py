from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from app.services.llm.nemotron import AsyncOpenAI
from pydantic import BaseModel
from sqlmodel import Session, select, func

from app.core.config import OPENAI_API_KEY
from app.core.database import get_session
from app.models import CodeUnit, FeatureCluster, ClusterMember, GraphEdge, ProjectGraphSnapshot, Repo
from app.services.search import get_latest_snapshot, vector_search, graph_traverse
from app.services.agents import explorer as graph_tools

logger = logging.getLogger("graphdev.chat")

router = APIRouter(prefix="/api/repos/{repo_id}", tags=["chat"])


class ChatHistoryItem(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str
    history: list[ChatHistoryItem] = []
    snapshot_id: str | None = None
    # Live graph screenshot + palette so Ask uses Nemotron Omni VLM
    image: str | None = None
    clusters: list[dict] | None = None
    step_id: str | None = None


TOOLS = [
    {
        "type": "function",
        "name": "vector_search",
        "description": "Search code units by semantic similarity against their LLM-generated descriptions. Descriptions focus on business concepts, domain entities, and user flows (NOT code syntax or framework names). Write queries that match this style.",
        "parameters": {
            "type": "object",
            "properties": {
                "queries": {"type": "array", "items": {"type": "string"}, "description": "1-3 queries using business/domain language, e.g. 'workspace task board drag reorder status columns' not 'TaskBoard component'"},
                "top_k": {"type": "integer", "description": "Number of results to return", "default": 8},
            },
            "required": ["queries"],
        },
    },
    {
        "type": "function",
        "name": "graph_traverse",
        "description": "Build a subgraph from seed node IDs. Use 'connect' mode to find paths between nodes. Use 'expand' mode to BFS outward from nodes in a direction.",
        "parameters": {
            "type": "object",
            "properties": {
                "seed_ids": {"type": "array", "items": {"type": "string"}, "description": "Node IDs to start from (from search results)"},
                "mode": {"type": "string", "enum": ["connect", "expand"], "description": "'connect' finds paths between seeds, 'expand' does BFS outward"},
                "direction": {"type": "string", "enum": ["outgoing", "incoming", "both"], "default": "both"},
                "max_depth": {"type": "integer", "default": 3, "description": "Max BFS hops"},
            },
            "required": ["seed_ids", "mode"],
        },
    },
    {
        "type": "function",
        "name": "dependencies",
        "description": "Programs and files a named symbol depends on, with hop distance and file:line.",
        "parameters": {"type": "object", "properties": {"focus": {"type": "string"}}, "required": ["focus"]},
    },
    {
        "type": "function",
        "name": "dependents",
        "description": "What depends on a named symbol, with hop distance and file:line.",
        "parameters": {"type": "object", "properties": {"focus": {"type": "string"}}, "required": ["focus"]},
    },
    {
        "type": "function",
        "name": "path",
        "description": "Shortest dependency path between two names.",
        "parameters": {"type": "object", "properties": {"source": {"type": "string"}, "target": {"type": "string"}}, "required": ["source", "target"]},
    },
    {
        "type": "function",
        "name": "filter_by_lens",
        "description": "Edges whose type matches a lens or legacy edge type.",
        "parameters": {"type": "object", "properties": {"lens": {"type": "string"}}, "required": ["lens"]},
    },
]


def _migration_run(repo_id: str):
    try:
        from app.api.routes.swarm_api import _run_for
        return _run_for(repo_id)
    except Exception:
        return None


def _build_system_prompt(repo: Repo, snapshot: ProjectGraphSnapshot, session: Session, run: dict | None = None) -> str:
    from app.services.migration.chat_context import migration_digest

    unit_count = session.exec(
        select(func.count()).where(CodeUnit.snapshot_id == snapshot.id)
    ).one()
    edge_count = session.exec(
        select(func.count()).where(GraphEdge.snapshot_id == snapshot.id)
    ).one()

    clusters = session.exec(
        select(FeatureCluster).where(FeatureCluster.snapshot_id == snapshot.id)
    ).all()
    cluster_labels = []
    for c in clusters:
        count = session.exec(
            select(func.count()).where(ClusterMember.cluster_id == c.id)
        ).one()
        cluster_labels.append(f"{c.label} ({count} units)")

    return f"""You are a modernization + codebase assistant for **{repo.name}**.

You are connected to the measured dependency graph and migration agent network — not a screenshot captioner.

Graph: {unit_count} units, {edge_count} edges.
Subsystems: {', '.join(cluster_labels) if cluster_labels else 'none detected'}.
Edge types include COPY, CALL, LINK, XCTL, FILE, JOB, TRANS, SCREEN (and Java CALL/LINK/TRANS equivalents).

## Active migration plan
{migration_digest(run)}

## How to answer
- Prefer MEASURED GRAPH SCOPE / tool results / migration packets over any image description.
- For "API related" / region questions: list the real clusters and concrete controllers/services/transactions — never collapse to a single node just because a cluster is literally named "api".
- Name symbols the repo actually has. Cite edge types and file paths when useful.
- On migration questions: side effects → what breaks / vulns → cite sources with markdown links.

## Tools
- **vector_search(queries, top_k)**: find units by business meaning / name.
- **graph_traverse(seed_ids, mode, direction)**: subgraphs from search results.
- **filter_by_lens(lens)**, **dependencies**, **dependents**, **path**: precise graph ops.

## Response style
- Lead with the answer in 2–5 short paragraphs. Concrete names > vague color talk.
- Include :::flow blocks when paths help. Use #N indices from tools, never raw UUIDs.
- Do NOT dump CSS hues or "I see a blue glow" unless the user asked about a color.

## Rules
- If MEASURED GRAPH SCOPE is present, answer from it first; tools optional to deepen.
- Else 1 vector_search (≤3 queries) + optional 1 graph_traverse.
- Max 3 flow blocks, ≤5 nodes each.
- Do NOT include :::actions blocks."""


def _sse(event_type: str, data: dict) -> str:
    return f"data: {json.dumps({**data, 'type': event_type})}\n\n"


@router.post("/chat")
async def chat_stream(
    repo_id: str,
    body: ChatRequest,
    session: Session = Depends(get_session),
):
    repo = session.get(Repo, repo_id)
    if not repo:
        raise HTTPException(404, "Repo not found")

    snapshot = get_latest_snapshot(repo_id, body.snapshot_id, session)
    if not snapshot:
        raise HTTPException(400, "No snapshots found")

    run = _migration_run(repo_id)
    system_prompt = _build_system_prompt(repo, snapshot, session, run)
    client = AsyncOpenAI(api_key=OPENAI_API_KEY)

    from app.services.migration.chat_context import detect_step_index, format_step_for_prompt, step_packet

    user_content = body.message
    step_idx = detect_step_index(body.message)
    if run and step_idx:
        packet = step_packet(run, step_idx)
        if packet:
            user_content = f"{body.message}\n\n{format_step_for_prompt(packet)}"

    messages: list[dict] = []
    for h in body.history:
        messages.append({"role": h.role, "content": h.content})
    messages.append({"role": "user", "content": user_content})

    node_registry: dict[str, dict] = {}  # index_key "#N" -> {id, qualname}

    def register_node(node_id: str, qualname: str) -> str:
        for key, val in node_registry.items():
            if val["id"] == node_id:
                return key
        idx = len(node_registry)
        key = f"#{idx}"
        node_registry[key] = {"id": node_id, "qualname": qualname}
        return key

    def resolve_indices(text: str) -> str:
        import re
        def replace_flow(m: re.Match) -> str:
            try:
                flow = json.loads(m.group(2))
                if "node_ids" in flow:
                    flow["node_ids"] = [
                        node_registry.get(ref, {}).get("id", ref) if ref.startswith("#") else ref
                        for ref in flow["node_ids"]
                    ]
                if "edge_keys" in flow:
                    for ek in flow["edge_keys"]:
                        if isinstance(ek.get("source"), str) and ek["source"].startswith("#"):
                            reg = node_registry.get(ek["source"], {})
                            ek["source"] = reg.get("qualname", ek["source"])
                        if isinstance(ek.get("target"), str) and ek["target"].startswith("#"):
                            reg = node_registry.get(ek["target"], {})
                            ek["target"] = reg.get("qualname", ek["target"])
                return f":::{m.group(1)}\n{json.dumps(flow)}\n:::"
            except (json.JSONDecodeError, KeyError):
                return m.group(0)
        return re.sub(r":::(flow)\n([\s\S]*?)\n:::", replace_flow, text)

    async def generate():
        nonlocal messages
        tool_counter = 0
        previous_response_id = None

        if step_idx and run:
            yield _sse("tool_start", {"id": "mig", "name": "migration_step", "args": {"queries": [f"step {step_idx}"]}})
            yield _sse("tool_done", {"id": "mig", "count": 1, "summary": [
                {"name": f"step {step_idx}", "kind": "migration", "sim": 1.0}
            ]})

        color_q = False
        try:
            from app.services.agents.scope import is_color_question, scope_facts, scope_question

            color_q = is_color_question(body.message)
            yield _sse("tool_start", {"id": "scope", "name": "graph_scope", "args": {"queries": [body.message[:80]]}})
            scope = await scope_question(
                session,
                snapshot.id,
                body.message,
                clusters=body.clusters,
            )
            kind = (
                scope.get("cluster_label")
                or (scope.get("cluster_labels") or [None])[0]
                or scope.get("hue_name")
                or scope.get("lens")
                or "match"
            )
            yield _sse("tool_done", {"id": "scope", "count": scope["count"], "summary": [
                {"name": n, "kind": str(kind), "sim": 1.0} for n in scope.get("top", [])
            ]})
            if scope["count"]:
                yield _sse("graph_focus", scope)
                facts = scope_facts(session, snapshot.id, scope)
                base = messages[-1]["content"] if messages else body.message
                if "[Migration step" not in base and facts:
                    base = f"{base}\n\n{facts}"
                    messages = messages[:-1] + [{"role": "user", "content": base}]
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"graph scope failed: {exc}")

        # Vision only for color questions — structural Ask uses the agent tool loop + measured scope
        image = (body.image or "").strip()
        if image and color_q:
            if not image.startswith("data:"):
                image = f"data:image/png;base64,{image}"
            if len(image) > 1_800_000:
                yield _sse("error", {"message": "Graph screenshot too large — zoom out and retry"})
                yield _sse("done", {})
                return
            from app.services.agents.gateway import complete_vision
            from app.services.migration.chat_context import migration_digest

            clusters = body.clusters or []
            palette_lines = []
            for c in clusters[:24]:
                label = str(c.get("label") or "?")
                hue_name = str(c.get("hue_name") or c.get("color_name") or "colored")
                css = str(c.get("color") or "")
                count = c.get("count")
                palette_lines.append(f"- {hue_name} cluster → label “{label}” ({count} units) css={css}")

            legend = (
                "Live 3D dependency graph. Answer the color/region question using the palette + MEASURED scope.\n"
                "Do not invent architecture from glow alone — prefer named units in the scope notes.\n"
                "pink/magenta ≈ hue 300–340 (never call these green). green ≈ hue 90–150.\n"
            )
            prompt = f"{legend}\n"
            if palette_lines:
                prompt += "GROUND-TRUTH cluster palette:\n" + "\n".join(palette_lines) + "\n\n"
            digest = migration_digest(run) if run else ""
            if digest:
                prompt += f"Migration context:\n{digest[:800]}\n\n"
            scoped = ""
            if messages and isinstance(messages[-1].get("content"), str):
                scoped = messages[-1]["content"]
            prompt += (
                f"Operator question: {body.message[:500]}\n"
                "Name the matching cluster label and what those units do in THIS repo. "
                "List several concrete symbols from the measured scope. Avoid CSS dumps.\n"
            )
            if scoped and scoped != body.message:
                prompt += f"\n{scoped[:2000]}\n"

            yield _sse("tool_start", {
                "id": "vision",
                "name": "graph_vision",
                "args": {"clusters": len(clusters), "queries": [body.message[:80]]},
            })
            result = await complete_vision(prompt, image, backend="nvidia", max_tokens=900)
            text = (result.get("text") or "").strip()
            if result.get("status") != "ok" or not text:
                err = result.get("error") or result.get("status") or "vision failed"
                yield _sse("tool_done", {"id": "vision", "count": 0, "summary": [{"name": "vision", "kind": "error", "sim": 0}]})
                # Fall through to tool agent instead of hard-failing
                logger.warning(f"vision failed, falling back to tools: {err}")
            else:
                yield _sse("tool_done", {
                    "id": "vision",
                    "count": len(clusters) or 1,
                    "summary": [
                        {"name": c.get("hue_name") or c.get("label") or "cluster", "kind": str(c.get("label") or ""), "sim": 1.0}
                        for c in clusters[:6]
                    ] or [{"name": result.get("model") or "omni", "kind": "vlm", "sim": 1.0}],
                })
                chunk = 48
                for i in range(0, len(text), chunk):
                    yield _sse("text_delta", {"delta": text[i : i + chunk]})
                yield _sse("done", {})
                return

        while True:
            create_kwargs: dict = {
                "model": "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning",
                "instructions": system_prompt,
                "tools": TOOLS,
                "stream": True,
                "reasoning": {"effort": "medium", "summary": "auto"},
            }

            if previous_response_id:
                create_kwargs["previous_response_id"] = previous_response_id
                create_kwargs["input"] = tool_outputs
            else:
                create_kwargs["input"] = messages

            response = await client.responses.create(**create_kwargs)

            pending_tool_calls: dict[str, dict] = {}
            has_tool_call = False
            response_id = None
            tool_outputs = []

            full_text = ""

            async for event in response:
                if event.type == "response.created":
                    response_id = event.response.id

                elif event.type == "response.reasoning_summary_text.delta":
                    yield _sse("reasoning", {"delta": event.delta})

                elif event.type == "response.output_text.delta":
                    full_text += event.delta
                    yield _sse("text_delta", {"delta": event.delta})

                elif event.type == "response.output_item.added":
                    if hasattr(event.item, "name") and event.item.name:
                        pending_tool_calls[event.item.id] = {
                            "name": event.item.name,
                            "call_id": event.item.call_id if hasattr(event.item, "call_id") else event.item.id,
                        }

                elif event.type == "response.function_call_arguments.done":
                    has_tool_call = True
                    item_id = event.item_id
                    tool_info = pending_tool_calls.get(item_id, {})
                    tool_name = tool_info.get("name", "")
                    call_id = tool_info.get("call_id", item_id)
                    args_json = event.arguments

                    try:
                        args = json.loads(args_json)
                    except json.JSONDecodeError:
                        args = {}

                    tool_counter += 1
                    tid = f"t{tool_counter}"
                    logger.info(f"tool_call: {tool_name}({json.dumps(args)})")
                    yield _sse("tool_start", {"id": tid, "name": tool_name, "args": args})

                    try:
                        if tool_name == "vector_search":
                            queries = args.get("queries", [])
                            if isinstance(queries, str):
                                queries = [queries]
                            result = await vector_search(
                                repo_id, snapshot, queries, args.get("top_k", 8), session,
                            )
                            logger.info(f"tool_result: {tool_name} -> {len(result)} results")

                            indexed_result = []
                            summary = []
                            for r in result[:8]:
                                idx = register_node(r["id"], r["qualname"])
                                indexed_result.append({**r, "index": idx})
                                summary.append({"name": r["symbol_name"], "kind": r["kind"], "sim": r.get("similarity", 0)})

                            yield _sse("tool_done", {"id": tid, "count": len(result), "summary": summary})
                            tool_output = json.dumps(indexed_result, default=str)

                        elif tool_name in {"dependencies", "dependents", "path", "filter_by_lens", "findings_for", "impact"}:
                            fn = {
                                "dependencies": graph_tools.dependencies,
                                "dependents": graph_tools.dependents,
                                "path": graph_tools.path,
                                "filter_by_lens": graph_tools.filter_by_lens,
                                "findings_for": graph_tools.findings_for,
                                "impact": graph_tools.dependents,
                            }[tool_name]
                            if tool_name == "path":
                                result = fn(session, snapshot.id, args.get("source", ""), args.get("target", ""))
                            elif tool_name == "filter_by_lens":
                                result = fn(session, snapshot.id, args.get("lens", ""))
                            else:
                                result = fn(session, snapshot.id, args.get("focus", ""))
                            yield _sse("tool_done", {"id": tid, "count": result.get("count", 0)})
                            tool_output = json.dumps(result, default=str)
                        elif tool_name == "graph_traverse":
                            seed_ids = args.get("seed_ids", [])
                            resolved_seeds = [
                                node_registry.get(s, {}).get("id", s) if s.startswith("#") else s
                                for s in seed_ids
                            ]
                            result = graph_traverse(
                                snapshot, resolved_seeds,
                                args.get("mode", "connect"), args.get("direction", "both"),
                                args.get("max_depth", 3), 30, session,
                            )
                            logger.info(f"tool_result: {tool_name} -> {len(result['nodes'])} nodes, {len(result['edges'])} edges")

                            indexed_nodes = []
                            for n in result["nodes"]:
                                idx = register_node(n["id"], n["qualname"])
                                indexed_nodes.append({**n, "index": idx})

                            indexed_edges = []
                            for e in result["edges"]:
                                src_idx = register_node(e["source_id"], e["source_qualname"])
                                tgt_idx = register_node(e["target_id"], e["target_qualname"])
                                indexed_edges.append({**e, "source_index": src_idx, "target_index": tgt_idx})

                            chains: list[str] = []
                            for e in indexed_edges[:12]:
                                src = e["source_qualname"].split("::")[-1]
                                tgt = e["target_qualname"].split("::")[-1]
                                chains.append(f"{e['source_index']} {src} -> {e['target_index']} {tgt}")

                            yield _sse("tool_done", {
                                "id": tid,
                                "count": len(result["nodes"]),
                                "edges": len(result["edges"]),
                                "chains": chains,
                            })
                            tool_output = json.dumps({"nodes": indexed_nodes, "edges": indexed_edges}, default=str)
                        else:
                            tool_output = json.dumps({"error": f"Unknown tool: {tool_name}"})
                            yield _sse("tool_done", {"id": tid, "count": 0})
                    except Exception as e:
                        logger.error(f"Tool {tool_name} failed: {e}")
                        tool_output = json.dumps({"error": str(e)})
                        yield _sse("tool_done", {"id": tid, "count": 0})

                    tool_outputs.append({
                        "type": "function_call_output",
                        "call_id": call_id,
                        "output": tool_output,
                    })

            previous_response_id = response_id

            if not has_tool_call:
                resolved_text = resolve_indices(full_text)
                if resolved_text != full_text:
                    logger.info(f"resolved {len(node_registry)} node indices in flow blocks")
                logger.info(f"chat response ({len(resolved_text)} chars):\n{resolved_text}")
                if resolved_text != full_text:
                    yield _sse("replace_text", {"text": resolved_text})
                yield _sse("done", {})
                return

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
