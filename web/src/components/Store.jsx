import { useCallback, useEffect, useRef, useState } from 'react'
import { fetchFeed, fetchItem, fetchSearch, fetchSources, logout, startCollect } from '../api'
import HealthStrip from './HealthStrip'
import ItemDetail from './ItemDetail'
import ItemList from './ItemList'
import SearchBar from './SearchBar'
import SubscriptionStrip from './SubscriptionStrip'

export default function Store({ me, onSignedOut }) {
  const [items, setItems] = useState([])
  const [cursor, setCursor] = useState(null)
  const [selected, setSelected] = useState(null)
  const [sources, setSources] = useState([])
  const [searching, setSearching] = useState(false)
  const [subscribedOnly, setSubscribedOnly] = useState(false)
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

  // Same ordering-guard shape as requestIdRef, for the two async writers of
  // `sources`/`collecting` (refreshSources and the poll below) -- without
  // it a slow refreshSources response landing after a newer poll tick could
  // overwrite it with stale data.
  const sourcesIdRef = useRef(0)

  // Mirrors `searching` for the poll effect below: that effect only
  // re-runs when `collecting` changes, so its closure would otherwise see
  // whatever `searching` was when the run started, not whether the user
  // searched *during* the run.
  const searchingRef = useRef(false)

  // Mirrors subscribedOnly for the same reason searchingRef mirrors
  // `searching`: the last query has to be re-runnable from a callback that
  // would otherwise close over a stale value.
  const lastQueryRef = useRef(null)

  // Own counter, separate from requestIdRef: `select` fires on every row
  // click, far more often than feed/search/loadMore. Sharing requestIdRef
  // would let a detail click cancel an in-flight loadFeed/search/loadMore
  // write by superseding its generation.
  const selectIdRef = useRef(0)

  // A 401 mid-session means the cookie was revoked or expired. Dropping back
  // to the login form is the truthful response; showing "401 Unauthorized" in
  // the error banner would leave a dead UI on screen.
  //
  // useCallback is load-bearing, not decoration: `fail` is passed to
  // SubscriptionStrip as `onError`, whose `reload` is useCallback(..., [onError])
  // and whose effect is keyed on [open, reload]. An unstable `fail` gives
  // `reload` a new identity on every Store render, so selecting an item or a
  // poll tick would re-fire fetchCatalog() while the strip is open. onSignedOut
  // is already memoised in App, so this is genuinely stable.
  const fail = useCallback(
    (e) => (e.status === 401 ? onSignedOut() : setError(String(e))),
    [onSignedOut],
  )

  const loadFeed = useCallback(() => {
    searchingRef.current = false
    lastQueryRef.current = null
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

  const refreshSources = useCallback(() => {
    if (!me.is_admin) return Promise.resolve()
    const reqId = ++sourcesIdRef.current
    return fetchSources()
      .then((r) => {
        if (sourcesIdRef.current !== reqId) return
        setSources(r.sources); setCollecting(r.collecting)
      })
      .catch(fail)
  }, [me.is_admin])

  // Reading `collecting` from the server rather than only from local state
  // means a page reload during a run picks the progress view back up.
  useEffect(() => { loadFeed(); refreshSources() }, [loadFeed, refreshSources])

  useEffect(() => {
    if (!collecting) return
    let cancelled = false
    const id = setInterval(async () => {
      const reqId = ++sourcesIdRef.current
      try {
        const r = await fetchSources()
        if (cancelled || sourcesIdRef.current !== reqId) return
        // Per-source rows update as each source commits (Task 4), so the
        // health strip fills in progressively. `collecting` is the server's
        // own flag -- run status cannot be used, because collect_tier only
        // ever commits terminal statuses and a reader never sees "running".
        setSources(r.sources)
        if (!r.collecting) {
          setCollecting(false)
          // Only replace the list with the full feed when the user isn't
          // looking at search results -- otherwise a run finishing while a
          // search is active silently discards it. Refreshing sources above
          // is enough to end the progress view either way.
          if (!searchingRef.current) loadFeed()
        }
      } catch (e) {
        if (!cancelled && sourcesIdRef.current === reqId) { setError(String(e)); setCollecting(false) }
      }
    }, 2000)
    return () => { cancelled = true; clearInterval(id) }
  }, [collecting, loadFeed])

  const select = (id) => {
    setError(null)
    const reqId = ++selectIdRef.current
    fetchItem(id)
      .then((item) => { if (selectIdRef.current === reqId) setSelected(item) })
      .catch((e) => { if (selectIdRef.current === reqId) fail(e) })
  }

  const search = (q, onlySubscribed = subscribedOnly) => {
    searchingRef.current = true
    lastQueryRef.current = q
    setSearching(true)
    setError(null)
    const reqId = ++requestIdRef.current
    fetchSearch(q, null, onlySubscribed)
      .then((r) => {
        if (requestIdRef.current !== reqId) return
        setItems(r.items); setCursor(null)
      })
      .catch((e) => { if (requestIdRef.current === reqId) fail(e) })
  }

  // Re-run the active search immediately so the checkbox has a visible
  // effect. With no search active the flag only applies to /api/search, so
  // there is nothing to re-run -- the feed is deliberately unfiltered.
  const changeSubscribedOnly = (next) => {
    setSubscribedOnly(next)
    if (searchingRef.current && lastQueryRef.current) search(lastQueryRef.current, next)
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

  const signOut = async () => {
    try { await logout() } finally { onSignedOut() }
  }

  return (
    <div className="app">
      <header className="header">
        <SearchBar
          onSearch={search}
          onClear={loadFeed}
          onCollect={collect}
          collecting={collecting || collectPending}
          canCollect={me.is_admin}
          subscribedOnly={subscribedOnly}
          onSubscribedOnlyChange={changeSubscribedOnly}
        />
        <div className="header-row">
          {me.is_admin && <HealthStrip sources={sources} />}
          <SubscriptionStrip onError={fail} />
          <span className="whoami">
            {me.display_name}
            {me.is_admin && <span className="badge">admin</span>}
            <button className="signout" onClick={signOut}>sign out</button>
          </span>
        </div>
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
