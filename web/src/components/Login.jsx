import { useState } from 'react'
import { login } from '../api'

export default function Login({ onDone }) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)

  const submit = async (e) => {
    e.preventDefault()
    if (busy) return
    setBusy(true)
    setError(null)
    try {
      onDone(await login(email, password))
    } catch (err) {
      // One message for a wrong password and an unknown email, matching the
      // server's single 401 -- the UI must not reintroduce the distinction the
      // API deliberately hides.
      setError(err.status === 401 ? 'Email or password is incorrect.' : String(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="auth" onSubmit={submit}>
      <h1>reachstore</h1>
      <label htmlFor="email">Email</label>
      <input
        id="email"
        type="email"
        autoComplete="username"
        value={email}
        onChange={(e) => setEmail(e.target.value)}
        required
      />
      <label htmlFor="password">Password</label>
      <input
        id="password"
        type="password"
        autoComplete="current-password"
        value={password}
        onChange={(e) => setPassword(e.target.value)}
        required
      />
      {error && <p className="error">{error}</p>}
      <button type="submit" disabled={busy}>{busy ? 'Signing in…' : 'Sign in'}</button>
      <p className="auth-note">
        Accounts are created by invitation. Ask whoever runs this instance for a
        setup link.
      </p>
    </form>
  )
}
