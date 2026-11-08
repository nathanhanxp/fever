"use client"

import { useEffect, useMemo, useState } from "react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { useGraphStore } from "@/store/graph-store"

type WaveStep = {
  id: string
  index?: number
  title: string
  detail?: string
  claim?: string
  deps_before?: Record<string, number>
  deps_after?: Record<string, number>
  legacy_remaining?: number
  risk_before?: number
  risk_after?: number
  removals?: { type?: string; file?: string; line?: number; reason?: string; source?: string; target?: string }[]
  requires?: { step_id: string; because?: string }[]
  unblocks?: string[]
}

type Impact = {
  changed: string[]
  ripple: string[]
  removed_edges?: { source: string; target: string; type?: string }[]
  added_edges?: { source: string; target: string; type?: string }[]
  deps_before?: Record<string, number>
  deps_after?: Record<string, number>
  risk_before?: number
  risk_after?: number
  title?: string
  detail?: string
  claim?: string
}

function tally(map?: Record<string, number>) {
  if (!map) return 0
  return Object.values(map).reduce((a, b) => a + b, 0)
}

function applyImpact(repoId: string, impact: Impact) {
  const data = useGraphStore.getState().repos[repoId]?.data
  if (!data) return
  const match = (raw: string) => {
    const short = raw.includes(":") ? raw.split(":").slice(1).join(":") : raw
    return data.nodes.find(
      (n) => n.id === raw || n.qualname === raw || n.symbol_name === raw || n.qualname === short || n.symbol_name === short,
    )?.id
  }
  const nodeIds = new Set<string>()
  const edgeKeys = new Set<string>()
  for (const id of impact.changed || []) {
    const mapped = match(id)
    if (mapped) nodeIds.add(mapped)
  }
  for (const id of impact.ripple || []) {
    const mapped = match(id)
    if (mapped) nodeIds.add(mapped)
  }
  for (const e of impact.removed_edges || []) {
    const s = match(e.source)
    const t = match(e.target)
    if (s && t) {
      nodeIds.add(s)
      nodeIds.add(t)
      edgeKeys.add(`${s}::${t}::${e.type || "FILE"}`)
    }
  }
  for (const e of impact.added_edges || []) {
    const s = match(e.source)
    const t = match(e.target)
    if (s && t) {
      nodeIds.add(s)
      nodeIds.add(t)
      edgeKeys.add(`${s}::${t}::${e.type || "FILE"}`)
    }
  }
  useGraphStore.getState().setHighlight(repoId, { source: "impact", nodeIds, edgeKeys })
  useGraphStore.getState().setEdgeTypeFilter(repoId, "All")
}

export function RoadmapScrubber({ repoId }: { repoId: string }) {
  const [steps, setSteps] = useState<WaveStep[]>([])
  const [curve, setCurve] = useState<{ step: number; legacy_dependencies: number; title?: string }[]>([])
  const [claim, setClaim] = useState("Predicted")
  const [index, setIndex] = useState(0)
  const [impact, setImpact] = useState<Impact | null>(null)
  const [error, setError] = useState("")
  const [playing, setPlaying] = useState(false)

  useEffect(() => {
    let alive = true
    fetch(`/api/repos/${repoId}/waves`)
      .then(async (r) => {
        if (!r.ok) throw new Error(await r.text())
        return r.json()
      })
      .then((body) => {
        if (!alive) return
        setSteps(body.steps || [])
        setCurve(body.curve || [])
        setClaim(body.claim || "Predicted")
        setError("")
      })
      .catch((err) => {
        if (!alive) return
        setError(typeof err?.message === "string" ? err.message : "No roadmap yet")
        setSteps([])
      })
    return () => { alive = false }
  }, [repoId])

  useEffect(() => {
    if (!steps.length) return
    const step = steps[Math.min(index, steps.length - 1)]
    if (!step) return
    let alive = true
    fetch(`/api/repos/${repoId}/waves/${step.id}/impact`)
      .then((r) => r.json())
      .then((body: Impact) => {
        if (!alive) return
        setImpact(body)
        applyImpact(repoId, body)
      })
      .catch(() => {})
    return () => { alive = false }
  }, [repoId, steps, index])

  useEffect(() => {
    if (!playing || !steps.length) return
    const timer = setInterval(() => {
      setIndex((i) => {
        if (i >= steps.length - 1) {
          setPlaying(false)
          return i
        }
        return i + 1
      })
    }, 1400)
    return () => clearInterval(timer)
  }, [playing, steps.length])

  const step = steps[index]
  const before = impact?.deps_before || step?.deps_before
  const after = impact?.deps_after || step?.deps_after
  const removedCount = useMemo(() => Math.max(0, tally(before) - tally(after)), [before, after])

  if (error && !steps.length) {
    return (
      <div className="absolute bottom-3 left-3 right-3 z-10 rounded-md border bg-background/90 backdrop-blur px-3 py-2 text-[11px] text-muted-foreground">
        Roadmap unavailable — open CardDemo or upload a zip first. {error.slice(0, 120)}
      </div>
    )
  }
  if (!steps.length) return null

  return (
    <div className="absolute bottom-3 left-3 right-3 z-10 rounded-md border bg-background/95 backdrop-blur shadow-sm px-3 py-2 space-y-2">
      <div className="flex items-center gap-2 flex-wrap">
        <Badge variant="outline" className="text-[10px]">Roadmap · {claim}</Badge>
        <Badge variant="outline" className="text-[10px]">Step {index + 1}/{steps.length}</Badge>
        {removedCount > 0 && (
          <Badge className="text-[10px]">−{removedCount} legacy deps</Badge>
        )}
        <div className="flex-1" />
        <Button size="sm" variant="ghost" className="h-6 text-[10px]" onClick={() => setIndex(0)}>Reset</Button>
        <Button size="sm" variant="outline" className="h-6 text-[10px]" onClick={() => setPlaying((p) => !p)}>
          {playing ? "Pause" : "Play waves"}
        </Button>
      </div>
      <input
        type="range"
        min={0}
        max={Math.max(0, steps.length - 1)}
        value={index}
        onChange={(e) => { setPlaying(false); setIndex(Number(e.target.value)) }}
        className="w-full accent-foreground"
      />
      <div className="grid grid-cols-1 md:grid-cols-[1.4fr_1fr] gap-2 text-[11px]">
        <div className="space-y-1 min-w-0">
          <p className="font-medium truncate">{step?.title}</p>
          <p className="text-muted-foreground line-clamp-2">{impact?.detail || step?.detail}</p>
          {(step?.removals || []).slice(0, 3).map((r, i) => (
            <p key={i} className="text-muted-foreground truncate">
              retire {r.type} {r.file}:{r.line} — {r.reason || "graph transformation"}
            </p>
          ))}
        </div>
        <div className="space-y-1 font-mono tabular-nums">
          <p>before {tally(before)} → after {tally(after)} deps</p>
          <p>risk {(impact?.risk_before ?? step?.risk_before ?? 0).toFixed?.(3) ?? impact?.risk_before} → {(impact?.risk_after ?? step?.risk_after ?? 0).toFixed?.(3) ?? impact?.risk_after}</p>
          {curve.length > 0 && (
            <p className="text-muted-foreground">
              curve: {curve.map((c) => c.legacy_dependencies).join(" → ")}
            </p>
          )}
          {(step?.requires || []).slice(0, 2).map((r, i) => (
            <p key={i} className="text-muted-foreground">requires {r.step_id}</p>
          ))}
        </div>
      </div>
    </div>
  )
}
