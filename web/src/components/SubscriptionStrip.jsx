import { useCallback, useEffect, useRef, useState } from 'react'
import { fetchCatalog, subscribe, unsubscribe } from '../api'

export default function SubscriptionStrip({ onError }) {
  const [open, setOpen] = useState(false)
  const [entries, setEntries] = useState([])

  // Same ordering-guard shape as Store's sourcesIdRef: toggling several rows
  // quickly fires several catalog reloads, and a slow earlier response landing
  // after a newer one would reinstate checkboxes the user has since changed.
  const reqIdRef = useRef(0)

  // Per-row in-flight set, held in a ref rather than state for the same reason
  // Store's loadMore guard is a ref: React batches state updates, so two
  // same-tick clicks on one row would both read the pre-click value and send
  // two requests.
  const pendingRef = useRef(new Set())

  const reload = useCallback(() => {
    const reqId = ++reqIdRef.current
    return fetchCatalog()
      .then((r) => { if (reqIdRef.current === reqId) setEntries(r.sources) })
      .catch(onError)
  }, [onError])

  useEffect(() => { if (open) reload() }, [open, reload])

  const toggle = async (entry) => {
    if (pendingRef.current.has(entry.source_id)) return
    pendingRef.current.add(entry.source_id)
    try {
      await (entry.subscribed ? unsubscribe : subscribe)(entry.source_id)
      await reload()
    } catch (e) {
      onError(e)
    } finally {
      pendingRef.current.delete(entry.source_id)
    }
  }

  const count = entries.filter((e) => e.subscribed).length

  return (
    <div className="subs">
      <button className="subs-summary" onClick={() => setOpen(!open)}>
        {open ? '▾' : '▸'} subscriptions{open && ` · ${count} of ${entries.length}`}
      </button>
      {open && (
        <ul className="subs-list">
          {entries.length === 0 && <li className="empty">no sources yet</li>}
          {entries.map((e) => (
            <li key={e.source_id}>
              <label>
                <input
                  type="checkbox"
                  checked={e.subscribed}
                  onChange={() => toggle(e)}
                />
                <span className="subs-id">{e.identifier}</span>
                <span className="subs-meta">tier {e.tier} · {e.kind}</span>
              </label>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
