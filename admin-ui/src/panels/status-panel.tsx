import { useEffect, useState } from "react"

import { Badge } from "@/components/ui/badge"
import { PanelSkeleton, Surface } from "@/components/surface"
import { TokenNeeded } from "@/components/node-table"
import { api, errorMessage } from "@/lib/api"
import type { HealthReport, HubStatus } from "@/lib/types"

export function StatusPanel({
  token,
  onError,
}: {
  token: string
  onError: (message: string) => void
}) {
  const [status, setStatus] = useState<HubStatus | null>(null)
  const [health, setHealth] = useState<HealthReport | null>(null)
  const [loading, setLoading] = useState(Boolean(token))

  useEffect(() => {
    if (!token) return
    let cancelled = false
    ;(async () => {
      try {
        const st = await api<HubStatus>(token, "/v1/status")
        const report = (await fetch("/health").then((r) => r.json())) as HealthReport
        if (cancelled) return
        setStatus(st)
        setHealth(report)
        onError("")
      } catch (err) {
        if (!cancelled) onError(errorMessage(err))
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [token, onError])

  if (!token) return <TokenNeeded />
  if (loading && !status) return <PanelSkeleton />
  if (!status || !health) return null

  const ok = health.ok !== false
  const version = status.version || health.version || ""

  return (
    <div className="flex flex-col gap-4">
      <Surface title="Hub" aside="inventory">
        <dl className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <Stat label="Name" value={status.name || "—"} />
          <Stat label="Hub id" value={status.hub_id || "—"} mono />
          <Stat label="Spokes" value={String((status.spokes || []).length)} />
          <Stat label="Targets" value={String((status.targets || []).length)} />
          <Stat label="Groups" value={String((status.groups || []).length)} />
          <div className="flex flex-col gap-1 rounded-lg bg-muted/40 p-3">
            <dt className="text-xs text-muted-foreground">Health</dt>
            <dd>
              <Badge variant={ok ? "secondary" : "destructive"}>
                {ok ? "ok" : "degraded"}
              </Badge>
            </dd>
          </div>
        </dl>
      </Surface>
      <Surface title="Paths" aside="live">
        <div className="flex flex-col gap-2 text-sm">
          <PathRow label="Inventory" value={status.inventory || ""} />
          <PathRow label="Root" value={status.root || ""} />
          <PathRow label="Known hosts" value={status.known_hosts || ""} />
          <PathRow label="Version" value={String(version)} />
        </div>
        <details className="rounded-lg border px-3 py-2">
          <summary className="cursor-pointer text-sm font-medium">
            Raw /health
          </summary>
          <pre className="mt-3 overflow-x-auto font-mono text-xs">
            {JSON.stringify(health, null, 2)}
          </pre>
        </details>
      </Surface>
    </div>
  )
}

function Stat({
  label,
  value,
  mono = false,
}: {
  label: string
  value: string
  mono?: boolean
}) {
  return (
    <div className="flex flex-col gap-1 rounded-lg bg-muted/40 p-3">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className={mono ? "font-mono text-sm" : "text-sm font-medium"}>
        {value}
      </dd>
    </div>
  )
}

function PathRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-wrap gap-2">
      <span className="w-28 text-muted-foreground">{label}</span>
      <span className="font-mono text-xs">{value}</span>
    </div>
  )
}
