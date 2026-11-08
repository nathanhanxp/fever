"use client"

import { useEffect, useState } from "react"
import { X } from "lucide-react"
import { useGraphStore } from "@/store/graph-store"
import type { CodeUnitNode } from "@/types/graph"

type Doc = { title?: string; source?: string; url?: string; passage?: string }
type Kev = {
  catalog_version?: string
  matched?: number
  total?: number
  url?: string
  items?: { cve?: string; name?: string; date_added?: string; url?: string }[]
}
type Risk = { color?: string; title?: string; detail?: string; claim?: string; file?: string; line?: number | string }
type Card = {
  found?: boolean
  ai_why?: string
  node?: { name?: string; kind?: string; file?: string; line?: number; summary?: string }
  edge?: { type?: string; source?: string; target?: string; file?: string; line?: number; snippet?: string }
  edges_by_type?: Record<string, number>
  risk?: Risk
  risks?: Risk[]
  findings?: { title?: string; file?: string; line?: number | string; snippet?: string }[]
  steps?: { index: number; title?: string; why?: string }[]
  docs?: Doc[]
  kev?: Kev | null
}

const DOT: Record<string, string> = { red: "bg-red-500", orange: "bg-orange-500", purple: "bg-purple-500" }
const PREDICTED: Record<string, string> = {
  orange: "Predicted risk · API boundary",
  purple: "Predicted risk · data in transit",
  red: "Measured legacy vulnerability",
}

const short = (s?: string) => (s || "").split(":").pop()
const linkHint = (u?: string) => {
  try {
    const x = new URL(u || "")
    const path = x.pathname.replace(/\/$/, "")
    const short = path.length > 56 ? `${path.slice(0, 54)}…` : path
    return `${x.hostname.replace(/^www\./, "")}${short}`
  } catch { return "" }
}

export function InspectPanel({ repoId, node, inDegree, outDegree, onClose }: {
  repoId: string
  node: CodeUnitNode | null
  inDegree: number
  outDegree: number
  onClose: () => void
}) {
  const edgeKey = useGraphStore((s) => s.repos[repoId]?.selectedEdgeKey ?? null)
  const graphNodes = useGraphStore((s) => s.repos[repoId]?.data?.nodes)
  const [card, setCard] = useState<Card | null>(null)
  const legacyEdgeKey = (() => {
    if (!edgeKey) return null
    const [src, tgt, type] = edgeKey.split("::")
    const name = (id: string) => {
      const n = graphNodes?.find((x) => x.id === id)
      return n ? n.qualname || n.symbol_name : id
    }
    return [name(src), name(tgt), type].filter(Boolean).join("::")
  })()
  const target = legacyEdgeKey
    ? `edges/audit?key=${encodeURIComponent(legacyEdgeKey)}`
    : node
      ? `nodes/audit?key=${encodeURIComponent(node.qualname || node.symbol_name)}`
      : null

  useEffect(() => {
    setCard(null)
    if (!target) return
    let alive = true
    fetch(`/api/repos/${repoId}/${target}`)
      .then((r) => r.json())
      .then((b: Card) => {
        if (!alive) return
        setCard(b)
        const path = b.edge?.file || b.node?.file || node?.file_path
        const ln = Number(b.edge?.line || b.node?.line || b.risk?.line || 0)
        if (path && ln > 0) {
          useGraphStore.getState().setSourceFocus(repoId, {
            path,
            line: ln,
            endLine: ln,
          })
        }
      })
      .catch(() => { if (alive) setCard({ found: false }) })
    return () => { alive = false }
  }, [repoId, target, node?.file_path])

  if (!target) return null

  const close = () => {
    useGraphStore.getState().selectEdge(repoId, null)
    onClose()
  }
  const risks = card?.risks ?? (card?.risk && card.risk.color && card.risk.color !== "none" ? [card.risk] : [])
  const predicted = risks.find((r) => r.color === "orange" || r.color === "purple")
  const title = edgeKey
    ? `${short(card?.edge?.source) || "…"} → ${short(card?.edge?.target) || "…"}`
    : node?.symbol_name
  const kind = edgeKey ? card?.edge?.type : card?.node?.kind || node?.kind
  const file = edgeKey ? card?.edge?.file : card?.node?.file || node?.file_path
  const line = edgeKey ? card?.edge?.line : card?.node?.line || node?.start_line
  const why = card?.ai_why || (!edgeKey ? (node?.llm_description || card?.node?.summary) : null)

  return (
    <div className="absolute bottom-3 left-1/2 -translate-x-1/2 z-40 w-[min(400px,calc(100%-20px))] max-h-[32%] overflow-auto rounded-md border border-border bg-background shadow-2xl pointer-events-auto isolate">
      <div className="sticky top-0 flex items-center gap-1.5 border-b bg-background px-3 py-1.5">
        <span className="text-[12px] font-semibold truncate">{title}</span>
        {kind && <span className="text-[9px] px-1 py-0.5 rounded bg-muted font-mono shrink-0">{kind === "TRANS" ? "HTTP" : kind === "SCREEN" ? "VIEW" : kind}</span>}
        <div className="flex-1" />
        <button type="button" onClick={close} className="p-0.5 text-muted-foreground hover:text-foreground"><X className="size-3.5" /></button>
      </div>

      {!card && <p className="px-3 py-2 text-[11px] text-muted-foreground">Loading…</p>}
      {card && !card.found && <p className="px-3 py-2 text-[11px] text-muted-foreground">No evidence for this selection.</p>}

      {card?.found && (
        <div className="px-3 py-2 space-y-2 text-[11px] bg-background">
          {predicted && (
            <div className={`flex items-center gap-1.5 rounded px-2 py-1 text-[10px] font-semibold ${
              predicted.color === "purple" ? "bg-purple-500/15 text-purple-300" : "bg-orange-500/15 text-orange-300"
            }`}>
              <span className={`size-1.5 rounded-full animate-pulse ${DOT[predicted.color || ""]}`} />
              {PREDICTED[predicted.color || ""] || "Predicted risk"}
            </div>
          )}
          {!predicted && risks[0]?.color === "red" && (
            <div className="flex items-center gap-1.5 rounded px-2 py-1 text-[10px] font-semibold bg-red-500/15 text-red-300">
              <span className="size-1.5 rounded-full bg-red-500" />
              {PREDICTED.red}
            </div>
          )}

          {why && (
            <p className="leading-snug">
              <span className="text-[9px] font-semibold uppercase tracking-wide text-sky-500 mr-1.5">AI</span>
              {why}
            </p>
          )}

          {file && (
            <button
              type="button"
              className="font-mono text-[10px] text-muted-foreground truncate text-left hover:text-foreground"
              onClick={() => useGraphStore.getState().setSourceFocus(repoId, {
                path: file,
                line: typeof line === "number" ? line : Number(line) || null,
                endLine: typeof line === "number" ? line : Number(line) || null,
              })}
            >
              {file}:{line}
            </button>
          )}

          {!edgeKey && (
            <div className="flex flex-wrap gap-1 text-[10px]">
              <span className="rounded border px-1 py-0.5">{inDegree} in · {outDegree} out</span>
              {Object.entries(card.edges_by_type || {}).slice(0, 4).map(([t, c]) => (
                <span key={t} className="rounded border px-1 py-0.5 font-mono">{t} {c}</span>
              ))}
            </div>
          )}

          {card.edge?.snippet && (
            <pre className="whitespace-pre-wrap rounded bg-muted p-1.5 text-[10px] font-mono line-clamp-3">{card.edge.snippet}</pre>
          )}

          {risks.slice(0, 2).map((r, i) => (
            <div key={i} className={`border-l-2 pl-2 ${r.color === "orange" ? "border-orange-500" : r.color === "purple" ? "border-purple-500" : "border-red-500"}`}>
              <p className="font-medium leading-snug">{r.title}</p>
              {r.detail && <p className="text-muted-foreground leading-snug line-clamp-2">{r.detail}</p>}
            </div>
          ))}

          {(card.steps || []).length > 0 && (
            <p className="text-muted-foreground leading-snug">
              <span className="text-[9px] uppercase tracking-wide mr-1">Steps</span>
              {card.steps!.map((s) => `#${s.index} ${s.title}`).join(" · ")}
            </p>
          )}

          {card.kev && (card.kev.items || []).length > 0 && (
            <div className="space-y-0.5">
              <p className="text-[9px] uppercase tracking-wide text-muted-foreground">Related KEV</p>
              {card.kev.items!.slice(0, 1).map((k) => (
                <a key={k.cve} href={k.url} target="_blank" rel="noreferrer" className="flex gap-1.5 text-[10px] hover:bg-muted/40 rounded px-0.5 -mx-0.5">
                  <span className="font-mono text-red-500 shrink-0">{k.cve}</span>
                  <span className="truncate">{k.name}</span>
                </a>
              ))}
            </div>
          )}

          {(card.docs || []).slice(0, 2).map((d, i) => (
            <a key={i} href={d.url} target="_blank" rel="noreferrer" className="block rounded border p-1.5 hover:bg-muted/40">
              <p className="font-medium leading-snug">{d.title}</p>
              <p className="text-[9px] text-muted-foreground break-all">{linkHint(d.url)} ↗</p>
              {d.passage && <p className="mt-0.5 italic leading-snug line-clamp-3 text-muted-foreground">“{d.passage}”</p>}
            </a>
          ))}
        </div>
      )}
    </div>
  )
}
