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

  // Distinct from "signed out": fetchMe() already returns null for a 401 and
  // rethrows everything else, so anything landing in this catch is a real
  // failure -- a 500, a dropped connection, a malformed response. Collapsing
  // it into setMe(null) would render a login form during an outage and tell
  // the user nothing.
  const [bootError, setBootError] = useState(null)

  useEffect(() => {
    fetchMe()
      .then(setMe)
      .catch((e) => { setBootError(String(e)); setMe(null) })
  }, [])

  const signedOut = useCallback(() => {
    setMe(null)
    // Drop any stale token so signing out does not bounce into the setup form.
    setSetupToken(null)
    // A deliberate sign-out just proved the server is reachable, so a boot
    // failure from earlier in this session is no longer true -- keeping it
    // would misreport a healthy server as still down.
    setBootError(null)
  }, [])

  if (me === undefined) return <p className="booting">…</p>
  if (me === null) {
    // The banner sits above the form rather than replacing it: the failure may
    // be transient, so let them try to sign in -- but never leave a real
    // outage looking like an ordinary signed-out visit.
    return (
      <>
        {bootError && <p className="error">Could not reach the server: {bootError}</p>}
        {setupToken
          ? <Setup token={setupToken} onDone={setMe} />
          : <Login onDone={setMe} />}
      </>
    )
  }
  return <Store me={me} onSignedOut={signedOut} />
}
