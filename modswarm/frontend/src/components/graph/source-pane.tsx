"use client"

import { useEffect, useRef, useState } from "react"
import { X } from "lucide-react"
import { useGraphStore } from "@/store/graph-store"

export function SourcePane({
  repoId,
  variant = "dock",
}: {
  repoId: string
  /** dock = bottom of left explorer; overlay kept for rare graph use */
  variant?: "dock" | "overlay"
}) {
  const focus = useGraphStore((s) => s.repos[repoId]?.sourceFocus ?? null)
  const [text, setText] = useState("")
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState("")
  const lineRefs = useRef<Map<number, HTMLDivElement>>(new Map())
  const scrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!focus?.path) {
      setText("")
      setErr("")
      return
    }
    let alive = true
    setLoading(true)
    setErr("")
    const q = new URLSearchParams({ path: focus.path })
    if (focus.line) q.set("line", String(focus.line))
    fetch(`/api/repos/${repoId}/source?${q}`)
      .then(async (r) => {
        if (!r.ok) throw new Error(await r.text())
        return r.json()
      })
      .then((b: { text?: string }) => {
        if (!alive) return
        setText(b.text || "")
        setLoading(false)
      })
      .catch((e) => {
        if (!alive) return
        setErr(String((e as Error)?.message || e))
        setText("")
        setLoading(false)
      })
    return () => { alive = false }
  }, [repoId, focus?.path])

  // Scroll relative to the pane viewport (not offsetParent / file-tree above)
  useEffect(() => {
    if (loading || !focus?.line || !text) return
    let cancelled = false
    const jump = () => {
      if (cancelled) return
      const el = lineRefs.current.get(focus.line!)
      const box = scrollRef.current
      if (!el || !box) return
      const elRect = el.getBoundingClientRect()
      const boxRect = box.getBoundingClientRect()
      const delta = elRect.top - boxRect.top - box.clientHeight / 2 + elRect.height / 2
      box.scrollTop += delta
    }
    const t1 = requestAnimationFrame(() => requestAnimationFrame(jump))
    const t2 = window.setTimeout(jump, 50)
    const t3 = window.setTimeout(jump, 200)
    return () => {
      cancelled = true
      cancelAnimationFrame(t1)
      window.clearTimeout(t2)
      window.clearTimeout(t3)
    }
  }, [loading, text, focus?.line, focus?.endLine, focus?.path])

  if (!focus?.path) return null

  const lines = text.split("\n")
  const start = focus.line || 0
  const end = focus.endLine || start

  const shell =
    variant === "overlay"
      ? "absolute bottom-3 left-3 z-[55] w-[min(420px,calc(100%-24px))] max-h-[34%] flex flex-col rounded-md border border-border bg-background shadow-2xl overflow-hidden pointer-events-auto"
      : "shrink-0 border-t bg-background flex flex-col h-[42%] min-h-[160px] max-h-[48%] overflow-hidden"

  return (
    <div className={shell}>
      <div className="flex items-center gap-1.5 border-b px-2.5 py-1.5 shrink-0">
        <span className="text-[11px] font-mono truncate" title={focus.path}>{focus.path}</span>
        {focus.line ? (
          <span className="text-[10px] text-muted-foreground shrink-0">:{focus.line}{end > start ? `–${end}` : ""}</span>
        ) : null}
        <button
          type="button"
          className="ml-auto p-0.5 text-muted-foreground hover:text-foreground"
          onClick={() => useGraphStore.getState().setSourceFocus(repoId, null)}
        >
          <X className="size-3.5" />
        </button>
      </div>
      <div ref={scrollRef} className="relative overflow-auto flex-1 min-h-0 font-mono text-[10px] leading-[1.45]">
        {loading && <p className="px-2.5 py-2 text-muted-foreground">Loading…</p>}
        {err && <p className="px-2.5 py-2 text-orange-400">{err}</p>}
        {!loading && !err && lines.map((row, i) => {
          const n = i + 1
          const on = start > 0 && n >= start && n <= end
          return (
            <div
              key={n}
              data-line={n}
              ref={(el) => {
                if (el) lineRefs.current.set(n, el)
                else lineRefs.current.delete(n)
              }}
              className={`flex px-2 ${on ? "bg-sky-500/25 text-foreground" : "text-muted-foreground/90"}`}
            >
              <span className="w-8 shrink-0 select-none text-right pr-2 opacity-50 tabular-nums">{n}</span>
              {/* pre (no wrap) so gutter line N is exactly one row — COBOL lines are long */}
              <pre className="flex-1 whitespace-pre m-0 overflow-x-auto">{row || " "}</pre>
            </div>
          )
        })}
      </div>
    </div>
  )
}
