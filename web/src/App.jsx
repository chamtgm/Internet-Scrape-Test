import { useCallback, useEffect, useState } from 'react'
import { fetchMe } from './api'
import Login from './components/Login'
import Setup from './components/Setup'
import Store from './components/Store'

// A fragment, not a query string: `/#setup=<token>` never reaches the server,
// so a single-use credential stays out of access logs, proxy logs, and the
// Referer header. The path stays `/` either way, which matters -- a real
// `/setup` path would 404 in production, because StaticFiles's html=True
// looks for 404.html rather than falling back to index.html.
const readSetupToken = () =>
  new URLSearchParams(window.location.hash.slice(1)).get('setup')

export default function App() {
  // undefined = still asking the server, null = signed out, object = signed in.
  // Three states, not two: rendering the login form while the check is still in
  // flight makes an already-signed-in user see a login flash on every reload.
  const [me, setMe] = useState(undefined)
  const [setupToken, setSetupToken] = useState(readSetupToken)

  useEffect(() => { fetchMe().then(setMe).catch(() => setMe(null)) }, [])

  const signedOut = useCallback(() => {
    setMe(null)
    // Drop any stale token so signing out does not bounce into the setup form.
    setSetupToken(null)
  }, [])

  if (me === undefined) return <p className="booting">…</p>
  if (me === null) {
    return setupToken
      ? <Setup token={setupToken} onDone={setMe} />
      : <Login onDone={setMe} />
  }
  return <Store me={me} onSignedOut={signedOut} />
}
