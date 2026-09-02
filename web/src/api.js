async function get(path, params) {
  const qs = params ? '?' + new URLSearchParams(params) : ''
  const res = await fetch(`/api${path}${qs}`)
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  return res.json()
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

export const fetchSearch = (q, kind) => get('/search', { q, ...(kind ? { kind } : {}) })
export const fetchItem = (id) => get(`/items/${id}`)
export const fetchSources = () => get('/sources')

export async function startCollect(tier, force = false) {
  const res = await fetch('/api/collect', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ tier, force }),
  })
  return { ok: res.ok, ...(await res.json()) }
}
