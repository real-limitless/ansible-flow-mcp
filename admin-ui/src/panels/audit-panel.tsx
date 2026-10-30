import { useEffect, useState } from "react"

import {
  Empty,
  EmptyHeader,
  EmptyTitle,
} from "@/components/ui/empty"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { TokenNeeded } from "@/components/node-table"
import { PanelSkeleton, Surface } from "@/components/surface"
import { api, errorMessage } from "@/lib/api"
import type { AuditEvent } from "@/lib/types"

export function AuditPanel({
  token,
  onError,
}: {
  token: string
  onError: (message: string) => void
}) {
  const [events, setEvents] = useState<AuditEvent[] | null>(null)
  const [loading, setLoading] = useState(Boolean(token))

  useEffect(() => {
    if (!token) return
    let cancelled = false
    ;(async () => {
      try {
        const body = await api<{ events?: AuditEvent[] }>(
          token,
          "/v1/audit?limit=80",
        )
        if (cancelled) return
        setEvents(body.events || [])
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
  if (loading && !events) return <PanelSkeleton />
  if (!events) return null

  return (
    <Surface title="Audit" aside="redacted">
      {events.length ? (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Time</TableHead>
              <TableHead>Event</TableHead>
              <TableHead>Detail</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {events.map((event, index) => {
              const { ts, event: name, ...rest } = event
              return (
                <TableRow key={`${ts ?? "event"}-${index}`}>
                  <TableCell className="font-mono">{ts ?? ""}</TableCell>
                  <TableCell>{name ?? ""}</TableCell>
                  <TableCell className="font-mono text-xs">
                    {JSON.stringify(rest)}
                  </TableCell>
                </TableRow>
              )
            })}
          </TableBody>
        </Table>
      ) : (
        <Empty>
          <EmptyHeader>
            <EmptyTitle>No audit events.</EmptyTitle>
          </EmptyHeader>
        </Empty>
      )}
    </Surface>
  )
}
