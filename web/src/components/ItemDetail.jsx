export default function ItemDetail({ item }) {
  if (!item) return <p className="empty">Select an item.</p>
  // item.url is entry.link, copied verbatim from whatever feed the user
  // subscribed to -- nothing upstream validates its scheme. React does not
  // sanitise href, so an unchecked javascript: URL would execute on this
  // origin, which (no auth; same-origin API) is the whole store. Render a
  // link only for http(s); otherwise plain text. Kept here, not in _summary
  // or the store -- this project stores raw and judges at read time.
  const safe = /^https?:\/\//i.test(item.url)
  const title = item.title ?? '(untitled)'
  return (
    <article>
      <h2 className="detail-title">
        {safe
          ? <a href={item.url} target="_blank" rel="noreferrer">{title}</a>
          : title}
      </h2>
      <p className="detail-meta">
        {item.source_identifier} · {item.published_at?.slice(0, 10) ?? 'undated'}
        {item.author_handle ? ` · ${item.author_handle}` : ''}
      </p>
      <div className="detail-body">{item.content_text}</div>
    </article>
  )
}
