import { useEffect, useState } from "react"
import { toast } from "sonner"

import { Button } from "@/components/ui/button"
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { NodeTable, TokenNeeded } from "@/components/node-table"
import { PanelSkeleton, Surface } from "@/components/surface"
import { api, errorMessage } from "@/lib/api"
import type { HostNode, HubStatus, IssuedToken, PingResult } from "@/lib/types"

const emptyEdit = { name: "", host: "", port: "", user: "" }

export function ServersPanel({
  token,
  onError,
  onRefresh,
}: {
  token: string
  onError: (message: string) => void
  onRefresh: () => void
}) {
  const [nodes, setNodes] = useState<HostNode[] | null>(null)
  const [spokeNames, setSpokeNames] = useState<string[]>([])
  const [loading, setLoading] = useState(Boolean(token))
  const [invName, setInvName] = useState("")
  const [invTtl, setInvTtl] = useState("900")
  const [invHub, setInvHub] = useState("")
  const [invAddr, setInvAddr] = useState("")
  const [invite, setInvite] = useState<IssuedToken | null>(null)
  const [edit, setEdit] = useState(emptyEdit)

  useEffect(() => {
    if (!token) return
    let cancelled = false
    ;(async () => {
      try {
        const [listed, status] = await Promise.all([
          api<{ nodes?: HostNode[] }>(token, "/v1/nodes"),
          api<HubStatus>(token, "/v1/status"),
        ])
        if (cancelled) return
        setNodes(listed.nodes || [])
        setSpokeNames(status.spokes || [])
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
  if (loading && !nodes) return <PanelSkeleton />
  if (!nodes) return null

  async function issueToken() {
    try {
      const body: Record<string, unknown> = {
        name: invName.trim(),
        ttl_seconds: Number(invTtl || 900),
      }
      if (invHub.trim()) body.hub = invHub.trim()
      if (invAddr.trim()) body.public_addr = invAddr.trim()
      const issued = await api<IssuedToken>(token, "/v1/tokens", {
        method: "POST",
        body: JSON.stringify(body),
      })
      setInvite(issued)
      onError("")
    } catch (err) {
      onError(errorMessage(err))
    }
  }

  async function saveNode() {
    try {
      const payload: Record<string, unknown> = {}
      if (edit.host.trim()) payload.ansible_host = edit.host.trim()
      if (edit.port.trim()) payload.ansible_port = Number(edit.port)
      if (edit.user.trim()) payload.ansible_user = edit.user.trim()
      await api(token, `/v1/nodes/${encodeURIComponent(edit.name.trim())}`, {
        method: "PATCH",
        body: JSON.stringify(payload),
      })
      onRefresh()
    } catch (err) {
      onError(errorMessage(err))
    }
  }

  async function remove(name: string) {
    try {
      await api(token, `/v1/nodes/${encodeURIComponent(name)}`, {
        method: "DELETE",
      })
      onRefresh()
    } catch (err) {
      onError(errorMessage(err))
    }
  }

  async function ping(name: string) {
    try {
      const res = await api<PingResult>(
        token,
        `/v1/nodes/${encodeURIComponent(name)}/ping`,
        { method: "POST", body: "{}" },
      )
      if (res.ok) toast.success(`Ping ok: ${name}`)
      else toast.error(`Ping failed: ${res.error || res.stderr || "error"}`)
    } catch (err) {
      onError(errorMessage(err))
    }
  }

  const aside = `${nodes.length} · ${spokeNames.join(", ") || "empty"}`

  return (
    <div className="flex flex-col gap-4">
      <Surface title="Invite spoke" aside="one-time">
        <FieldGroup className="grid sm:grid-cols-2">
          <Field>
            <FieldLabel htmlFor="invName">Name</FieldLabel>
            <Input
              id="invName"
              value={invName}
              placeholder="web-01"
              onChange={(event) => setInvName(event.target.value)}
            />
          </Field>
          <Field>
            <FieldLabel htmlFor="invTtl">TTL seconds</FieldLabel>
            <Input
              id="invTtl"
              value={invTtl}
              onChange={(event) => setInvTtl(event.target.value)}
            />
          </Field>
          <Field>
            <FieldLabel htmlFor="invHub">Join hub</FieldLabel>
            <Input
              id="invHub"
              value={invHub}
              placeholder="mcp-join@hub"
              onChange={(event) => setInvHub(event.target.value)}
            />
          </Field>
          <Field>
            <FieldLabel htmlFor="invAddr">Public addr</FieldLabel>
            <Input
              id="invAddr"
              value={invAddr}
              placeholder="web-01"
              onChange={(event) => setInvAddr(event.target.value)}
            />
          </Field>
        </FieldGroup>
        <Button type="button" className="self-start" onClick={() => void issueToken()}>
          Issue token
        </Button>
        {invite ? (
          <div className="flex flex-col gap-2 rounded-lg bg-muted/50 p-3">
            <p className="text-sm text-muted-foreground">Shown once. Copy now.</p>
            <pre className="overflow-x-auto font-mono text-xs">{invite.token}</pre>
            <p className="text-sm font-medium">Join command</p>
            <pre className="overflow-x-auto font-mono text-xs">
              {invite.join_command}
            </pre>
          </div>
        ) : null}
      </Surface>
      <Surface title="Enrolled spokes" aside={aside}>
        <NodeTable
          nodes={nodes}
          empty="No spokes yet."
          removeLabel="Revoke"
          onEdit={(node) =>
            setEdit({
              name: node.name ?? "",
              host: node.ansible_host ?? "",
              port: node.ansible_port == null ? "" : String(node.ansible_port),
              user: node.ansible_user ?? "",
            })
          }
          onRemove={remove}
          onPing={ping}
        />
      </Surface>
      <Surface title="Edit spoke" aside="update_node">
        <FieldGroup className="grid sm:grid-cols-2">
          <Field>
            <FieldLabel htmlFor="edName">Name</FieldLabel>
            <Input
              id="edName"
              value={edit.name}
              onChange={(event) =>
                setEdit((current) => ({ ...current, name: event.target.value }))
              }
            />
          </Field>
          <Field>
            <FieldLabel htmlFor="edHost">ansible_host</FieldLabel>
            <Input
              id="edHost"
              value={edit.host}
              onChange={(event) =>
                setEdit((current) => ({ ...current, host: event.target.value }))
              }
            />
          </Field>
          <Field>
            <FieldLabel htmlFor="edPort">port</FieldLabel>
            <Input
              id="edPort"
              value={edit.port}
              onChange={(event) =>
                setEdit((current) => ({ ...current, port: event.target.value }))
              }
            />
          </Field>
          <Field>
            <FieldLabel htmlFor="edUser">user</FieldLabel>
            <Input
              id="edUser"
              value={edit.user}
              onChange={(event) =>
                setEdit((current) => ({ ...current, user: event.target.value }))
              }
            />
          </Field>
        </FieldGroup>
        <Button type="button" className="self-start" onClick={() => void saveNode()}>
          Save
        </Button>
      </Surface>
    </div>
  )
}
