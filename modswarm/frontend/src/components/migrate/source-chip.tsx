"use client"

function hostname(url?: string) {
  if (!url) return null
  try {
    return new URL(url).hostname.replace(/^www\./, "")
  } catch {
    return null
  }
}

export type SourceDoc = {
  title?: string
  source?: string
  url?: string
  passage?: string
}

/** Compact citation chip — title + host link, passage on hover. Not a text blob. */
export function SourceChip({ doc }: { doc: SourceDoc }) {
  const host = hostname(doc.url)
  const label = doc.title || doc.source || "Source"
  const inner = (
    <div className="rounded-md border bg-background px-2.5 py-2 hover:bg-muted/50 transition-colors">
      <div className="flex items-start gap-2">
        <div className="min-w-0 flex-1">
          <p className="text-[11px] font-medium leading-snug line-clamp-2">{label}</p>
          <p className="text-[10px] text-muted-foreground mt-0.5 truncate">
            {host || doc.source || "citation"}
            {doc.url ? " ↗" : ""}
          </p>
        </div>
      </div>
      {doc.passage && (
        <p className="text-[10px] text-muted-foreground mt-1.5 line-clamp-2 leading-snug border-t border-border/60 pt-1.5">
          {doc.passage}
        </p>
      )}
    </div>
  )

  if (!doc.url) return inner
  return (
    <a href={doc.url} target="_blank" rel="noreferrer" className="block" title={doc.url}>
      {inner}
    </a>
  )
}

export function SourceList({ docs, max = 4 }: { docs?: SourceDoc[]; max?: number }) {
  const list = (docs || []).filter((d) => d.title || d.url || d.source).slice(0, max)
  if (!list.length) return null
  return (
    <div className="space-y-1.5">
      <p className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">Sources</p>
      {list.map((d, i) => (
        <SourceChip key={d.url || d.title || i} doc={d} />
      ))}
    </div>
  )
}
