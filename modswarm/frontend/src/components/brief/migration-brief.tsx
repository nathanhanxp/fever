"use client"

import { useEffect, useState } from "react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { useGraphStore } from "@/store/graph-store"
import { highlightNode } from "@/lib/graph-utils"

type Brief = {
  business_summary?: string
  migrating_to?: {
    language?: string
    framework?: string
    database?: string
    api?: string
    runtime?: string
    scheduler?: string
    components?: { name?: string; lens?: string; stack_hint?: string }[]
  }
  inventory?: Record<string, number>
  hidden_deficits?: {
    id?: string
    title?: string
    severity?: string
    claim?: string
    file?: string
    line?: number
    business?: string
  }[]
  hub_risks?: {
    id?: string
    name?: string
    kind?: string
    programs_touched?: number
    why_it_matters?: string
    file?: string
  }[]
  first_waves?: {
    id?: string
    title?: string
    removes?: number
    unlocks?: number
    business?: string
    risk_before?: number
    risk_after?: number
  }[]
  counts?: Record<string, number>
  label?: string
}

function focusQualname(repoId: string, qualname: string) {
  const data = useGraphStore.getState().repos[repoId]?.data
  if (!data) return
  const short = qualname.includes(":") ? qualname.split(":").slice(1).join(":") : qualname
  const node = data.nodes.find(
    (n) => n.qualname === qualname || n.symbol_name === qualname || n.qualname === short || n.symbol_name === short || n.id === qualname,
  )
  if (!node) return
  useGraphStore.getState().selectNode(repoId, node.id)
  useGraphStore.getState().setHighlight(repoId, highlightNode(data, node.id, 1))
}

export function MigrationBrief({ repoId, onAsk }: { repoId: string; onAsk?: (q: string) => void }) {
  const [brief, setBrief] = useState<Brief | null>(null)
  const [err, setErr] = useState("")

  useEffect(() => {
    let alive = true
    fetch(`/api/repos/${repoId}/brief`)
      .then(async (r) => {
        if (!r.ok) throw new Error(await r.text())
        return r.json()
      })
      .then((b) => { if (alive) { setBrief(b); setErr("") } })
      .catch((e) => { if (alive) setErr(e?.message || "Brief unavailable") })
    return () => { alive = false }
  }, [repoId])

  if (err && !brief) {
    return <p className="p-4 text-xs text-muted-foreground">{err}</p>
  }
  if (!brief) {
    return <p className="p-4 text-xs text-muted-foreground">Building your migration brief…</p>
  }

  const to = brief.migrating_to || {}
  const inv = brief.inventory || {}
  const counts = brief.counts || {}

  return (
    <div className="flex flex-col gap-4 p-4 text-sm overflow-auto h-full">
      <section className="space-y-2">
        <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Migrating to</p>
        <div className="grid grid-cols-2 gap-2">
          {[
            ["Language", to.language],
            ["App stack", to.framework],
            ["Data", to.database],
            ["API", to.api],
            ["Runtime", to.runtime],
            ["Batch", to.scheduler],
          ].map(([k, v]) => (
            <div key={k} className="rounded-md border px-2.5 py-2">
              <p className="text-[10px] text-muted-foreground">{k}</p>
              <p className="font-medium text-[13px] leading-tight">{v || "—"}</p>
            </div>
          ))}
        </div>
        <div className="flex flex-wrap gap-1.5 pt-1">
          {(to.components || []).slice(0, 8).map((c) => (
            <Badge key={`${c.lens}-${c.name}`} variant="outline" className="text-[10px]">
              {c.name}
            </Badge>
          ))}
        </div>
      </section>

      <section className="space-y-1.5">
        <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">What moves</p>
        <div className="flex flex-wrap gap-2 text-xs">
          <Badge variant="secondary">{inv.programs ?? 0} programs</Badge>
          <Badge variant="secondary">{inv.copybooks ?? 0} copybooks</Badge>
          <Badge variant="secondary">{inv.jobs ?? 0} jobs</Badge>
          <Badge variant="secondary">{inv.screens ?? 0} screens</Badge>
          <Badge variant="secondary">{inv.legacy_edges ?? 0} deps</Badge>
        </div>
        <p className="text-xs text-muted-foreground leading-relaxed">{brief.business_summary}</p>
      </section>

      <section className="space-y-2">
        <div className="flex items-center gap-2">
          <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Hidden deficits</p>
          <Badge variant="outline" className="text-[10px]">{counts.security_issues ?? 0} security</Badge>
          <Badge variant="outline" className="text-[10px]">{counts.quality_issues ?? 0} quality</Badge>
        </div>
        <ul className="space-y-2">
          {(brief.hidden_deficits || []).slice(0, 6).map((d) => (
            <li key={d.id || d.title} className="rounded-md border px-2.5 py-2 space-y-1">
              <div className="flex items-center gap-2">
                <Badge className="text-[10px] capitalize" variant={d.severity === "high" || d.severity === "critical" ? "destructive" : "outline"}>
                  {d.severity}
                </Badge>
                <span className="text-[10px] text-muted-foreground">{d.claim}</span>
              </div>
              <p className="font-medium text-[13px] leading-snug">{d.title}</p>
              <p className="text-xs text-muted-foreground leading-snug">{d.business}</p>
              {d.file && (
                <button
                  type="button"
                  className="text-[11px] text-foreground/80 underline-offset-2 hover:underline"
                  onClick={() => onAsk?.(`Show evidence for ${d.title} in ${d.file}:${d.line}`)}
                >
                  {d.file}:{d.line}
                </button>
              )}
            </li>
          ))}
          {!brief.hidden_deficits?.length && (
            <li className="text-xs text-muted-foreground">No accepted deficits yet.</li>
          )}
        </ul>
      </section>

      <section className="space-y-2">
        <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Business blast radius</p>
        <ul className="space-y-2">
          {(brief.hub_risks || []).slice(0, 5).map((h) => (
            <li key={h.id} className="rounded-md border px-2.5 py-2">
              <button
                type="button"
                className="text-left w-full space-y-1"
                onClick={() => h.id && focusQualname(repoId, h.id)}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="font-medium text-[13px]">{h.name}</span>
                  <Badge variant="secondary" className="text-[10px]">{h.programs_touched} linked</Badge>
                </div>
                <p className="text-xs text-muted-foreground leading-snug">{h.why_it_matters}</p>
              </button>
            </li>
          ))}
        </ul>
      </section>

      <section className="space-y-2">
        <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">First moves</p>
        <ul className="space-y-2">
          {(brief.first_waves || []).slice(0, 4).map((w, i) => (
            <li key={w.id} className="rounded-md border px-2.5 py-2 space-y-1">
              <p className="font-medium text-[13px]">{i + 1}. {w.title}</p>
              <p className="text-xs text-muted-foreground leading-snug">{w.business}</p>
              <p className="text-[11px] font-mono text-muted-foreground">
                −{w.removes ?? 0} deps · unlocks {w.unlocks ?? 0} · risk {w.risk_before}→{w.risk_after}
              </p>
              <Button
                size="sm"
                variant="outline"
                className="h-7 text-[11px]"
                onClick={() => onAsk?.(`Simulate replacing the units in wave ${w.title}. What breaks?`)}
              >
                Ask impact
              </Button>
            </li>
          ))}
        </ul>
      </section>

      <p className="text-[10px] text-muted-foreground pb-4">{brief.label}</p>
    </div>
  )
}
