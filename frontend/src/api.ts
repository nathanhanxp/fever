import type { AskResult, RunModel } from "./types"

export async function fetchRun(): Promise<RunModel & { status: string }> {
  const res = await fetch("/api/run")
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function fetchFile(path: string): Promise<string> {
  const res = await fetch("/api/file?path=" + encodeURIComponent(path))
  if (!res.ok) throw new Error(await res.text())
  const data = await res.json()
  return data.text as string
}

export async function ask(question: string, depth: number): Promise<AskResult> {
  const res = await fetch("/api/ask", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question, depth }),
  })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function simulate(nodeId: string, depth: number) {
  const res = await fetch("/api/simulate/" + encodeURIComponent(nodeId) + "?depth=" + depth, { method: "POST" })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function saveBrief(body: unknown) {
  const res = await fetch("/api/brief", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function saveWeights(weights: Record<string, number>) {
  const res = await fetch("/api/weights", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ weights }),
  })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function validateOrder(order: string[]) {
  const res = await fetch("/api/validate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ order }),
  })
  if (!res.ok) throw new Error(await res.text())
  return res.json() as Promise<{ violations: Array<{ step_id: string; message: string }> }>
}

export function workOrderUrl(stepId: string) {
  return "/api/work-order/" + stepId
}
