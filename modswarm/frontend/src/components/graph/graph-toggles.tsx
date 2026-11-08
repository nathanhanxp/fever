"use client"

import { useEffect } from "react"
import { Sparkle, Waypoints, Network, X } from "lucide-react"
import { Badge } from "@/components/ui/badge"
import { cn } from "@/lib/utils"
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip"
import { useGraphStore } from "@/store/graph-store"

export type ToggleKey = "labels" | "edges" | "clusters"

interface GraphTogglesProps {
  repoId?: string
  nodeCount: number
  edgeCount: number
  clusterCount: number
  showLabels: boolean
  showEdges: boolean
  showClusters: boolean
  onToggle: (key: ToggleKey) => void
  isHighlighted: boolean
  highlightLabel?: string
  onReset: () => void
  riskLevel?: string
  riskLabel?: string
  onRiskClose?: () => void
  /** COBOL/CICS edge verbs — hide on Java/modern graphs */
  showCobolLenses?: boolean
}

const toggles: {
  key: ToggleKey
  icon: typeof Sparkle
  countKey: keyof Pick<GraphTogglesProps, "nodeCount" | "edgeCount" | "clusterCount">
  stateKey: keyof Pick<GraphTogglesProps, "showLabels" | "showEdges" | "showClusters">
  onLabel: string
  offLabel: string
}[] = [
  { key: "labels", icon: Sparkle, countKey: "nodeCount", stateKey: "showLabels", onLabel: "Hide labels", offLabel: "Show all labels" },
  { key: "edges", icon: Waypoints, countKey: "edgeCount", stateKey: "showEdges", onLabel: "Hide edges", offLabel: "Show all edges" },
  { key: "clusters", icon: Network, countKey: "clusterCount", stateKey: "showClusters", onLabel: "Hide clusters", offLabel: "Show clusters" },
]

const BASE_LENSES = [
  "All",
  "API",
  "Data",
  "Code",
  "Platform",
  "Batch",
  "Integration",
  "Security",
  "Compliance",
  "Migration",
]

const COBOL_LENSES = ["COPY", "CALL", "FILE", "JOB", "TRANS", "SCREEN"]

const LENS_TO_TYPES: Record<string, string[]> = {
  All: [],
  Migration: ["migration-API", "migration-Data", "migration-Code", "migration-Platform", "migration-Batch", "migration-Integration", "migration-Security", "migration-Compliance"],
  COPY: ["COPY"],
  CALL: ["CALL"],
  LINK: ["LINK"],
  XCTL: ["XCTL"],
  FILE: ["FILE"],
  JOB: ["JOB"],
  TRANS: ["TRANS"],
  SCREEN: ["SCREEN"],
  API: ["TRANS", "SCREEN", "LINK", "XCTL", "COPY", "migration-API"],
  Data: ["FILE", "migration-Data"],
  Code: ["CALL", "migration-Code"],
  Platform: ["migration-Platform"],
  Batch: ["JOB", "migration-Batch"],
  Integration: ["migration-Integration"],
  Security: ["migration-Security"],
  Compliance: ["migration-Compliance"],
}

export function GraphToggles(props: GraphTogglesProps) {
  const repoId = props.repoId ?? (typeof window !== "undefined" ? window.location.pathname.split("/")[1] : "")
  const edgeTypeFilter = useGraphStore((s) => s.repos[repoId]?.edgeTypeFilter ?? "All")
  // Default hide COBOL chips unless explicitly enabled (Java/jforum must stay clean)
  const lenses = props.showCobolLenses === true
    ? [...BASE_LENSES, ...COBOL_LENSES]
    : BASE_LENSES

  useEffect(() => {
    if (props.showCobolLenses !== true && COBOL_LENSES.includes(edgeTypeFilter)) {
      useGraphStore.getState().setEdgeTypeFilter(repoId, "All")
    }
  }, [props.showCobolLenses, edgeTypeFilter, repoId])

  if (props.isHighlighted) {
    return (
      <div className="absolute top-3 right-3 z-10">
        <button
          type="button"
          onClick={props.onReset}
          className="h-6 w-6 flex items-center justify-center rounded-md border border-border bg-background/80 backdrop-blur-sm text-muted-foreground hover:text-foreground transition-colors cursor-pointer"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      </div>
    )
  }

  const riskColors: Record<string, string> = {
    low: "bg-emerald-950 text-emerald-400 border-emerald-500/40",
    medium: "bg-amber-950 text-amber-400 border-amber-500/40",
    high: "bg-orange-950 text-orange-400 border-orange-500/40",
    critical: "bg-red-950 text-red-400 border-red-500/40",
  }

  return (
    <TooltipProvider>
      <div className="absolute top-3 left-3 z-10 flex items-center gap-1 flex-wrap max-w-[62%]">
        {lenses.map((lens) => (
          <Badge
            key={lens}
            variant={edgeTypeFilter === lens ? "default" : "outline"}
            className="h-5 px-2 text-[10px] cursor-pointer select-none"
            onClick={() => {
              useGraphStore.getState().setEdgeTypeFilter(repoId, lens)
              if (lens !== "All" && !props.showEdges) props.onToggle("edges")
            }}
          >
            {lens}
          </Badge>
        ))}
      </div>
      <div className="absolute top-3 right-3 z-10 flex items-center gap-1.5">
        {props.riskLevel && (
          <>
            <Badge
              variant="outline"
              className={cn(
                "h-5 px-2 text-[10px] font-semibold uppercase flex items-center gap-1 cursor-pointer select-none border",
                riskColors[props.riskLevel] ?? riskColors.low,
              )}
              onClick={props.onRiskClose}
            >
              {props.riskLevel}
              {props.riskLabel && <span className="font-normal normal-case text-[10px] opacity-70">{props.riskLabel}</span>}
              <X className="h-2.5 w-2.5 ml-0.5" />
            </Badge>
            <span className="w-px h-3 bg-border" />
          </>
        )}
        {toggles.map((t) => {
          const active = props[t.stateKey]
          const count = props[t.countKey]
          return (
            <Tooltip key={t.key}>
              <TooltipTrigger asChild>
                <Badge
                  variant={active ? "default" : "outline"}
                  className={`h-5 px-2 text-xs font-normal flex items-center gap-1 cursor-pointer transition-all select-none ${
                    active
                      ? "bg-primary text-primary-foreground"
                      : "hover:bg-accent hover:text-accent-foreground"
                  }`}
                  onClick={() => props.onToggle(t.key)}
                >
                  <t.icon className="h-3 w-3" />
                  {count}
                </Badge>
              </TooltipTrigger>
              <TooltipContent>
                <p>{active ? t.onLabel : t.offLabel}</p>
              </TooltipContent>
            </Tooltip>
          )
        })}
      </div>
    </TooltipProvider>
  )
}

export { LENS_TO_TYPES }
