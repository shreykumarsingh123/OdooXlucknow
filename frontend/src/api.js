const BASE = import.meta.env.VITE_API_BASE_URL || '/api'
const ACCESS = 'bl_access'
const REFRESH = 'bl_refresh'

export class ApiError extends Error {
  constructor(status, body) {
    super(body?.message || 'Something went wrong. Please try again.')
    this.status = status
    this.fields = body?.fields || {}
  }
}

export const tokens = {
  get: () => localStorage.getItem(ACCESS),
  set(access, refresh) {
    localStorage.setItem(ACCESS, access)
    if (refresh) localStorage.setItem(REFRESH, refresh)
  },
  clear() {
    localStorage.removeItem(ACCESS)
    localStorage.removeItem(REFRESH)
  },
}

async function refreshAccess() {
  const refresh = localStorage.getItem(REFRESH)
  if (!refresh) return false
  let response
  try {
    response = await fetch(`${BASE}/auth/refresh/`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ refresh }),
    })
  } catch {
    // The server is out of reach. That says nothing about the session, so keep it.
    throw new ApiError(0, { message: 'Cannot reach the server. Check your connection and try again.' })
  }
  if (!response.ok) return false
  tokens.set((await response.json()).access)
  return true
}

async function request(method, path, body, retried = false) {
  const headers = { 'Content-Type': 'application/json' }
  if (tokens.get()) headers.Authorization = `Bearer ${tokens.get()}`
  let response
  try {
    response = await fetch(`${BASE}${path}`, { method, headers, body: body === undefined ? undefined : JSON.stringify(body) })
  } catch {
    throw new ApiError(0, { message: 'Cannot reach the server. Check your connection and try again.' })
  }
  if (response.status === 401 && !retried && !path.startsWith('/auth/login')) {
    if (await refreshAccess()) return request(method, path, body, true)
    tokens.clear()
    if (!location.pathname.startsWith('/login')) location.assign('/login')
  }
  if (response.status === 204) return null
  const data = await response.json().catch(() => null)
  if (!response.ok) throw new ApiError(response.status, data)
  return data
}

async function download(path, filename) {
  const send = () => fetch(`${BASE}${path}`, { headers: { Authorization: `Bearer ${tokens.get()}` } })
  let response = await send()
  if (response.status === 401 && await refreshAccess()) response = await send()
  if (!response.ok) throw new ApiError(response.status, await response.json().catch(() => null))
  const url = URL.createObjectURL(await response.blob())
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  link.click()
  URL.revokeObjectURL(url)
}

export const api = {
  download,
  get: (path) => request('GET', path),
  post: (path, body = {}) => request('POST', path, body),
  put: (path, body) => request('PUT', path, body),
  patch: (path, body) => request('PATCH', path, body),
  del: (path) => request('DELETE', path),
}

export function query(params) {
  const clean = Object.entries(params).filter(([, value]) => value !== '' && value !== undefined && value !== null)
  return clean.length ? `?${new URLSearchParams(clean)}` : ''
}
