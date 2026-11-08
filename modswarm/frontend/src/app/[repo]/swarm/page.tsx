"use client"

import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import { useParams } from "next/navigation"
import Link from "next/link"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"

type DagNode = { id: string; role: string; count: number; parallel?: boolean }
type DagEdge = { source: string; target: string }
type Decision = {
  id?: number
  role: string
  kind: string
  verdict?: string
  text?: string
  decision?: string
  latency_s?: number | null
}
type Stage = { id: string; label: string; detail: string; status?: string; latency_s?: number | null }
type ThreadCell = {
  concurrency: number
  allocated: number
  capacity: number
  wall_s: number | null
  calls_per_s: number | null
  ok?: number
  errors?: number
  latency_vs_serial_x: number | null
  fill: number
  status?: string
}
type VultrThreadMatrix = {
  backend?: string
  model?: string
  configured?: boolean
  threads?: ThreadCell[]
  baseline_wall_s?: number | null
  max_conc?: number | null
  max_conc_wall_s?: number | null
  latency_gain_x?: number | null
  max_calls_per_s?: number | null
  capacity?: number
  host?: string
  label?: string
}

const STAGE_TO_ROLES: Record<string, string[]> = {
  plan: ["coord"],
  fanout: ["mapper", "lens", "data", "security", "ops", "quality", "code", "api"],
  gate: ["prover"],
  write: ["plan"],
  exec: ["explain", "coord", "analyst", "prover"],
}

function VultrThreadMatrixCard({
  matrix,
  busy,
  onRun,
  measuredAt,
}: {
  matrix: VultrThreadMatrix | null | undefined
  busy: boolean
  onRun: () => void
  measuredAt?: number | null
}) {
  const threads = matrix?.threads?.length
    ? matrix.threads
    : [1, 2, 4, 8].map((c) => ({
        concurrency: c,
        allocated: c,
        capacity: 8,
        wall_s: null,
        calls_per_s: null,
        latency_vs_serial_x: null,
        fill: c / 8,
        status: "pending",
      }))
  const maxWall = Math.max(...threads.map((t) => t.wall_s || 0), 0.001)
  const maxCps = Math.max(...threads.map((t) => t.calls_per_s || 0), 0.001)
  const configured = matrix?.configured !== false
  const when = measuredAt
    ? new Date(measuredAt * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })
    : null

  return (
    <div className="border rounded-md overflow-hidden bg-gradient-to-br from-[#007BFC]/12 via-background to-emerald-500/5">
      <div className="px-3 py-2 border-b flex flex-wrap items-center gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <span className="inline-flex h-5 w-5 items-center justify-center rounded bg-[#007BFC] text-[9px] font-bold text-white shrink-0">V</span>
          <div className="min-w-0">
            <p className="text-xs font-semibold tracking-tight truncate">Vultr Serverless Thread Matrix</p>
            <p className="text-[10px] text-muted-foreground truncate">
              Thread capacity · latency under max concurrency · {matrix?.host?.replace(/^https?:\/\//, "") || "api.vultrinference.com"}
            </p>
          </div>
        </div>
        <Badge variant="outline" className="text-[10px] font-mono">Measured</Badge>
        <div className="flex-1" />
        {when && <span className="text-[10px] font-mono text-muted-foreground">{when}</span>}
        <Button size="sm" variant="outline" className="h-7 text-[11px]" disabled={busy || !configured} onClick={onRun}>
          {busy ? "Probing threads…" : matrix?.threads?.length ? "Re-run matrix" : "Run thread matrix"}
        </Button>
      </div>

      <div className="p-3 space-y-3">
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
          <div className="rounded-md border bg-background/70 px-2.5 py-2">
            <p className="text-[9px] uppercase tracking-wide text-muted-foreground">Capacity</p>
            <p className="text-lg font-semibold font-mono tabular-nums">{matrix?.capacity ?? 8}<span className="text-[11px] text-muted-foreground"> threads</span></p>
          </div>
          <div className="rounded-md border bg-background/70 px-2.5 py-2">
            <p className="text-[9px] uppercase tracking-wide text-muted-foreground">Max conc</p>
            <p className="text-lg font-semibold font-mono tabular-nums">{matrix?.max_conc ?? "—"}</p>
          </div>
          <div className="rounded-md border bg-background/70 px-2.5 py-2">
            <p className="text-[9px] uppercase tracking-wide text-muted-foreground">Latency gain</p>
            <p className="text-lg font-semibold font-mono tabular-nums text-emerald-400">
              {matrix?.latency_gain_x != null ? `${matrix.latency_gain_x}×` : "—"}
            </p>
          </div>
          <div className="rounded-md border bg-background/70 px-2.5 py-2">
            <p className="text-[9px] uppercase tracking-wide text-muted-foreground">Peak thruput</p>
            <p className="text-lg font-semibold font-mono tabular-nums">
              {matrix?.max_calls_per_s != null ? matrix.max_calls_per_s : "—"}
              <span className="text-[11px] text-muted-foreground"> c/s</span>
            </p>
          </div>
        </div>

        {!configured && (
          <p className="text-[11px] text-amber-400">VULTR_API_KEY not configured — matrix cells stay empty until the serverless endpoint is live.</p>
        )}

        <div className="space-y-2">
          <div className="flex items-center justify-between text-[10px] text-muted-foreground">
            <span>Thread allocation vs wall latency</span>
            <span className="font-mono">serial {matrix?.baseline_wall_s ?? "—"}s → max {matrix?.max_conc_wall_s ?? "—"}s</span>
          </div>
          {threads.map((t) => {
            const wallPct = t.wall_s != null ? Math.max(8, (t.wall_s / maxWall) * 100) : 0
            const cpsPct = t.calls_per_s != null ? Math.max(8, (t.calls_per_s / maxCps) * 100) : 0
            const slots = Array.from({ length: t.capacity }, (_, i) => i < t.allocated)
            return (
              <div key={t.concurrency} className="rounded-md border bg-background/60 px-2.5 py-2 space-y-1.5">
                <div className="flex items-center gap-2">
                  <span className="text-[11px] font-mono font-semibold w-10 shrink-0">×{t.concurrency}</span>
                  <div className="flex gap-0.5" title={`${t.allocated}/${t.capacity} threads allocated`}>
                    {slots.map((on, i) => (
                      <span
                        key={i}
                        className={`h-3 w-2.5 rounded-[2px] ${
                          on
                            ? busy && t.status === "pending"
                              ? "bg-[#007BFC]/50 animate-pulse"
                              : "bg-[#007BFC]"
                            : "bg-muted"
                        }`}
                      />
                    ))}
                  </div>
                  <span className="ml-auto text-[10px] font-mono text-muted-foreground">
                    {t.wall_s != null ? `${t.wall_s}s` : "—"}
                    {t.latency_vs_serial_x != null ? ` · ${t.latency_vs_serial_x}×` : ""}
                    {t.calls_per_s != null ? ` · ${t.calls_per_s} c/s` : ""}
                  </span>
                </div>
                <div className="grid grid-cols-2 gap-2">
                  <div>
                    <p className="text-[9px] text-muted-foreground mb-0.5">wall latency</p>
                    <div className="h-1.5 rounded-full bg-muted overflow-hidden">
                      <div
                        className="h-full rounded-full bg-sky-400/90 transition-all duration-500"
                        style={{ width: `${wallPct}%`, opacity: t.wall_s != null ? 1 : 0.25 }}
                      />
                    </div>
                  </div>
                  <div>
                    <p className="text-[9px] text-muted-foreground mb-0.5">throughput</p>
                    <div className="h-1.5 rounded-full bg-muted overflow-hidden">
                      <div
                        className="h-full rounded-full bg-emerald-400/90 transition-all duration-500"
                        style={{ width: `${cpsPct}%`, opacity: t.calls_per_s != null ? 1 : 0.25 }}
                      />
                    </div>
                  </div>
                </div>
              </div>
            )
          })}
        </div>

        <p className="text-[10px] text-muted-foreground leading-snug">
          Core swarm fan-out (lenses → prover gate) runs on Vultr Serverless Inference. Raising concurrency from 1→8 measures whether infrastructure absorbs parallel Nemotron load instead of serializing on one thread.
        </p>
      </div>
    </div>
  )
}

export default function SwarmPage() {
  const { repo } = useParams<{ repo: string }>()
  const [data, setData] = useState<Record<string, unknown> | null>(null)
  const [stages, setStages] = useState<Stage[]>([])
  const [activeStage, setActiveStage] = useState<string | null>(null)
  const [logs, setLogs] = useState<string[]>([])
  const [decisions, setDecisions] = useState<Decision[]>([])
  const [demoBusy, setDemoBusy] = useState(false)
  const [demoNote, setDemoNote] = useState("")
  const [demoStep, setDemoStep] = useState<{ id: string; title: string; cuts?: number } | null>(null)
  const [matrix, setMatrix] = useState<VultrThreadMatrix | null>(null)
  const [matrixBusy, setMatrixBusy] = useState(false)
  const [matrixAt, setMatrixAt] = useState<number | null>(null)
  const termRef = useRef<HTMLDivElement>(null)

  const refresh = () => {
    fetch(`/api/repos/${repo}/swarm`)
      .then((r) => r.json())
      .then((body: Record<string, unknown>) => {
        setData(body)
        if (body.vultr_thread_matrix) setMatrix(body.vultr_thread_matrix as VultrThreadMatrix)
        if (typeof body.benchmark_measured_at === "number") setMatrixAt(body.benchmark_measured_at)
        const last = body.demo_last_playback as { step_id?: string; title?: string; removed_edges?: number } | undefined
        if (last?.step_id) {
          setDemoStep({
            id: String(last.step_id),
            title: String(last.title || last.step_id),
            cuts: Number(last.removed_edges) || 0,
          })
        }
      })
      .catch(() => setData({}))
  }
  useEffect(() => { refresh() }, [repo])

  const dag = data?.dag as { nodes: DagNode[]; edges: DagEdge[] } | undefined

  const layout = useMemo(() => {
    const nodes = dag?.nodes || []
    const cols = new Map<string, number>()
    for (const n of nodes) {
      const role = n.role.toLowerCase()
      if (role.includes("coord")) cols.set(n.id, 0)
      else if (role.includes("mapper")) cols.set(n.id, 1)
      else if (role.includes("prover")) cols.set(n.id, 3)
      else if (role.includes("plan")) cols.set(n.id, 4)
      else if (role.includes("explain")) cols.set(n.id, 5)
      else cols.set(n.id, 2)
    }
    const byCol: Record<number, DagNode[]> = {}
    for (const n of nodes) (byCol[cols.get(n.id) ?? 2] ||= []).push(n)
    const pos = new Map<string, { x: number; y: number }>()
    for (const [c, list] of Object.entries(byCol)) {
      list.forEach((n, i) => pos.set(n.id, { x: Number(c) * 148 + 28, y: 28 + i * 48 }))
    }
    return { pos, width: 900, height: Math.max(200, ...[...pos.values()].map((p) => p.y + 50)) }
  }, [dag])

  const runDemo = useCallback(async () => {
    setDemoBusy(true)
    setLogs([`$ modswarm demo --architecture --repo ${repo.slice(0, 8)}…`])
    setDecisions([])
    setDemoNote("")
    setDemoStep(null)
    setActiveStage(null)
    try {
      const res = await fetch(`/api/repos/${repo}/swarm/demo`, { method: "POST" })
      if (!res.ok || !res.body) throw new Error(await res.text())
      const reader = res.body.getReader()
      const dec = new TextDecoder()
      let buf = ""
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buf += dec.decode(value, { stream: true })
        const parts = buf.split("\n\n")
        buf = parts.pop() || ""
        for (const part of parts) {
          const line = part.split("\n").find((l) => l.startsWith("data: "))
          if (!line) continue
          const ev = JSON.parse(line.slice(6)) as Record<string, unknown>
          const type = String(ev.type || "")
          if (type === "demo_start") {
            setStages(((ev.stages as Stage[]) || []).map((s) => ({ ...s, status: "pending" })))
            const sid = String(ev.step_id || "")
            const stitle = String(ev.step_title || sid)
            if (sid) setDemoStep({ id: sid, title: stitle, cuts: Number(ev.cuts_planned) || 0 })
            setLogs((L) => [
              ...L,
              `# target: ${ev.target}`,
              `# next legal cut: ${sid} “${stitle}” · ${ev.cuts_planned ?? "?"} measured removals`,
              `# live: plan → lens fan-out (real snippets) → prover → planner → playback`,
            ])
          } else if (type === "stage") {
            const id = String(ev.id)
            setActiveStage(id)
            setStages((ss) => ss.map((s) => s.id === id ? { ...s, status: String(ev.status), latency_s: ev.latency_s as number | undefined } : s))
          } else if (type === "log") {
            setLogs((L) => [...L, String(ev.line || "")])
          } else if (type === "decision") {
            setDecisions((d) => [{
              role: String(ev.role),
              kind: String(ev.kind),
              verdict: String(ev.verdict || "accept"),
              text: String(ev.text || ""),
              latency_s: ev.latency_s as number | undefined,
            }, ...d].slice(0, 24))
          } else if (type === "playback") {
            setDemoStep({
              id: String(ev.step_id || ""),
              title: String(ev.title || ""),
              cuts: Number(ev.removed_edges) || 0,
            })
            setLogs((L) => [
              ...L,
              `# playback ${ev.ok ? "ok" : "blocked"} · ${ev.removed_edges} edges · ${ev.retire_nodes} nodes`,
            ])
          } else if (type === "demo_done") {
            setDemoNote(String(ev.message || ""))
            if (ev.step_id) {
              setDemoStep({
                id: String(ev.step_id),
                title: String(ev.step_title || ev.step_id),
                cuts: Number(ev.removed_edges) || 0,
              })
            }
            setLogs((L) => [...L, `# done in ${ev.wall_s}s · ${ev.message}`])
            setActiveStage(null)
            refresh()
          }
        }
      }
    } catch (e) {
      setLogs((L) => [...L, `# error: ${(e as Error).message}`])
    } finally {
      setDemoBusy(false)
    }
  }, [repo])

  const runThreadMatrix = useCallback(async () => {
    setMatrixBusy(true)
    try {
      const res = await fetch(`/api/repos/${repo}/swarm/benchmark?focus=vultr`, { method: "POST" })
      if (!res.ok) throw new Error(await res.text())
      const body = await res.json()
      setMatrix((body.vultr_thread_matrix as VultrThreadMatrix) || null)
      setMatrixAt(typeof body.measured_at === "number" ? body.measured_at : Date.now() / 1000)
      setLogs((L) => [
        ...L,
        `# vultr thread matrix · gain ${body.vultr_thread_matrix?.latency_gain_x ?? "—"}× · peak ${body.vultr_thread_matrix?.max_calls_per_s ?? "—"} c/s`,
      ])
    } catch (e) {
      setLogs((L) => [...L, `# vultr matrix error: ${(e as Error).message}`])
    } finally {
      setMatrixBusy(false)
    }
  }, [repo])

  useEffect(() => {
    if (termRef.current) termRef.current.scrollTop = termRef.current.scrollHeight
  }, [logs.length])

  if (!data) return <p className="p-6 text-sm text-muted-foreground">Loading swarm…</p>

  const hotRoles = activeStage ? STAGE_TO_ROLES[activeStage] || [] : []
  const backends = (data.backends as { vultr?: boolean; vultr_model?: string }) || {}

  return (
    <div className="mx-auto w-full max-w-7xl px-6 md:px-10 py-8 space-y-7">
      <div className="space-y-4">
        <div className="flex flex-wrap items-center gap-2">
          <h1 className="text-2xl font-semibold tracking-tight">Workflow</h1>
          <div className="flex-1" />
          <Button asChild size="sm" variant="ghost"><Link href={`/${repo}`}>Explore</Link></Button>
          <Button asChild size="sm" variant="ghost"><Link href={`/${repo}/migration`}>Theater</Link></Button>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Button size="sm" disabled={demoBusy} onClick={() => void runDemo()}>
            {demoBusy ? "Running live swarm…" : "Run architecture demo"}
          </Button>
          <span className="text-[11px] text-muted-foreground font-mono">
            calls {String(data.nemotron_calls ?? 0)} · wall {String(data.wall_s ?? "—")}s · speedup {String(data.speedup ?? "—")}×
          </span>
          {demoStep?.id && (
            <span className="text-[11px] text-muted-foreground">
              cut <span className="font-mono text-foreground">{demoStep.id}</span>
              {demoStep.title ? ` · ${demoStep.title}` : ""}
              {demoStep.cuts != null ? ` · ${demoStep.cuts} edges` : ""}
              {" · "}
              <Link className="underline underline-offset-2 hover:text-foreground" href={`/${repo}`}>Explore</Link>
              {" / "}
              <Link className="underline underline-offset-2 hover:text-foreground" href={`/${repo}/migration`}>Theater</Link>
            </span>
          )}
        </div>

        <VultrThreadMatrixCard
          matrix={matrix ?? {
            configured: !!backends.vultr,
            capacity: 8,
            model: backends.vultr_model,
            host: "api.vultrinference.com/v1",
            threads: [],
          }}
          busy={matrixBusy}
          onRun={() => void runThreadMatrix()}
          measuredAt={matrixAt}
        />
        <div>
          {(stages.length > 0 ? stages : [
            { id: "plan", label: "Coordinator", detail: "Next legal cut from requires[]" },
            { id: "fanout", label: "Lenses ∥", detail: "Real snippets → Nemotron" },
            { id: "gate", label: "Prover", detail: "Primary-source gate" },
            { id: "write", label: "Planner", detail: "Write onto measured plan" },
            { id: "exec", label: "Execute", detail: "Explore playback cut" },
          ]).map((s, i, arr) => (
            <span key={s.id} className="inline-flex items-center gap-1.5 mr-1 mb-1">
              <span className={`rounded-md border px-2.5 py-1.5 text-left ${
                s.status === "running" || activeStage === s.id ? "border-sky-400 bg-sky-500/15"
                  : s.status === "done" ? "border-emerald-500/40 bg-emerald-500/10"
                    : "bg-background/80"
              }`}>
                <span className="text-[11px] font-semibold">{i + 1}. {s.label}</span>
                <span className="block text-[10px] text-muted-foreground">{s.detail}</span>
              </span>
              {i < arr.length - 1 && <span className="text-muted-foreground text-xs">→</span>}
            </span>
          ))}
        </div>
        {demoNote && <p className="text-[12px] text-emerald-400">{demoNote}</p>}
      </div>

      <div className="grid lg:grid-cols-2 gap-4">
        <div className="border rounded-md overflow-hidden">
          <div className="px-3 py-2 border-b flex items-center gap-2">
            <p className="text-xs font-medium">Live swarm DAG</p>
            <span className="text-[10px] text-muted-foreground">highlights follow the demo stage</span>
            {demoBusy && <span className="ml-auto text-[10px] text-sky-400 animate-pulse">live</span>}
          </div>
          <div className="bg-muted/15 overflow-auto">
            <svg width={layout.width} height={layout.height} className="min-w-full">
              {(dag?.edges || []).map((e, i) => {
                const a = layout.pos.get(e.source)
                const b = layout.pos.get(e.target)
                if (!a || !b) return null
                return <line key={i} x1={a.x + 104} y1={a.y + 16} x2={b.x} y2={b.y + 16} stroke="currentColor" strokeOpacity={0.35} />
              })}
              {(dag?.nodes || []).map((n) => {
                const p = layout.pos.get(n.id)
                if (!p) return null
                const hot = hotRoles.some((h) => n.role.toLowerCase().includes(h))
                return (
                  <g key={n.id} transform={`translate(${p.x},${p.y})`}>
                    <rect width={112} height={34} rx={6}
                      className={hot ? "fill-sky-500/25 stroke-sky-400" : "fill-background stroke-border"}
                      strokeWidth={hot ? 1.6 : 1} />
                    {n.parallel && <circle cx={104} cy={8} r={3} className="fill-violet-400" />}
                    <text x={8} y={14} className="fill-foreground text-[10px] font-medium">{n.role}</text>
                    <text x={8} y={26} className="fill-muted-foreground text-[9px]">×{n.count}{n.parallel ? " ∥" : ""}</text>
                  </g>
                )
              })}
              {!dag?.nodes?.length && (
                <text x={24} y={40} className="fill-muted-foreground text-[12px]">Run the demo to populate the DAG from live Nemotron tasks.</text>
              )}
            </svg>
          </div>
        </div>

        <div className="border rounded-md overflow-hidden">
          <div className="px-3 py-1.5 border-b flex items-center gap-2 bg-zinc-950 text-zinc-300">
            <span className="size-2 rounded-full bg-red-500/80" />
            <span className="size-2 rounded-full bg-amber-500/80" />
            <span className="size-2 rounded-full bg-emerald-500/80" />
            <p className="text-[11px] font-mono ml-2">agent-trace.log</p>
          </div>
          <div ref={termRef} className="h-[280px] overflow-auto bg-zinc-950 text-zinc-300 font-mono text-[11px] leading-relaxed p-3">
            {logs.map((line, i) => (
              <div key={i} className={
                line.startsWith("#") ? "text-zinc-500"
                  : line.startsWith("OK") ? "text-emerald-400/90"
                    : line.startsWith("$") ? "text-sky-400"
                      : ""
              }>{line}</div>
            ))}
            {demoBusy && <div className="text-zinc-500 animate-pulse">▌</div>}
            {!logs.length && <div className="text-zinc-500"># press Run architecture demo</div>}
          </div>
        </div>
      </div>

      <div className="border rounded-md overflow-hidden">
        <div className="px-3 py-2 border-b flex items-center gap-2">
          <p className="text-xs font-medium">Decision tape</p>
          <span className="text-[10px] text-muted-foreground">live accept / reject from the demo</span>
        </div>
        <div className="max-h-[240px] overflow-auto divide-y">
          {decisions.map((d, i) => (
            <div key={i} className="px-3 py-2">
              <div className="flex items-center gap-2 text-[10px]">
                <span className="font-mono uppercase text-muted-foreground">{d.kind}</span>
                <span className="font-medium">{d.role}</span>
                <span className="ml-auto font-mono text-emerald-500">{d.verdict}</span>
                <span className="text-muted-foreground font-mono">{d.latency_s ?? "—"}s</span>
              </div>
              <p className="mt-0.5 text-[12px] leading-snug">{d.text || d.decision}</p>
            </div>
          ))}
          {!decisions.length && (
            <p className="p-4 text-xs text-muted-foreground">Decisions appear as each agent stage completes.</p>
          )}
        </div>
      </div>

      <div className="flex gap-2">
        <Button variant="outline" onClick={() => window.open(`/api/repos/${repo}/report.pdf`)}>Export PDF</Button>
        <Button variant="ghost" onClick={refresh}>Refresh</Button>
      </div>
    </div>
  )
}
