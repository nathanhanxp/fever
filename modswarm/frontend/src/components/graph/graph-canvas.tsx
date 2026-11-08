"use client"

if (typeof window !== "undefined") {
  const origWarn = console.warn
  console.warn = (...args: unknown[]) => {
    if (typeof args[0] === "string" && args[0].includes("THREE.Clock")) return
    origWarn(...args)
  }
}

import { useMemo, useState, useCallback, useRef } from "react"
import { Canvas } from "@react-three/fiber"
import { Stars as DreiStars } from "@react-three/drei"
import { EffectComposer, Bloom } from "@react-three/postprocessing"
import * as THREE from "three"
import { useTheme } from "next-themes"
import { useGraphData } from "@/lib/use-graph-data"
import { useGraphStore } from "@/store/graph-store"
import { buildClusterColorMap, getIntraClusterEdges, highlightNode, computeDegrees } from "@/lib/graph-utils"
import { GraphToggles, LENS_TO_TYPES, type ToggleKey } from "@/components/graph/graph-toggles"
import { InspectPanel } from "@/components/graph/inspect-panel"
import { NodeCloud, HUB_THRESHOLD } from "@/components/graph/node-cloud"
import { NoveltyLegend } from "@/components/graph/novelty-legend"
import { WhatIfPanel } from "@/components/migrate/what-if-panel"
import { NodeLabels, ClusterLabels, ProximityLabels } from "@/components/graph/graph-labels"
import { EdgeLines } from "@/components/graph/edge-lines"
import { CameraRig } from "@/components/graph/camera-rig"
import type { CodeUnitNode, GraphEdge, ClusterColorMap, GraphHighlight, ImpactStatus, MRAnalysisResponse } from "@/types/graph"

interface GraphCanvasProps {
  repoId: string
  snapshotId: string | null
  mrData?: MRAnalysisResponse | null
}

interface SceneProps {
  nodes: CodeUnitNode[]
  edges: GraphEdge[]
  clusterColors: ClusterColorMap
  isDark: boolean
  bgColor: string
  showLabels: boolean
  showEdges: boolean
  showClusters: boolean
  highlight: GraphHighlight | null
  focusNodes: CodeUnitNode[] | null
  onNodeClick: (nodeId: string) => void
  impactMap: Map<string, ImpactStatus> | null
  cyberRisk?: Record<string, string | null>
  retiredIds?: Set<string>
  removedKeys?: Set<string>
  flashingKeys?: Set<string>
  glowEdgeKeys?: Set<string>
  glowNodeIds?: Set<string>
  cyberGlowNodeIds?: Set<string>
  onEdgeClick?: (key: string) => void
  /** When true, CameraRig ignores focusNodes so Play Step never re-frames the view */
  lockCamera?: boolean
  /** Hide floating HTML labels so they don't cover the bottom inspect card */
  hideLabels?: boolean
}

function Scene({ nodes, edges, clusterColors, isDark, bgColor, showLabels, showEdges, showClusters, highlight, focusNodes, onNodeClick, impactMap, cyberRisk, retiredIds, removedKeys, flashingKeys, glowEdgeKeys, glowNodeIds, cyberGlowNodeIds, onEdgeClick, lockCamera, hideLabels }: SceneProps) {
  const posMap = useMemo(() => {
    const map = new Map<string, [number, number, number]>()
    for (const n of nodes) map.set(n.id, [n.x3d, n.y3d, n.z3d])
    return map
  }, [nodes])

  const clusterEdges = useMemo(
    () => (showClusters ? getIntraClusterEdges(nodes, edges) : []),
    [showClusters, nodes, edges],
  )

  const clusterColorMap = useMemo(() => {
    const map = new Map<string, string>()
    for (const e of clusterEdges) {
      const key = `${e.source}::${e.target}`
      map.set(key, clusterColors.get(e.clusterLabel) ?? "#ffffff")
    }
    return map
  }, [clusterEdges, clusterColors])

  const hubIds = useMemo(() => {
    const set = new Set<string>()
    for (const n of nodes) {
      if (n.hub_score > HUB_THRESHOLD) set.add(n.id)
    }
    return set
  }, [nodes])

  const typeColors: Record<string, string> = {
    COPY: "#7aa2ff", CALL: "#f0c14a", LINK: "#d27bff", XCTL: "#ff8b6a",
    FILE: "#3ddc97", JOB: "#ff6b8a", TRANS: "#5ad1e6", SCREEN: "#c8d48a",
    "migration-API": "#7aa2ff", "migration-Data": "#3ddc97", "migration-Code": "#f0c14a",
    "migration-Platform": "#d27bff", "migration-Batch": "#ff8b6a",
    "migration-Integration": "#5ad1e6", "migration-Security": "#ff6b8a",
    "migration-Compliance": "#c8d48a",
  }

  const edgeColorMap = useMemo(() => {
    const map = new Map<string, string>()
    for (const e of edges) {
      const color = typeColors[e.edge_type]
      if (color) map.set(`${e.source}::${e.target}`, color)
    }
    return map
  }, [edges])

  const dashedKeys = useMemo(() => {
    const set = new Set<string>()
    for (const e of edges) {
      if (String(e.edge_type).startsWith("migration-")) set.add(`${e.source}::${e.target}`)
    }
    return set
  }, [edges])

  const legacyStyle = useMemo(
    () => edges.some((e) => ["COPY", "CALL", "FILE", "JOB", "TRANS", "SCREEN", "LINK", "XCTL"].includes(e.edge_type)),
    [edges],
  )

  const allEdgeList = useMemo(
    () => edges
      .filter((e) => legacyStyle || (!hubIds.has(e.source) && !hubIds.has(e.target)))
      .map((e) => ({ source: e.source, target: e.target, type: e.edge_type })),
    [edges, hubIds, legacyStyle],
  )

  const clusterEdgeList = useMemo(
    () => clusterEdges.map((e) => ({ source: e.source, target: e.target, type: e.edge_type })),
    [clusterEdges],
  )

  const { innerEdges, outerEdges, specificEdges } = useMemo(() => {
    if (!highlight) return { innerEdges: [], outerEdges: [], specificEdges: [] }

    type E = { source: string; target: string; type?: string }
    const inner: E[] = []
    const outer: E[] = []
    const specific: E[] = []

    const seen = new Set<string>()
    const push = (list: E[], e: { source: string; target: string; edge_type?: string }, typed = false) => {
      const k = `${e.source}::${e.target}::${e.edge_type || ""}`
      if (seen.has(k)) return
      seen.add(k)
      list.push(typed ? { source: e.source, target: e.target, type: e.edge_type } : { source: e.source, target: e.target })
    }

    if (highlight.edgeKeys.size > 0) {
      for (const e of edges) {
        const key = `${e.source}::${e.target}::${e.edge_type}`
        const loose = `${e.source}::${e.target}`
        if (highlight.edgeKeys.has(key) || highlight.edgeKeys.has(loose)) {
          push(specific, e, true)
        }
      }
    }

    for (const e of edges) {
      const srcIn = highlight.nodeIds.has(e.source)
      const tgtIn = highlight.nodeIds.has(e.target)
      if (srcIn && tgtIn) push(inner, e, true)
      else if (srcIn || tgtIn) push(outer, e)
    }

    return { innerEdges: inner, outerEdges: outer, specificEdges: specific }
  }, [highlight, edges])

  const impactLabelNodes = useMemo(() => {
    if (!impactMap) return []
    return nodes.filter((n) => {
      const status = impactMap.get(n.id)
      return status === "changed" || status === "added"
    })
  }, [impactMap, nodes])

  const affectedIds = useMemo(() => {
    if (!impactMap) return new Set<string>()
    const ids = new Set<string>()
    for (const [id, status] of impactMap) {
      if (status !== "unaffected") ids.add(id)
    }
    return ids
  }, [impactMap])

  const changedIds = useMemo(() => {
    if (!impactMap) return new Set<string>()
    const ids = new Set<string>()
    for (const [id, status] of impactMap) {
      if (status === "changed" || status === "added") ids.add(id)
    }
    return ids
  }, [impactMap])

  const impactEdgeList = useMemo(() => {
    if (!impactMap) return []
    return edges
      .filter((e) => changedIds.has(e.source) || changedIds.has(e.target))
      .filter((e) => affectedIds.has(e.source) && affectedIds.has(e.target))
      .map((e) => ({ source: e.source, target: e.target }))
  }, [impactMap, edges, affectedIds, changedIds])

  const impactEdgeColorMap = useMemo(() => {
    if (!impactMap) return undefined
    const map = new Map<string, string>()
    for (const e of impactEdgeList) {
      const srcStatus = impactMap.get(e.source) ?? "unaffected"
      const tgtStatus = impactMap.get(e.target) ?? "unaffected"
      const color = (srcStatus === "changed" || tgtStatus === "changed") ? "#ef4444"
        : (srcStatus === "added" || tgtStatus === "added") ? "#22c55e"
        : "#f59e0b"
      map.set(`${e.source}::${e.target}`, color)
    }
    return map
  }, [impactMap, impactEdgeList])

  return (
    <>
      <color attach="background" args={[bgColor]} />
      <ambientLight intensity={isDark ? 0.2 : 1.5} />

      {isDark && (
        <DreiStars radius={200} depth={40} count={1500} factor={4} saturation={0} fade speed={1} />
      )}

      <NodeCloud
        nodes={nodes}
        clusterColors={clusterColors}
        isDark={isDark}
        highlight={lockCamera && !highlight?.isolate ? null : highlight}
        onNodeClick={onNodeClick}
        bgColor={bgColor}
        impactMap={impactMap}
        cyberRisk={cyberRisk}
        retiredIds={retiredIds}
        glowIds={glowNodeIds}
        cyberGlowIds={cyberGlowNodeIds}
      />

      {impactMap ? (
        <>
          {showLabels && !hideLabels && impactLabelNodes.length > 0 && (
            <NodeLabels nodes={impactLabelNodes} clusterColors={clusterColors} isDark={isDark} />
          )}
          {showEdges && impactEdgeList.length > 0 && (
            <EdgeLines edges={impactEdgeList} posMap={posMap} isDark={isDark} colorMap={impactEdgeColorMap} />
          )}
          {showClusters && !hideLabels && (
            <ClusterLabels nodes={nodes.filter((n) => affectedIds.has(n.id))} clusterColors={clusterColors} isDark={isDark} />
          )}
        </>
      ) : !highlight || (lockCamera && !highlight.isolate) ? (
        <>
          {!hideLabels && (showLabels ? (
            <NodeLabels nodes={nodes} clusterColors={clusterColors} isDark={isDark} />
          ) : (
            <ProximityLabels nodes={nodes} clusterColors={clusterColors} isDark={isDark} />
          ))}

          {showEdges && (
            <EdgeLines
              edges={allEdgeList}
              posMap={posMap}
              isDark={isDark}
              colorMap={edgeColorMap}
              dashedKeys={dashedKeys}
              removedKeys={removedKeys}
              flashingKeys={flashingKeys}
              retiredIds={retiredIds}
              glowKeys={glowEdgeKeys}
              cyberGlowIds={cyberGlowNodeIds}
              cyberRisk={cyberRisk}
              faded
              onEdgeClick={onEdgeClick}
            />
          )}

          {showClusters && !hideLabels && (
            <>
              <ClusterLabels nodes={nodes} clusterColors={clusterColors} isDark={isDark} />
              {clusterEdgeList.length > 0 && (
                <EdgeLines
                  edges={clusterEdgeList}
                  posMap={posMap}
                  isDark={isDark}
                  colorMap={clusterColorMap}
                  retiredIds={retiredIds}
                  removedKeys={removedKeys}
                />
              )}
            </>
          )}
          {showClusters && hideLabels && clusterEdgeList.length > 0 && (
            <EdgeLines
              edges={clusterEdgeList}
              posMap={posMap}
              isDark={isDark}
              colorMap={clusterColorMap}
              retiredIds={retiredIds}
              removedKeys={removedKeys}
            />
          )}
        </>
      ) : (
        <>
          {(specificEdges.length > 0 || innerEdges.length > 0) && (
            <EdgeLines
              edges={specificEdges.length > 0 ? [...specificEdges, ...innerEdges] : innerEdges}
              posMap={posMap}
              isDark={isDark}
              colorMap={highlight.isolate ? edgeColorMap : undefined}
              centerNodeId={focusNodes?.[0]?.id}
              onEdgeClick={onEdgeClick}
              retiredIds={retiredIds}
              removedKeys={removedKeys}
              glowKeys={glowEdgeKeys}
              cyberGlowIds={cyberGlowNodeIds}
              cyberRisk={cyberRisk}
            />
          )}
          {!highlight.isolate && outerEdges.length > 0 && (
            <EdgeLines edges={outerEdges} posMap={posMap} isDark={isDark} dimmed onEdgeClick={onEdgeClick} retiredIds={retiredIds} removedKeys={removedKeys} />
          )}
          {!hideLabels && (showLabels ? (
            <NodeLabels nodes={nodes} clusterColors={clusterColors} isDark={isDark} />
          ) : (
            <NodeLabels
              nodes={nodes
                .filter((n) => highlight.nodeIds.has(n.id))
                .sort((a, b) => b.hub_score - a.hub_score)
                .slice(0, 40)}
              clusterColors={clusterColors}
              isDark={isDark}
            />
          ))}
          {showClusters && !hideLabels && (
            <ClusterLabels nodes={nodes} clusterColors={clusterColors} isDark={isDark} />
          )}
        </>
      )}

      <CameraRig nodes={nodes} focusNodes={lockCamera ? null : focusNodes} />
    </>
  )
}

export function GraphCanvas({ repoId, snapshotId, mrData }: GraphCanvasProps) {
  useGraphData(repoId, snapshotId)
  const containerRef = useRef<HTMLDivElement>(null)

  const { resolvedTheme } = useTheme()
  const isDark = resolvedTheme === "dark"

  const repo = useGraphStore((s) => s.repos[repoId])
  const data = repo?.data ?? null
  const bgColor = isDark ? "#0a0a0a" : "#ffffff"

  const [showLabels, setShowLabels] = useState(false)
  const [showEdges, setShowEdges] = useState(true)
  const [showClusters, setShowClusters] = useState(false)

  const selectedNodeId = repo?.selectedNodeId ?? null
  const highlight = repo?.highlight ?? null
  const edgeTypeFilter = repo?.edgeTypeFilter ?? "All"
  const removedEdgeKeys = repo?.removedEdgeKeys
  const flashingEdgeKeys = repo?.flashingEdgeKeys
  const cyberRisk = repo?.cyberRisk ?? {}
  const retiredNodeIds = repo?.retiredNodeIds
  const playbackStepId = repo?.playbackStepId

  // Only real COBOL/CICS source — jforum reuses kind=program + CALL/COPY labels
  const showCobolLenses = useMemo(() => {
    if (!data) return false
    return data.nodes.some((n) => {
      const id = String(n.id || "").toLowerCase()
      const path = String(n.file_path || n.qualname || "").toLowerCase()
      if (id.startsWith("java:") || path.endsWith(".java") || path.includes("/java/")) return false
      return (
        id.startsWith("pgm:") ||
        path.endsWith(".cbl") ||
        path.endsWith(".cpy") ||
        path.endsWith(".jcl") ||
        path.endsWith(".bms") ||
        path.includes(".cbl") ||
        path.includes(".cpy")
      )
    })
  }, [data])

  // Lens filter only — do NOT drop removed edges here (EdgeLines fades them out in place).
  // Chat isolate must see every edge that the scope returned, so ignore the lens then.
  const filteredEdges = useMemo(() => {
    if (!data) return []
    if (highlight?.isolate) return data.edges
    const allowed = LENS_TO_TYPES[edgeTypeFilter] ?? []
    if (!allowed.length) return data.edges
    return data.edges.filter((e) => allowed.includes(e.edge_type) || allowed.some((a) => e.edge_type === a))
  }, [data, edgeTypeFilter, highlight?.isolate])

  const handleEdgeClick = useCallback((key: string) => {
    if (!data) return
    const [s, t, typ] = key.split("::")
    const src = data.nodes.find((n) => n.id === s)
    const tgt = data.nodes.find((n) => n.id === t)
    const auditKey = `${src?.qualname || s}::${tgt?.qualname || t}::${typ || ""}`
    // selectEdge already clears the node — do NOT call selectNode(null) after (it wipes the edge)
    useGraphStore.getState().selectEdge(repoId, auditKey)
    const path = src?.file_path || tgt?.file_path
    const line = src?.start_line || tgt?.start_line
    if (path) {
      useGraphStore.getState().setSourceFocus(repoId, {
        path,
        line: line || null,
        endLine: (src?.end_line || tgt?.end_line || line) || null,
      })
    }
  }, [repoId, data])


  const clusterColors = useMemo(
    () => (data ? buildClusterColorMap(data.nodes, isDark) : new Map<string, string>()),
    [data, isDark],
  )

  const clusterCount = useMemo(() => {
    if (!data) return 0
    return new Set(data.nodes.map((n) => n.cluster_label).filter(Boolean)).size
  }, [data])

  const selectedNode = useMemo(() => {
    if (!data || !selectedNodeId) return null
    return data.nodes.find((n) => n.id === selectedNodeId) ?? null
  }, [data, selectedNodeId])

  const degrees = useMemo(() => {
    if (!data) return new Map<string, { in: number; out: number }>()
    return computeDegrees(filteredEdges)
  }, [filteredEdges])

  const handleNodeClick = useCallback((nodeId: string) => {
    if (!data) return
    // Keep isolate / playback glow — only open the inspect panel
    useGraphStore.getState().selectNode(repoId, nodeId)
    const cur = useGraphStore.getState().repos[repoId]?.highlight
    if (!cur?.isolate && !playbackStepId) {
      useGraphStore.getState().setHighlight(repoId, highlightNode(data, nodeId, 1))
    }
    const node = data.nodes.find((n) => n.id === nodeId)
    if (node?.file_path) {
      useGraphStore.getState().setSourceFocus(repoId, {
        path: node.file_path,
        line: node.start_line || null,
        endLine: node.end_line || node.start_line || null,
      })
    }
  }, [repoId, data, playbackStepId])

  const handleReset = useCallback(() => {
    useGraphStore.getState().selectNode(repoId, null)
    useGraphStore.getState().selectEdge(repoId, null)
    useGraphStore.getState().setHighlight(repoId, null)
  }, [repoId])

  const handleToggle = useCallback((key: ToggleKey) => {
    if (key === "labels") setShowLabels((v) => !v)
    if (key === "edges") {
      setShowEdges((v) => !v)
      setShowClusters(false)
    }
    if (key === "clusters") {
      setShowClusters((v) => !v)
      setShowEdges(false)
    }
  }, [])

  // Playback must NOT enter impact mode — that re-renders edges and dims the whole graph.
  const impactMap = useMemo(() => {
    if (mrData?.report.overlay_graph) {
      const map = new Map<string, ImpactStatus>()
      for (const n of mrData.report.overlay_graph.nodes) {
        map.set(n.id, n.impact_status)
      }
      return map
    }
    return null
  }, [mrData])

  const isImpactMode = !!impactMap
  const lockCamera = !!(retiredNodeIds && retiredNodeIds.size > 0) || !!playbackStepId

  if (!data) {
    return (
      <div className="flex-1 flex items-center justify-center text-xs text-muted-foreground">
        Loading graph...
      </div>
    )
  }

  const nodeDeg = selectedNode ? degrees.get(selectedNode.id) : undefined

  return (
    <div ref={containerRef} data-graph-canvas className="flex-1 relative bg-background">
      <GraphToggles
        repoId={repoId}
        nodeCount={isImpactMode ? (mrData?.report.changed_units.length ?? 0) : data.nodes.length}
        edgeCount={isImpactMode ? (mrData?.report.impacted_units.length ?? 0) : filteredEdges.length}
        clusterCount={isImpactMode ? (mrData?.report.cluster_impact.length ?? 0) : clusterCount}
        showLabels={showLabels}
        showEdges={showEdges}
        showClusters={showClusters}
        onToggle={handleToggle}
        isHighlighted={!isImpactMode && !!highlight}
        highlightLabel={selectedNode?.symbol_name}
        onReset={handleReset}
        showCobolLenses={showCobolLenses}
      />
      {!isImpactMode && <NoveltyLegend live={!!(repo?.glowNodeIds && repo.glowNodeIds.size > 0)} />}
      {highlight?.isolate && (
        <div className="absolute top-28 left-3 z-10 flex items-center gap-2 rounded-md border bg-background/90 backdrop-blur px-2.5 py-1.5 text-[12px]">
          <span className="font-medium">{highlight.label || "Scoped"}</span>
          <span className="text-muted-foreground font-mono">{highlight.nodeIds.size} units · {highlight.edgeKeys.size || "…"} edges</span>
          <button type="button" className="text-muted-foreground hover:text-foreground" onClick={handleReset}>Clear</button>
        </div>
      )}
      <Canvas
        className="absolute inset-0 z-0 !h-full !w-full"
        style={{ position: "absolute", inset: 0, zIndex: 0 }}
        camera={{ position: [0, 45, 0], near: 0.01, far: 1000, up: [0, 1, 0] }}
        dpr={[1, 1.5]}
        raycaster={{ params: { Line: { threshold: 0.55 }, Points: { threshold: 0.4 } } as never }}
        gl={{
          antialias: true,
          preserveDrawingBuffer: true,
          toneMapping: isDark ? THREE.ACESFilmicToneMapping : THREE.NoToneMapping,
          toneMappingExposure: 1,
        }}
      >
        <Scene
          nodes={data.nodes}
          edges={filteredEdges}
          clusterColors={clusterColors}
          isDark={isDark}
          bgColor={bgColor}
          showLabels={showLabels}
          showEdges={showEdges}
          showClusters={showClusters}
          highlight={highlight}
          focusNodes={selectedNode ? [selectedNode] : highlight?.nodeIds.size ? data.nodes.filter((n) => highlight.nodeIds.has(n.id)) : null}
          onNodeClick={handleNodeClick}
          impactMap={impactMap}
          cyberRisk={cyberRisk}
          retiredIds={retiredNodeIds}
          removedKeys={removedEdgeKeys}
          flashingKeys={flashingEdgeKeys}
          glowEdgeKeys={repo?.glowEdgeKeys}
          glowNodeIds={repo?.glowNodeIds}
          cyberGlowNodeIds={repo?.cyberGlowNodeIds}
          onEdgeClick={handleEdgeClick}
          lockCamera={lockCamera}
          // Always hide graph names while the bottom inspect card is open
          hideLabels={!!(selectedNode || repo?.selectedEdgeKey)}
        />
        {/* Bloom overdraw flashes lines through HTML overlays — disable while inspect is open */}
        {!(selectedNode || repo?.selectedEdgeKey) && (
          <EffectComposer>
            <Bloom
              kernelSize={5}
              luminanceThreshold={isDark ? 0.0 : 0.8}
              luminanceSmoothing={0.5}
              intensity={0.75}
              radius={isDark ? 0.5 : 0.6}
            />
          </EffectComposer>
        )}
      </Canvas>
      <InspectPanel
        repoId={repoId}
        node={selectedNode}
        inDegree={nodeDeg?.in ?? 0}
        outDegree={nodeDeg?.out ?? 0}
        onClose={handleReset}
      />
      {!isImpactMode && <WhatIfPanel repoId={repoId} />}
    </div>
  )
}
