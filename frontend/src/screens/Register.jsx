import { useState } from 'react'
import Logo from '../components/Logo'
import { register } from '../auth'
import './Login.css'

/** A single password-requirement row: neutral before typing, then met / unmet. */
function PwReq({ met, pending, children }) {
  const state = pending ? 'pending' : met ? 'met' : 'unmet'
  return (
    <li className={'pw-req pw-req--' + state}>
      <span className="pw-req-icon" aria-hidden="true">
        {pending ? '•' : met ? '✓' : '✗'}
      </span>
      {children}
    </li>
  )
}

/** Minimal eye / eye-off icon (lucide-style paths, no extra dependency). */
function EyeIcon({ off }) {
  return (
    <svg
      width="18"
      height="18"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {off ? (
        <>
          <path d="M9.88 9.88a3 3 0 1 0 4.24 4.24" />
          <path d="M10.73 5.08A10.43 10.43 0 0 1 12 5c7 0 10 7 10 7a13.16 13.16 0 0 1-1.67 2.68" />
          <path d="M6.61 6.61A13.526 13.526 0 0 0 2 12s3 7 10 7a9.74 9.74 0 0 0 5.39-1.61" />
          <line x1="2" x2="22" y1="2" y2="22" />
        </>
      ) : (
        <>
          <path d="M2 12s3-7 10-7 10 7 10 7-3 7-10 7-10-7-10-7Z" />
          <circle cx="12" cy="12" r="3" />
        </>
      )}
    </svg>
  )
}

export default function Register({ navigate }) {
  const [email, setEmail] = useState('')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [showConfirm, setShowConfirm] = useState(false)
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(false)

  const passwordsMismatch =
    confirmPassword.length > 0 && password !== confirmPassword

  // Password strength: at least 8 chars, and both letters and numbers.
  const pwHasMinLength = password.length >= 8
  const pwHasLetterAndNumber = /[a-zA-Z]/.test(password) && /[0-9]/.test(password)
  const passwordStrong = pwHasMinLength && pwHasLetterAndNumber

  function validate() {
    if (!email.trim() || !username.trim() || !password || !confirmPassword) {
      return 'Please fill in all fields.'
    }
    if (!passwordStrong) {
      return 'Password must be at least 8 characters long and include both letters and numbers.'
    }
    if (password !== confirmPassword) {
      return 'Passwords do not match.'
    }
    return null
  }

  async function handleSubmit(e) {
    e.preventDefault()
    if (loading) return

    const validationError = validate()
    if (validationError) {
      setError(validationError)
      return
    }

    setError(null)
    setLoading(true)
    try {
      // register() creates the account and logs in, returning a token.
      await register({ email: email.trim(), username: username.trim(), password })
      navigate('dashboard')
    } catch (err) {
      setError(err.message)
      setLoading(false)
    }
  }

  return (
    <div className="screen-enter auth-screen">
      <div className="top-bar">
        <Logo onClick={() => navigate('dashboard')} />
      </div>

      <div className="auth-head">
        <h1>Create your account</h1>
        <p>Save your sessions and track progress over time.</p>
      </div>

      <form className="auth-form" onSubmit={handleSubmit}>
        <div className="auth-field">
          <label htmlFor="reg-email">Email</label>
          <input
            id="reg-email"
            type="email"
            autoComplete="email"
            autoCapitalize="off"
            autoCorrect="off"
            spellCheck="false"
            value={email}
            onChange={e => setEmail(e.target.value)}
            disabled={loading}
            required
          />
        </div>

        <div className="auth-field">
          <label htmlFor="reg-username">Username</label>
          <input
            id="reg-username"
            type="text"
            autoComplete="username"
            autoCapitalize="off"
            autoCorrect="off"
            spellCheck="false"
            value={username}
            onChange={e => setUsername(e.target.value)}
            disabled={loading}
            required
          />
        </div>

        <div className="auth-field">
          <label htmlFor="reg-pw">Password</label>
          <div className="auth-input-wrap">
            <input
              id="reg-pw"
              type={showPassword ? 'text' : 'password'}
              autoComplete="new-password"
              value={password}
              onChange={e => setPassword(e.target.value)}
              disabled={loading}
              required
            />
            <button
              type="button"
              className={'auth-pw-toggle' + (showPassword ? ' is-active' : '')}
              onClick={() => setShowPassword(v => !v)}
              disabled={loading}
              aria-label={showPassword ? 'Hide password' : 'Show password'}
              aria-pressed={showPassword}
              tabIndex={-1}
            >
              <EyeIcon off={showPassword} />
            </button>
          </div>
          <ul className="pw-reqs">
            <PwReq met={pwHasMinLength} pending={password.length === 0}>
              At least 8 characters
            </PwReq>
            <PwReq met={pwHasLetterAndNumber} pending={password.length === 0}>
              Contains letters and numbers
            </PwReq>
          </ul>
        </div>

        <div className="auth-field">
          <label htmlFor="reg-pw-confirm">Confirm password</label>
          <div className="auth-input-wrap">
            <input
              id="reg-pw-confirm"
              type={showConfirm ? 'text' : 'password'}
              autoComplete="new-password"
              value={confirmPassword}
              onChange={e => setConfirmPassword(e.target.value)}
              disabled={loading}
              aria-invalid={passwordsMismatch}
              required
            />
            <button
              type="button"
              className={'auth-pw-toggle' + (showConfirm ? ' is-active' : '')}
              onClick={() => setShowConfirm(v => !v)}
              disabled={loading}
              aria-label={showConfirm ? 'Hide password' : 'Show password'}
              aria-pressed={showConfirm}
              tabIndex={-1}
            >
              <EyeIcon off={showConfirm} />
            </button>
          </div>
          {passwordsMismatch && (
            <span className="auth-field-hint">Passwords do not match.</span>
          )}
        </div>

        {error && <div className="error-box">{error}</div>}

        <button
          type="submit"
          className="btn btn-primary"
          disabled={
            loading ||
            !email ||
            !username ||
            !password ||
            !confirmPassword ||
            !passwordStrong ||
            password !== confirmPassword
          }
        >
          {loading ? 'Creating account…' : 'Sign Up'}
        </button>
      </form>

      <p className="auth-alt">
        Already have an account?{' '}
        <button type="button" className="auth-link" onClick={() => navigate('login')}>
          Log in
        </button>
      </p>

      <button type="button" className="auth-back" onClick={() => navigate('welcome')}>
        ← Back
      </button>
    </div>
  )
}
