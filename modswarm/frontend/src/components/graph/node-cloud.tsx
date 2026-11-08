"use client"

import { useRef, useMemo, useEffect, useState } from "react"
import { useFrame } from "@react-three/fiber"
import * as THREE from "three"
import type { CodeUnitNode, ClusterColorMap, GraphHighlight, ImpactStatus } from "@/types/graph"

export const HUB_THRESHOLD = 0.15
const LERP_SPEED = 4
const MAX_INSTANCES = 1024

interface NodeTarget {
  x: number
  y: number
  z: number
  scale: number
  r: number
  g: number
  b: number
}

const IMPACT_COLORS: Record<string, string> = {
  changed: "#ef4444",
  added: "#22c55e",
  ripple: "#f59e0b",
  deleted: "#6b7280",
}

const CYBER_COLORS: Record<string, string> = {
  legacy: "#ef4444",
  orange: "#f97316",
  purple: "#a855f7",
}

function computeTargets(
  nodes: CodeUnitNode[],
  clusterColors: ClusterColorMap,
  isDark: boolean,
  highlight: GraphHighlight | null,
  bgColor: THREE.Color,
  impactMap: Map<string, ImpactStatus> | null,
  cyberRisk?: Record<string, string | null>,
  retiredIds?: Set<string>,
  glowIds?: Set<string>,
  cyberGlowIds?: Set<string>,
): NodeTarget[] {
  const orphan = new THREE.Color(isDark ? "#a0a0a0" : "#404040")
  const stepGlow = new THREE.Color("#38bdf8")
  const tc = new THREE.Color()

  return nodes.map((n) => {
    // MR overlay only — never used for migration playback
    if (impactMap) {
      const status = impactMap.get(n.id) ?? "unaffected"
      const impactColor = IMPACT_COLORS[status]
      if (impactColor) {
        tc.set(impactColor)
        const opacity = status === "deleted" ? 0.22 : status === "ripple" ? 0.8 : 1
        const scale = status === "deleted" ? 0.08 : (isDark ? 0.15 : 0.17)
        return {
          x: n.x3d, y: n.y3d, z: n.z3d,
          scale,
          r: tc.r * opacity + bgColor.r * (1 - opacity),
          g: tc.g * opacity + bgColor.g * (1 - opacity),
          b: tc.b * opacity + bgColor.b * (1 - opacity),
        }
      }
      const dimOpacity = isDark ? 0.08 : 0.12
      const clusterColor = n.cluster_label ? clusterColors.get(n.cluster_label) : undefined
      if (clusterColor) tc.set(clusterColor)
      else tc.copy(orphan)
      return {
        x: n.x3d, y: n.y3d, z: n.z3d,
        scale: isDark ? 0.15 : 0.17,
        r: tc.r * dimOpacity + bgColor.r * (1 - dimOpacity),
        g: tc.g * dimOpacity + bgColor.g * (1 - dimOpacity),
        b: tc.b * dimOpacity + bgColor.b * (1 - dimOpacity),
      }
    }

    const isRetired = retiredIds?.has(n.id) ?? false
    const isTarget = n.kind === "target" || n.runtime === "target"
    // Regular Play glow vs predicted-risk glow (orange/purple) — only cyberGlowIds get risk paint
    const glowing = glowIds?.has(n.id) ?? false
    const cyberHot = glowing && (cyberGlowIds?.has(n.id) ?? false)
    const cyber = cyberHot ? cyberRisk?.[n.id] : null
    const clusterColor = n.cluster_label ? clusterColors.get(n.cluster_label) : undefined
    if (cyber && CYBER_COLORS[cyber]) tc.set(CYBER_COLORS[cyber])
    else if (glowing) tc.copy(stepGlow)
    else if (isTarget) tc.set("#34d399")
    else if (clusterColor) tc.set(clusterColor)
    else tc.copy(orphan)

    if (glowing) {
      const hot = !!(cyber && CYBER_COLORS[cyber])
      const m = hot ? 3.1 : 1.55
      return {
        x: n.x3d, y: n.y3d, z: n.z3d,
        scale: hot ? 0.48 : 0.22,
        r: tc.r * m, g: tc.g * m, b: tc.b * m,
      }
    }

    if (isRetired) {
      const dimOpacity = isDark ? 0.45 : 0.55
      return {
        x: n.x3d, y: n.y3d, z: n.z3d,
        scale: isDark ? 0.13 : 0.14,
        r: tc.r * dimOpacity + bgColor.r * (1 - dimOpacity),
        g: tc.g * dimOpacity + bgColor.g * (1 - dimOpacity),
        b: tc.b * dimOpacity + bgColor.b * (1 - dimOpacity),
      }
    }

    let opacity: number
    let bright = false
    if (highlight && highlight.source !== "impact") {
      if (highlight.nodeIds.has(n.id)) {
        opacity = 1
        bright = true
      } else if (highlight.isolate) {
        const o = isDark ? 0.06 : 0.1
        return {
          x: n.x3d, y: n.y3d, z: n.z3d,
          scale: 0.06,
          r: tc.r * o + bgColor.r * (1 - o),
          g: tc.g * o + bgColor.g * (1 - o),
          b: tc.b * o + bgColor.b * (1 - o),
        }
      } else {
        opacity = isDark ? 0.2 : 0.5
      }
    } else {
      opacity = n.hub_score > HUB_THRESHOLD ? (isDark ? 0.25 : 0.3) : 1
    }

    const boost = bright ? 1.5 : 1
    const r = Math.min(1, tc.r * boost)
    const g = Math.min(1, tc.g * boost)
    const b = Math.min(1, tc.b * boost)

    return {
      x: n.x3d, y: n.y3d, z: n.z3d,
      scale: isTarget ? (isDark ? 0.22 : 0.24) : (isDark ? 0.15 : 0.17),
      r: r * opacity + bgColor.r * (1 - opacity),
      g: g * opacity + bgColor.g * (1 - opacity),
      b: b * opacity + bgColor.b * (1 - opacity),
    }
  })
}

export function NodeCloud({
  nodes, clusterColors, isDark, highlight, onNodeClick, bgColor, impactMap, cyberRisk, retiredIds, glowIds, cyberGlowIds,
}: {
  nodes: CodeUnitNode[]
  clusterColors: ClusterColorMap
  isDark: boolean
  highlight: GraphHighlight | null
  onNodeClick?: (nodeId: string) => void
  bgColor: string
  impactMap?: Map<string, ImpactStatus> | null
  cyberRisk?: Record<string, string | null>
  retiredIds?: Set<string>
  glowIds?: Set<string>
  cyberGlowIds?: Set<string>
}) {
  const meshRef = useRef<THREE.InstancedMesh>(null)
  const pointerDownRef = useRef(0)
  const [hovered, setHovered] = useState(false)
  const tempObj = useMemo(() => new THREE.Object3D(), [])
  const tempColor = useMemo(() => new THREE.Color(), [])
  const bg = useMemo(() => new THREE.Color(bgColor), [bgColor])

  useEffect(() => {
    if (onNodeClick) {
      document.body.style.cursor = hovered ? "pointer" : "default"
    }
    return () => { document.body.style.cursor = "default" }
  }, [hovered, onNodeClick])

  const currentPos = useRef(new Float32Array(MAX_INSTANCES * 3))
  const currentCol = useRef(new Float32Array(MAX_INSTANCES * 3))
  const currentScale = useRef(new Float32Array(MAX_INSTANCES))
  const nodeIndexMap = useRef(new Map<string, number>())
  const activeCount = useRef(0)

  const targets = useMemo(
    () => computeTargets(nodes, clusterColors, isDark, highlight, bg, impactMap ?? null, cyberRisk, retiredIds, glowIds, cyberGlowIds),
    [nodes, clusterColors, isDark, highlight, bg, impactMap, cyberRisk, retiredIds, glowIds, cyberGlowIds],
  )

  useMemo(() => {
    const prevMap = nodeIndexMap.current
    const prevPos = currentPos.current
    const prevCol = currentCol.current
    const prevScale = currentScale.current
    const nextMap = new Map<string, number>()

    const newPos = new Float32Array(MAX_INSTANCES * 3)
    const newCol = new Float32Array(MAX_INSTANCES * 3)
    const newScale = new Float32Array(MAX_INSTANCES)

    for (let i = 0; i < nodes.length; i++) {
      const n = nodes[i]
      nextMap.set(n.qualname, i)
      const prevIdx = prevMap.get(n.qualname)
      const tgt = targets[i]

      if (prevIdx !== undefined && prevIdx < activeCount.current) {
        newPos[i * 3] = prevPos[prevIdx * 3]
        newPos[i * 3 + 1] = prevPos[prevIdx * 3 + 1]
        newPos[i * 3 + 2] = prevPos[prevIdx * 3 + 2]
        newCol[i * 3] = prevCol[prevIdx * 3]
        newCol[i * 3 + 1] = prevCol[prevIdx * 3 + 1]
        newCol[i * 3 + 2] = prevCol[prevIdx * 3 + 2]
        newScale[i] = prevScale[prevIdx]
      } else {
        newPos[i * 3] = tgt.x
        newPos[i * 3 + 1] = tgt.y
        newPos[i * 3 + 2] = tgt.z
        newCol[i * 3] = bg.r
        newCol[i * 3 + 1] = bg.g
        newCol[i * 3 + 2] = bg.b
        newScale[i] = 0
      }
    }

    currentPos.current = newPos
    currentCol.current = newCol
    currentScale.current = newScale
    nodeIndexMap.current = nextMap
    activeCount.current = nodes.length
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [nodes])

  useFrame((state, delta) => {
    if (!meshRef.current || nodes.length === 0) return
    const pos = currentPos.current
    const col = currentCol.current
    const scl = currentScale.current
    const t = Math.min(1, delta * LERP_SPEED)
    const pulse = 0.5 + 0.5 * Math.sin(state.clock.elapsedTime * 3.2)

    for (let i = 0; i < nodes.length; i++) {
      const tgt = targets[i]
      const glowing = glowIds?.has(nodes[i].id) ?? false
      const cyber = glowing && cyberGlowIds?.has(nodes[i].id) ? cyberRisk?.[nodes[i].id] : null
      const hot = cyber === "orange" || cyber === "purple"
      const pulseBoost = hot ? 1 + pulse * 0.95 : glowing ? 1 + pulse * 0.12 : 1
      const glowBoost = hot ? 2.2 + pulse * 2.8 : glowing ? 1.15 : 1

      pos[i * 3] += (tgt.x - pos[i * 3]) * t
      pos[i * 3 + 1] += (tgt.y - pos[i * 3 + 1]) * t
      pos[i * 3 + 2] += (tgt.z - pos[i * 3 + 2]) * t

      col[i * 3] += (tgt.r - col[i * 3]) * t
      col[i * 3 + 1] += (tgt.g - col[i * 3 + 1]) * t
      col[i * 3 + 2] += (tgt.b - col[i * 3 + 2]) * t

      scl[i] += (tgt.scale * pulseBoost - scl[i]) * t

      tempObj.position.set(pos[i * 3], pos[i * 3 + 1], pos[i * 3 + 2])
      tempObj.scale.setScalar(scl[i])
      tempObj.updateMatrix()
      meshRef.current.setMatrixAt(i, tempObj.matrix)

      tempColor.setRGB(col[i * 3] * glowBoost, col[i * 3 + 1] * glowBoost, col[i * 3 + 2] * glowBoost)
      meshRef.current.setColorAt(i, tempColor)
    }

    for (let i = nodes.length; i < MAX_INSTANCES; i++) {
      tempObj.scale.setScalar(0)
      tempObj.updateMatrix()
      meshRef.current.setMatrixAt(i, tempObj.matrix)
    }

    meshRef.current.instanceMatrix.needsUpdate = true
    if (meshRef.current.instanceColor) meshRef.current.instanceColor.needsUpdate = true
  })

  return (
    <instancedMesh
      ref={meshRef}
      args={[undefined, undefined, MAX_INSTANCES]}
      frustumCulled={false}
      onPointerDown={() => { pointerDownRef.current = Date.now() }}
      onPointerUp={(e) => {
        if (!onNodeClick) return
        if (Date.now() - pointerDownRef.current > 200) return
        const idx = e.instanceId
        if (idx !== undefined && idx < nodes.length) {
          e.stopPropagation()
          onNodeClick(nodes[idx].id)
        }
      }}
      onPointerOver={() => { if (onNodeClick) setHovered(true) }}
      onPointerOut={() => { setHovered(false) }}
    >
      <sphereGeometry args={[1, 16, 16]} />
      <meshBasicMaterial toneMapped={false} />
    </instancedMesh>
  )
}
