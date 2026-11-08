"use client"

import { useEffect, useMemo, useState } from "react"
import { useParams } from "next/navigation"
import Link from "next/link"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { useGraphStore } from "@/store/graph-store"

type Doc = { title?: string; url?: string; passage?: string; source?: string }
type Vuln = { risk?: string; evidence?: string; fix?: string }
type WaveStep = {
  id: string
  title: string
  stack_title?: string
  detail?: string
  why_now?: string
  why?: string
  claim?: string
  deps_before?: Record<string, number>
  deps_after?: Record<string, number>
  legacy_remaining?: number
  risk_before?: number
  risk_after?: number
  cut_count?: number
  removals?: { type?: string; file?: string; line?: number; reason?: string; source?: string; target?: string }[]
  vulns?: Vuln[]
  docs?: Doc[]
  engineer_prompt?: string
}

function sum(m?: Record<string, number>) {
  return Object.values(m || {}).reduce((a, b) => a + b, 0)
}

function host(u?: string) {
  try { return new URL(u || "").hostname.replace(/^www\./, "") } catch { return "" }
}

export default function MigrationPage() {
  const { repo } = useParams<{ repo: string }>()
  const [waves, setWaves] = useState<WaveStep[]>([])
  const [curve, setCurve] = useState<{ legacy_dependencies: number }[]>([])
  const [active, setActive] = useState(0)
  const [error, setError] = useState("")
  const [planned, setPlanned] = useState<boolean | null>(null)

  useEffect(() => {
    fetch(`/api/repos/${repo}/waves`)
      .then(async (r) => {
        if (!r.ok) throw new Error(await r.text())
        return r.json()
      })
      .then((body) => {
        setWaves(body.steps || [])
        setCurve(body.curve || [])
        setPlanned(body.planned !== false && (body.steps || []).length > 0)
      })
      .catch((e) => setError(String(e?.message || e)))
  }, [repo])

  const series = useMemo(() => {
    if (curve.length) return curve.map((c) => c.legacy_dependencies)
    return waves.map((w) => w.legacy_remaining ?? sum(w.deps_after))
  }, [curve, waves])

  const maxDep = Math.max(...series, 1)
  const step = waves[active]

  if (error) {
    return (
      <div className="p-6 space-y-3">
        <p className="text-sm">{error}</p>
        <Button asChild variant="outline"><Link href={`/${repo}`}>Back to Explore</Link></Button>
      </div>
    )
  }

  if (planned === null) {
    return <p className="p-6 text-sm text-muted-foreground">Loading migration theater…</p>
  }

  if (!planned || !waves.length) {
    return (
      <div className="p-6 space-y-3 max-w-lg">
        <h1 className="text-lg font-semibold">Migration theater</h1>
        <p className="text-sm text-muted-foreground leading-relaxed">
          No steps yet — open Explore → Migrate, enter a target (e.g. Azure SQL), and press Plan.
          Theater fills from that planned wave list.
        </p>
        <Button asChild variant="outline"><Link href={`/${repo}`}>Back to Explore</Link></Button>
      </div>
    )
  }

  return (
    <div className="p-6 space-y-5 max-w-6xl">
      <div className="flex flex-wrap items-center gap-2">
        <h1 className="text-lg font-semibold mr-2">Migration theater</h1>
        <Badge>graph surgery</Badge>
        <Badge variant="outline">{waves.length} cuts → 0 edges</Badge>
        <Button asChild size="sm" variant="ghost"><Link href={`/${repo}`}>Play on graph</Link></Button>
        <Button asChild size="sm" variant="ghost"><Link href={`/${repo}/swarm`}>Workflow</Link></Button>
        <Button size="sm" variant="outline" onClick={() => window.open(`/api/repos/${repo}/report.pdf`)}>PDF</Button>
      </div>

      <p className="text-sm text-muted-foreground max-w-2xl">
        Each step is a measured edge cut with file:line evidence — not a Java dump. Orange/purple cyber risks only light when that cut creates an API or transit boundary.
      </p>

      {/* Dependency collapse curve */}
      <div className="border rounded-md p-4 space-y-3">
        <div className="flex items-baseline gap-2">
          <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Legacy deps</p>
          <span className="font-mono text-sm">{series[0] ?? "—"} → {series[series.length - 1] ?? 0}</span>
        </div>
        <div className="flex items-end gap-0.5 h-28">
          {series.map((v, i) => (
            <button
              key={i}
              type="button"
              title={`step ${i + 1}: ${v}`}
              onClick={() => setActive(Math.min(i, waves.length - 1))}
              className={`flex-1 min-w-[4px] rounded-t transition-colors ${i === active ? "bg-sky-400" : "bg-sky-500/40 hover:bg-sky-500/70"}`}
              style={{ height: `${Math.max(4, (v / maxDep) * 100)}%` }}
            />
          ))}
        </div>
        <p className="text-[10px] text-muted-foreground font-mono">click a bar → inspect that cut</p>
      </div>

      <div className="grid lg:grid-cols-[220px_1fr] gap-4">
        <div className="border rounded-md max-h-[560px] overflow-auto divide-y">
          {waves.map((w, i) => (
            <button
              key={w.id}
              type="button"
              onClick={() => setActive(i)}
              className={`w-full text-left px-3 py-2 hover:bg-muted/40 ${i === active ? "bg-muted/60" : ""}`}
            >
              <div className="flex items-center gap-2 text-[11px]">
                <span className="font-mono text-muted-foreground">{i + 1}</span>
                <span className="font-medium truncate">{w.stack_title || w.title}</span>
              </div>
              <p className="text-[10px] font-mono text-muted-foreground mt-0.5">
                −{w.cut_count ?? (w.removals || []).length} edges · {sum(w.deps_before)}→{sum(w.deps_after)}
              </p>
            </button>
          ))}
        </div>

        {step && (
          <div className="border rounded-md p-4 space-y-4 min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant="outline">#{active + 1}</Badge>
              <h2 className="text-base font-semibold">{step.stack_title || step.title}</h2>
              <Badge variant="outline">{step.claim || "Predicted"}</Badge>
              <Button
                size="sm"
                className="ml-auto"
                onClick={() => {
                  useGraphStore.getState().setEdgeTypeFilter(repo, "All")
                  window.location.href = `/${repo}`
                }}
              >
                Scrub on graph
              </Button>
            </div>

            <div className="space-y-1">
              <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">Why this cut</p>
              <p className="text-sm leading-snug">{step.why_now || step.why || step.detail}</p>
            </div>

            <div className="grid sm:grid-cols-3 gap-2 text-center">
              <div className="rounded-md border p-2">
                <p className="text-[10px] text-muted-foreground">edges cut</p>
                <p className="text-lg font-mono">{step.cut_count ?? (step.removals || []).length}</p>
              </div>
              <div className="rounded-md border p-2">
                <p className="text-[10px] text-muted-foreground">deps</p>
                <p className="text-lg font-mono">{sum(step.deps_before)}→{sum(step.deps_after)}</p>
              </div>
              <div className="rounded-md border p-2">
                <p className="text-[10px] text-muted-foreground">risk</p>
                <p className="text-lg font-mono">{step.risk_before ?? "—"}→{step.risk_after ?? "—"}</p>
              </div>
            </div>

            {(step.removals || []).length > 0 && (
              <div className="space-y-1">
                <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">Measured cuts</p>
                <div className="max-h-36 overflow-auto space-y-1">
                  {(step.removals || []).slice(0, 12).map((r, i) => (
                    <p key={i} className="text-[11px] font-mono truncate">
                      <span className="text-red-400">−{r.type}</span> {r.source}→{r.target} · {r.file}:{r.line}
                    </p>
                  ))}
                </div>
              </div>
            )}

            {(step.vulns || []).length > 0 && (
              <div className="space-y-1.5">
                <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">Modernization vulns</p>
                {(step.vulns || []).slice(0, 4).map((v, i) => (
                  <div key={i} className="rounded-md border-l-2 border-orange-500 pl-2.5 py-1">
                    <p className="text-[12px] font-medium leading-snug">{v.risk}</p>
                    <p className="text-[10px] font-mono text-muted-foreground">{v.evidence}</p>
                  </div>
                ))}
              </div>
            )}

            {(step.docs || []).length > 0 && (
              <div className="space-y-1.5">
                <p className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">Why the agent chose this — sources</p>
                {(step.docs || []).map((d, i) => (
                  <a key={i} href={d.url} target="_blank" rel="noreferrer" className="block rounded-md border p-2.5 hover:bg-muted/40">
                    <p className="text-[12px] font-medium">{d.title}</p>
                    <p className="text-[10px] text-muted-foreground">{host(d.url)} ↗</p>
                    {d.passage && <p className="mt-1 text-[11px] italic leading-snug">“{d.passage}”</p>}
                  </a>
                ))}
              </div>
            )}

            {step.engineer_prompt && (
              <details className="text-[11px]">
                <summary className="cursor-pointer text-muted-foreground">Example prompt for another coding agent</summary>
                <pre className="mt-2 whitespace-pre-wrap rounded bg-muted/50 p-2 font-mono">{step.engineer_prompt}</pre>
              </details>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
