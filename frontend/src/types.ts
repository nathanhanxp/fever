export type NodeKind = "program" | "copybook" | "dataset" | "job" | "transaction" | "screen" | "interface" | string

export interface GraphNode {
  id: string
  name: string
  kind: NodeKind
  subtype: string
  file: string
  line: number
  summary: string
  cluster: string
  degree: number
  hub: boolean
  risk: number
  status: string
  entry: boolean
  external: boolean
  x: number
  y: number
  z: number
  capability?: string
  capability_label?: string
  pos?: { layered?: number[]; topdown?: number[]; similarity?: number[] | null }
  qualityCount?: number
  blast?: number
  provedRatio?: number
  ledger?: number | null
}

export interface GraphEdge {
  id: string
  source: string
  target: string
  type: string
  file: string
  line: number
  snippet: string
  mechanism: string
  proved: boolean
  dynamic: boolean
  predicted?: boolean
  agent?: string
}

export interface Finding {
  id: string
  lens: string
  type: string
  rule: string
  title: string
  file: string
  line: number
  snippet: string
  authority: string
  confidence: number
  agent: string
  verdict: string
  verdict_reason: string
  claim: string
  severity: string
  node_id: string
}

export interface Step {
  id: string
  index: number
  verb: string
  title: string
  detail: string
  claim: string
  remove_ids: string[]
  removals: Array<{
    id: string
    reason: string
    mechanism: string
    file: string
    line: number
    snippet: string
    type: string
    source: string
    target: string
  }>
  add_nodes: GraphNode[]
  add_edges: GraphEdge[]
  migrate: string[]
  requires: Array<{ step_id: string; because: string }>
  unblocks: string[]
  files: string[]
  acceptance: string[]
  risks: string[]
  risk_before: number
  risk_after: number
  deps_before: Record<string, number>
  deps_after: Record<string, number>
  legacy_remaining: number
}

export interface Driver {
  id: string
  label: string
  weight: number
  score: number
  text: string
  citations: Array<{ file: string; line: number; title: string }>
}

export interface RunModel {
  status?: string
  repo: string
  license: string
  elapsed_seconds: number
  nodes: GraphNode[]
  edges: GraphEdge[]
  findings: Finding[]
  triage: { raw: number; triaged: number; rejected: number; structural_dupes: number; embeddings: string }
  measured: {
    claim: string
    rule: string
    file: string
    literal_preview: string
    before: number
    after: number
    diff: string
    note: string
  } | null
  behavior_queue: Array<{ finding_id: string; title: string; file: string; line: number; decision: string; reason: string }>
  rules: Array<{ id: string; program: string; file: string; line: number; snippet: string; text: string; claim: string; decision: string; note: string }>
  drivers: Driver[]
  plan: { steps: Step[]; curve: Array<{ step: number; legacy_dependencies: number; title: string; id?: string }>; claim: string; version?: number; reason?: string }
  plan_version: number
  plan_versions: Array<{ version: number; reason: string; steps: string[] }>
  validator: { legal_order_violations: Array<{ step_id: string; message: string }>; invalid_demo_violations: Array<{ step_id: string; message: string }>; invalid_order: string[] }
  clusters: Array<{ id: string; label: string; size: number; hubs: string[]; summary: string }>
  agents: Array<{ id: string; role: string; status: string; started: number; seconds: number; tokens: number; model: string; host: string; note: string }>
  benchmark: { rows: Array<Record<string, unknown>>; note: string }
  model_benchmark?: { rows: Array<Record<string, unknown>> }
  stats: Record<string, number>
  geometry?: {
    similarity: { method?: string; error?: string; fitted_on?: string; n_fitted?: number; random_state?: number } | null
    clustering: { method: string; used_for_view: boolean; n_clusters: number; note: string; hdbscan_n?: number; noise?: number }
  }
  limits: string[]
  models: Array<{ role: string; model: string; host: string; called: boolean }>
  brief: { target: string; where: string; downtime: string; asked: boolean }
}

export interface AskResult {
  answer: string
  citations: Array<{ file: string; line: number; title: string; node_id?: string }>
  counts: Array<{ label: string; node_ids: string[] }>
  highlight: { focus: string; downstream: Record<string, number>; upstream: Record<string, number>; direction: string }
  ui: { edge_types?: string[]; simulate?: string }
  result_card?: ResultCard | null
  claim: string
}

export interface ResultCard {
  focus: string
  claim: string
  affected: number
  by_kind: Record<string, number>
  by_type: Record<string, number>
  risk_before: number
  risk_after: number
  step_id: string | null
  note: string
  downstream: Record<string, number>
}

export const EDGE_TYPES = ["COPY", "CALL", "LINK", "XCTL", "FILE", "JOB", "TRANS", "SCREEN"] as const
