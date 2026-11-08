import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react"
import { Canvas, useFrame, useThree } from "@react-three/fiber"
import { OrbitControls } from "@react-three/drei"
import * as THREE from "three"
import type { GraphEdge, GraphNode } from "./types"

const KIND: Record<string, string> = {
  program: "#9ec1ff",
  copybook: "#5ec8c5",
  dataset: "#8fd18a",
  job: "#d2a2e0",
  transaction: "#f0a36a",
  screen: "#f0a3c2",
  interface: "#d6e38a",
}

const EDGE: Record<string, string> = {
  COPY: "#5ec8c5",
  CALL: "#c4b5fd",
  LINK: "#a78bfa",
  XCTL: "#f0a3c2",
  FILE: "#8fd18a",
  JOB: "#e1a54a",
  TRANS: "#f0a36a",
  SCREEN: "#9ec1ff",
}

export interface Hop {
  hop: number
  dir: "focus" | "down" | "up"
}

interface Props {
  nodes: GraphNode[]
  edges: Array<GraphEdge & { visual?: "keep" | "removed" | "added"; weight?: number }>
  hops: Record<string, Hop>
  migrated: Set<string>
  onSelect: (id: string) => void
  overlay?: string
  focus?: boolean
  topdown?: boolean
  labelIds?: string[]
  onHover?: (id: string | null) => void
  fitKey?: string
}

function heat(t: number) {
  if (t >= 0.66) return "#e07a6a"
  if (t >= 0.33) return "#e1a54a"
  return "#8fd18a"
}

function kindColor(n: GraphNode, migrated: Set<string>, overlay: string) {
  if (overlay === "legacy") return migrated.has(n.id) || n.status === "modern" ? "#8fd18a" : "#8a8175"
  if (overlay === "risk") return heat(Math.max(0, Math.min(1, n.risk || 0)))
  if (overlay === "quality") return heat(Math.max(0, Math.min(1, (n.qualityCount || 0) / 12)))
  if (overlay === "blast") return heat(Math.max(0, Math.min(1, (n.blast || n.degree || 0) / 40)))
  if (overlay === "ledger") return n.ledger == null ? "#6a655c" : heat(1 - n.ledger)
  if (overlay === "prover") return heat(1 - (n.provedRatio ?? 1))
  if (n.kind === "cluster") return "#d6c7a1"
  if (n.kind === "interface" || n.status === "modern") return "#d6e38a"
  if (migrated.has(n.id)) return "#8fd18a"
  if (n.external) return "#6a655c"
  if (n.kind === "program" && n.subtype === "batch") return "#e1a54a"
  return KIND[n.kind] || "#b7b2a8"
}

type Sample = { x: number; y: number; z: number; s: number; r: number; g: number; b: number }

function sceneRadiusOf(nodes: GraphNode[]) {
  if (!nodes.length) return 8
  let x = 0, y = 0, z = 0
  for (const n of nodes) { x += n.x; y += n.y; z += n.z }
  const k = nodes.length
  const c = [x / k, y / k, z / k]
  let m = 8
  for (const n of nodes) {
    const d = Math.hypot(n.x - c[0], n.y - c[1], n.z - c[2])
    if (d > m) m = d
  }
  return m
}

function NodeCloud({ nodes, hops, migrated, onSelect, overlay = "none", focus = false, onHover }: Props) {
  const mesh = useRef<THREE.InstancedMesh>(null)
  const dummy = useMemo(() => new THREE.Object3D(), [])
  const color = useMemo(() => new THREE.Color(), [])
  const bg = useMemo(() => new THREE.Color("#07080c"), [])
  const cur = useRef<Map<string, Sample>>(new Map())
  const capacity = Math.max(nodes.length, 1)
  const radius = useMemo(() => sceneRadiusOf(nodes), [nodes])

  const targets = useMemo(() => {
    const active = Object.keys(hops).length > 0
    const base = Math.max(0.16, radius * 0.014)
    return nodes.map((n) => {
      const h = hops[n.id]
      let hex = kindColor(n, migrated, overlay)
      let scale = base * Math.sqrt(1 + (n.degree || 1)) / Math.sqrt(8)
      if (n.kind === "cluster") scale *= 1.8
      if (n.hub) scale *= 1.25
      scale = Math.max(base * 0.55, Math.min(base * 3.2, scale))
      let mix = n.muted ? 0.72 : 0
      if (focus || active) {
        if (!h) mix = Math.max(mix, 0.9)
        else if (h.dir === "focus") { hex = "#fff6e4"; scale *= 1.35; mix = 0 }
        else if (h.dir === "down") { hex = h.hop <= 1 ? "#e1a54a" : "#a86b32"; scale *= 1.15; mix = 0 }
        else { hex = h.hop <= 1 ? "#9ec1ff" : "#5d7eab"; scale *= 1.1; mix = 0 }
      }
      color.set(hex)
      return {
        id: n.id,
        x: n.x, y: n.y, z: n.z, s: scale,
        r: color.r * (1 - mix) + bg.r * mix,
        g: color.g * (1 - mix) + bg.g * mix,
        b: color.b * (1 - mix) + bg.b * mix,
      }
    })
  }, [nodes, hops, migrated, overlay, focus, color, bg, radius])

  useFrame((_, dt) => {
    const m = mesh.current
    if (!m) return
    const k = 1 - Math.exp(-6 * dt)
    const next = new Map<string, Sample>()
    targets.forEach((t, i) => {
      const prev = cur.current.get(t.id)
      const c = prev
        ? { x: prev.x, y: prev.y, z: prev.z, s: prev.s, r: prev.r, g: prev.g, b: prev.b }
        : { x: t.x, y: t.y, z: t.z, s: 0, r: t.r, g: t.g, b: t.b }
      c.x += (t.x - c.x) * k
      c.y += (t.y - c.y) * k
      c.z += (t.z - c.z) * k
      c.s += (t.s - c.s) * k
      c.r += (t.r - c.r) * k
      c.g += (t.g - c.g) * k
      c.b += (t.b - c.b) * k
      next.set(t.id, c)
      dummy.position.set(c.x, c.y, c.z)
      dummy.scale.setScalar(Math.max(0.001, c.s))
      dummy.updateMatrix()
      m.setMatrixAt(i, dummy.matrix)
      color.setRGB(c.r, c.g, c.b)
      m.setColorAt(i, color)
    })
    cur.current = next
    m.count = targets.length
    m.instanceMatrix.needsUpdate = true
    if (m.instanceColor) m.instanceColor.needsUpdate = true
  })

  const geom = useMemo(() => new THREE.SphereGeometry(1, 12, 12), [])
  const mat = useMemo(() => new THREE.MeshBasicMaterial({ toneMapped: false }), [])

  return (
    <instancedMesh
      key={capacity}
      ref={mesh}
      args={[geom, mat, capacity]}
      onClick={(e) => {
        e.stopPropagation()
        const i = e.instanceId
        if (i == null || !nodes[i]) return
        onSelect(nodes[i].id)
      }}
      onPointerMove={(e) => {
        e.stopPropagation()
        const i = e.instanceId
        if (i == null || !nodes[i]) return
        onHover?.(nodes[i].id)
      }}
      onPointerOut={() => onHover?.(null)}
    />
  )
}

function Labels({ nodes, hops, labelIds = [], onPlace }: Props & { onPlace: (rows: { id: string; name: string; x: number; y: number }[]) => void }) {
  const { camera, size } = useThree()
  const sig = useRef("")
  const placeRef = useRef(onPlace)
  placeRef.current = onPlace
  useFrame(() => {
    const wanted = new Map<string, GraphNode>()
    for (const n of nodes) if (n.kind === "cluster") wanted.set(n.id, n)
    for (const id of labelIds) {
      const n = nodes.find((x) => x.id === id)
      if (n) wanted.set(n.id, n)
    }
    for (const n of nodes) {
      const h = hops[n.id]
      if (h && (h.dir === "focus" || h.hop <= 1)) wanted.set(n.id, n)
    }
    const ranked = [...wanted.values()].sort((a, b) => (b.degree || 0) - (a.degree || 0) || a.name.localeCompare(b.name))
    const kept: { id: string; name: string; x: number; y: number; r: number; b: number }[] = []
    for (const n of ranked) {
      if (kept.length >= 14) break
      const v = new THREE.Vector3(n.x, n.y + 0.4, n.z).project(camera)
      if (v.z > 1) continue
      const x = (v.x * 0.5 + 0.5) * size.width
      const y = (-v.y * 0.5 + 0.5) * size.height
      const w = Math.min(140, 8 + n.name.length * 7)
      const box = { l: x - w / 2, t: y - 9, r: x + w / 2, b: y + 9 }
      const hit = kept.some((k) => box.l < k.r && k.x - (k.r - k.x) < box.r && box.t < k.b && k.y - 9 < box.b)
      if (hit) continue
      kept.push({ id: n.id, name: n.name.length > 28 ? n.name.slice(0, 26) + "…" : n.name, x, y, r: box.r, b: box.b })
    }
    const next = kept.map((k) => `${k.id}@${Math.round(k.x)}:${Math.round(k.y)}`).join("|")
    if (next === sig.current) return
    sig.current = next
    placeRef.current(kept.map(({ id, name, x, y }) => ({ id, name, x, y })))
  })
  return null
}

function edgeOffset(a: GraphNode, b: GraphNode, topdown: boolean) {
  const dx = b.x - a.x
  const dy = b.y - a.y
  const dz = b.z - a.z
  if (topdown) {
    const len = Math.hypot(dx, dz) || 1
    return { x: -dz / len, y: 0, z: dx / len }
  }
  const cx = dy * 0 - dz * 1
  const cy = dz * 0 - dx * 0
  const cz = dx * 1 - dy * 0
  const len = Math.hypot(cx, cy, cz) || 1
  return { x: cx / len, y: cy / len, z: cz / len }
}

function provedRatio(e: Props["edges"][number]) {
  const n = e.weight || 1
  const k = e.proved_count ?? (e.proved ? n : 0)
  return { k, n, ratio: k / n }
}

function Edges({ nodes, edges, hops, topdown = false }: Props) {
  const geom = useRef<THREE.BufferGeometry>(null)
  const posMap = useMemo(() => new Map(nodes.map((n) => [n.id, n])), [nodes])
  const started = useRef(performance.now() - 3000)
  useEffect(() => { started.current = performance.now() }, [hops, edges])

  const segs = useMemo(() => {
    const list: { x1: number; y1: number; z1: number; x2: number; y2: number; z2: number; color: THREE.Color; hop: number; dashed: boolean; ghost: boolean }[] = []
    const active = Object.keys(hops).length > 0
    for (const e of edges) {
      const a = posMap.get(e.source)
      const b = posMap.get(e.target)
      if (!a || !b) continue
      const inPath = hops[e.source] && hops[e.target]
      let hex = EDGE[e.type] || "#888"
      if (e.visual === "removed") hex = "#e07a6a"
      else if (e.visual === "added") hex = "#8fd18a"
      else if (active && !inPath) hex = "#24282e"
      const hop = inPath ? Math.max(hops[e.source].hop, hops[e.target].hop) : 0
      const copies = Math.min(4, Math.max(1, Math.round(Math.log2((e.weight || 1) + 1))))
      const perp = edgeOffset(a, b, topdown)
      const { ratio } = provedRatio(e)
      const dashed = ratio < 0.5
      for (let c = 0; c < copies; c++) {
        const off = (c - (copies - 1) / 2) * 0.12
        list.push({
          x1: a.x + perp.x * off, y1: a.y + perp.y * off, z1: a.z + perp.z * off,
          x2: b.x + perp.x * off, y2: b.y + perp.y * off, z2: b.z + perp.z * off,
          color: new THREE.Color(hex), hop, dashed, ghost: e.visual === "removed",
        })
      }
    }
    return list
  }, [edges, posMap, hops, topdown])

  const capacity = Math.max(8, segs.reduce((n, s) => n + (s.dashed ? 4 : 1), 0))
  const position = useMemo(() => new Float32Array(capacity * 2 * 3), [capacity])
  const color = useMemo(() => new Float32Array(capacity * 2 * 3), [capacity])

  const draw = () => {
    const g = geom.current
    if (!g) return
    const elapsed = (performance.now() - started.current) / 1000
    let ptr = 0
    let cptr = 0
    let count = 0
    for (const s of segs) {
      const grow = Math.max(0, Math.min(1, (elapsed - s.hop * 0.18) / 0.35))
      const pieces = s.dashed ? 4 : 1
      for (let p = 0; p < pieces; p++) {
        const a0 = s.dashed ? p / pieces : 0
        const a1 = s.dashed ? (p + 0.55) / pieces : 1
        if (grow <= a0) continue
        const end = Math.min(a1, grow)
        const x1 = s.x1 + (s.x2 - s.x1) * a0
        const y1 = s.y1 + (s.y2 - s.y1) * a0
        const z1 = s.z1 + (s.z2 - s.z1) * a0
        const x2 = s.x1 + (s.x2 - s.x1) * end
        const y2 = s.y1 + (s.y2 - s.y1) * end
        const z2 = s.z1 + (s.z2 - s.z1) * end
        position[ptr++] = x1; position[ptr++] = y1; position[ptr++] = z1
        position[ptr++] = x2; position[ptr++] = y2; position[ptr++] = z2
        const fade = s.ghost ? Math.max(0.2, 1 - elapsed) : 1
        for (let k = 0; k < 2; k++) {
          color[cptr++] = s.color.r * fade; color[cptr++] = s.color.g * fade; color[cptr++] = s.color.b * fade
        }
        count++
      }
    }
    const posAttr = g.getAttribute("position") as THREE.BufferAttribute
    const colAttr = g.getAttribute("color") as THREE.BufferAttribute
    posAttr.needsUpdate = true
    colAttr.needsUpdate = true
    g.setDrawRange(0, count * 2)
  }
  useLayoutEffect(draw)
  useFrame(draw)

  return (
    <lineSegments key={capacity}>
      <bufferGeometry ref={geom}>
        <bufferAttribute attach="attributes-position" args={[position, 3]} count={capacity * 2} />
        <bufferAttribute attach="attributes-color" args={[color, 3]} count={capacity * 2} />
      </bufferGeometry>
      <lineBasicMaterial vertexColors transparent opacity={0.9} toneMapped={false} />
    </lineSegments>
  )
}

function Arrows({ nodes, edges }: Props) {
  const mesh = useRef<THREE.InstancedMesh>(null)
  const dummy = useMemo(() => new THREE.Object3D(), [])
  const up = useMemo(() => new THREE.Vector3(0, 1, 0), [])
  const dir = useMemo(() => new THREE.Vector3(), [])
  const tint = useMemo(() => new THREE.Color(), [])
  const list = useMemo(() => {
    const pos = new Map(nodes.map((n) => [n.id, n]))
    const out: { x: number; y: number; z: number; dx: number; dy: number; dz: number; color: string }[] = []
    for (const e of edges) {
      if (e.visual === "removed") continue
      const a = pos.get(e.source)
      const b = pos.get(e.target)
      if (!a || !b) continue
      const dx = b.x - a.x
      const dy = b.y - a.y
      const dz = b.z - a.z
      const len = Math.hypot(dx, dy, dz) || 1
      out.push({
        x: a.x + dx * 0.84, y: a.y + dy * 0.84, z: a.z + dz * 0.84,
        dx: dx / len, dy: dy / len, dz: dz / len,
        color: e.visual === "added" ? "#8fd18a" : (EDGE[e.type] || "#6a655c"),
      })
    }
    return out
  }, [nodes, edges])
  useFrame(() => {
    const m = mesh.current
    if (!m) return
    list.forEach((a, i) => {
      dummy.position.set(a.x, a.y, a.z)
      dir.set(a.dx, a.dy, a.dz)
      if (dir.lengthSq() < 1e-8) return
      dummy.quaternion.setFromUnitVectors(up, dir)
      dummy.scale.set(0.07, 0.2, 0.07)
      dummy.updateMatrix()
      m.setMatrixAt(i, dummy.matrix)
      tint.set(a.color)
      m.setColorAt(i, tint)
    })
    m.count = list.length
    m.instanceMatrix.needsUpdate = true
    if (m.instanceColor) m.instanceColor.needsUpdate = true
  })
  const cap = Math.max(list.length, 1)
  const geom = useMemo(() => new THREE.ConeGeometry(1, 1, 5), [])
  const mat = useMemo(() => new THREE.MeshBasicMaterial({ toneMapped: false }), [])
  return <instancedMesh key={cap} ref={mesh} args={[geom, mat, cap]} />
}

function CameraFit({ center, radius, topdown, fitKey }: { center: [number, number, number]; radius: number; topdown: boolean; fitKey: string }) {
  const { camera, controls } = useThree()
  const fitted = useRef("")
  const goal = useRef(new THREE.Vector3(center[0], center[1], center[2]))
  useFrame((_, dt) => {
    const orbit = controls as { target?: THREE.Vector3; enableRotate?: boolean; update?: () => void } | null
    if (!orbit?.target) return
    if (fitted.current !== fitKey) {
      fitted.current = fitKey
      camera.up.set(topdown ? 0 : 0, topdown ? 0 : 1, topdown ? -1 : 0)
      if (topdown) {
        camera.position.set(center[0], center[1] + Math.max(radius * 2.4, 12), center[2])
        orbit.enableRotate = false
      } else {
        const fov = "fov" in camera ? (camera as THREE.PerspectiveCamera).fov : 46
        const dist = radius / Math.tan((fov * Math.PI / 180) / 2) * 0.62
        camera.position.set(center[0] + dist * 0.18, center[1] + dist * 0.32, center[2] + dist)
        orbit.enableRotate = true
      }
      camera.near = 0.05
      camera.far = Math.max(800, radius * 24)
      camera.lookAt(center[0], center[1], center[2])
      camera.updateProjectionMatrix()
      orbit.target.set(center[0], center[1], center[2])
      goal.current.set(center[0], center[1], center[2])
      orbit.update?.()
      return
    }
    goal.current.set(center[0], center[1], center[2])
    const k = 1 - Math.exp(-4 * dt)
    orbit.target.lerp(goal.current, k)
  })
  return null
}

export function GraphCanvas(props: Props) {
  const [placed, setPlaced] = useState<{ id: string; name: string; x: number; y: number }[]>([])
  const drag = useRef({ x: 0, y: 0, moved: false })
  const center = useMemo(() => {
    if (!props.nodes.length) return [0, 0, 0] as [number, number, number]
    let x = 0, y = 0, z = 0
    for (const n of props.nodes) { x += n.x; y += n.y; z += n.z }
    const k = props.nodes.length
    return [x / k, y / k, z / k] as [number, number, number]
  }, [props.nodes])
  const radius = useMemo(() => {
    let m = 8
    for (const n of props.nodes) {
      const d = Math.hypot(n.x - center[0], n.y - center[1], n.z - center[2])
      if (d > m) m = d
    }
    return m
  }, [props.nodes, center])
  const fitKey = props.fitKey || (props.topdown ? "top" : "persp")
  const tip = useMemo(() => {
    const id = props.labelIds?.[0]
    if (!id) return ""
    const e = props.edges.find((edge) => (edge.weight || 1) > 1 && (edge.source === id || edge.target === id))
    if (!e) return ""
    const { k, n } = provedRatio(e)
    return `${k} of ${n} proved`
  }, [props.edges, props.labelIds])
  return (
    <div
      className="graph-stage"
      onPointerDown={(e) => { drag.current = { x: e.clientX, y: e.clientY, moved: false } }}
      onPointerMove={(e) => {
        if (Math.hypot(e.clientX - drag.current.x, e.clientY - drag.current.y) > 4) drag.current.moved = true
      }}
    >
      <Canvas
        style={{ width: "100%", height: "100%" }}
        key={props.topdown ? "top" : "persp"}
        camera={{ position: [18, 14, 28], fov: 46, near: 0.1, far: 800 }}
        onPointerMissed={() => {
          if (!drag.current.moved) props.onSelect("")
        }}
      >
        <color attach="background" args={["#07080c"]} />
        <NodeCloud {...props} />
        <Edges {...props} />
        <Arrows {...props} />
        <Labels {...props} onPlace={setPlaced} />
        <CameraFit center={center} radius={radius} topdown={!!props.topdown} fitKey={fitKey} />
        <OrbitControls makeDefault enableDamping dampingFactor={0.12} maxDistance={radius * 6} minDistance={2} />
      </Canvas>
      <div className="label-layer">
        {placed.map((p) => (
          <div key={p.id} className="glabel" style={{ transform: `translate(${p.x}px, ${p.y}px) translate(-50%, -50%)` }}>{p.name}</div>
        ))}
        {tip && <div className="ebadge">{tip}</div>}
      </div>
    </div>
  )
}

export function edgeLegend() {
  return Object.entries(EDGE)
}
