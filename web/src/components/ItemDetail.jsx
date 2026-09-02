export default function ItemDetail({ item }) {
  if (!item) return <p className="empty">Select an item.</p>
  return (
    <article>
      <h2 className="detail-title">
        <a href={item.url} target="_blank" rel="noreferrer">{item.title ?? '(untitled)'}</a>
      </h2>
      <p className="detail-meta">
        {item.source_identifier} · {item.published_at?.slice(0, 10) ?? 'undated'}
        {item.author_handle ? ` · ${item.author_handle}` : ''}
      </p>
      <div className="detail-body">{item.content_text}</div>
    </article>
  )
}
