import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  Empty,
  EmptyDescription,
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
import { DangerConfirm } from "@/components/danger-confirm"
import type { HostNode } from "@/lib/types"

function nodeName(node: HostNode): string {
  return node.name ?? ""
}

export function NodeTable({
  nodes,
  empty,
  removeLabel,
  onEdit,
  onRemove,
  onPing,
}: {
  nodes: HostNode[]
  empty: string
  removeLabel: string
  onEdit: (node: HostNode) => void
  onRemove: (name: string) => Promise<void>
  onPing?: (name: string) => Promise<void>
}) {
  if (!nodes.length) {
    return (
      <Empty>
        <EmptyHeader>
          <EmptyTitle>{empty}</EmptyTitle>
        </EmptyHeader>
      </Empty>
    )
  }

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Name</TableHead>
          <TableHead>Host</TableHead>
          <TableHead>Port</TableHead>
          <TableHead>User</TableHead>
          <TableHead>Groups</TableHead>
          <TableHead />
        </TableRow>
      </TableHeader>
      <TableBody>
        {nodes.map((node) => {
          const name = nodeName(node)
          const groups = node.groups ?? []
          return (
            <TableRow key={name}>
              <TableCell className="font-mono">{name}</TableCell>
              <TableCell className="font-mono">
                {node.ansible_host || "—"}
              </TableCell>
              <TableCell className="font-mono">
                {node.ansible_port ?? "—"}
              </TableCell>
              <TableCell className="font-mono">
                {node.ansible_user || "—"}
              </TableCell>
              <TableCell>
                {groups.length ? (
                  <span className="flex flex-wrap gap-1">
                    {groups.map((group) => (
                      <Badge key={group}>{group}</Badge>
                    ))}
                  </span>
                ) : (
                  "—"
                )}
              </TableCell>
              <TableCell>
                <div className="flex flex-wrap justify-end gap-2">
                  {onPing ? (
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      onClick={() => {
                        void onPing(name)
                      }}
                    >
                      Ping
                    </Button>
                  ) : null}
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    onClick={() => onEdit(node)}
                  >
                    Edit
                  </Button>
                  <DangerConfirm
                    title={`${removeLabel} ${name}?`}
                    description={
                      removeLabel === "Revoke"
                        ? `Revoke spoke ${name}?`
                        : `Remove target ${name}?`
                    }
                    confirmLabel={removeLabel}
                    onConfirm={() => onRemove(name)}
                    trigger={
                      <Button type="button" variant="destructive" size="sm">
                        {removeLabel}
                      </Button>
                    }
                  />
                </div>
              </TableCell>
            </TableRow>
          )
        })}
      </TableBody>
    </Table>
  )
}

export function TokenNeeded() {
  return (
    <Empty>
      <EmptyHeader>
        <EmptyTitle>Admin token required</EmptyTitle>
        <EmptyDescription>Set admin token first</EmptyDescription>
      </EmptyHeader>
    </Empty>
  )
}
