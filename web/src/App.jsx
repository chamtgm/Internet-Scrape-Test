import { useCallback, useEffect, useRef, useState } from 'react'
import { fetchFeed, fetchItem, fetchSearch, fetchSources, startCollect } from './api'
import HealthStrip from './components/HealthStrip'
import ItemDetail from './components/ItemDetail'
import ItemList from './components/ItemList'
import SearchBar from './components/SearchBar'

export default function App() {
  const [items, setItems] = useState([])
  const [cursor, setCursor] = useState(null)
  const [selected, setSelected] = useState(null)
  const [sources, setSources] = useState([])
  const [searching, setSearching] = useState(false)
  const [collecting, setCollecting] = useState(false)
  const [collectPending, setCollectPending] = useState(false)
  const [loadingMore, setLoadingMore] = useState(false)
  const [error, setError] = useState(null)

  // Plain `useState` booleans aren't enough to gate a same-tick double click:
  // two `click()` dispatches that happen before React re-renders both still
  // close over the pre-click `false`, so the guard has to be a ref (mutated
  // synchronously, shared by every closure) rather than state.
  const loadingMoreRef = useRef(false)
  const collectPendingRef = useRef(false)

  // Generation counter: loadFeed/search/loadMore all write `items`/`cursor`
  // from an uncancelled fetch. Bumping this ref on every new call and only
  // applying a response whose captured id still matches lets a stale,
  // slow response (e.g. a "Load more" that started before a search) get
  // silently dropped instead of corrupting whatever is now on screen.
  const requestIdRef = useRef(0)

  const fail = (e) => setError(String(e))

  const loadFeed = useCallback(() => {
    setSearching(false)
    setError(null)
    const reqId = ++requestIdRef.current
    fetchFeed(null)
      .then((r) => {
        if (requestIdRef.current !== reqId) return
        setItems(r.items); setCursor(r.next_cursor)
      })
      .catch((e) => { if (requestIdRef.current === reqId) fail(e) })
  }, [])

  const refreshSources = useCallback(
    () => fetchSources()
      .then((r) => { setSources(r.sources); setCollecting(r.collecting) })
      .catch(fail),
    []
  )

  // Reading `collecting` from the server rather than only from local state
  // means a page reload during a run picks the progress view back up.
  useEffect(() => { loadFeed(); refreshSources() }, [loadFeed, refreshSources])

  const select = (id) => {
    setError(null)
    fetchItem(id).then(setSelected).catch(fail)
  }

  const search = (q) => {
    setSearching(true)
    setError(null)
    const reqId = ++requestIdRef.current
    fetchSearch(q)
      .then((r) => {
        if (requestIdRef.current !== reqId) return
        setItems(r.items); setCursor(null)
      })
      .catch((e) => { if (requestIdRef.current === reqId) fail(e) })
  }

  const loadMore = () => {
    // In-flight guard: a second click while a page is loading is a no-op,
    // so a rapid double-click can't fire two requests with the same cursor
    // and append a duplicate page.
    if (loadingMoreRef.current) return
    loadingMoreRef.current = true
    setLoadingMore(true)
    setError(null)
    const reqId = ++requestIdRef.current
    fetchFeed(cursor)
      .then((r) => {
        if (requestIdRef.current !== reqId) return
        setItems((prev) => [...prev, ...r.items]); setCursor(r.next_cursor)
      })
      .catch((e) => { if (requestIdRef.current === reqId) fail(e) })
      .finally(() => { loadingMoreRef.current = false; setLoadingMore(false) })
  }

  const collect = async (tier) => {
    // Same in-flight reasoning as loadMore: `collecting` only flips true once
    // the server answers, so a click sent but not yet answered still needs a guard.
    if (collectPendingRef.current) return
    collectPendingRef.current = true
    setCollectPending(true)
    setError(null)
    try {
      const res = await startCollect(tier)
      if (!res.ok) { setError(res.reason ?? 'could not start collection'); return }
      setCollecting(true)
    } catch (e) { fail(e) } finally { collectPendingRef.current = false; setCollectPending(false) }
  }

  return (
    <div className="app">
      <header className="header">
        <SearchBar onSearch={search} onClear={loadFeed} onCollect={collect} collecting={collecting || collectPending} />
        <HealthStrip sources={sources} />
      </header>
      {error && <p className="error">{error}</p>}
      <main className="panes">
        <ItemList
          items={items}
          selectedId={selected?.id}
          onSelect={select}
          onLoadMore={loadMore}
          hasMore={!searching && cursor !== null}
          loadingMore={loadingMore}
        />
        <section className="detail"><ItemDetail item={selected} /></section>
      </main>
    </div>
  )
}
