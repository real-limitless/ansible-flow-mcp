export const TOKEN_KEY = "ansible_flow_admin_token"

export function errorMessage(err: unknown): string {
  if (err instanceof Error && err.message) return err.message
  return "Request failed"
}

function errorFrom(body: unknown, res: Response): string {
  if (body && typeof body === "object" && "error" in body) {
    const error = (body as { error?: unknown }).error
    if (typeof error === "string" && error) return error
  }
  return res.statusText || String(res.status)
}

export async function api<T>(
  token: string,
  path: string,
  opts: RequestInit = {},
): Promise<T> {
  if (!token) throw new Error("Set admin token first")
  const headers = new Headers()
  headers.set("Authorization", `Bearer ${token}`)
  headers.set("Content-Type", "application/json")
  if (opts.headers) {
    new Headers(opts.headers).forEach((value, key) => {
      headers.set(key, value)
    })
  }
  const res = await fetch(path, { ...opts, headers })
  const text = await res.text()
  let body: unknown
  try {
    body = text ? JSON.parse(text) : {}
  } catch {
    body = { raw: text }
  }
  if (!res.ok) throw new Error(errorFrom(body, res))
  return body as T
}
