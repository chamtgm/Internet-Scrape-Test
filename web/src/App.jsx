import { useEffect, useState } from 'react'
import { fetchFeed } from './api'
import ItemList from './components/ItemList'

export default function App() {
  const [items, setItems] = useState([])
  const [cursor, setCursor] = useState(null)
  const [selectedId, setSelectedId] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    fetchFeed(null)
      .then((r) => { setItems(r.items); setCursor(r.next_cursor) })
      .catch((e) => setError(String(e)))
  }, [])

  const loadMore = () =>
    fetchFeed(cursor)
      .then((r) => { setItems((prev) => [...prev, ...r.items]); setCursor(r.next_cursor) })
      .catch((e) => setError(String(e)))

  return (
    <div className="app">
      <header className="header"><strong>reachstore</strong></header>
      {error && <p className="error">{error}</p>}
      <main className="panes">
        <ItemList
          items={items}
          selectedId={selectedId}
          onSelect={setSelectedId}
          onLoadMore={loadMore}
          hasMore={cursor !== null}
        />
        <section className="detail">
          {selectedId ? <p>Item {selectedId} selected.</p> : <p className="empty">Select an item.</p>}
        </section>
      </main>
    </div>
  )
}
