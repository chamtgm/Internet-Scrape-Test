import { useState } from 'react'
import { setupAccount } from '../api'

const MIN_PASSWORD_LENGTH = 8

export default function Setup({ token, onDone }) {
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)

  const submit = async (e) => {
    e.preventDefault()
    if (busy) return
    // Checked here as well as on the server: catching a mismatch or a short
    // password before the request keeps a single-use link from being spent on
    // a typo. The server is still the authority.
    if (password !== confirm) return setError('The two passwords do not match.')
    if (password.length < MIN_PASSWORD_LENGTH) {
      return setError(`Use at least ${MIN_PASSWORD_LENGTH} characters.`)
    }
    setBusy(true)
    setError(null)
    try {
      const me = await setupAccount(token, password)
      // Clear the token from the address bar so a reload does not retry a link
      // that is now spent.
      history.replaceState(null, '', location.pathname)
      onDone(me)
    } catch (err) {
      setError(
        err.status === 400
          ? 'This setup link is invalid, expired, or already used. Ask for a new one.'
          : String(err)
      )
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="auth" onSubmit={submit}>
      <h1>Choose a password</h1>
      <label htmlFor="new-password">Password</label>
      <input
        id="new-password"
        type="password"
        autoComplete="new-password"
        value={password}
        onChange={(e) => setPassword(e.target.value)}
        required
      />
      <label htmlFor="confirm-password">Confirm password</label>
      <input
        id="confirm-password"
        type="password"
        autoComplete="new-password"
        value={confirm}
        onChange={(e) => setConfirm(e.target.value)}
        required
      />
      {error && <p className="error">{error}</p>}
      <button type="submit" disabled={busy}>{busy ? 'Creating…' : 'Create account'}</button>
    </form>
  )
}
