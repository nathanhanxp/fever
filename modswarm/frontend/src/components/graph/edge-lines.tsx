"use client"

import { useEffect, useMemo, useRef } from "react"
import { useFrame, useThree, type ThreeEvent } from "@react-three/fiber"
import { Line } from "@react-three/drei"
import * as THREE from "three"

const GROW_DURATION = 0.4
const FADE_DURATION = 0.55

interface EdgeSpec {
  source: string
  target: string
  type?: string
}

/**
 * All edges in one LineSegments draw call. Grow / fade / retire animate by
 * mutating GPU buffers in useFrame — no React re-render per frame.
 */
export function EdgeLines({
  edges,
  posMap,
  isDark,
  colorMap,
  centerNodeId,
  dimmed,
  removedKeys,
  flashingKeys,
  retiredIds,
  glowKeys,
  cyberGlowIds,
  cyberRisk,
  faded,
  onEdgeClick,
}: {
  edges: EdgeSpec[]
  posMap: Map<string, [number, number, number]>
  isDark: boolean
  colorMap?: Map<string, string>
  centerNodeId?: string
  dimmed?: boolean
  dashedKeys?: Set<string>
  removedKeys?: Set<string>
  flashingKeys?: Set<string>
  retiredIds?: Set<string>
  /** Current Play step edges: full brightness + bloom */
  glowKeys?: Set<string>
  /** Predicted-risk endpoints for this step — orange/purple edge tint */
  cyberGlowIds?: Set<string>
  cyberRisk?: Record<string, string | null>
  /** Resting state for the full graph: edges barely visible, nodes untouched */
  faded?: boolean
  onEdgeClick?: (key: string) => void
}) {
  const raycaster = useThree((s) => s.raycaster)
  useEffect(() => {
    raycaster.params.Line = { threshold: 0.65 }
  }, [raycaster])

  const defaultColor = isDark ? "#ffffff" : "#333333"
  const dimFactor = dimmed ? 0.3 : 1

  const prepared = useMemo(() => {
    const seen = new Set<string>()
    const list: { key: string; s: [number, number, number]; t: [number, number, number]; spec: EdgeSpec; delay: number; color: THREE.Color; alpha: number }[] = []
    const dist = new Map<string, number>()
    if (centerNodeId) {
      const adj = new Map<string, string[]>()
      for (const e of edges) {
        if (!adj.has(e.source)) adj.set(e.source, [])
        if (!adj.has(e.target)) adj.set(e.target, [])
        adj.get(e.source)!.push(e.target)
        adj.get(e.target)!.push(e.source)
      }
      dist.set(centerNodeId, 0)
      const q = [centerNodeId]
      for (let qi = 0; qi < q.length; qi++) {
        const d = dist.get(q[qi])!
        for (const nb of adj.get(q[qi]) ?? []) if (!dist.has(nb)) { dist.set(nb, d + 1); q.push(nb) }
      }
    }
    edges.forEach((e, i) => {
      const key = `${e.source}::${e.target}::${e.type || ""}`
      if (seen.has(key)) return
      const s = posMap.get(e.source)
      const t = posMap.get(e.target)
      if (!s || !t) return
      seen.add(key)
      const custom = colorMap?.get(`${e.source}::${e.target}`)
      const d = centerNodeId ? Math.min(dist.get(e.source) ?? 99, dist.get(e.target) ?? 99) : 0
      list.push({
        key,
        s,
        t,
        spec: e,
        delay: dimmed ? 0 : centerNodeId ? 0.3 + d * 0.3 : Math.min(1.5, i * 0.002),
        color: new THREE.Color(custom ?? defaultColor),
        alpha: (faded
          ? custom ? (isDark ? 0.018 : 0.07) : isDark ? 0.012 : 0.05
          : custom ? (isDark ? 0.5 : 0.85) : isDark ? 0.15 : 0.5) * dimFactor,
      })
    })
    return list
  }, [edges, posMap, colorMap, centerNodeId, defaultColor, dimFactor, dimmed, isDark, faded])

  const n = prepared.length
  const geometry = useMemo(() => {
    const g = new THREE.BufferGeometry()
    const pos = new Float32Array(n * 6)
    prepared.forEach((e, i) => {
      pos.set(e.s, i * 6)
      pos.set(e.s, i * 6 + 3)
    })
    g.setAttribute("position", new THREE.BufferAttribute(pos, 3))
    g.setAttribute("color", new THREE.BufferAttribute(new Float32Array(n * 8), 4))
    return g
  }, [prepared, n])
  useEffect(() => () => geometry.dispose(), [geometry])

  const known = useRef<Set<string>>(new Set())
  const grow = useRef<Float32Array>(new Float32Array(0))
  const growStart = useRef<Float32Array>(new Float32Array(0))
  const curA = useRef<Float32Array>(new Float32Array(0))
  const curM = useRef<Float32Array>(new Float32Array(0))
  const needsInit = useRef(true)

  useEffect(() => {
    grow.current = new Float32Array(n)
    growStart.current = new Float32Array(n).fill(-1)
    curA.current = new Float32Array(n)
    curM.current = new Float32Array(n).fill(1)
    needsInit.current = true
  }, [n, prepared])

  const removed = useMemo(() => {
    const flags = new Uint8Array(n)
    prepared.forEach((e, i) => {
      const { source: s, target: t } = e.spec
      if (retiredIds && (retiredIds.has(s) || retiredIds.has(t))) flags[i] = 1
      else if (removedKeys && removedKeys.size > 0 && (removedKeys.has(e.key) || removedKeys.has(`${s}::${t}`) || removedKeys.has(`${t}::${s}`))) flags[i] = 1
    })
    return flags
  }, [prepared, n, removedKeys, retiredIds])

  const glow = useMemo(() => {
    const flags = new Uint8Array(n)
    if (!glowKeys || glowKeys.size === 0) return flags
    prepared.forEach((e, i) => {
      const { source: s, target: t } = e.spec
      if (glowKeys.has(e.key) || glowKeys.has(`${s}::${t}`) || glowKeys.has(`${t}::${s}`)) flags[i] = 1
    })
    return flags
  }, [prepared, n, glowKeys])

  const flashing = useMemo(() => {
    if (!flashingKeys || flashingKeys.size === 0) return []
    return prepared.filter((e) => flashingKeys.has(e.key) || flashingKeys.has(`${e.spec.source}::${e.spec.target}`))
  }, [prepared, flashingKeys])

  useFrame(({ clock }, delta) => {
    const now = clock.getElapsedTime()
    const pos = geometry.getAttribute("position") as THREE.BufferAttribute
    const col = geometry.getAttribute("color") as THREE.BufferAttribute
    const P = pos.array as Float32Array
    const C = col.array as Float32Array
    if (grow.current.length !== n) return
    let posDirty = false
    let colDirty = false
    const k = Math.min(1, delta * 5)

    if (needsInit.current) {
      const firstMount = known.current.size === 0
      prepared.forEach((e, i) => {
        const seenBefore = known.current.has(e.key)
        growStart.current[i] = seenBefore || !firstMount ? now - GROW_DURATION : now + e.delay
        known.current.add(e.key)
      })
      needsInit.current = false
    }

    for (let i = 0; i < n; i++) {
      const e = prepared[i]
      let g = grow.current[i]
      if (g < 1) {
        g = Math.min(1, Math.max(0, (now - growStart.current[i]) / GROW_DURATION))
        if (g !== grow.current[i]) {
          grow.current[i] = g
          const o = i * 6
          P[o + 3] = e.s[0] + (e.t[0] - e.s[0]) * g
          P[o + 4] = e.s[1] + (e.t[1] - e.s[1]) * g
          P[o + 5] = e.s[2] + (e.t[2] - e.s[2]) * g
          posDirty = true
        }
      }
      const isGlow = !!glow[i]
      let risk: "orange" | "purple" | null = null
      if (isGlow && cyberGlowIds && cyberRisk) {
        const rs = cyberGlowIds.has(e.spec.source) ? cyberRisk[e.spec.source] : null
        const rt = cyberGlowIds.has(e.spec.target) ? cyberRisk[e.spec.target] : null
        if (rs === "purple" || rt === "purple") risk = "purple"
        else if (rs === "orange" || rt === "orange") risk = "orange"
      }
      const targetA = isGlow ? 1 : e.alpha * (removed[i] ? (faded ? 0.4 : 0) : 1)
      const targetM = isGlow ? (risk ? 3.6 : 1.7) : 1
      let a = curA.current[i]
      let m = curM.current[i]
      if (Math.abs(a - targetA) > 0.002) a += (targetA - a) * k
      else a = targetA
      if (Math.abs(m - targetM) > 0.01) m += (targetM - m) * k
      else m = targetM
      const outA = a * g
      const o = i * 8
      const baseR = risk === "orange" ? 0.98 : risk === "purple" ? 0.66 : isGlow ? 0.22 : e.color.r
      const baseG = risk === "orange" ? 0.45 : risk === "purple" ? 0.33 : isGlow ? 0.74 : e.color.g
      const baseB = risk === "orange" ? 0.09 : risk === "purple" ? 0.97 : isGlow ? 0.98 : e.color.b
      if (a !== curA.current[i] || m !== curM.current[i] || C[o + 3] !== outA || isGlow) {
        curA.current[i] = a
        curM.current[i] = m
        C[o] = C[o + 4] = baseR * m
        C[o + 1] = C[o + 5] = baseG * m
        C[o + 2] = C[o + 6] = baseB * m
        C[o + 3] = C[o + 7] = outA
        colDirty = true
      }
    }
    if (posDirty) {
      pos.needsUpdate = true
      geometry.computeBoundingSphere()
    }
    if (colDirty) col.needsUpdate = true
  })

  const handleClick = (ev: ThreeEvent<MouseEvent>) => {
    if (!onEdgeClick || ev.index == null) return
    const i = Math.floor(ev.index / 2)
    if (!prepared[i]) return
    ev.stopPropagation()
    onEdgeClick(prepared[i].key)
  }

  return (
    <>
      <lineSegments geometry={geometry} onClick={onEdgeClick ? handleClick : undefined} frustumCulled={false}>
        <lineBasicMaterial vertexColors transparent depthWrite={false} toneMapped={false} />
      </lineSegments>
      {flashing.map((e) => (
        <FlashEdge key={e.key} start={e.s} end={e.t} />
      ))}
    </>
  )
}

function FlashEdge({ start, end }: { start: [number, number, number]; end: [number, number, number] }) {
  const ref = useRef<{ material: THREE.Material & { opacity: number } } | null>(null)
  useFrame(() => {
    if (ref.current) ref.current.material.opacity = 0.45 + 0.55 * Math.abs(Math.sin(performance.now() / 180))
  })
  return (
    <Line
      ref={ref as never}
      points={[start, end]}
      color="#ef4444"
      lineWidth={2}
      transparent
      dashed
      dashSize={0.35}
      gapSize={0.22}
    />
  )
}
