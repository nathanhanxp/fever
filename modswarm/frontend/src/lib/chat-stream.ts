export interface GraphScope {
  node_ids: string[]
  edge_keys: string[]
  count: number
  edge_count?: number
  lens?: string | null
  label?: string | null
  top?: string[]
  model?: string | null
}

export interface StreamCallbacks {
  onReasoning: (delta: string) => void
  onToolStart: (id: string, name: string, args: Record<string, unknown>) => void
  onToolDone: (id: string, data: Record<string, unknown>) => void
  onTextDelta: (delta: string) => void
  onReplaceText: (text: string) => void
  onGraphFocus?: (scope: GraphScope) => void
  onDone: () => void
  onError: (error: string) => void
}

export type ChatVisionPayload = {
  image?: string | null
  clusters?: { label: string; color: string; hue?: number; hue_name?: string; count?: number }[]
  step_id?: string | null
}

export async function streamChat(
  repoId: string,
  message: string,
  history: { role: string; content: string }[],
  callbacks: StreamCallbacks,
  snapshotId?: string | null,
  vision?: ChatVisionPayload | null,
) {
  const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? ""
  const key = typeof window !== "undefined" ? localStorage.getItem("graphdev-api-key") : null
  const headers: Record<string, string> = { "Content-Type": "application/json" }
  if (key) headers["X-API-Key"] = key

  const res = await fetch(`${apiUrl}/api/repos/${repoId}/chat`, {
    method: "POST",
    headers,
    body: JSON.stringify({
      message,
      history,
      snapshot_id: snapshotId ?? undefined,
      image: vision?.image || undefined,
      clusters: vision?.clusters || undefined,
      step_id: vision?.step_id || undefined,
    }),
  })

  if (!res.ok) {
    callbacks.onError(`Chat request failed: ${res.status}`)
    return
  }

  const reader = res.body!.getReader()
  const decoder = new TextDecoder()
  let buffer = ""

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })

    const lines = buffer.split("\n")
    buffer = lines.pop() ?? ""

    for (const line of lines) {
      if (!line.startsWith("data: ")) continue
      try {
        const data = JSON.parse(line.slice(6))
        switch (data.type) {
          case "reasoning":
            callbacks.onReasoning(data.delta)
            break
          case "tool_start":
            callbacks.onToolStart(data.id, data.name, data.args)
            break
          case "tool_done":
            callbacks.onToolDone(data.id, data)
            break
          case "text_delta":
            callbacks.onTextDelta(data.delta)
            break
          case "replace_text":
            callbacks.onReplaceText(data.text)
            break
          case "graph_focus":
            callbacks.onGraphFocus?.(data)
            break
          case "done":
            callbacks.onDone()
            break
          case "error":
            callbacks.onError(data.message ?? "Unknown error")
            break
        }
      } catch {
        // skip malformed SSE lines
      }
    }
  }

  callbacks.onDone()
}
