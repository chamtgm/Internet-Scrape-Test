// Status-carrying error: the login gate has to tell "not logged in" (401)
// apart from a real failure, and `new Error('401 Unauthorized')` would force
// callers to parse a string to find out.
export class ApiError extends Error {
  constructor(status, statusText) {
    super(`${status} ${statusText}`)
    this.status = status
  }
}

async function get(path, params) {
  const qs = params ? '?' + new URLSearchParams(params) : ''
  const res = await fetch(`/api${path}${qs}`)
  if (!res.ok) throw new ApiError(res.status, res.statusText)
  return res.json()
}

// Cookies ride along because fetch defaults to credentials: 'same-origin'
// and the Vite proxy keeps the browser same-origin. That default is also why
// no CORS middleware exists anywhere in this project.
async function send(method, path, body) {
  const res = await fetch(`/api${path}`, {
    method,
    ...(body === undefined
      ? {}
      : { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) }),
  })
  if (!res.ok) throw new ApiError(res.status, res.statusText)
  return res.status === 204 ? null : res.json()
}

export function fetchFeed(cursor, limit = 50) {
  const params = { limit }
  if (cursor) {
    params.before_id = cursor.id
    // Omit the key entirely when the cursor row had no published_at. Sending
    // an empty string is a 422, and omitting it is also the correct meaning:
    // the server reads a bare before_id as "continue through the NULLS LAST
    // tail".
    if (cursor.published_at !== null) params.before_published_at = cursor.published_at
  }
  return get('/feed', params)
}

export const fetchSearch = (q, kind, subscribedOnly = false) =>
  get('/search', {
    q,
    ...(kind ? { kind } : {}),
    ...(subscribedOnly ? { subscribed_only: true } : {}),
  })
export const fetchItem = (id) => get(`/items/${id}`)
export const fetchSources = () => get('/sources')

// null, not a throw: "nobody is logged in" is the expected answer on a first
// visit, not a failure worth showing the user.
export async function fetchMe() {
  try {
    return await get('/auth/me')
  } catch (e) {
    if (e.status === 401) return null
    throw e
  }
}

export const login = (email, password) => send('POST', '/auth/login', { email, password })
export const setupAccount = (token, password) => send('POST', '/auth/setup', { token, password })
export const logout = () => send('POST', '/auth/logout')

export const fetchCatalog = () => get('/catalog')
export const subscribe = (sourceId) => send('PUT', `/subscriptions/${sourceId}`)
export const unsubscribe = (sourceId) => send('DELETE', `/subscriptions/${sourceId}`)

export async function startCollect(tier, force = false) {
  const res = await fetch('/api/collect', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ tier, force }),
  })
  return { ok: res.ok, ...(await res.json()) }
}
