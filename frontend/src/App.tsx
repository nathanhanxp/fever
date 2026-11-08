import { useEffect, useMemo, useRef, useState } from "react"
import { ask, fetchFile, fetchRun, saveBrief, saveWeights, simulate, validateOrder, workOrderUrl } from "./api"
import { edgeLegend, GraphCanvas, type Hop } from "./Graph"
import { buildScene, dominantType } from "./graphView"
import type { AskResult, GraphEdge, GraphNode, ResultCard, RunModel, Step } from "./types"
import { EDGE_TYPES } from "./types"

type Tab = "explore" | "agents"

export function App() {
  const [model, setModel] = useState<RunModel | null>(null)
  const [status, setStatus] = useState("loading")
  const [tab, setTab] = useState<Tab>("explore")
  const [selected, setSelected] = useState("")
  const [filePath, setFilePath] = useState("")
  const [fileText, setFileText] = useState("")
  const [line, setLine] = useState(1)
  const [depth, setDepth] = useState(2)
  const [types, setTypes] = useState<string[]>([])
  const [typesReady, setTypesReady] = useState(false)
  const [direction, setDirection] = useState<"both" | "down" | "up">("both")
  const [hideHubs, setHideHubs] = useState(true)
  const [layout, setLayout] = useState<"layered" | "similarity" | "topdown">("layered")
  const [expanded, setExpanded] = useState<string | null>(null)
  const [overlay, setOverlay] = useState("none")
  const [showAllEdges, setShowAllEdges] = useState(false)
  const [edgeMenu, setEdgeMenu] = useState(false)
  const [hoverId, setHoverId] = useState<string | null>(null)
  const [stepIndex, setStepIndex] = useState(0)
  const [playing, setPlaying] = useState(false)
  const [question, setQuestion] = useState("What depends on COCOM01Y?")
  const [answer, setAnswer] = useState<AskResult | null>(null)
  const [card, setCard] = useState<ResultCard | null>(null)
  const [busy, setBusy] = useState(false)
  const [verdict, setVerdict] = useState("all")
  const [violations, setViolations] = useState<string[]>([])
  const [benchNote, setBenchNote] = useState("")
  const codeRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    let stop = false
    const tick = async () => {
      try {
        const run = await fetchRun()
        if (stop) return
        if (run.status === "done" && run.nodes) {
          setModel(run)
          setStatus("done")
          if (!typesReady) {
            setTypes([dominantType(run.edges)])
            setTypesReady(true)
          }
          return
        }
        setStatus(run.status || "running")
      } catch (err) {
        if (!stop) setStatus(err instanceof Error ? err.message : "error")
      }
      if (!stop) setTimeout(tick, 600)
    }
    tick()
    return () => { stop = true }
  }, [])

  useEffect(() => {
    if (!playing || !model) return
    const id = window.setInterval(() => {
      setStepIndex((n) => {
        if (n >= model.plan.steps.length) {
          setPlaying(false)
          return n
        }
        return n + 1
      })
    }, 1100)
    return () => window.clearInterval(id)
  }, [playing, model])

  useEffect(() => {
    if (!filePath) return
    const el = codeRef.current?.querySelector(`[data-line="${line}"]`)
    el?.scrollIntoView({ block: "center" })
  }, [filePath, line, fileText])

  const openFile = async (path: string, at: number) => {
    if (!path) return
    setFilePath(path)
    setLine(at || 1)
    try {
      setFileText(await fetchFile(path))
    } catch {
      setFileText("Could not read " + path)
    }
  }

  const view = useMemo(() => project(model, stepIndex, types, false), [model, stepIndex, types])
  const scene = useMemo(() => {
    if (!view || !model) return null
    return buildScene({
      nodes: view.nodes,
      edges: view.edges,
      layout,
      expanded,
      hideHubs,
      types,
      showAllEdges,
      migrated: view.migrated,
      findings: model.findings,
      rules: model.rules,
    })
  }, [view, model, layout, expanded, hideHubs, types, showAllEdges])

  const hops = useMemo(() => {
    if (!view || !model || !scene) return {}
    if (answer?.highlight && (answer.highlight.focus || Object.keys(answer.highlight.downstream).length)) {
      const lift = (id: string) => {
        const n = model.nodes.find((x) => x.id === id)
        if (!n) return id
        const cap = n.capability || n.cluster
        if (hideHubs && n.hub) return ""
        if (expanded === cap) return id
        return `cap:${cap}`
      }
      const map: Record<string, Hop> = {}
      const put = (id: string, hop: number, dir: Hop["dir"]) => {
        const key = lift(id)
        if (!key) return
        const prev = map[key]
        if (!prev || hop < prev.hop) map[key] = { hop, dir }
      }
      if (answer.highlight.focus) put(answer.highlight.focus, 0, "focus")
      for (const [id, hop] of Object.entries(answer.highlight.downstream)) put(id, hop, "down")
      for (const [id, hop] of Object.entries(answer.highlight.upstream)) put(id, hop, "up")
      return map
    }
    if (selected) {
      const map = walk(scene.edges, selected, depth, direction)
      if (stepIndex > 0) {
        for (const e of scene.edges) {
          if (e.visual !== "removed" && e.visual !== "added") continue
          if (!map[e.source]) map[e.source] = { hop: 1, dir: "down" }
          if (!map[e.target]) map[e.target] = { hop: 1, dir: "down" }
        }
      }
      return map
    }
    if (stepIndex > 0) {
      const pin: Record<string, Hop> = {}
      for (const e of scene.edges) {
        if (e.visual === "removed" || e.visual === "added") {
          pin[e.source] = { hop: 0, dir: "focus" }
          pin[e.target] = { hop: 1, dir: "down" }
        }
      }
      return pin
    }
    return {}
  }, [view, model, scene, answer, selected, depth, direction, stepIndex, expanded, hideHubs])

  if (!model || !view || !scene) {
    return <div className="loading">Mapping CardDemo… {status}. Parsers are reading COBOL, JCL, and BMS.</div>
  }

  const node = view.nodes.find((n) => n.id === selected) || model.nodes.find((n) => n.id === selected)
  const step = stepIndex > 0 ? model.plan.steps[stepIndex - 1] : null
  const maxLegacy = model.plan.curve[0]?.legacy_dependencies || 1

  const labelIds = (() => {
    if (!hoverId) return []
    const h = scene.nodes.find((n) => n.id === hoverId)
    if (!h || h.kind === "cluster") return []
    const near = scene.nodes
      .filter((n) => n.id !== hoverId && n.kind !== "cluster")
      .map((n) => ({ id: n.id, d: Math.hypot(n.x - h.x, n.z - h.z) }))
      .sort((a, b) => a.d - b.d)
      .slice(0, 2)
      .map((n) => n.id)
    return [hoverId, ...near]
  })()

  const selectNode = (id: string) => {
    setAnswer(null)
    if (!id) { setSelected(""); return }
    if (id.startsWith("cap:")) {
      const cap = id.slice(4)
      setExpanded((cur) => (cur === cap ? null : cap))
      setSelected(id)
      return
    }
    setSelected(id)
    const n = model.nodes.find((x) => x.id === id) || view.nodes.find((x) => x.id === id)
    if (n?.file) openFile(n.file, n.line || 1)
  }

  const onAsk = async (q: string) => {
    setBusy(true)
    setQuestion(q)
    try {
      const res = await ask(q, depth)
      setAnswer(res)
      if (res.ui?.edge_types) setTypes(res.ui.edge_types)
      if (res.highlight?.focus) {
        setSelected(res.highlight.focus)
        const n = model.nodes.find((x) => x.id === res.highlight.focus)
        if (n?.file) openFile(n.file, n.line || 1)
      }
      if (res.result_card) setCard(res.result_card)
      const cite = res.citations?.[0]
      if (cite?.file) openFile(cite.file, cite.line || 1)
    } finally {
      setBusy(false)
    }
  }

  const onSimulate = async (id: string) => {
    setBusy(true)
    try {
      const res = await simulate(id, depth) as ResultCard
      setCard(res)
      setSelected(id)
      setAnswer({
        answer: `${res.affected} units are downstream of this node within ${depth} hops. Risk ${res.risk_before} → ${res.risk_after}. ${res.note}`,
        citations: [],
        counts: [
          { label: `${res.affected} affected`, node_ids: Object.keys(res.downstream) },
          ...Object.entries(res.by_type).map(([t, n]) => ({ label: `${n} ${t}`, node_ids: Object.keys(res.downstream) })),
        ],
        highlight: { focus: id, downstream: res.downstream, upstream: {}, direction: "downstream" },
        ui: {},
        result_card: res,
        claim: "Predicted",
      })
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="app">
      <header className="top">
        <div className="brand">Modernization <span>Swarm</span></div>
        <div className="tabs">
          <button className={tab === "explore" ? "on" : ""} onClick={() => setTab("explore")}>Explore</button>
          <button className={tab === "agents" ? "on" : ""} onClick={() => setTab("agents")}>Agents</button>
        </div>
        <div className="meta grow">
          {model.repo} · {model.license} · {model.stats.programs} programs · {model.stats.edges} edges · {model.elapsed_seconds}s
        </div>
        <div className="meta">{model.triage.raw} raw / {model.triage.triaged} triaged / {model.triage.rejected} rejected</div>
      </header>
      {tab === "explore" ? (
        <div className="panes">
          <section className="pane">
            <div className="pane-h"><h2>Legacy code</h2></div>
            <div className="scroll" style={{ maxHeight: "34%" }}>
              <FileTree nodes={model.nodes} active={filePath} onOpen={(p) => openFile(p, 1)} />
            </div>
            <div className="scroll" ref={codeRef} style={{ flex: 1, borderTop: "1px solid var(--line)" }}>
              {fileText ? <CodeView text={fileText} line={line} /> : <p className="meta" style={{ padding: 12 }}>Select a file or a node. Evidence lines highlight here.</p>}
            </div>
          </section>
          <section className="center">
            <div className="toolbar">
              {(["layered", "similarity", "topdown"] as const).map((key) => (
                <button key={key} className={layout === key ? "chip on" : "chip"} disabled={key === "similarity" && !model.geometry?.similarity?.method}
                  onClick={() => setLayout(key)}>
                  {key === "layered" ? "Layered" : key === "similarity" ? "Similarity" : "2D top-down"}
                </button>
              ))}
              <button className="chip" onClick={() => setEdgeMenu((v) => !v)}>Edges: {types.join(", ") || "none"}</button>
              <button className={hideHubs ? "chip on" : "chip"} onClick={() => setHideHubs((v) => !v)}>
                {scene.hubCopybooks} shared copybooks affect everything below
              </button>
              <button className={showAllEdges ? "chip on" : "chip"} onClick={() => setShowAllEdges((v) => !v)}>
                {showAllEdges ? "Showing all edges" : `Top edges · ${scene.hiddenEdges} hidden`}
              </button>
              {edgeMenu && (
                <div className="popover">
                  {EDGE_TYPES.map((t) => (
                    <label key={t}>
                      <input type="checkbox" checked={types.includes(t)} onChange={() => setTypes((cur) => cur.includes(t) ? cur.filter((x) => x !== t) : [...cur, t])} />
                      {t}
                    </label>
                  ))}
                </div>
              )}
              <span className="meta" title={model.geometry?.clustering?.note}>{scene.nodes.filter((n) => n.kind === "cluster").length} clusters</span>
              {layout === "similarity" && model.geometry?.similarity?.error && <span className="warn">{model.geometry.similarity.error}</span>}
            </div>
            <div className="overlay-bar">
              {["none", "prover", "risk", "quality", "blast", "ledger", "legacy"].map((name) => (
                <label key={name}><input type="radio" name="overlay" checked={overlay === name} onChange={() => setOverlay(name)} />{name}</label>
              ))}
            </div>
            {scene.nodes.length === 0 ? (
              <div className="loading">No clusters to draw with the current filters.</div>
            ) : (
              <GraphCanvas nodes={scene.nodes} edges={scene.edges} hops={hops} migrated={scene.migrated} onSelect={selectNode}
                overlay={overlay} focus={!!selected || stepIndex > 0} topdown={layout === "topdown"} labelIds={labelIds} onHover={setHoverId} />
            )}
            <div className="legend">
              {edgeLegend().map(([name, color]) => (
                <span key={name}><i className="swatch" style={{ background: color }} />{name}</span>
              ))}
              <span>dashed = unproved · thickness = count</span>
            </div>
            <div className="roadmap">
              <div className="row">
                <button className="btn" onClick={() => setPlaying((p) => !p)}>{playing ? "Pause" : "Play roadmap"}</button>
                <button className="btn" onClick={() => { setPlaying(false); setStepIndex(0) }}>Reset</button>
                <input type="range" min={0} max={model.plan.steps.length} value={stepIndex}
                  onChange={(e) => { setPlaying(false); setStepIndex(Number(e.target.value)) }} />
                <span className="mono">{stepIndex}/{model.plan.steps.length}</span>
              </div>
              <div className="meta" style={{ marginTop: 4 }}>
                {step ? step.title : "Detected graph"} · {model.plan.curve[stepIndex]?.legacy_dependencies ?? "—"} legacy dependencies remaining. Counts, not time.
              </div>
              <div className="curve">
                {model.plan.curve.map((pt) => (
                  <i key={pt.step} className={pt.step === stepIndex ? "on" : ""}
                    style={{ height: `${Math.max(8, (pt.legacy_dependencies / maxLegacy) * 28)}px` }}
                    title={`${pt.title}: ${pt.legacy_dependencies}`} />
                ))}
              </div>
            </div>
          </section>
          <section className="pane">
            <div className="pane-h"><h2>Explain / ask</h2><span className="tag pred">Predicted ≠ Measured</span></div>
            <div className="scroll explain">
              {step && (
                <StepCard step={step} onFile={openFile} />
              )}
              {node && (
                <NodeCard
                  model={model}
                  node={node}
                  edges={view.edges}
                  onFile={openFile}
                  onSimulate={() => onSimulate(node.id)}
                />
              )}
              {card && (
                <div className="card">
                  <div className="k">Ripple result · {card.claim}</div>
                  <p>{card.affected} affected units. Risk {card.risk_before} → {card.risk_after}.</p>
                  <p className="meta">{Object.entries(card.by_kind).map(([k, n]) => `${n} ${k}`).join(" · ")}</p>
                  <p className="meta">{Object.entries(card.by_type).map(([k, n]) => `${n} ${k}`).join(" · ")}</p>
                  <p className="meta">{card.note}</p>
                </div>
              )}
              <div className="card chat">
                <div className="k">Ask the graph</div>
                <div className="chips">
                  {["What depends on COCOM01Y?", "What does COSGN00C depend on?", "Show only FILE dependencies", "Path from COSGN00C to COMEN01C"].map((q) => (
                    <button key={q} className="chip" onClick={() => onAsk(q)}>{q}</button>
                  ))}
                </div>
                <textarea value={question} onChange={(e) => setQuestion(e.target.value)} />
                <button className="btn" disabled={busy} onClick={() => onAsk(question)}>{busy ? "Asking…" : "Ask"}</button>
                {answer && (
                  <>
                    <p>{answer.answer}</p>
                    <div className="chips">
                      {answer.counts.map((c) => (
                        <button key={c.label} className="chip on" onClick={() => {
                          setAnswer({ ...answer, highlight: { focus: answer.highlight.focus, downstream: Object.fromEntries(c.node_ids.map((id) => [id, 1])), upstream: {}, direction: "downstream" } })
                        }}>{c.label}</button>
                      ))}
                    </div>
                    {answer.citations.map((c, i) => (
                      <button key={i} className="cite" onClick={() => {
                        if (c.file) openFile(c.file, c.line)
                        if (c.node_id) setSelected(c.node_id)
                      }}>{c.file}:{c.line} {c.title}</button>
                    ))}
                  </>
                )}
              </div>
              <div className="card">
                <div className="k">Dependency filter</div>
                <div className="filters">
                  {EDGE_TYPES.map((t) => (
                    <label key={t}>
                      <input type="checkbox" checked={types.includes(t)} onChange={() => {
                        setTypes((cur) => cur.includes(t) ? cur.filter((x) => x !== t) : [...cur, t])
                      }} />{t}
                    </label>
                  ))}
                </div>
                <label className="meta">Hop depth {depth}</label>
                <input type="range" min={1} max={4} value={depth} onChange={(e) => setDepth(Number(e.target.value))} />
                <div className="filters">
                  {(["both", "down", "up"] as const).map((d) => (
                    <button key={d} className={direction === d ? "chip on" : "chip"} onClick={() => setDirection(d)}>
                      {d === "down" ? "Downstream" : d === "up" ? "Upstream" : "Both"}
                    </button>
                  ))}
                  <label><input type="checkbox" checked={hideHubs} onChange={() => setHideHubs((v) => !v)} /> hide hubs</label>
                </div>
                <p className="meta">{model.nodes.filter((n) => n.hub).length} hubs. Toggle hides them. Colored edges, not positions, are the dependencies.</p>
              </div>
              <Drivers model={model} onSaved={(m) => setModel({ ...model, drivers: m.drivers })} />
              <Brief model={model} onApplied={(next) => setModel({ ...model, ...next, plan: next.plan, rules: next.rules, plan_version: next.version, brief: { ...model.brief, asked: true, target: next.plan?.reason || model.brief.target } })} />
            </div>
          </section>
        </div>
      ) : (
        <Agents
          model={model}
          verdict={verdict}
          setVerdict={setVerdict}
          violations={violations}
          benchNote={benchNote}
          onRejectDemo={async () => {
            const res = await validateOrder(model.validator.invalid_order)
            setViolations(res.violations.map((v) => v.message))
          }}
          onBench={async () => {
            setBenchNote("Calling NVIDIA…")
            const res = await fetch("/api/benchmark/model", { method: "POST" })
            const data = await res.json()
            setModel({ ...model, model_benchmark: data })
            setBenchNote("")
          }}
          onFile={openFile}
        />
      )}
    </div>
  )
}

function project(model: RunModel | null, stepIndex: number, types: string[], hideHubs: boolean) {
  if (!model) return null
  const removed = new Set<string>()
  const added: Array<GraphEdge & { visual: "added" }> = []
  const extra: GraphNode[] = []
  const migrated = new Set<string>()
  for (let i = 0; i < stepIndex; i++) {
    const s = model.plan.steps[i]
    s.remove_ids.forEach((id) => removed.add(id))
    s.add_edges.forEach((e) => added.push({ ...e, visual: "added" }))
    extra.push(...s.add_nodes)
    s.migrate.forEach((id) => migrated.add(id))
  }
  const just = stepIndex > 0 ? new Set(model.plan.steps[stepIndex - 1].remove_ids) : new Set<string>()
  const allow = new Set(types)
  const edges: Array<GraphEdge & { visual?: "keep" | "removed" | "added" }> = []
  for (const e of model.edges) {
    if (allow.size && !allow.has(e.type)) continue
    if (removed.has(e.id)) {
      if (just.has(e.id)) edges.push({ ...e, visual: "removed" })
      continue
    }
    edges.push({ ...e, visual: "keep" })
  }
  for (const e of added) {
    if (!allow.size || allow.has(e.type)) edges.push(e)
  }
  let nodes = [...model.nodes, ...extra]
  if (hideHubs) {
    const hidden = new Set(nodes.filter((n) => n.hub).map((n) => n.id))
    nodes = nodes.filter((n) => !n.hub)
    return { nodes, edges: edges.filter((e) => !hidden.has(e.source) && !hidden.has(e.target)), migrated }
  }
  return { nodes, edges, migrated }
}

function walk(edges: GraphEdge[], focus: string, depth: number, direction: "both" | "down" | "up"): Record<string, Hop> {
  const out = new Map<string, string[]>()
  const inn = new Map<string, string[]>()
  for (const e of edges) {
    if (!out.has(e.source)) out.set(e.source, [])
    if (!inn.has(e.target)) inn.set(e.target, [])
    out.get(e.source)!.push(e.target)
    inn.get(e.target)!.push(e.source)
  }
  const hops: Record<string, Hop> = { [focus]: { hop: 0, dir: "focus" } }
  const grow = (adj: Map<string, string[]>, dir: "down" | "up") => {
    let frontier = [focus]
    const seen = new Set([focus])
    for (let d = 1; d <= depth; d++) {
      const next: string[] = []
      for (const id of frontier) {
        for (const nxt of adj.get(id) || []) {
          if (seen.has(nxt)) continue
          seen.add(nxt)
          if (!hops[nxt]) hops[nxt] = { hop: d, dir }
          next.push(nxt)
        }
      }
      frontier = next
    }
  }
  if (direction !== "up") grow(inn, "down")
  if (direction !== "down") grow(out, "up")
  return hops
}

function FileTree({ nodes, active, onOpen }: { nodes: GraphNode[]; active: string; onOpen: (p: string) => void }) {
  const groups = new Map<string, string[]>()
  for (const n of nodes) {
    if (!n.file) continue
    const dir = n.file.split("/").slice(0, -1).join("/") || "."
    if (!groups.has(dir)) groups.set(dir, [])
    const list = groups.get(dir)!
    if (!list.includes(n.file)) list.push(n.file)
  }
  return (
    <div className="tree">
      {[...groups.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([dir, files]) => (
        <div key={dir}>
          <div className="dir">{dir}</div>
          {files.sort().map((f) => (
            <button key={f} className={f === active ? "on" : ""} onClick={() => onOpen(f)}>
              {f.split("/").pop()}
            </button>
          ))}
        </div>
      ))}
    </div>
  )
}

function CodeView({ text, line }: { text: string; line: number }) {
  const rows = text.split("\n")
  return (
    <div className="code">
      {rows.map((row, i) => (
        <div key={i} className={i + 1 === line ? "ln hit" : "ln"} data-line={i + 1}>
          <i>{i + 1}</i><b>{row || " "}</b>
        </div>
      ))}
    </div>
  )
}

function NodeCard({ model, node, edges, onFile, onSimulate }: {
  model: RunModel
  node: GraphNode
  edges: GraphEdge[]
  onFile: (p: string, line: number) => void
  onSimulate: () => void
}) {
  const outgoing = edges.filter((e) => e.source === node.id).slice(0, 8)
  const incoming = edges.filter((e) => e.target === node.id).slice(0, 8)
  const findings = model.findings.filter((f) => f.node_id === node.id && f.verdict !== "rejected").slice(0, 4)
  const nameOf = (id: string) => model.nodes.find((n) => n.id === id)?.name || id
  return (
    <div className="card">
      <div className="k">{node.kind} · {node.cluster}{node.hub ? " · hub" : ""}{node.entry ? " · entry" : ""}</div>
      <strong>{node.name}</strong>
      <p>{node.summary}</p>
      <p className="meta">Depends on {outgoing.length === 8 ? "8+" : outgoing.length} shown. {incoming.length === 8 ? "8+" : incoming.length} shown depend on it.</p>
      {outgoing.map((e) => (
        <button key={e.id} className="cite" onClick={() => onFile(e.file, e.line)}>
          {e.type}{e.proved ? "" : " (unproved)"} → {nameOf(e.target)} · {e.file}:{e.line}
        </button>
      ))}
      {findings.map((f) => (
        <p key={f.id}><span className={f.claim === "Measured" ? "tag meas" : f.claim === "Candidate" ? "tag cand" : "tag pred"}>{f.claim}</span> {f.title}</p>
      ))}
      <button className="btn" onClick={onSimulate}>Simulate replacing this</button>
    </div>
  )
}

function StepCard({ step, onFile }: { step: Step; onFile: (p: string, line: number) => void }) {
  return (
    <div className="card">
      <div className="k">Step {step.index} · {step.verb} · {step.claim}</div>
      <strong>{step.title}</strong>
      <p>{step.detail}</p>
      <p>Risk {step.risk_before} → {step.risk_after}. Legacy dependencies {step.legacy_remaining}.</p>
      {step.removals.slice(0, 5).map((r) => (
        <button key={r.id} className="cite" onClick={() => onFile(r.file, r.line)}>
          removes {r.type} {r.file}:{r.line} — {r.reason}
        </button>
      ))}
      {step.requires.slice(0, 4).map((r) => <p key={r.step_id} className="meta">Requires {r.step_id}: {r.because}</p>)}
      {step.unblocks.length > 0 && <p className="meta">Unblocks {step.unblocks.join(", ")}</p>}
      <a className="btn" href={workOrderUrl(step.id)} style={{ display: "inline-block", textDecoration: "none" }}>Work order</a>
    </div>
  )
}

function Drivers({ model, onSaved }: { model: RunModel; onSaved: (m: { drivers: RunModel["drivers"] }) => void }) {
  const [weights, setWeights] = useState<Record<string, number>>(() => Object.fromEntries(model.drivers.map((d) => [d.id, d.weight])))
  return (
    <div className="card">
      <div className="k">Why modernize</div>
      {model.drivers.map((d) => (
        <div key={d.id}>
          <div className="row" style={{ display: "flex", justifyContent: "space-between" }}>
            <span>{d.label}</span><span className="mono">{d.score}</span>
          </div>
          <p className="meta">{d.text}</p>
          <input type="range" min={0} max={5} step={1} value={weights[d.id] ?? 1}
            onChange={(e) => setWeights({ ...weights, [d.id]: Number(e.target.value) })} />
        </div>
      ))}
      <button className="btn" onClick={async () => onSaved(await saveWeights(weights))}>Update weights</button>
      <p className="meta">Weights change emphasis only. No dollar figures. Edges stay as detected.</p>
    </div>
  )
}

function Brief({ model, onApplied }: { model: RunModel; onApplied: (next: { plan: RunModel["plan"]; rules: RunModel["rules"]; version: number }) => void }) {
  const [target, setTarget] = useState("Java services on containers")
  const [where, setWhere] = useState("cloud containers")
  const [downtime, setDowntime] = useState("weekend window")
  const [rules, setRules] = useState(model.rules)
  return (
    <div className="card">
      <div className="k">Modernization brief</div>
      <p className="meta">Optional. Preferences change the recommendation text, not the facts. Plan v{model.plan_version}.</p>
      <label className="meta">Target</label>
      <select value={target} onChange={(e) => setTarget(e.target.value)}>
        <option>Java services on containers</option>
        <option>Python services</option>
        <option>COBOL on a compatible runtime</option>
      </select>
      <label className="meta">Where it runs</label>
      <select value={where} onChange={(e) => setWhere(e.target.value)}>
        <option>cloud containers</option>
        <option>mainframe-compatible runtime</option>
        <option>undecided</option>
      </select>
      <label className="meta">Downtime</label>
      <select value={downtime} onChange={(e) => setDowntime(e.target.value)}>
        <option>no downtime</option>
        <option>weekend window</option>
        <option>unconstrained</option>
      </select>
      {rules.slice(0, 6).map((r) => (
        <div key={r.id} style={{ marginTop: 8 }}>
          <div className="meta">{r.program}:{r.line} · {r.claim}</div>
          <div>{r.text}</div>
          <div className="chips">
            {["Preserve", "Change", "Retire"].map((d) => (
              <button key={d} className={r.decision === d ? "chip on" : "chip"} onClick={() => setRules(rules.map((x) => x.id === r.id ? { ...x, decision: d } : x))}>{d}</button>
            ))}
          </div>
        </div>
      ))}
      <button className="btn" style={{ marginTop: 8 }} onClick={async () => {
        const next = await saveBrief({ target, where, downtime, rules })
        onApplied(next)
      }}>Re-plan from brief</button>
    </div>
  )
}

function Agents({ model, verdict, setVerdict, violations, benchNote, onRejectDemo, onBench, onFile }: {
  model: RunModel
  verdict: string
  setVerdict: (v: string) => void
  violations: string[]
  benchNote: string
  onRejectDemo: () => void
  onBench: () => void
  onFile: (p: string, line: number) => void
}) {
  const rows = model.findings.filter((f) => verdict === "all" || f.verdict === verdict).slice(0, 200)
  return (
    <div className="agents">
      <div>
        <h2>Swarm</h2>
        <p className="meta">Times are shares of the measured {model.elapsed_seconds}s build. Tokens are zero because this run used parsers, not a model, for facts.</p>
        <div className="dag">
          {model.agents.map((a) => (
            <div key={a.id} className="agent">
              <strong>{a.role}</strong>
              <div className="meta">{a.status} · {a.seconds}s · {a.tokens} tokens</div>
              <div className="meta">{a.model} @ {a.host}</div>
              <div>{a.note}</div>
            </div>
          ))}
        </div>
      </div>
      <div className="card">
        <div className="k">Plan versions</div>
        {model.plan_versions.map((v) => <p key={v.version}><strong>v{v.version}.</strong> {v.reason}</p>)}
        <button className="btn" onClick={onRejectDemo}>Reject an invalid reordering</button>
        {violations.map((v) => <p key={v} className="warn">{v}</p>)}
        {model.validator.legal_order_violations.length === 0 && <p className="meta">The shipped order has {model.validator.legal_order_violations.length} validator violations.</p>}
      </div>
      <div>
        <div className="pane-h" style={{ paddingLeft: 0 }}>
          <h2>Findings</h2>
          <select value={verdict} onChange={(e) => setVerdict(e.target.value)}>
            <option value="all">all</option>
            <option value="accepted">accepted</option>
            <option value="downgraded">downgraded</option>
            <option value="candidate">candidate</option>
            <option value="rejected">rejected</option>
          </select>
        </div>
        <p className="meta">Raw {model.triage.raw} → triaged {model.triage.triaged}. {model.triage.embeddings}</p>
        <div className="table-wrap">
          <table>
            <thead><tr><th>Verdict</th><th>Claim</th><th>Finding</th><th>Evidence</th><th>Agent</th></tr></thead>
            <tbody>
              {rows.map((f) => (
                <tr key={f.id} className={f.verdict === "rejected" ? "rej" : ""}>
                  <td>{f.verdict}</td>
                  <td>{f.claim}</td>
                  <td>{f.title}<div className="meta">{f.verdict_reason}</div></td>
                  <td>{f.file ? <button className="cite" onClick={() => onFile(f.file, f.line)}>{f.file}:{f.line}</button> : "—"}</td>
                  <td>{f.agent}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
      {model.measured && (
        <div className="card">
          <div className="k">Measured static re-run · {model.measured.rule}</div>
          <p>{model.measured.file}: detector count {model.measured.before} → {model.measured.after}. {model.measured.note}</p>
          <div className="diff">{model.measured.diff}</div>
        </div>
      )}
      <div className="card">
        <div className="k">Parser benchmark</div>
        <p className="meta">{model.benchmark.note}</p>
        <table>
          <thead><tr><th>Backend</th><th>Mode</th><th>Concurrency</th><th>Seconds</th><th>Calls/s</th></tr></thead>
          <tbody>
            {model.benchmark.rows.map((r, i) => (
              <tr key={i}>
                <td>{String(r.backend)}</td>
                <td>{String(r.mode || "")}</td>
                <td>{String(r.concurrency ?? "")}</td>
                <td>{String(r.seconds ?? "")}</td>
                <td>{String(r.calls_per_second ?? "")}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <button className="btn" onClick={onBench}>Run NVIDIA model benchmark</button>
        <span className="meta"> {benchNote}</span>
        {model.model_benchmark && (
          <table>
            <tbody>
              {model.model_benchmark.rows.map((r, i) => (
                <tr key={i}><td>{String(r.backend)}</td><td>{String(r.model || r.status)}</td><td>{String(r.concurrency ?? "")}</td><td>{String(r.seconds ?? r.note ?? "")}</td><td>{String(r.tokens ?? "")}</td></tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
      <div className="card">
        <div className="k">Models</div>
        {model.models.map((m) => <p key={m.role}><strong>{m.role}.</strong> {m.model} — {m.host}</p>)}
        <div className="k">Limits</div>
        {model.limits.map((l) => <p key={l} className="meta">{l}</p>)}
        <a className="btn" href="/api/roadmap.pdf">Export PDF</a>
      </div>
    </div>
  )
}
