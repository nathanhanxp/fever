"use client"

import { useEffect, useState } from "react"
import { useParams } from "next/navigation"
import { Badge } from "@/components/ui/badge"

export default function EvalPage() {
  const { repo } = useParams<{ repo: string }>()
  const [data, setData] = useState<{ questions?: { id: number; question: string; expected: string[]; label: string }[]; prover?: string } | null>(null)
  useEffect(() => {
    fetch(`/api/repos/${repo}/eval`).then((r) => r.json()).then(setData)
  }, [repo])
  if (!data) return <p className="p-6 text-sm">Loading eval seeds.</p>
  return (
    <div className="p-6 space-y-3 max-w-3xl">
      <Badge variant="outline">{data.prover}</Badge>
      <p className="text-sm">Expected node names are read from the graph. Prover precision stays “awaiting labels” until docs/labels.csv is filled in.</p>
      <ol className="text-sm space-y-2">
        {(data.questions || []).map((q) => (
          <li key={q.id}>{q.question} <span className="text-muted-foreground">expected {q.expected.join(", ")} ({q.label})</span></li>
        ))}
      </ol>
    </div>
  )
}
