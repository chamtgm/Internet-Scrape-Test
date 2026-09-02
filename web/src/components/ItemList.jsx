export default function ItemList({ items, selectedId, onSelect, onLoadMore, hasMore }) {
  if (items.length === 0) return <div className="item-list"><p className="empty">No items.</p></div>

  return (
    <div className="item-list">
      {items.map((item) => (
        <button
          key={item.id}
          className={`item-row${item.id === selectedId ? ' selected' : ''}`}
          onClick={() => onSelect(item.id)}
        >
          <div className="item-title">{item.title ?? '(untitled)'}</div>
          <div className="item-meta">
            {item.source_identifier} · {item.published_at?.slice(0, 10) ?? 'undated'}
          </div>
        </button>
      ))}
      {hasMore && <button className="load-more" onClick={onLoadMore}>Load more</button>}
    </div>
  )
}
