import { useCallback, useState } from "react"

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert"
import { Button } from "@/components/ui/button"
import { Field, FieldLabel } from "@/components/ui/field"
import { Input } from "@/components/ui/input"
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { Toaster } from "@/components/ui/sonner"
import { TOKEN_KEY } from "@/lib/api"
import { AuditPanel } from "@/panels/audit-panel"
import { GroupsPanel } from "@/panels/groups-panel"
import { ServersPanel } from "@/panels/servers-panel"
import { StatusPanel } from "@/panels/status-panel"
import { TargetsPanel } from "@/panels/targets-panel"
import { Badge } from "@/components/ui/badge"

type TabId = "status" | "servers" | "targets" | "groups" | "audit"

const TABS: { id: TabId; label: string }[] = [
  { id: "status", label: "Status" },
  { id: "servers", label: "Servers" },
  { id: "targets", label: "Targets" },
  { id: "groups", label: "Groups" },
  { id: "audit", label: "Audit" },
]

function readToken(): string {
  return sessionStorage.getItem(TOKEN_KEY) || ""
}

export function App() {
  const [draft, setDraft] = useState(readToken)
  const [token, setToken] = useState(readToken)
  const [tab, setTab] = useState<TabId>("status")
  const [error, setError] = useState("")
  const [reload, setReload] = useState(0)
  const onError = useCallback((message: string) => {
    setError(message)
  }, [])

  const refresh = useCallback(() => {
    if (!readToken()) {
      setError("Set admin token first")
      return
    }
    setError("")
    setReload((current) => current + 1)
  }, [])

  function saveToken() {
    const next = draft.trim()
    sessionStorage.setItem(TOKEN_KEY, next)
    setToken(next)
    if (!next) {
      setError("Set admin token first")
      return
    }
    setError("")
    setReload((current) => current + 1)
  }

  return (
    <div className="chassis-glow relative min-h-svh">
      <div aria-hidden className="chassis-grid pointer-events-none fixed inset-0 opacity-35" />
      <div className="relative mx-auto flex w-full max-w-6xl flex-col gap-6 px-6 pt-6 pb-16">
        <header className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <span
              aria-hidden
              className="size-3.5 rounded-sm bg-primary shadow-[0_0_16px_color-mix(in_srgb,var(--primary)_45%,transparent)]"
            />
            <div className="text-lg font-semibold tracking-tight">
              ansible<span className="text-primary">-flow</span>
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            <Badge>Admin</Badge>
            <Badge variant="secondary">Hub</Badge>
            <Badge variant="outline">Local</Badge>
          </div>
        </header>

        <section className="flex max-w-3xl flex-col gap-2">
          <p className="text-xs font-medium tracking-wide text-muted-foreground uppercase">
            Operator console · hub inventory
          </p>
          <h1 className="text-3xl font-semibold tracking-tight">
            Fleet control.
            <br />
            <em className="text-primary">Agents stay on stdio.</em>
          </h1>
          <p className="text-muted-foreground">
            Enroll spokes, register Ansible targets, group hosts, and read the hub
            audit — same membership APIs as the TUI and hub MCP session.
          </p>
        </section>

        <Tabs
          value={tab}
          onValueChange={(value) => {
            setTab(value as TabId)
            refresh()
          }}
        >
          <div className="flex flex-wrap items-end justify-between gap-3">
            <TabsList aria-label="Admin sections">
              {TABS.map((item) => (
                <TabsTrigger key={item.id} value={item.id}>
                  {item.label}
                </TabsTrigger>
              ))}
            </TabsList>
            <div className="flex flex-wrap items-end gap-2">
              <form
                className="flex flex-wrap items-end gap-2"
                onSubmit={(event) => {
                  event.preventDefault()
                  saveToken()
                }}
              >
                <Field className="w-56">
                  <FieldLabel htmlFor="admin-token" className="sr-only">
                    Admin token
                  </FieldLabel>
                  <Input
                    id="admin-token"
                    type="password"
                    placeholder="Admin token"
                    autoComplete="off"
                    spellCheck={false}
                    value={draft}
                    onChange={(event) => setDraft(event.target.value)}
                  />
                </Field>
                <Button type="submit">Save</Button>
              </form>
              <Button type="button" variant="outline" onClick={refresh}>
                Refresh
              </Button>
            </div>
          </div>

          {error ? (
            <Alert variant="destructive">
              <AlertTitle>Could not load</AlertTitle>
              <AlertDescription>{error}</AlertDescription>
            </Alert>
          ) : null}

          {tab === "status" ? (
            <StatusPanel key={reload} token={token} onError={onError} />
          ) : null}
          {tab === "servers" ? (
            <ServersPanel
              key={reload}
              token={token}
              onError={onError}
              onRefresh={refresh}
            />
          ) : null}
          {tab === "targets" ? (
            <TargetsPanel
              key={reload}
              token={token}
              onError={onError}
              onRefresh={refresh}
            />
          ) : null}
          {tab === "groups" ? (
            <GroupsPanel
              key={reload}
              token={token}
              onError={onError}
              onRefresh={refresh}
            />
          ) : null}
          {tab === "audit" ? (
            <AuditPanel key={reload} token={token} onError={onError} />
          ) : null}
        </Tabs>
      </div>
      <Toaster />
    </div>
  )
}

export default App
