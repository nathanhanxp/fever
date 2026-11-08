"use client"

import { useCallback, useEffect, useRef, useState } from "react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { useGraphStore } from "@/store/graph-store"
type Wave = {
  id: string
  title: string
  detail?: string
  deps_before?: Record<string, number>
  deps_after?: Record<string, number>
  risk_before?: number
  risk_after?: number
  engineer_prompt?: string
  why_now?: string
  vulns?: { risk?: string; evidence?: string; fix?: string }[]
}

type PlayResult = {
  ok: boolean
  title?: string
  detail?: string
  engineer_prompt?: string
  missing?: string[]
  retire_nodes?: string[]
  removed_edges?: { source: string; target: string; type?: string }[]
  retire_all?: boolean
  agents?: {
    coordinator?: { allowed?: boolean; missing_prereqs?: string[]; model?: string; reason?: string; role?: string }
    analyst?: { risk_before?: number; risk_after?: number; deps_before?: Record<string, number>; deps_after?: Record<string, number>; model?: string; role?: string; delta?: string }
    prover?: { rejected?: boolean; reason?: string; model?: string; role?: string }
  }
  cyber_on_step?: { color?: string; title?: string; detail?: string; node_id?: string }[]
  sources?: { title?: string; source?: string; url?: string; passage?: string }[]
  ribbon?: { risk_before?: number; risk_after?: number; deps_before?: number; deps_after?: number }
}

type Stack = {
  description?: string
  language?: string
  framework?: string
  database?: string
  api?: string
  runtime?: string
  scheduler?: string
}

const PRESETS: { label: string; sub: string; stack: Stack }[] = [
  {
    label: "Java · Spring · Postgres",
    sub: "COBOL → Spring Boot + PostgreSQL",
    stack: { language: "Java 21", framework: "Spring Boot", database: "PostgreSQL", api: "REST", runtime: "containers", scheduler: "workflow scheduler" },
  },
  {
    label: "Kotlin · Quarkus · Postgres",
    sub: "COBOL → Quarkus services",
    stack: { language: "Kotlin", framework: "Quarkus", database: "PostgreSQL", api: "REST", runtime: "containers", scheduler: "workflow scheduler" },
  },
  {
    label: ".NET · Azure SQL",
    sub: "COBOL → ASP.NET Core",
    stack: { language: "C#", framework: "ASP.NET Core", database: "Azure SQL", api: "REST", runtime: "containers", scheduler: "Azure Functions" },
  },
]

function sum(m?: Record<string, number>) {
  return Object.values(m || {}).reduce((a, b) => a + b, 0)
}

function mapLegacyToGraphId(repoId: string, raw: string): string | null {
  const data = useGraphStore.getState().repos[repoId]?.data
  if (!data || !raw) return null
  const short = raw.includes(":") ? raw.split(":").slice(1).join(":") : raw
  const upper = short.toUpperCase()
  return (
    data.nodes.find((n) => {
      if (n.id === raw || n.qualname === raw || n.symbol_name === raw) return true
      if (n.qualname === short || n.symbol_name === short) return true
      const q = (n.qualname || "").toUpperCase()
      const s = (n.symbol_name || "").toUpperCase()
      return q === upper || s === upper || q.endsWith(`:${upper}`) || q.endsWith(upper)
    })?.id ?? null
  )
}

const EMPTY_COMPLETED: string[] = []

export function MigratePanel({ repoId, active = true }: { repoId: string; active?: boolean }) {
  const [waves, setWaves] = useState<Wave[]>([])
  const [stack, setStack] = useState<Stack>({})
  const index = useGraphStore((s) => s.repos[repoId]?.migrateIndex ?? 0)
  const completed = useGraphStore((s) => s.repos[repoId]?.migrateCompleted ?? EMPTY_COMPLETED)
  const setIndex = (i: number) => useGraphStore.getState().setPlayback(repoId, { migrateIndex: i })
  const [play, setPlay] = useState<PlayResult | null>(null)
  const [busy, setBusy] = useState(false)
  const [planning, setPlanning] = useState(false)
  const [planNote, setPlanNote] = useState("")
  const [researchNote, setResearchNote] = useState("")
  const [error, setError] = useState("")
  const [target, setTarget] = useState("")
  const [cyberMap, setCyberMap] = useState<Record<string, string> | null>(null)

  const retiredNodeIds = useGraphStore((s) => s.repos[repoId]?.retiredNodeIds)
  const removedEdgeKeys = useGraphStore((s) => s.repos[repoId]?.removedEdgeKeys)
  const graphData = useGraphStore((s) => s.repos[repoId]?.data)
  const graphEpoch = useGraphStore((s) => s.repos[repoId]?.graphEpoch ?? 0)
  const totalEdges = graphData?.edges.length ?? 0
  const remainingEdges = (() => {
    if (!graphData) return 0
    const retired = retiredNodeIds || new Set<string>()
    const removed = removedEdgeKeys || new Set<string>()
    if (retired.size > 0 && retired.size >= (graphData.nodes?.length || 0)) return 0
    let n = 0
    for (const e of graphData.edges) {
      if (retired.has(e.source) || retired.has(e.target)) continue
      const key = `${e.source}::${e.target}::${e.edge_type}`
      if (removed.has(key) || removed.has(`${e.source}::${e.target}`)) continue
      n += 1
    }
    return n
  })()

  const [planned, setPlanned] = useState(false)

  const clearUi = useCallback(() => {
    setWaves([])
    setStack({})
    setPlay(null)
    setBusy(false)
    setPlanning(false)
    setPlanNote("")
    setResearchNote("")
    setError("")
    setTarget("")
    setCyberMap(null)
    setPlanned(false)
    useGraphStore.getState().resetPlayback(repoId)
    useGraphStore.getState().setPlayback(repoId, { migrateIndex: 0, migrateCompleted: [] })
  }, [repoId])

  const loadWaves = useCallback(async () => {
    const b = await fetch(`/api/repos/${repoId}/waves`).then((r) => r.json())
    const isPlanned = b.planned === true && Array.isArray(b.steps) && b.steps.length > 0
    setPlanned(isPlanned)
    const steps: Wave[] = isPlanned
      ? (b.steps || []).map((s: Wave & { stack_title?: string }) => ({ ...s, title: s.stack_title || s.title }))
      : []
    setWaves(steps)
    return steps
  }, [repoId])

  const load = useCallback(() => {
    // Always start blank on enter/switch — demo-friendly; Plan fills it again
    clearUi()
    fetch(`/api/repos/${repoId}/brief`)
      .then((r) => r.json())
      .then((b) => {
        setCyberMap(b.cyber_map || {})
      })
      .catch((e) => setError(String(e?.message || e)))
  }, [repoId, clearUi])

  useEffect(() => { load() }, [load])

  useEffect(() => {
    if (!graphData || !cyberMap) return
    const map: Record<string, "legacy" | "orange" | "purple" | null> = {}
    for (const [k, v] of Object.entries(cyberMap)) {
      const gid = mapLegacyToGraphId(repoId, k)
      if (gid) map[gid] = v === "red" ? "legacy" : (v as "orange" | "purple")
    }
    useGraphStore.getState().setPlayback(repoId, { cyberRisk: map })
  }, [graphData, cyberMap, repoId])

  const applyRetire = (result: PlayResult, stepId: string, opts?: { flashOnly?: boolean }) => {
    const repo = useGraphStore.getState().repos[repoId]
    const data = repo?.data
    if (!data) return
    const retired = new Set(repo?.retiredNodeIds || [])
    const removed = new Set(repo?.removedEdgeKeys || [])
    const wasRetired = new Set(retired)
    const wasRemoved = new Set(removed)
    const flashing = new Set<string>()
    // Fresh glow every step — previous step's glow is fully cleared
    const glowEdges = new Set<string>()
    const glowNodes = new Set<string>()
    const cyberGlow = new Set<string>()
    const cache = new Map<string, string | null>()
    const gid = (raw: string) => {
      if (!cache.has(raw)) cache.set(raw, mapLegacyToGraphId(repoId, raw))
      return cache.get(raw) ?? null
    }
    const cyber = { ...(repo?.cyberRisk || {}) }

    const stepRetired = new Set<string>()
    for (const raw of result.retire_nodes || []) {
      const id = gid(raw)
      if (id) stepRetired.add(id)
    }
    for (const r of result.cyber_on_step || []) {
      const id = r?.node_id ? gid(String(r.node_id)) : null
      if (!id) continue
      stepRetired.add(id)
      cyberGlow.add(id)
      if (r.color === "purple" || r.color === "orange") cyber[id] = r.color
    }
    // Only nodes newly retired THIS step drive the glow
    const newlyRetired = new Set<string>()
    for (const id of stepRetired) {
      if (!wasRetired.has(id)) newlyRetired.add(id)
    }

    const newPairs = new Set<string>()
    for (const e of result.removed_edges || []) {
      const s = gid(e.source)
      const t = gid(e.target)
      if (!s || !t) continue
      const key = `${s}::${t}::${e.type || ""}`
      const pair = `${s}::${t}`
      if (!wasRemoved.has(key) && !wasRemoved.has(pair)) {
        newPairs.add(pair)
        newPairs.add(`${t}::${s}`)
      }
    }

    const light = (ge: { source: string; target: string; edge_type: string }) => {
      const key = `${ge.source}::${ge.target}::${ge.edge_type}`
      const pair = `${ge.source}::${ge.target}`
      const hit =
        newlyRetired.has(ge.source) ||
        newlyRetired.has(ge.target) ||
        newPairs.has(pair)
      if (!hit) return false
      glowEdges.add(key)
      glowNodes.add(ge.source)
      glowNodes.add(ge.target)
      if (opts?.flashOnly) flashing.add(key)
      return true
    }

    if (result.retire_all && !opts?.flashOnly) {
      for (const n of data.nodes) {
        retired.add(n.id)
        glowNodes.add(n.id)
      }
      for (const ge of data.edges) {
        const key = `${ge.source}::${ge.target}::${ge.edge_type}`
        glowEdges.add(key)
        removed.add(key)
        removed.add(`${ge.source}::${ge.target}`)
      }
    } else {
      for (const id of newlyRetired) glowNodes.add(id)
      if (!opts?.flashOnly) for (const id of stepRetired) retired.add(id)

      for (const ge of data.edges) {
        light(ge)
        if (opts?.flashOnly) continue
        // Persist cuts: this step's lit edges + anything touching any retired node
        const key = `${ge.source}::${ge.target}::${ge.edge_type}`
        if (
          glowEdges.has(key) ||
          retired.has(ge.source) ||
          retired.has(ge.target)
        ) {
          removed.add(key)
          removed.add(`${ge.source}::${ge.target}`)
        }
      }
    }

    useGraphStore.getState().setPlayback(repoId, {
      retiredNodeIds: retired,
      removedEdgeKeys: removed,
      flashingEdgeKeys: flashing,
      glowEdgeKeys: glowEdges,
      glowNodeIds: glowNodes,
      cyberGlowNodeIds: cyberGlow,
      cyberRisk: cyber,
      playbackStepId: stepId,
    })
  }

  const completedRef = useRef<string[]>(completed)
  const stopRef = useRef(false)
  const [autoplay, setAutoplay] = useState(false)
  const restoringRef = useRef(false)

  useEffect(() => { completedRef.current = completed }, [completed])

  const setDone = (ids: string[]) => {
    completedRef.current = ids
    useGraphStore.getState().setPlayback(repoId, { migrateCompleted: ids })
  }

  /** Rebuild graph cuts from completed steps when returning to Migrate / Explore */
  const restoreGraph = useCallback(async (steps: Wave[], done: string[], force = false) => {
    if (!done.length || restoringRef.current) return
    const repo = useGraphStore.getState().repos[repoId]
    const hasCuts = (repo?.retiredNodeIds?.size || 0) > 0 || (repo?.removedEdgeKeys?.size || 0) > 0
    if (hasCuts && !force) return
    restoringRef.current = true
    try {
      useGraphStore.getState().setPlayback(repoId, {
        retiredNodeIds: new Set(),
        removedEdgeKeys: new Set(),
        flashingEdgeKeys: new Set(),
        glowEdgeKeys: new Set(),
        glowNodeIds: new Set(),
        cyberGlowNodeIds: new Set(),
      })
      const applied: string[] = []
      for (const id of done) {
        const res = await fetch(`/api/repos/${repoId}/waves/${id}/play`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ completed: applied }),
        })
        const body: PlayResult = await res.json()
        if (!body.ok) break
        applied.push(id)
        applyRetire(applied.length >= steps.length ? { ...body, retire_all: true } : body, id)
      }
      useGraphStore.getState().setPlayback(repoId, { glowEdgeKeys: new Set(), glowNodeIds: new Set(), cyberGlowNodeIds: new Set() })
    } finally {
      restoringRef.current = false
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [repoId])

  // When Migrate becomes active / Explore remounts / graph was cleared, rebuild cuts
  useEffect(() => {
    if (!active || !waves.length || !completed.length || !graphData) return
    const repo = useGraphStore.getState().repos[repoId]
    const hasCuts = (repo?.retiredNodeIds?.size || 0) > 0 || (repo?.removedEdgeKeys?.size || 0) > 0
    void restoreGraph(waves, completed, !hasCuts)
  }, [active, waves, completed, graphData, graphEpoch, restoreGraph, repoId])

  const pickStack = async (preset: Stack) => {
    stopRef.current = true
    setStack(preset)
    setPlanning(true)
    setError("")
    setPlay(null)
    setDone([])
    setIndex(0)
    useGraphStore.getState().resetPlayback(repoId)
    try {
      const res = await fetch(`/api/repos/${repoId}/stack`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(preset),
      })
      const body = await res.json()
      if (body.target_stack) {
        setStack(body.target_stack)
        setTarget(
          body.target_stack.description
            || [body.target_stack.language, body.target_stack.framework, body.target_stack.database].filter(Boolean).join(" · ")
            || target,
        )
      }
      const nem = body.nemotron || {}
      const research = body.research as { sources?: { title?: string; url?: string }[]; queries?: string[]; latency_s?: number } | undefined
      const nSrc = research?.sources?.length ?? nem.research_sources ?? 0
      const sample = (body.sample_titles as string[] | undefined)?.filter(Boolean) || []
      const rev = body.plan_revision as { rewritten?: number; fixture?: boolean } | undefined
      if (body.fixture) {
        setResearchNote(
          `Demo plan for ${body.label || "C# · ASP.NET · Azure SQL"} (${nSrc} sources · ~${research?.latency_s ?? "1.5"}s).`,
        )
      } else if (nSrc) {
        const titles = (research?.sources || []).slice(0, 3).map((s) => s.title || s.url).filter(Boolean)
        setResearchNote(
          `New live plan · ${body.label || "target"} (${nSrc} sources${research?.latency_s != null ? ` · ${research.latency_s}s` : ""})${
            titles.length ? `: ${titles.join(" · ")}` : ""
          }`,
        )
      } else {
        setResearchNote(`New plan · ${body.label || "target"} — web search empty, used repo evidence.`)
      }
      const guidance = nem.guidance ? String(nem.guidance) : ""
      const preview = sample.length ? `Steps now: ${sample.slice(0, 2).join(" · ")}` : ""
      setPlanNote([guidance, preview, rev?.rewritten ? `(${rev.rewritten} step titles retargeted)` : ""].filter(Boolean).join("\n"))
      if (nem.error) setError(String(nem.error))
      else if (!body.fixture && nem.status && nem.status !== "ok" && nem.status !== "skipped") {
        setError(`Planner ${nem.status} — retry Plan (need a live Nemotron answer for this target).`)
      }
      setPlanned(true)
      // Force-refresh steps so a prior target's titles/whys cannot stick in the UI
      setWaves([])
      setDone([])
      setIndex(0)
      await loadWaves()

    } catch (e) {
      setError(String((e as Error)?.message || e))
    } finally {
      setPlanning(false)
    }
  }

  const runStep = async (i: number): Promise<boolean> => {
    const target = waves[i]
    if (!target) return false
    const done = completedRef.current
    const res = await fetch(`/api/repos/${repoId}/waves/${target.id}/play`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ completed: done }),
    })
    const body: PlayResult = await res.json()
    setPlay(body)
    if (!body.ok || body.agents?.prover?.rejected) {
      applyRetire(body, target.id, { flashOnly: true })
      setIndex(i)
      return false
    }
    const next = done.includes(target.id) ? done : [...done, target.id]
    setDone(next)
    applyRetire(next.length >= waves.length ? { ...body, retire_all: true } : body, target.id)
    const after = waves.findIndex((w, j) => j > i && !next.includes(w.id))
    const first = waves.findIndex((w) => !next.includes(w.id))
    setIndex(after >= 0 ? after : first >= 0 ? first : i)
    return true
  }

  const playStep = async () => {
    setBusy(true)
    try {
      await runStep(index)
    } finally {
      setBusy(false)
    }
  }

  const playAll = async () => {
    stopRef.current = false
    setAutoplay(true)
    setBusy(true)
    try {
      for (let i = 0; i < waves.length && !stopRef.current; i++) {
        if (completedRef.current.includes(waves[i].id)) continue
        if (!(await runStep(i))) break
      }
    } finally {
      setBusy(false)
      setAutoplay(false)
    }
  }

  const reset = () => {
    stopRef.current = true
    setDone([])
    setIndex(0)
    setPlay(null)
    useGraphStore.getState().resetPlayback(repoId)
  }

  const jumpTo = (sid: string) => {
    const i = waves.findIndex((w) => w.id === sid)
    if (i >= 0) setIndex(i)
  }

  const step = waves[index]
  const ribbon = play?.ribbon || (play?.agents?.analyst
    ? {
        risk_before: play.agents.analyst.risk_before,
        risk_after: play.agents.analyst.risk_after,
        deps_before: sum(play.agents.analyst.deps_before),
        deps_after: sum(play.agents.analyst.deps_after),
      }
    : null)

  return (
    <div className="flex flex-col h-full overflow-auto">
      {/* 1. Target */}
      <section className="p-3 border-b space-y-2">
        <p className="text-[11px] font-semibold tracking-wide uppercase text-muted-foreground">1 · Migrate to</p>
        <form
          className="flex gap-1.5"
          onSubmit={(e) => {
            e.preventDefault()
            if (target.trim()) void pickStack({ description: target.trim() })
          }}
        >
          <input
            value={target}
            onChange={(e) => setTarget(e.target.value)}
            placeholder="e.g. Go + gRPC + CockroachDB on Kubernetes"
            className="flex-1 min-w-0 rounded-md border bg-transparent px-2.5 py-1.5 text-[13px] outline-none focus:border-foreground"
          />
          <Button type="submit" size="sm" className="h-8 text-[12px]" disabled={planning || !target.trim()}>Plan</Button>
        </form>
        <div className="flex flex-wrap gap-1.5">
          {PRESETS.map((p) => (
            <button
              key={p.label}
              type="button"
              disabled={planning}
              onClick={() => { setTarget(p.sub.replace("COBOL → ", "")); void pickStack(p.stack) }}
              className="rounded-full border px-2.5 py-1 text-[11px] text-muted-foreground hover:text-foreground hover:bg-muted/50"
            >
              {p.label}
            </button>
          ))}
        </div>
        {planning && (
          <p className="text-[12px] text-muted-foreground animate-pulse">
            Searching the web for how to modernize into your target, then Nemotron writes the steps…
          </p>
        )}
        {researchNote && !planning && planned && (
          <p className="text-[11px] text-muted-foreground leading-snug">{researchNote}</p>
        )}
        {planNote && !planning && planned && (
          <p className="text-[12px] leading-snug border rounded-md px-2.5 py-2 bg-muted/30 whitespace-pre-wrap">{planNote}</p>
        )}
        {(stack.language || stack.database) && planned && !planning && (
          <p className="text-[11px] text-muted-foreground font-mono">
            {[stack.language, stack.framework, stack.database, stack.api].filter(Boolean).join(" · ")}
          </p>
        )}
        {error && <p className="text-xs text-destructive">{error}</p>}
      </section>

      {/* 2. Play */}
      <section className="p-3 border-b space-y-2">
        <div className="flex items-center gap-2">
          <p className="text-[11px] font-semibold tracking-wide uppercase text-muted-foreground">2 · Play</p>
          <Badge variant="outline" className="text-[10px] font-mono">
            {planned ? `${completed.length}/${waves.length}` : "—"}
          </Badge>
          <Badge variant="outline" className="text-[10px] font-mono">
            edges {remainingEdges}
          </Badge>
          <div className="flex-1" />
          <Button
            size="sm"
            variant="ghost"
            className="h-7 text-[11px]"
            disabled={!waves.length}
            onClick={() => window.open(`/api/repos/${repoId}/report.pdf`, "_blank")}
          >
            Export PDF
          </Button>
          <Button size="sm" variant="ghost" className="h-7 text-[11px]" onClick={reset}>Reset</Button>
        </div>
        {!planned && !planning && (
          <p className="text-[12px] text-muted-foreground leading-snug rounded-md border border-dashed px-2.5 py-3">
            Graph is Measured. Steps appear after you choose a target above and press <span className="font-medium text-foreground">Plan</span>
            — e.g. type <span className="font-mono text-foreground">Azure SQL</span> or pick a preset.
          </p>
        )}

        <div className="flex gap-1.5">
          <Button size="sm" className="h-8 flex-1 text-[12px]" disabled={!planned || busy || !step || planning || completed.length >= waves.length} onClick={() => void playStep()}>
            {busy && !autoplay ? "Agents…" : `Play step ${step ? index + 1 : ""}`}
          </Button>
          {autoplay ? (
            <Button size="sm" variant="outline" className="h-8 text-[12px]" onClick={() => { stopRef.current = true }}>
              Stop
            </Button>
          ) : (
            <Button size="sm" variant="outline" className="h-8 text-[12px]" disabled={!planned || busy || planning || completed.length >= waves.length} onClick={() => void playAll()}>
              Play all
            </Button>
          )}
        </div>

        {play?.missing && play.missing.length > 0 && (
          <div className="flex flex-wrap items-center gap-1.5 text-[11px] rounded-md border border-destructive/60 px-2.5 py-2">
            <span className="text-destructive font-medium">Prover blocked · needs</span>
            {play.missing.map((m) => {
              const i = waves.findIndex((w) => w.id === m)
              return (
                <button key={m} type="button" className="rounded border px-1.5 py-0.5 font-mono hover:bg-muted" onClick={() => jumpTo(m)}>
                  step {i + 1}
                </button>
              )
            })}
          </div>
        )}

        {ribbon && (
          <div className="flex gap-2 text-[11px] font-mono">
            <span className="rounded border px-2 py-1">risk {ribbon.risk_before}→{ribbon.risk_after}</span>
            <span className="rounded border px-2 py-1">deps {ribbon.deps_before}→{ribbon.deps_after}</span>
          </div>
        )}

        {step ? (
          <div className="space-y-1.5">
            <p className="text-[13px] font-medium leading-snug">{index + 1}. {step.title}</p>
            <p className="text-[11px] text-muted-foreground leading-snug">{step.why_now || step.detail}</p>
            {(step.vulns || []).map((v, i) => (
              <div key={i} className="text-[11px] leading-snug border-l-2 border-red-500 pl-2">
                <p>{v.risk}</p>
                <p className="text-muted-foreground font-mono text-[10px]">{v.evidence}</p>
              </div>
            ))}
            {step.engineer_prompt && (
              <details className="text-[11px]">
                <summary className="cursor-pointer text-muted-foreground">Prompt for a coding agent</summary>
                <p className="font-mono mt-1 rounded bg-muted/50 px-2 py-1.5 whitespace-pre-wrap">{step.engineer_prompt}</p>
              </details>
            )}
          </div>
        ) : (
          <p className="text-[12px] text-muted-foreground">Pick a target — Nemotron builds the step list.</p>
        )}

        {remainingEdges === 0 && totalEdges > 0 && (
          <p className="text-[12px] text-emerald-500 font-medium">Cutover complete · 0 edges left</p>
        )}
      </section>

      {/* 3. Agents this step */}
      {play && (
        <section className="p-3 border-b space-y-2">
          <p className="text-[11px] font-semibold tracking-wide uppercase text-muted-foreground">3 · Agents (this step)</p>
          <div className="grid gap-1.5">
            {[
              { key: "coordinator", a: play.agents?.coordinator, tip: "Sequencing" },
              { key: "prover", a: play.agents?.prover, tip: "Gate" },
            ].map(({ key, a, tip }) => (
              a ? (
                <div key={key} className={`rounded-md border px-2.5 py-2 ${("rejected" in a && a.rejected) ? "border-destructive/60" : ""}`}>
                  <div className="flex items-baseline gap-2">
                    <p className="text-[12px] font-medium">{tip}</p>
                  </div>
                  <p className="text-[11px] text-muted-foreground mt-0.5 line-clamp-2">
                    {"reason" in a ? a.reason : ("delta" in a ? a.delta : a.role)}
                  </p>
                </div>
              ) : null
            ))}
          </div>
          {(play.cyber_on_step || []).slice(0, 2).map((c, i) => (
            <div key={i} className="text-[11px] rounded-md border border-orange-500/40 px-2.5 py-2 space-y-0.5">
              <p>
                <span className={c.color === "purple" ? "text-purple-400" : "text-orange-400"}>●</span>{" "}
                <span className="font-medium">{c.title}</span>
              </p>
              {c.detail && <p className="text-muted-foreground leading-snug">{c.detail}</p>}
            </div>
          ))}
          {(play.sources || []).slice(0, 3).map((d, i) => (
            <a
              key={i}
              href={d.url}
              target="_blank"
              rel="noreferrer"
              className="block rounded-md border px-2.5 py-2 hover:bg-muted/40"
            >
              <p className="text-[11px] font-medium leading-snug">{d.title}</p>
              <p className="text-[9px] text-muted-foreground break-all">{d.url}</p>
              {d.passage && <p className="mt-0.5 text-[10px] italic text-muted-foreground line-clamp-2">“{d.passage}”</p>}
            </a>
          ))}
        </section>
      )}

      {/* Step list — compact */}
      {waves.length > 0 && (
        <ul className="p-3 space-y-1 pb-6">
          {waves.map((w, i) => (
            <li key={w.id}>
              <button
                type="button"
                className={`w-full text-left text-[11px] rounded px-2 py-1.5 ${
                  i === index ? "bg-muted font-medium" : "text-muted-foreground hover:text-foreground"
                } ${completed.includes(w.id) ? "line-through opacity-50" : ""}`}
                onClick={() => setIndex(i)}
              >
                {i + 1}. {w.title}
                {w.engineer_prompt && <span className="ml-1 text-[9px] text-emerald-500">●</span>}
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
