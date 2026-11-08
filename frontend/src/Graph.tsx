import { useEffect, useLayoutEffect, useMemo, useRef, type RefObject } from "react"
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

function NodeCloud({ nodes, hops, migrated, onSelect, overlay = "none", focus = false, labelIds = [], onHover }: Props) {
  const mesh = useRef<THREE.InstancedMesh>(null)
  const dummy = useMemo(() => new THREE.Object3D(), [])
  const color = useMemo(() => new THREE.Color(), [])
  const bg = useMemo(() => new THREE.Color("#07080c"), [])
  const cur = useRef<{ x: number; y: number; z: number; s: number; r: number; g: number; b: number }[]>([])

  const targets = useMemo(() => {
    const active = Object.keys(hops).length > 0
    return nodes.map((n) => {
      const h = hops[n.id]
      let hex = kindColor(n, migrated, overlay)
      let scale = n.kind === "cluster" ? 0.62 + Math.min(0.35, (n.degree || 1) / 80) : n.hub ? 0.28 : 0.16
      let mix = 0
      if (focus || active) {
        if (!h) mix = 0.9
        else if (h.dir === "focus") { hex = "#fff6e4"; scale *= 1.35; mix = 0 }
        else if (h.dir === "down") { hex = h.hop <= 1 ? "#e1a54a" : "#a86b32"; scale *= 1.15 }
        else { hex = h.hop <= 1 ? "#9ec1ff" : "#5d7eab"; scale *= 1.1 }
      }
      color.set(hex)
      return {
        x: n.x, y: n.y, z: n.z, s: scale,
        r: color.r * (1 - mix) + bg.r * mix,
        g: color.g * (1 - mix) + bg.g * mix,
        b: color.b * (1 - mix) + bg.b * mix,
      }
    })
  }, [nodes, hops, migrated, color, bg])

  useLayoutEffect(() => {
    const m = mesh.current
    if (!m) return
    cur.current = targets.map((t) => ({ ...t }))
    targets.forEach((t, i) => {
      dummy.position.set(t.x, t.y, t.z)
      dummy.scale.setScalar(Math.max(0.02, t.s))
      dummy.updateMatrix()
      m.setMatrixAt(i, dummy.matrix)
      color.setRGB(t.r, t.g, t.b)
      m.setColorAt(i, color)
    })
    m.count = Math.min(targets.length, 2048)
    m.instanceMatrix.needsUpdate = true
    if (m.instanceColor) m.instanceColor.needsUpdate = true
  }, [targets, color, dummy])

  useFrame((_, dt) => {
    const m = mesh.current
    if (!m) return
    const k = 1 - Math.exp(-6 * dt)
    targets.forEach((t, i) => {
      const c = cur.current[i] || (cur.current[i] = { ...t })
      c.x += (t.x - c.x) * k
      c.y += (t.y - c.y) * k
      c.z += (t.z - c.z) * k
      c.s += (t.s - c.s) * k
      c.r += (t.r - c.r) * k
      c.g += (t.g - c.g) * k
      c.b += (t.b - c.b) * k
      dummy.position.set(c.x, c.y, c.z)
      dummy.scale.setScalar(Math.max(0.02, c.s))
      dummy.updateMatrix()
      m.setMatrixAt(i, dummy.matrix)
      color.setRGB(c.r, c.g, c.b)
      m.setColorAt(i, color)
    })
    m.count = Math.min(targets.length, 2048)
    m.instanceMatrix.needsUpdate = true
    if (m.instanceColor) m.instanceColor.needsUpdate = true
  })

  const geom = useMemo(() => new THREE.SphereGeometry(1, 12, 12), [])
  const mat = useMemo(() => new THREE.MeshBasicMaterial({ toneMapped: false }), [])

  return (
    <>
      <instancedMesh
        ref={mesh}
        args={[geom, mat, 2048]}
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
      >
      </instancedMesh>
    </>
  )
}

function projectLabel(n: GraphNode, camera: THREE.Camera, width: number, height: number) {
  const v = new THREE.Vector3(n.x, n.y + 0.7, n.z).project(camera)
  if (v.z > 1) return null
  return { x: (v.x * 0.5 + 0.5) * width, y: (-v.y * 0.5 + 0.5) * height }
}

function LabelLayer({ nodes, labelIds = [] }: Props) {
  const { camera, size } = useThree()
  const el = useMemo(() => document.createElement("div"), [])
  const place = () => {
    const shown = nodes.filter((n) => n.kind === "cluster" || labelIds.includes(n.id)).slice(0, 40)
    const next = shown.map((n) => {
      const p = projectLabel(n, camera, size.width, size.height)
      const raw = n.name.length > 22 ? n.name.slice(0, 20) + "…" : n.name
      const text = raw.replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c] || c))
      return p ? `<div class="${n.kind === "cluster" ? "glabel" : "glabel unit"}" style="transform:translate(${p.x}px,${p.y}px) translate(-50%,-50%)">${text}</div>` : ""
    }).join("")
    if (el.dataset.html !== next) {
      el.dataset.html = next
      el.innerHTML = next
    }
  }
  useLayoutEffect(() => {
    try {
      if (!el.isConnected) {
        el.className = "label-layer"
        document.querySelector(".graph-stage")?.appendChild(el)
      }
      place()
    } catch (err) {
      el.className = "label-layer"
      document.querySelector(".graph-stage")?.appendChild(el)
      el.textContent = String(err)
    }
    return () => el.remove()
  })
  useFrame(() => {
    try { place() } catch { /* layout effect reports it */ }
  })
  return null
}

function EdgeBadges({ nodes, edges }: Props) {
  const { camera, size } = useThree()
  const pos = useMemo(() => new Map(nodes.map((n) => [n.id, n])), [nodes])
  const el = useMemo(() => document.createElement("div"), [])
  useLayoutEffect(() => {
    el.className = "label-layer badges"
    document.querySelector(".graph-stage")?.appendChild(el)
    return () => el.remove()
  }, [el])
  useFrame(() => {
    const next = edges.slice(0, 18).map((e) => {
      const a = pos.get(e.source)
      const b = pos.get(e.target)
      if (!a || !b || (e.weight || 1) < 2) return ""
      const mid = { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2, z: (a.z + b.z) / 2, name: String(e.weight), kind: "badge" } as GraphNode
      const p = projectLabel(mid, camera, size.width, size.height)
      return p ? `<div class="ebadge" style="transform:translate(${p.x}px,${p.y}px) translate(-50%,-50%)">${e.weight}</div>` : ""
    }).join("")
    if (el.dataset.html !== next) {
      el.dataset.html = next
      el.innerHTML = next
    }
  })
  return null
}

function Edges({ nodes, edges, hops }: Props) {
  const geom = useRef<THREE.BufferGeometry>(null)
  const posMap = useMemo(() => new Map(nodes.map((n) => [n.id, n])), [nodes])
  const started = useRef(performance.now() - 3000)
  useEffect(() => { started.current = performance.now() }, [hops, edges])

  const segs = useMemo(() => {
    const list: { x1: number; y1: number; z1: number; x2: number; y2: number; z2: number; color: THREE.Color; hop: number; dashed: boolean }[] = []
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
      for (let c = 0; c < copies; c++) {
        const off = (c - (copies - 1) / 2) * 0.08
        list.push({
          x1: a.x, y1: a.y + off, z1: a.z, x2: b.x, y2: b.y + off, z2: b.z,
          color: new THREE.Color(hex), hop, dashed: !e.proved || !!e.dynamic || e.visual === "added",
        })
      }
    }
    return list
  }, [edges, posMap, hops])

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
        for (let k = 0; k < 2; k++) {
          color[cptr++] = s.color.r; color[cptr++] = s.color.g; color[cptr++] = s.color.b
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

export function GraphCanvas(props: Props) {
  const labelHost = useRef<HTMLDivElement>(null)
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
  useLayoutEffect(() => {
    const host = labelHost.current
    if (!host) return
    const canvas = host.parentElement?.querySelector("canvas")
    const width = canvas?.clientWidth || 760
    const height = canvas?.clientHeight || 800
    const cam = new THREE.PerspectiveCamera(props.topdown ? 32 : 32, width / height, 0.1, 900)
    if (props.topdown) cam.position.set(center[0], 48, center[2] + 0.01)
    else cam.position.set(center[0], center[1], center[2] + 42)
    cam.lookAt(center[0], center[1], center[2])
    cam.updateProjectionMatrix()
    cam.updateMatrixWorld()
    const labels = props.nodes.filter((n) => n.kind === "cluster" || (props.labelIds || []).includes(n.id)).slice(0, 40)
    const nodeHtml = labels.map((n) => {
      const p = projectLabel(n, cam, width, height)
      if (!p) return ""
      const raw = n.name.length > 22 ? n.name.slice(0, 20) + "…" : n.name
      const text = raw.replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c] || c))
      return `<div class="${n.kind === "cluster" ? "glabel" : "glabel unit"}" data-id="${n.id}" style="transform:translate(${p.x}px,${p.y}px) translate(-50%,-50%)">${text}</div>`
    }).join("")
    const byId = new Map(props.nodes.map((n) => [n.id, n]))
    const badgeHtml = props.edges.filter((e) => (e.weight || 1) >= 2).slice(0, 12).map((e) => {
      const a = byId.get(e.source)
      const b = byId.get(e.target)
      if (!a || !b) return ""
      const mid = { ...a, x: (a.x + b.x) / 2, y: (a.y + b.y) / 2, z: (a.z + b.z) / 2 }
      const p = projectLabel(mid, cam, width, height)
      return p ? `<div class="ebadge" style="transform:translate(${p.x}px,${p.y}px) translate(-50%,-140%)">${e.weight}</div>` : ""
    }).join("")
    host.innerHTML = nodeHtml + badgeHtml
    host.onclick = (ev) => {
      const id = (ev.target as HTMLElement).dataset?.id
      if (id) props.onSelect(id)
    }
  }, [props.nodes, props.edges, props.labelIds, props.topdown, props.onSelect, center])
  return (
    <div className="graph-stage">
    <Canvas
      style={{ width: "100%", height: "100%" }}
      key={(props.topdown ? "top" : "persp") + ":" + props.nodes.length + ":" + (props.nodes[0]?.id || "")}
      camera={{ position: props.topdown ? [center[0], 48, center[2] + 0.01] : [center[0], center[1], center[2] + 42], fov: 32, near: 0.1, far: 400 }}
      onCreated={({ camera }) => camera.lookAt(center[0], center[1], center[2])}
      onPointerMissed={() => props.onSelect("")}
    >
      <color attach="background" args={["#07080c"]} />
      <NodeCloud {...props} />
      <Edges {...props} />
      <OrbitControls target={center} enableDamping dampingFactor={0.12} maxDistance={radius * 6} minDistance={2} />
    </Canvas>
    <div className="label-layer" ref={labelHost} />
    </div>
  )
}

export function edgeLegend() {
  return Object.entries(EDGE)
}
