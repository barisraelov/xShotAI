import { useEffect, useRef, useState } from 'react'
import Logo from '../components/Logo'
import { verifyEmail } from '../auth'
import './Login.css'

/**
 * /verify-email?token=... landing screen.
 *
 * There is no router in this app (App.jsx is a view state-machine); App.jsx
 * detects the /verify-email path at boot and renders this screen, passing the
 * token through as `verifyToken`.
 */
export default function VerifyEmail({ navigate, verifyToken }) {
  const [status, setStatus] = useState('loading') // 'loading' | 'success' | 'error'
  const [message, setMessage] = useState('')
  const started = useRef(false)

  useEffect(() => {
    // Guard against React 18 StrictMode double-invoke — the token is single-use,
    // so a second request would always report it as already consumed.
    if (started.current) return
    started.current = true

    const token =
      verifyToken ||
      new URLSearchParams(window.location.search).get('token') ||
      ''

    if (!token) {
      setStatus('error')
      setMessage('This verification link is missing its token.')
      return
    }

    verifyEmail(token)
      .then(msg => {
        setStatus('success')
        setMessage(msg)
      })
      .catch(err => {
        setStatus('error')
        setMessage(err.message)
      })
  }, [verifyToken])

  function goToLogin() {
    // Drop the token from the address bar so a refresh doesn't re-run this.
    try {
      window.history.replaceState({}, '', '/')
    } catch {
      /* ignore */
    }
    navigate('login')
  }

  return (
    <div className="screen-enter auth-screen">
      <div className="top-bar">
        <Logo onClick={() => navigate('welcome')} />
      </div>

      <div className="auth-head">
        <h1>Email verification</h1>
      </div>

      {status === 'loading' && (
        <p className="verify-status">Verifying your email address…</p>
      )}

      {status === 'success' && (
        <>
          <div className="verify-badge verify-badge--ok" aria-hidden="true">✓</div>
          <p className="verify-status">
            {message || 'Your email address has been verified.'} You can log in now.
          </p>
          <button
            type="button"
            className="btn btn-primary"
            style={{ marginTop: 18 }}
            onClick={goToLogin}
          >
            Go to Log In
          </button>
        </>
      )}

      {status === 'error' && (
        <>
          <div className="verify-badge verify-badge--bad" aria-hidden="true">✕</div>
          <p className="verify-status">
            {message || 'This verification link is invalid or has expired.'}
          </p>
          <p className="auth-field-hint" style={{ opacity: 1 }}>
            Try registering again to get a fresh link, or log in if your account
            is already verified.
          </p>
          <div className="cta-row" style={{ marginTop: 18 }}>
            <button type="button" className="btn" onClick={() => navigate('register')}>
              Sign Up
            </button>
            <button type="button" className="btn btn-primary" onClick={goToLogin}>
              Log In
            </button>
          </div>
        </>
      )}

      <button type="button" className="auth-back" onClick={() => navigate('welcome')}>
        ← Back
      </button>
    </div>
  )
}
