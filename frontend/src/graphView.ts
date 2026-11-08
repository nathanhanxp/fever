import type { GraphEdge, GraphNode } from "./types"

export const EDGE_CAP = 18

export interface SceneEdge extends GraphEdge {
  visual?: "keep" | "removed" | "added"
  weight: number
  member_ids: string[]
}

export interface Scene {
  nodes: GraphNode[]
  edges: SceneEdge[]
  migrated: Set<string>
  hubCopybooks: number
  hiddenEdges: number
  mode: "clusters" | "units"
}

function posOf(n: GraphNode, layout: "layered" | "similarity" | "topdown"): [number, number, number] {
  const p = n.pos?.[layout]
  if (p && p.length === 3) return [p[0], p[1], p[2]]
  if (layout === "topdown") return [n.x, 0, n.z || n.y]
  return [n.x, n.y, n.z]
}

function separate(items: { x: number; z: number }[], minDist = 5) {
  for (let k = 0; k < 24; k++) {
    for (let i = 0; i < items.length; i++) {
      for (let j = i + 1; j < items.length; j++) {
        const dx = items[i].x - items[j].x
        const dz = items[i].z - items[j].z
        const dist = Math.hypot(dx, dz) || 0.001
        if (dist >= minDist) continue
        const push = (minDist - dist) / 2
        const ux = dx / dist
        const uz = dz / dist
        items[i].x += ux * push
        items[i].z += uz * push
        items[j].x -= ux * push
        items[j].z -= uz * push
      }
    }
  }
}

export function dominantType(edges: GraphEdge[]): string {
  const counts = new Map<string, number>()
  for (const e of edges) counts.set(e.type, (counts.get(e.type) || 0) + 1)
  let best = "COPY"
  let n = -1
  for (const [t, c] of counts) if (c > n) { best = t; n = c }
  return best
}

export function buildScene(opts: {
  nodes: GraphNode[]
  edges: Array<GraphEdge & { visual?: "keep" | "removed" | "added" }>
  layout: "layered" | "similarity" | "topdown"
  expanded: string | null
  hideHubs: boolean
  types: string[]
  showAllEdges: boolean
  migrated: Set<string>
  findings?: { node_id: string; lens: string; verdict: string }[]
  rules?: { program: string; decision: string }[]
}): Scene {
  const allow = new Set(opts.types)
  const hubsHidden = opts.hideHubs
  const hubCopybooks = opts.nodes.filter((n) => n.hub && n.kind === "copybook").length
  const visibleUnits = opts.nodes.filter((n) => !(hubsHidden && n.hub))
  const byCap = new Map<string, GraphNode[]>()
  for (const n of visibleUnits) {
    const cap = n.capability || n.cluster || "other"
    if (!byCap.has(cap)) byCap.set(cap, [])
    byCap.get(cap)!.push(n)
  }
  const unitCap = new Map<string, string>()
  for (const n of opts.nodes) unitCap.set(n.id, n.capability || n.cluster || "other")

  const clusterNodes: GraphNode[] = []
  const centroids = [...byCap.entries()].map(([cap, members]) => {
    let x = 0, y = 0, z = 0
    for (const m of members) {
      const p = posOf(m, opts.layout)
      x += p[0]; y += p[1]; z += p[2]
    }
    return { cap, members, x: x / members.length, y: y / members.length, z: z / members.length }
  })
  const mx = centroids.reduce((s, c) => s + c.x, 0) / Math.max(1, centroids.length)
  const mz = centroids.reduce((s, c) => s + c.z, 0) / Math.max(1, centroids.length)
  const ring = [...centroids].sort((a, b) => Math.atan2(a.z - mz, a.x - mx) - Math.atan2(b.z - mz, b.x - mx) || a.cap.localeCompare(b.cap))
  const cols = Math.ceil(Math.sqrt(ring.length))
  const rows = Math.ceil(ring.length / cols)
  ring.forEach((c, i) => {
    const col = i % cols
    const row = Math.floor(i / cols)
    c.x = (col - (cols - 1) / 2) * 6.2
    c.y = ((rows - 1) / 2 - row) * 4.2
    c.z = 0
    if (opts.layout === "topdown") {
      c.z = -c.y
      c.y = 0
    }
  })
  const titleOf = (members: GraphNode[]) => {
    const counts = new Map<string, number>()
    for (const m of members) counts.set(m.cluster || "group", (counts.get(m.cluster || "group") || 0) + 1)
    let best = "group"
    let n = -1
    for (const [k, v] of counts) if (v > n) { best = k; n = v }
    return best
  }
  const titles = centroids.map((c) => titleOf(c.members))
  const titleCount = new Map<string, number>()
  for (const t of titles) titleCount.set(t, (titleCount.get(t) || 0) + 1)
  centroids.forEach((c, ci) => {
    const memberIds = new Set(c.members.map((m) => m.id))
    const q = (opts.findings || []).filter((f) => f.lens === "quality" && f.verdict !== "rejected" && memberIds.has(f.node_id)).length
    const touching = opts.edges.filter((e) => memberIds.has(e.source) || memberIds.has(e.target))
    const proved = touching.filter((e) => e.proved).length
    const ruleRows = (opts.rules || []).filter((r) => c.members.some((m) => m.name === r.program))
    const decided = ruleRows.filter((r) => r.decision && r.decision !== "unset").length
    clusterNodes.push({
      id: `cap:${c.cap}`,
      name: (titleCount.get(titles[ci]) || 0) > 1 ? `${titles[ci]} (${c.members.length})` : titles[ci],
      kind: "cluster",
      subtype: "capability",
      file: "",
      line: 0,
      summary: `${c.members.length} units`,
      cluster: c.cap,
      capability: c.cap,
      degree: c.members.reduce((s, m) => s + (m.degree || 0), 0),
      hub: false,
      risk: Math.max(...c.members.map((m) => m.risk || 0)),
      status: c.members.every((m) => opts.migrated.has(m.id)) ? "modern" : "legacy",
      entry: c.members.some((m) => m.entry),
      external: false,
      x: c.x, y: c.y, z: c.z,
      qualityCount: q,
      blast: c.members.reduce((s, m) => s + (m.degree || 0), 0),
      provedRatio: touching.length ? proved / touching.length : 1,
      ledger: ruleRows.length ? decided / ruleRows.length : null,
    })
  })

  const expandedMembers = opts.expanded ? (byCap.get(opts.expanded) || []) : []
  const memberPos = new Map<string, [number, number, number]>()
  expandedMembers.forEach((m, i) => {
    const base = centroids.find((c) => c.cap === opts.expanded)!
    const ang = i * 2.399
    const rad = 0.85 * Math.sqrt(i + 0.4)
    memberPos.set(m.id, [base.x + rad * Math.cos(ang), base.y + (i % 5) * 0.15, base.z + rad * Math.sin(ang)])
  })
  const unitNodes = expandedMembers.map((m) => {
    const p = memberPos.get(m.id)!
    return { ...m, x: p[0], y: p[1], z: p[2] }
  })

  const locate = (id: string): string | null => {
    if (hubsHidden && opts.nodes.find((n) => n.id === id)?.hub) return null
    const cap = unitCap.get(id)
    if (!cap) return null
    if (opts.expanded === cap) return id
    if (!byCap.has(cap)) return null
    return `cap:${cap}`
  }

  type Acc = { type: string; source: string; target: string; ids: string[]; proved: boolean; visual: "keep" | "removed" | "added"; file: string; line: number; snippet: string; mechanism: string }
  const groups = new Map<string, Acc>()
  let hiddenEdges = 0
  for (const e of opts.edges) {
    if (allow.size && !allow.has(e.type) && e.visual !== "removed" && e.visual !== "added") continue
    const s = locate(e.source)
    const t = locate(e.target)
    if (!s || !t || s === t) {
      hiddenEdges++
      continue
    }
    const key = `${s}|${t}|${e.type}|${e.visual || "keep"}`
    const cur = groups.get(key)
    if (cur) {
      cur.ids.push(e.id)
      cur.proved = cur.proved && e.proved
    } else {
      groups.set(key, {
        type: e.type, source: s, target: t, ids: [e.id], proved: e.proved,
        visual: e.visual || "keep", file: e.file, line: e.line, snippet: e.snippet, mechanism: e.mechanism,
      })
    }
  }
  let list = [...groups.values()].sort((a, b) => b.ids.length - a.ids.length)
  const capped = !opts.showAllEdges && list.length > EDGE_CAP
  if (capped) {
    hiddenEdges += list.slice(EDGE_CAP).reduce((n, g) => n + g.ids.length, 0)
    list = list.slice(0, EDGE_CAP)
  }
  const edges: SceneEdge[] = list.map((g) => ({
    id: `agg:${g.source}:${g.target}:${g.type}:${g.visual}`,
    source: g.source,
    target: g.target,
    type: g.type,
    file: g.file,
    line: g.line,
    snippet: g.snippet,
    mechanism: g.mechanism,
    proved: g.proved,
    dynamic: !g.proved,
    visual: g.visual,
    weight: g.ids.length,
    member_ids: g.ids,
    agent: "graph",
  }))

  return {
    nodes: [...clusterNodes, ...unitNodes],
    edges,
    migrated: opts.migrated,
    hubCopybooks,
    hiddenEdges,
    mode: opts.expanded ? "units" : "clusters",
  }
}
