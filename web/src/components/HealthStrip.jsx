import { useState } from 'react'

export default function HealthStrip({ sources }) {
  const [open, setOpen] = useState(false)
  const healthy = sources.filter((s) => s.last_status === 'success').length
  const failing = sources.filter((s) => s.last_status === 'failed').length

  return (
    <div className="health">
      <button className="health-summary" onClick={() => setOpen(!open)}>
        {open ? '▾' : '▸'} {sources.length} sources · {healthy} healthy · {failing} failing
      </button>
      {open && (
        <ul className="health-list">
          {sources.map((s) => (
            <li key={s.source_id}>
              <span className={`dot ${s.last_status ?? 'never'}`} />
              <span className="health-id">{s.identifier}</span>
              <span className="health-meta">
                {s.item_count} items
                {s.consecutive_failures > 0 && ` · ${s.consecutive_failures} failures`}
              </span>
              {s.error_text && <div className="health-error">{s.error_text}</div>}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
