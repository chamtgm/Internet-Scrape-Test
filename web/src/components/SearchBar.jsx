import { useState } from 'react'

export default function SearchBar({ onSearch, onClear, onCollect, collecting }) {
  const [q, setQ] = useState('')
  const [tier, setTier] = useState(1)

  const submit = (e) => {
    e.preventDefault()
    if (q.trim()) onSearch(q.trim())
    else onClear()
  }

  return (
    <form className="searchbar" onSubmit={submit}>
      <input
        value={q}
        onChange={(e) => setQ(e.target.value)}
        placeholder="search collected items…"
        aria-label="search"
      />
      {q && <button type="button" onClick={() => { setQ(''); onClear() }}>clear</button>}
      <select value={tier} onChange={(e) => setTier(Number(e.target.value))} aria-label="tier">
        <option value={1}>Tier 1</option>
        <option value={2}>Tier 2</option>
        <option value={3}>Tier 3</option>
      </select>
      <button type="button" onClick={() => onCollect(tier)} disabled={collecting}>
        {collecting ? 'Collecting…' : 'Collect'}
      </button>
    </form>
  )
}
