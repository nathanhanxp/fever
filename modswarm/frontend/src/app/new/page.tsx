"use client"

import { useState } from "react"
import { toast } from "sonner"
import { Button } from "@/components/ui/button"
import { Input } from "@/components/ui/input"
import { ProgressIndicator } from "@/components/ui/progress-indicator"
import { Logo } from "@/components/logo"

export default function NewRepoPage() {
  const [loading, setLoading] = useState(false)
  const [complete, setComplete] = useState(false)
  const [repoId, setRepoId] = useState<string | null>(null)
  const [status, setStatus] = useState("")

  const go = (id: string) => {
    setRepoId(id)
    setComplete(true)
    window.location.href = `/${id}`
  }

  const openPreset = async (path: string, label: string) => {
    setLoading(true)
    setStatus(`Opening ${label}…`)
    try {
      const res = await fetch(path, { method: "POST" })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) {
        toast.error(typeof data.detail === "string" ? data.detail : `Failed to open ${label}`)
        setLoading(false)
        return
      }
      go(data.repo_id)
    } catch {
      toast.error("Network error — is the backend running on port 8090?")
      setLoading(false)
    }
  }

  const onUpload = async (file: File) => {
    setLoading(true)
    setComplete(false)
    setStatus(`Uploading ${file.name}…`)
    try {
      const body = new FormData()
      body.append("file", file)
      const res = await fetch("/api/upload", { method: "POST", body })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) {
        const detail = Array.isArray(data.detail)
          ? data.detail.map((d: { msg?: string }) => d.msg).join("; ")
          : data.detail
        toast.error(detail || `Upload failed (${res.status})`)
        setLoading(false)
        setStatus("")
        return
      }
      if (!data.repo_id) {
        toast.error("Upload returned no repo_id")
        setLoading(false)
        return
      }
      setStatus(`Parsed ${data.units ?? "?"} units, ${data.legacy_edges ?? "?"} edges`)
      go(data.repo_id)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Upload failed")
      setLoading(false)
      setStatus("")
    }
  }

  return (
    <div className="min-h-screen flex flex-col items-center justify-center px-4">
      <div className="w-full max-w-[420px] space-y-8">
        <div className="flex flex-col items-center space-y-3">
          <Logo width={80} height={80} className="h-20 w-20" />
          <div className="text-center space-y-2">
            <h1 className="text-2xl font-semibold tracking-tight">
              Open a legacy codebase
            </h1>
            <p className="text-sm text-muted-foreground leading-relaxed">
              Upload a zip (COBOL / Java), or open a preset — CardDemo (COBOL→Spring) or jforum3 (VRaptor→Quarkus).
            </p>
          </div>
        </div>

        <div className="space-y-3">
          <label className="text-xs font-medium text-muted-foreground">Zip file</label>
          <Input
            type="file"
            accept=".zip,application/zip"
            disabled={loading}
            onChange={(e) => {
              const file = e.target.files?.[0]
              if (file) void onUpload(file)
              e.target.value = ""
            }}
          />
          {status && <p className="text-xs text-muted-foreground">{status}</p>}
          {loading ? (
            <ProgressIndicator
              profile="repo-add"
              isActive={loading}
              isComplete={complete}
              onComplete={() => { if (repoId) window.location.href = `/${repoId}` }}
              completeMessage="Repository ready"
              className="w-full"
            />
          ) : (
            <div className="space-y-2">
              <Button type="button" className="w-full h-11" onClick={() => void openPreset("/api/preset/carddemo", "CardDemo")}>
                Open CardDemo (COBOL)
              </Button>
              <Button
                type="button"
                variant="outline"
                className="w-full h-11"
                onClick={() => void openPreset("/api/preset/jforum3", "jforum3")}
              >
                Open jforum3 (Java → Quarkus)
              </Button>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
