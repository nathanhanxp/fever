"use client"

import { useCallback, useEffect, useRef, useState } from "react"
import { useGraphStore } from "@/store/graph-store"

type Frame = {
  step_id: string
  index: number
  title: string
  ok: boolean
  fault?: boolean
  retire_nodes?: string[]
  removed_edges?: { source: string; target: string; type?: string; cause?: string; file?: string; line?: number }[]
  nodes?: string[]
  edges?: { source: string; target: string; type?: string; cause?: string; file?: string; line?: number }[]
  cyber?: { node_id?: string; color?: string; title?: string; detail?: string }[]
  explanation?: string
}

type FaultEdge = {
  source: string
  target: string
  type?: string
  cause?: string
  file?: string
  line?: number
  snippet?: string
}

type WhatIfResult = {
  frames: Frame[]
  fault?: {
    step_id: string
    index: number
    title: string
    explanation: string
    color?: string
    cyber?: Frame["cyber"]
    missing?: string[]
    missing_titles?: string[]
    nodes?: string[]
    edges?: FaultEdge[]
    why?: string
  } | null
  ok?: boolean
  note?: string
  order_titles?: { id: string; index: number; title?: string }[]
}

function mapLegacyToGraphId(repoId: string, raw: string): string | null {
  const data = useGraphStore.getState().repos[repoId]?.data
  if (!data || !raw) return null
  const short = raw.includes(":") ? raw.split(":").slice(1).join(":") : raw
  const upper = short.toUpperCase()
  return (
    data.nodes.find((n) => {
      if (n.id === raw || n.qualname === raw || n.symbol_name === raw) return true
      const q = (n.qualname || "").toUpperCase()
      const s = (n.symbol_name || "").toUpperCase()
      return q === upper || s === upper || q.endsWith(`:${upper}`) || q.endsWith(upper)
    })?.id ?? null
  )
}

function nodeLabel(repoId: string, raw: string): string {
  const id = mapLegacyToGraphId(repoId, raw)
  const data = useGraphStore.getState().repos[repoId]?.data
  const n = id ? data?.nodes.find((x) => x.id === id) : null
  return n?.symbol_name || n?.qualname || raw.split(":").pop() || raw
}

const PRESETS = [
  "what if step 10 before 2",
  "what if step 18 before 3",
  "what if step 26 before 6",
]

export function WhatIfPanel({ repoId }: { repoId: string }) {
  const [open, setOpen] = useState(false)
  const [text, setText] = useState("what if step 10 before 2")
  const [busy, setBusy] = useState(false)
  const [status, setStatus] = useState("")
  const [path, setPath] = useState<{ index: number; title: string; ok: boolean }[]>([])
  const [fault, setFault] = useState<WhatIfResult["fault"]>(null)
  const stopRef = useRef(false)
  const hasPlan = useGraphStore((s) => !!s.repos[repoId]?.data)

  const paintFaultOnGraph = useCallback((
    frame: Frame,
    faultInfo: WhatIfResult["fault"] | null | undefined,
    accumulate: { retired: Set<string>; removed: Set<string> },
  ) => {
    const data = useGraphStore.getState().repos[repoId]?.data
    if (!data) return

    const glowEdges = new Set<string>()
    const glowNodes = new Set<string>()
    const flashEdges = new Set<string>()
    const isolateNodes = new Set<string>()
    const isolateEdges = new Set<string>()
    const cyberPatch: Record<string, "orange" | "purple" | "legacy" | null> = {
      ...(useGraphStore.getState().repos[repoId]?.cyberRisk || {}),
    }

    const edgeRows = faultInfo?.edges || frame.edges || frame.removed_edges || []
    const nodeRows = faultInfo?.nodes || frame.nodes || frame.retire_nodes || []

    for (const raw of nodeRows) {
      const id = mapLegacyToGraphId(repoId, raw)
      if (!id) continue
      glowNodes.add(id)
      isolateNodes.add(id)
      accumulate.retired.add(id)
    }
    for (const e of edgeRows) {
      const s = mapLegacyToGraphId(repoId, e.source)
      const t = mapLegacyToGraphId(repoId, e.target)
      if (!s || !t) continue
      const full = `${s}::${t}::${e.type || ""}`
      const short = `${s}::${t}`
      glowEdges.add(full)
      glowEdges.add(short)
      flashEdges.add(full)
      flashEdges.add(short)
      isolateEdges.add(full)
      isolateEdges.add(short)
      glowNodes.add(s)
      glowNodes.add(t)
      isolateNodes.add(s)
      isolateNodes.add(t)
      accumulate.removed.add(full)
      accumulate.removed.add(short)
    }

    for (const c of frame.cyber || faultInfo?.cyber || []) {
      const id = c.node_id ? mapLegacyToGraphId(repoId, c.node_id) : null
      if (!id) continue
      glowNodes.add(id)
      isolateNodes.add(id)
      cyberPatch[id] = c.color === "purple" ? "purple" : "orange"
    }

    const primaryEdge = edgeRows[0]
    let selectedEdge: string | null = null
    if (primaryEdge) {
      const s = mapLegacyToGraphId(repoId, primaryEdge.source)
      const t = mapLegacyToGraphId(repoId, primaryEdge.target)
      if (s && t) selectedEdge = `${s}::${t}::${primaryEdge.type || ""}`
    }
    const primaryNode = [...isolateNodes][0] || null

    useGraphStore.getState().setHighlight(repoId, {
      source: "what-if",
      isolate: true,
      label: faultInfo
        ? `Fault · #${faultInfo.index} ${faultInfo.title}`
        : `Step #${frame.index}`,
      nodeIds: isolateNodes.size ? isolateNodes : glowNodes,
      edgeKeys: isolateEdges.size ? isolateEdges : glowEdges,
    })
    useGraphStore.getState().setPlayback(repoId, {
      retiredNodeIds: new Set(accumulate.retired),
      removedEdgeKeys: new Set(accumulate.removed),
      glowEdgeKeys: glowEdges,
      glowNodeIds: glowNodes,
      flashingEdgeKeys: flashEdges,
      cyberGlowNodeIds: new Set(
        [...glowNodes].filter((id) => cyberPatch[id] === "orange" || cyberPatch[id] === "purple"),
      ),
      cyberRisk: cyberPatch,
      playbackStepId: frame.step_id,
    })
    if (selectedEdge) useGraphStore.getState().selectEdge(repoId, selectedEdge)
    else if (primaryNode) useGraphStore.getState().selectNode(repoId, primaryNode)
  }, [repoId])

  const applyFrame = useCallback((frame: Frame, accumulate: { retired: Set<string>; removed: Set<string> }, faulting: boolean) => {
    if (faulting) {
      paintFaultOnGraph(frame, null, accumulate)
      return
    }
    const data = useGraphStore.getState().repos[repoId]?.data
    if (!data) return
    const glowEdges = new Set<string>()
    const glowNodes = new Set<string>()

    for (const raw of frame.retire_nodes || []) {
      const id = mapLegacyToGraphId(repoId, raw)
      if (!id) continue
      glowNodes.add(id)
      accumulate.retired.add(id)
    }
    for (const e of frame.removed_edges || []) {
      const s = mapLegacyToGraphId(repoId, e.source)
      const t = mapLegacyToGraphId(repoId, e.target)
      if (!s || !t) continue
      const key = `${s}::${t}::${e.type || ""}`
      glowEdges.add(key)
      glowNodes.add(s)
      glowNodes.add(t)
      accumulate.removed.add(key)
      accumulate.removed.add(`${s}::${t}`)
    }

    useGraphStore.getState().setPlayback(repoId, {
      retiredNodeIds: new Set(accumulate.retired),
      removedEdgeKeys: new Set(accumulate.removed),
      glowEdgeKeys: glowEdges,
      glowNodeIds: glowNodes,
      flashingEdgeKeys: new Set(),
      cyberGlowNodeIds: new Set(),
      playbackStepId: frame.step_id,
    })
  }, [repoId, paintFaultOnGraph])

  const run = async () => {
    if (!text.trim()) return
    stopRef.current = false
    setBusy(true)
    setFault(null)
    setPath([])
    setStatus("Simulating…")
    useGraphStore.getState().setHighlight(repoId, null)
    useGraphStore.getState().selectNode(repoId, null)
    useGraphStore.getState().selectEdge(repoId, null)
    useGraphStore.getState().setPlayback(repoId, {
      retiredNodeIds: new Set(),
      removedEdgeKeys: new Set(),
      flashingEdgeKeys: new Set(),
      glowEdgeKeys: new Set(),
      glowNodeIds: new Set(),
      cyberGlowNodeIds: new Set(),
      playbackStepId: null,
    })
    try {
      const res = await fetch(`/api/repos/${repoId}/what-if`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: text.trim() }),
      })
      const body: WhatIfResult = await res.json()
      if (!body.frames?.length && !body.ok) {
        setStatus("Could not parse — try “what if step 10 before 2”")
        return
      }

      if (body.ok) {
        setPath([])
        setFault(null)
        setStatus(body.note || "Legal — no fault.")
        return
      }

      const acc = { retired: new Set<string>(), removed: new Set<string>() }
      const trail: { index: number; title: string; ok: boolean }[] = []
      for (const frame of body.frames) {
        if (stopRef.current) break
        trail.push({ index: frame.index, title: frame.title, ok: !frame.fault })
        setPath([...trail])
        setStatus(frame.fault ? `FAULT at #${frame.index}` : `#${frame.index} ok`)
        applyFrame(frame, acc, !!frame.fault)
        await new Promise((r) => setTimeout(r, frame.fault ? 900 : 450))
      }
      if (body.fault) {
        setFault(body.fault)
        const last = body.frames[body.frames.length - 1]
        if (last) paintFaultOnGraph(last, body.fault, acc)
      }
    } catch (e) {
      setStatus(String((e as Error)?.message || e))
    } finally {
      setBusy(false)
    }
  }

  useEffect(() => {
    setOpen(false)
    setFault(null)
    setPath([])
    setStatus("")
    setBusy(false)
    stopRef.current = true
  }, [repoId])

  useEffect(() => () => { stopRef.current = true }, [])

  if (!hasPlan) return null

  return (
    <div className="absolute bottom-4 right-3 z-40 w-[min(340px,calc(100%-24px))]">
      {!open ? (
        <button
          type="button"
          onClick={() => setOpen(true)}
          className="rounded-md border bg-background/95 backdrop-blur px-3 py-2 text-[12px] font-medium shadow-md hover:bg-muted/60"
        >
          What if…
        </button>
      ) : (
        <div className="rounded-md border bg-background shadow-xl overflow-hidden max-h-[min(70vh,520px)] flex flex-col">
          <div className="flex items-center gap-2 border-b px-3 py-1.5 shrink-0">
            <p className="text-[11px] font-semibold">What if</p>
            <span className="text-[10px] text-muted-foreground">reorder → fault</span>
            <button type="button" className="ml-auto text-[11px] text-muted-foreground hover:text-foreground" onClick={() => setOpen(false)}>×</button>
          </div>
          <div className="p-2.5 space-y-2 overflow-y-auto">
            <form className="flex gap-1" onSubmit={(e) => { e.preventDefault(); void run() }}>
              <input
                value={text}
                onChange={(e) => setText(e.target.value)}
                placeholder="what if step 10 before 2"
                className="flex-1 min-w-0 rounded border bg-transparent px-2 py-1 text-[12px] outline-none focus:border-foreground"
              />
              <button type="submit" disabled={busy} className="rounded border px-2 py-1 text-[11px] font-medium hover:bg-muted disabled:opacity-50">
                {busy ? "…" : "Run"}
              </button>
            </form>
            <div className="flex flex-wrap gap-1">
              {PRESETS.map((p) => (
                <button
                  key={p}
                  type="button"
                  className="rounded-full border px-2 py-0.5 text-[10px] text-muted-foreground hover:text-foreground"
                  onClick={() => setText(p)}
                >
                  {p.replace("what if ", "")}
                </button>
              ))}
            </div>
            {status && <p className="text-[10px] font-mono text-muted-foreground">{status}</p>}
            {path.length > 0 && (
              <div className="flex flex-wrap gap-1">
                {path.map((p) => (
                  <span
                    key={p.index}
                    className={`text-[9px] font-mono rounded px-1.5 py-0.5 border ${
                      p.ok ? "border-emerald-500/40 text-emerald-400" : "border-orange-500/60 text-orange-300"
                    }`}
                    title={p.title}
                  >
                    #{p.index}{p.ok ? "" : " ✕"}
                  </span>
                ))}
              </div>
            )}
            {fault && (
              <div className={`rounded border-l-2 pl-2 py-1.5 space-y-1.5 ${fault.color === "purple" ? "border-purple-500" : "border-orange-500"}`}>
                <p className="text-[10px] font-semibold uppercase tracking-wide text-orange-400">
                  Predicted fault · #{fault.index}
                </p>
                <p className="text-[12px] font-medium leading-snug">{fault.title}</p>
                <p className="text-[11px] leading-snug text-muted-foreground">{fault.explanation}</p>
                {fault.why && (
                  <p className="text-[10px] leading-snug">
                    <span className="font-semibold text-foreground">Why: </span>
                    {fault.why}
                  </p>
                )}
                {!!(fault.nodes && fault.nodes.length) && (
                  <div className="space-y-0.5">
                    <p className="text-[9px] uppercase tracking-wide text-muted-foreground">Failed nodes</p>
                    <div className="flex flex-wrap gap-1">
                      {fault.nodes.slice(0, 8).map((n) => {
                        const label = nodeLabel(repoId, n)
                        const gid = mapLegacyToGraphId(repoId, n)
                        return (
                          <button
                            key={n}
                            type="button"
                            className="rounded border border-orange-500/40 bg-orange-500/10 px-1.5 py-0.5 text-[10px] font-mono text-orange-200 hover:bg-orange-500/20"
                            title={n}
                            onClick={() => {
                              if (!gid) return
                              useGraphStore.getState().selectNode(repoId, gid)
                              const cur = useGraphStore.getState().repos[repoId]?.highlight
                              if (cur?.isolate) {
                                useGraphStore.getState().setHighlight(repoId, {
                                  ...cur,
                                  nodeIds: new Set([gid, ...cur.nodeIds]),
                                })
                              }
                            }}
                          >
                            {label}
                          </button>
                        )
                      })}
                    </div>
                  </div>
                )}
                {!!(fault.edges && fault.edges.length) && (
                  <div className="space-y-0.5">
                    <p className="text-[9px] uppercase tracking-wide text-muted-foreground">Cause edges</p>
                    {fault.edges.slice(0, 5).map((e, i) => {
                      const s = mapLegacyToGraphId(repoId, e.source)
                      const t = mapLegacyToGraphId(repoId, e.target)
                      const key = s && t ? `${s}::${t}::${e.type || ""}` : null
                      return (
                        <button
                          key={i}
                          type="button"
                          className="block w-full text-left rounded border border-border/60 px-1.5 py-1 hover:bg-muted/40"
                          onClick={() => {
                            if (!key) return
                            useGraphStore.getState().selectEdge(repoId, key)
                          }}
                        >
                          <p className="text-[10px] font-mono">
                            <span className="text-orange-300">{e.type || "EDGE"}</span>{" "}
                            {nodeLabel(repoId, e.source)} → {nodeLabel(repoId, e.target)}
                          </p>
                          <p className="text-[9px] text-muted-foreground truncate">
                            {e.cause || (e.file ? `${e.file}${e.line != null ? `:${e.line}` : ""}` : "measured dependency")}
                          </p>
                        </button>
                      )
                    })}
                  </div>
                )}
                {fault.missing_titles && (
                  <p className="text-[10px] font-mono text-muted-foreground">
                    missing prereq: {fault.missing_titles.join(", ")}
                  </p>
                )}
                {(fault.cyber || []).slice(0, 3).map((c, i) => (
                  <p key={i} className="text-[10px] text-muted-foreground">
                    <span className={c.color === "purple" ? "text-purple-400" : "text-orange-400"}>●</span>{" "}
                    {c.title}
                  </p>
                ))}
              </div>
            )}
            <button
              type="button"
              className="text-[10px] text-muted-foreground hover:text-foreground"
              onClick={() => {
                stopRef.current = true
                useGraphStore.getState().resetPlayback(repoId)
                useGraphStore.getState().setHighlight(repoId, null)
                useGraphStore.getState().selectNode(repoId, null)
                useGraphStore.getState().selectEdge(repoId, null)
                setFault(null)
                setPath([])
                setStatus("")
              }}
            >
              Reset graph
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
