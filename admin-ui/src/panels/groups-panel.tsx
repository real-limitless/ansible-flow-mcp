import { useEffect, useState } from "react"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Checkbox } from "@/components/ui/checkbox"
import {
  Empty,
  EmptyDescription,
  EmptyHeader,
  EmptyTitle,
} from "@/components/ui/empty"
import {
  Field,
  FieldGroup,
  FieldLabel,
  FieldLegend,
  FieldSet,
} from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { DangerConfirm } from "@/components/danger-confirm"
import { TokenNeeded } from "@/components/node-table"
import { PanelSkeleton, Surface } from "@/components/surface"
import { api, errorMessage } from "@/lib/api"
import type { GroupRecord, HubStatus } from "@/lib/types"

export function GroupsPanel({
  token,
  onError,
  onRefresh,
}: {
  token: string
  onError: (message: string) => void
  onRefresh: () => void
}) {
  const [groups, setGroups] = useState<GroupRecord[] | null>(null)
  const [members, setMembers] = useState<string[]>([])
  const [loading, setLoading] = useState(Boolean(token))
  const [groupName, setGroupName] = useState("")
  const [memberGroup, setMemberGroup] = useState("")
  const [checked, setChecked] = useState<Set<string>>(new Set())

  useEffect(() => {
    if (!token) return
    let cancelled = false
    ;(async () => {
      try {
        const [listed, status] = await Promise.all([
          api<{ groups?: GroupRecord[] }>(token, "/v1/groups"),
          api<HubStatus>(token, "/v1/status"),
        ])
        if (cancelled) return
        setGroups(listed.groups || [])
        setMembers([...(status.spokes || []), ...(status.targets || [])])
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
  if (loading && !groups) return <PanelSkeleton />
  if (!groups) return null

  async function addGroup() {
    try {
      await api(token, "/v1/groups", {
        method: "POST",
        body: JSON.stringify({ name: groupName.trim() }),
      })
      onRefresh()
    } catch (err) {
      onError(errorMessage(err))
    }
  }

  async function saveMembers() {
    try {
      const hosts = members.filter((name) => checked.has(name))
      await api(token, `/v1/groups/${encodeURIComponent(memberGroup.trim())}/members`, {
        method: "PUT",
        body: JSON.stringify({ hosts }),
      })
      onRefresh()
    } catch (err) {
      onError(errorMessage(err))
    }
  }

  async function remove(name: string) {
    try {
      await api(token, `/v1/groups/${encodeURIComponent(name)}`, {
        method: "DELETE",
      })
      onRefresh()
    } catch (err) {
      onError(errorMessage(err))
    }
  }

  function loadMembers(name: string) {
    setMemberGroup(name)
    const group = groups?.find((item) => item.name === name)
    setChecked(new Set(group?.hosts || []))
  }

  return (
    <div className="flex flex-col gap-4">
      <Surface title="Create group" aside="custom">
        <FieldGroup>
          <Field>
            <FieldLabel htmlFor="grName">Name</FieldLabel>
            <Input
              id="grName"
              value={groupName}
              placeholder="prod"
              onChange={(event) => setGroupName(event.target.value)}
            />
          </Field>
        </FieldGroup>
        <Button type="button" className="self-start" onClick={() => void addGroup()}>
          Create
        </Button>
      </Surface>
      <Surface title="Groups" aside={String(groups.length)}>
        {groups.length ? (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Name</TableHead>
                <TableHead>Members</TableHead>
                <TableHead />
              </TableRow>
            </TableHeader>
            <TableBody>
              {groups.map((group) => (
                <TableRow key={group.name}>
                  <TableCell className="font-mono">{group.name}</TableCell>
                  <TableCell>
                    {(group.hosts || []).length ? (
                      <span className="flex flex-wrap gap-1">
                        {(group.hosts || []).map((host) => (
                          <Badge key={host} variant="secondary">
                            {host}
                          </Badge>
                        ))}
                      </span>
                    ) : (
                      "—"
                    )}
                  </TableCell>
                  <TableCell>
                    <div className="flex flex-wrap justify-end gap-2">
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        onClick={() => loadMembers(group.name)}
                      >
                        Members
                      </Button>
                      <DangerConfirm
                        title={`Delete group ${group.name}?`}
                        description={`Delete group ${group.name}?`}
                        confirmLabel="Delete"
                        onConfirm={() => remove(group.name)}
                        trigger={
                          <Button type="button" variant="destructive" size="sm">
                            Delete
                          </Button>
                        }
                      />
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        ) : (
          <Empty>
            <EmptyHeader>
              <EmptyTitle>No custom groups.</EmptyTitle>
            </EmptyHeader>
          </Empty>
        )}
      </Surface>
      <Surface title="Set members" aside="enrolled only">
        <Field>
          <FieldLabel htmlFor="gmName">Group</FieldLabel>
          <Input
            id="gmName"
            value={memberGroup}
            onChange={(event) => setMemberGroup(event.target.value)}
          />
        </Field>
        {members.length ? (
          <FieldSet>
            <FieldLegend variant="label">Hosts</FieldLegend>
            <FieldGroup>
              {members.map((name) => (
                <Field key={name} orientation="horizontal">
                  <Checkbox
                    id={`host-${name}`}
                    checked={checked.has(name)}
                    onCheckedChange={(value) => {
                      setChecked((current) => {
                        const next = new Set(current)
                        if (value === true) next.add(name)
                        else next.delete(name)
                        return next
                      })
                    }}
                  />
                  <FieldLabel htmlFor={`host-${name}`} className="font-mono">
                    {name}
                  </FieldLabel>
                </Field>
              ))}
            </FieldGroup>
          </FieldSet>
        ) : (
          <Empty>
            <EmptyHeader>
              <EmptyDescription>
                Enroll a spoke or register a target first
              </EmptyDescription>
            </EmptyHeader>
          </Empty>
        )}
        <Button type="button" className="self-start" onClick={() => void saveMembers()}>
          Save members
        </Button>
      </Surface>
    </div>
  )
}
