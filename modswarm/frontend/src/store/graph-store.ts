import { create } from "zustand"
import type { GraphData, GraphHighlight } from "@/types/graph"

export type CyberRisk = "legacy" | "orange" | "purple" | null

export type SourceFocus = {
  path: string
  line?: number | null
  endLine?: number | null
} | null

interface RepoGraph {
  data: GraphData | null
  highlight: GraphHighlight | null
  selectedNodeId: string | null
  selectedEdgeKey: string | null
  edgeTypeFilter: string
  /** Playback: units already retired / migrated — dimmed on the graph */
  retiredNodeIds: Set<string>
  /** Playback: edges removed by completed steps */
  removedEdgeKeys: Set<string>
  /** Prover rejection: edges that flash dashed red until resolved */
  flashingEdgeKeys: Set<string>
  /** Current Play step: edges/nodes that glow, then fall back to faded */
  glowEdgeKeys: Set<string>
  glowNodeIds: Set<string>
  /** Subset of glow nodes that should paint predicted orange/purple this step */
  cyberGlowNodeIds: Set<string>
  /** Predictive cyber horizon: node id → orange (post-mig API) | purple (transit) | legacy (red) */
  cyberRisk: Record<string, CyberRisk>
  playbackStepId: string | null
  /** Persist Migrate panel progress across Ask ↔ Migrate */
  migrateIndex: number
  migrateCompleted: string[]
  /** Bottom-left source viewer */
  sourceFocus: SourceFocus
  /** Bumps when graph cuts are cleared so Migrate can re-apply completed steps */
  graphEpoch: number
}

interface GraphState {
  repos: Record<string, RepoGraph>
  setData: (repoId: string, data: GraphData | null) => void
  setHighlight: (repoId: string, highlight: GraphHighlight | null) => void
  selectNode: (repoId: string, nodeId: string | null) => void
  selectEdge: (repoId: string, edgeKey: string | null) => void
  setEdgeTypeFilter: (repoId: string, edgeTypeFilter: string) => void
  setSourceFocus: (repoId: string, focus: SourceFocus) => void
  setPlayback: (
    repoId: string,
    patch: Partial<Pick<RepoGraph, "retiredNodeIds" | "removedEdgeKeys" | "flashingEdgeKeys" | "glowEdgeKeys" | "glowNodeIds" | "cyberGlowNodeIds" | "playbackStepId" | "cyberRisk" | "migrateIndex" | "migrateCompleted" | "sourceFocus">>,
  ) => void
  resetPlayback: (repoId: string) => void
  reset: (repoId: string) => void
}

function makeEmptyRepo(): RepoGraph {
  return {
    data: null,
    highlight: null,
    selectedNodeId: null,
    selectedEdgeKey: null,
    edgeTypeFilter: "All",
    retiredNodeIds: new Set(),
    removedEdgeKeys: new Set(),
    flashingEdgeKeys: new Set(),
    glowEdgeKeys: new Set(),
    glowNodeIds: new Set(),
    cyberGlowNodeIds: new Set(),
    cyberRisk: {},
    playbackStepId: null,
    migrateIndex: 0,
    migrateCompleted: [],
    sourceFocus: null,
    graphEpoch: 0,
  }
}

function getRepo(state: GraphState, repoId: string): RepoGraph {
  return state.repos[repoId] ?? makeEmptyRepo()
}

export const useGraphStore = create<GraphState>((set, get) => ({
  repos: {},

  setData: (repoId, data) =>
    set((s) => ({
      repos: {
        ...s.repos,
        [repoId]: { ...getRepo(s, repoId), data },
      },
    })),

  setHighlight: (repoId, highlight) =>
    set((s) => ({
      repos: {
        ...s.repos,
        [repoId]: { ...getRepo(s, repoId), highlight },
      },
    })),

  selectNode: (repoId, nodeId) =>
    set((s) => ({
      repos: {
        ...s.repos,
        [repoId]: { ...getRepo(s, repoId), selectedNodeId: nodeId, selectedEdgeKey: null },
      },
    })),

  selectEdge: (repoId, edgeKey) =>
    set((s) => ({
      repos: {
        ...s.repos,
        [repoId]: { ...getRepo(s, repoId), selectedEdgeKey: edgeKey, selectedNodeId: null },
      },
    })),

  setEdgeTypeFilter: (repoId, edgeTypeFilter) =>
    set((s) => ({
      repos: {
        ...s.repos,
        [repoId]: { ...getRepo(s, repoId), edgeTypeFilter },
      },
    })),

  setSourceFocus: (repoId, focus) =>
    set((s) => ({
      repos: {
        ...s.repos,
        [repoId]: { ...getRepo(s, repoId), sourceFocus: focus },
      },
    })),

  setPlayback: (repoId, patch) =>
    set((s) => ({
      repos: {
        ...s.repos,
        [repoId]: { ...getRepo(s, repoId), ...patch },
      },
    })),

  resetPlayback: (repoId) =>
    set((s) => {
      const cur = getRepo(s, repoId)
      return {
        repos: {
          ...s.repos,
          [repoId]: {
            ...cur,
            retiredNodeIds: new Set(),
            removedEdgeKeys: new Set(),
            flashingEdgeKeys: new Set(),
            glowEdgeKeys: new Set(),
            glowNodeIds: new Set(),
            cyberGlowNodeIds: new Set(),
            playbackStepId: null,
            highlight: null,
            graphEpoch: (cur.graphEpoch || 0) + 1,
            // Keep migrateIndex / migrateCompleted so Ask↔Migrate / tab switches restore
          },
        },
      }
    }),

  reset: (repoId) =>
    set((s) => ({
      repos: {
        ...s.repos,
        [repoId]: makeEmptyRepo(),
      },
    })),
}))
