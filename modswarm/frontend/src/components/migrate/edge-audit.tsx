"use client"

import { useEffect, useState } from "react"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { useGraphStore } from "@/store/graph-store"
import { SourceList } from "@/components/migrate/source-chip"

type Audit = {
  found?: boolean
  edge?: {
    type?: string
    source?: string
    target?: string
    file?: string
    line?: number
    snippet?: string
  }
  risk?: {
    color?: string
    title?: string
    detail?: string
    claim?: string
  }
  docs?: { title?: string; source?: string; url?: string; passage?: string }[]
  threat_context?: { framework?: string; kev?: string; epss?: number | null; label?: string }
  reasoning?: string
  agents?: { role?: string; model?: string; host?: string; job?: string }[]
  claim?: string
}

const colorDot: Record<string, string> = {
  red: "bg-red-500",
  orange: "bg-orange-500",
  purple: "bg-purple-500",
}

export function EdgeAudit({ repoId }: { repoId: string }) {
  const edgeKey = useGraphStore((s) => s.repos[repoId]?.selectedEdgeKey ?? null)
  const [audit, setAudit] = useState<Audit | null>(null)

  useEffect(() => {
    if (!edgeKey) {
      setAudit(null)
      return
    }
    let alive = true
    fetch(`/api/repos/${repoId}/edges/audit?key=${encodeURIComponent(edgeKey)}`)
      .then((r) => r.json())
      .then((b) => { if (alive) setAudit(b) })
      .catch(() => { if (alive) setAudit({ found: false }) })
    return () => { alive = false }
  }, [repoId, edgeKey])

  if (!edgeKey) return null

  const riskColor = audit?.risk?.color

  return (
    <div className="absolute top-12 right-3 z-20 w-[340px] max-h-[70vh] overflow-auto rounded-md border bg-background/95 backdrop-blur shadow-lg p-3 space-y-2.5 text-xs">
      <div className="flex items-center gap-2">
        <p className="font-medium text-sm">Edge audit</p>
        <div className="flex-1" />
        <Button size="sm" variant="ghost" className="h-6 text-[10px]" onClick={() => useGraphStore.getState().selectEdge(repoId, null)}>
          Close
        </Button>
      </div>
      {!audit && <p className="text-muted-foreground">Loading sources…</p>}
      {audit && !audit.found && <p className="text-muted-foreground">No Measured edge matched this click.</p>}
      {audit?.found && (
        <>
          <div className="flex flex-wrap gap-1 items-center">
            <Badge variant="outline">{audit.edge?.type}</Badge>
            {riskColor && riskColor !== "none" && (
              <Badge variant="outline" className="gap-1">
                <span className={`inline-block size-1.5 rounded-full ${colorDot[riskColor] || "bg-muted-foreground"}`} />
                {riskColor} risk
              </Badge>
            )}
            <Badge variant="outline">{audit.risk?.claim || audit.claim}</Badge>
          </div>
          <p className="font-medium text-[13px] leading-snug">{audit.risk?.title}</p>
          <p className="text-muted-foreground leading-snug">{audit.reasoning || audit.risk?.detail}</p>
          {audit.edge?.file && (
            <p className="font-mono text-[11px]">{audit.edge.file}:{audit.edge.line}</p>
          )}
          {audit.edge?.snippet && (
            <pre className="whitespace-pre-wrap rounded bg-muted/50 p-2 text-[10px] max-h-24 overflow-auto">{audit.edge.snippet}</pre>
          )}
          {audit.threat_context && (
            <div className="rounded border p-2 space-y-1">
              <p className="font-medium">Threat context</p>
              <p>{audit.threat_context.framework}</p>
              <p className="text-muted-foreground">{audit.threat_context.kev}</p>
              {audit.threat_context.epss != null && (
                <p className="font-mono text-[10px]">EPSS {audit.threat_context.epss}</p>
              )}
              <p className="text-[10px]">{audit.threat_context.label}</p>
              <div className="flex flex-wrap gap-1 pt-1">
                <a
                  href="https://www.cisa.gov/known-exploited-vulnerabilities-catalog"
                  target="_blank"
                  rel="noreferrer"
                  className="text-[10px] underline text-muted-foreground hover:text-foreground"
                >
                  CISA KEV ↗
                </a>
                <a
                  href="https://osv.dev/"
                  target="_blank"
                  rel="noreferrer"
                  className="text-[10px] underline text-muted-foreground hover:text-foreground"
                >
                  OSV ↗
                </a>
                <a
                  href="https://owasp.org/API-Security/"
                  target="_blank"
                  rel="noreferrer"
                  className="text-[10px] underline text-muted-foreground hover:text-foreground"
                >
                  OWASP API ↗
                </a>
              </div>
            </div>
          )}
          <SourceList docs={audit.docs} max={5} />
          <div className="space-y-1">
            <p className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">Agents</p>
            {(audit.agents || []).map((a, i) => (
              <p key={i} className="text-muted-foreground leading-snug">
                <span className="text-foreground font-medium">{a.role}</span>
                <span className="block text-[10px]">{a.job}</span>
              </p>
            ))}
          </div>
        </>
      )}
    </div>
  )
}
