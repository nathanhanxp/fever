import { buildClusterColorMap } from "@/lib/graph-utils"
import type { CodeUnitNode } from "@/types/graph"

function hueName(hue: number): string {
  const h = ((hue % 360) + 360) % 360
  if (h < 15 || h >= 345) return "red"
  if (h < 40) return "orange"
  if (h < 70) return "yellow/gold"
  if (h < 160) return "green"
  if (h < 200) return "cyan"
  if (h < 255) return "blue"
  if (h < 300) return "purple/violet"
  return "pink/magenta"
}

function parseHue(css: string): number | null {
  const m = /hsl\(\s*([0-9.]+)/i.exec(css)
  return m ? Number(m[1]) : null
}

export type ClusterPaletteRow = {
  label: string
  color: string
  hue: number
  hue_name: string
  count: number
}

/** PNG (preferred) of the live R3F graph + ground-truth cluster palette for the VLM. */
export function captureGraphVision(
  nodes: CodeUnitNode[],
  isDark: boolean,
): { image: string; clusters: ClusterPaletteRow[] } | null {
  const canvas = document.querySelector<HTMLCanvasElement>("[data-graph-canvas] canvas")
  if (!canvas || !canvas.width || !canvas.height) return null

  const maxW = 1100
  const scale = Math.min(1, maxW / Math.max(1, canvas.width))
  const w = Math.max(1, Math.round(canvas.width * scale))
  const h = Math.max(1, Math.round(canvas.height * scale))
  const off = document.createElement("canvas")
  off.width = w
  off.height = h
  const ctx = off.getContext("2d")
  if (!ctx) return null
  ctx.drawImage(canvas, 0, 0, w, h)

  let image = off.toDataURL("image/png")
  if (image.length > 1_700_000) {
    image = off.toDataURL("image/jpeg", 0.92)
  }

  const map = buildClusterColorMap(nodes, isDark)
  const counts = new Map<string, number>()
  for (const n of nodes) {
    if (!n.cluster_label) continue
    counts.set(n.cluster_label, (counts.get(n.cluster_label) || 0) + 1)
  }
  const clusters = [...map.entries()]
    .map(([label, color]) => {
      const hue = parseHue(color) ?? 0
      return {
        label,
        color,
        hue,
        hue_name: hueName(hue),
        count: counts.get(label) || 0,
      }
    })
    .sort((a, b) => b.count - a.count)

  return { image, clusters }
}
