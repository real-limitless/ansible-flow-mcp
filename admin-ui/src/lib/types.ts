export type HostNode = {
  name?: string
  ansible_host?: string
  ansible_port?: number | string | null
  ansible_user?: string
  ansible_connection?: string
  groups?: string[]
}

export type HubStatus = {
  name?: string
  hub_id?: string
  spokes?: string[]
  targets?: string[]
  groups?: unknown[]
  inventory?: string
  root?: string
  known_hosts?: string
  version?: string
}

export type HealthReport = {
  ok?: boolean
  version?: string
} & Record<string, unknown>

export type GroupRecord = {
  name: string
  hosts?: string[]
}

export type AuditEvent = {
  ts?: string
  event?: string
} & Record<string, unknown>

export type IssuedToken = {
  token: string
  join_command: string
}

export type PingResult = {
  ok?: boolean
  error?: string
  stderr?: string
}
