import { useEffect, useState } from "react"

import { Button } from "@/components/ui/button"
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { NodeTable, TokenNeeded } from "@/components/node-table"
import { PanelSkeleton, Surface } from "@/components/surface"
import { api, errorMessage } from "@/lib/api"
import type { HostNode } from "@/lib/types"

const emptyEdit = { name: "", host: "", conn: "", port: "", user: "" }

export function TargetsPanel({
  token,
  onError,
  onRefresh,
}: {
  token: string
  onError: (message: string) => void
  onRefresh: () => void
}) {
  const [targets, setTargets] = useState<HostNode[] | null>(null)
  const [loading, setLoading] = useState(Boolean(token))
  const [name, setName] = useState("")
  const [host, setHost] = useState("")
  const [conn, setConn] = useState("ssh")
  const [port, setPort] = useState("")
  const [user, setUser] = useState("")
  const [edit, setEdit] = useState(emptyEdit)

  useEffect(() => {
    if (!token) return
    let cancelled = false
    ;(async () => {
      try {
        const listed = await api<{ targets?: HostNode[] }>(token, "/v1/targets")
        if (cancelled) return
        setTargets(listed.targets || [])
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
  if (loading && !targets) return <PanelSkeleton />
  if (!targets) return null

  async function addTarget() {
    try {
      const payload: Record<string, unknown> = {
        name: name.trim(),
        ansible_host: host.trim(),
        ansible_connection: conn.trim() || "ssh",
      }
      if (port.trim()) payload.ansible_port = Number(port)
      if (user.trim()) payload.ansible_user = user.trim()
      await api(token, "/v1/targets", {
        method: "POST",
        body: JSON.stringify(payload),
      })
      onRefresh()
    } catch (err) {
      onError(errorMessage(err))
    }
  }

  async function saveTarget() {
    try {
      const payload: Record<string, unknown> = {}
      if (edit.host.trim()) payload.ansible_host = edit.host.trim()
      if (edit.conn.trim()) payload.ansible_connection = edit.conn.trim()
      if (edit.port.trim()) payload.ansible_port = Number(edit.port)
      if (edit.user.trim()) payload.ansible_user = edit.user.trim()
      await api(token, `/v1/targets/${encodeURIComponent(edit.name.trim())}`, {
        method: "PATCH",
        body: JSON.stringify(payload),
      })
      onRefresh()
    } catch (err) {
      onError(errorMessage(err))
    }
  }

  async function remove(targetName: string) {
    try {
      await api(token, `/v1/targets/${encodeURIComponent(targetName)}`, {
        method: "DELETE",
      })
      onRefresh()
    } catch (err) {
      onError(errorMessage(err))
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <Surface title="Register target" aside="no secrets">
        <p className="text-sm text-muted-foreground">
          Ansible-only host. Do not enter passwords — use hub Ansible cfg or path
          refs.
        </p>
        <FieldGroup className="grid sm:grid-cols-2">
          <Field>
            <FieldLabel htmlFor="tgName">Name</FieldLabel>
            <Input
              id="tgName"
              value={name}
              placeholder="win-01"
              onChange={(event) => setName(event.target.value)}
            />
          </Field>
          <Field>
            <FieldLabel htmlFor="tgHost">ansible_host</FieldLabel>
            <Input
              id="tgHost"
              value={host}
              onChange={(event) => setHost(event.target.value)}
            />
          </Field>
          <Field>
            <FieldLabel htmlFor="tgConn">connection</FieldLabel>
            <Input
              id="tgConn"
              value={conn}
              onChange={(event) => setConn(event.target.value)}
            />
          </Field>
          <Field>
            <FieldLabel htmlFor="tgPort">port</FieldLabel>
            <Input
              id="tgPort"
              value={port}
              onChange={(event) => setPort(event.target.value)}
            />
          </Field>
          <Field>
            <FieldLabel htmlFor="tgUser">user</FieldLabel>
            <Input
              id="tgUser"
              value={user}
              onChange={(event) => setUser(event.target.value)}
            />
          </Field>
        </FieldGroup>
        <Button type="button" className="self-start" onClick={() => void addTarget()}>
          Register
        </Button>
      </Surface>
      <Surface title="Registered targets" aside="no spoke_call">
        <NodeTable
          nodes={targets}
          empty="No targets yet."
          removeLabel="Remove"
          onEdit={(node) =>
            setEdit({
              name: node.name ?? "",
              host: node.ansible_host ?? "",
              conn: node.ansible_connection ?? "",
              port: node.ansible_port == null ? "" : String(node.ansible_port),
              user: node.ansible_user ?? "",
            })
          }
          onRemove={remove}
        />
      </Surface>
      <Surface title="Edit target" aside="update_target">
        <FieldGroup className="grid sm:grid-cols-2">
          <Field>
            <FieldLabel htmlFor="teName">Name</FieldLabel>
            <Input
              id="teName"
              value={edit.name}
              onChange={(event) =>
                setEdit((current) => ({ ...current, name: event.target.value }))
              }
            />
          </Field>
          <Field>
            <FieldLabel htmlFor="teHost">ansible_host</FieldLabel>
            <Input
              id="teHost"
              value={edit.host}
              onChange={(event) =>
                setEdit((current) => ({ ...current, host: event.target.value }))
              }
            />
          </Field>
          <Field>
            <FieldLabel htmlFor="teConn">connection</FieldLabel>
            <Input
              id="teConn"
              value={edit.conn}
              onChange={(event) =>
                setEdit((current) => ({ ...current, conn: event.target.value }))
              }
            />
          </Field>
          <Field>
            <FieldLabel htmlFor="tePort">port</FieldLabel>
            <Input
              id="tePort"
              value={edit.port}
              onChange={(event) =>
                setEdit((current) => ({ ...current, port: event.target.value }))
              }
            />
          </Field>
          <Field>
            <FieldLabel htmlFor="teUser">user</FieldLabel>
            <Input
              id="teUser"
              value={edit.user}
              onChange={(event) =>
                setEdit((current) => ({ ...current, user: event.target.value }))
              }
            />
          </Field>
        </FieldGroup>
        <Button type="button" className="self-start" onClick={() => void saveTarget()}>
          Save
        </Button>
      </Surface>
    </div>
  )
}
