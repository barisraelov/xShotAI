import { useState } from 'react'
import Logo from '../components/Logo'
import { login } from '../auth'
import './Login.css'

export default function Login({ navigate }) {
  const [identifier, setIdentifier] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(false)

  async function handleSubmit(e) {
    e.preventDefault()
    if (loading) return
    setError(null)
    setLoading(true)
    try {
      await login(identifier.trim(), password)
      navigate('dashboard')
    } catch (err) {
      setError(err.message)
      setLoading(false)
    }
  }

  return (
    <div className="screen-enter auth-screen">
      <div className="top-bar">
        <Logo />
      </div>

      <div className="auth-head">
        <h1>Welcome back</h1>
        <p>Log in to analyze and track your sessions.</p>
      </div>

      <form className="auth-form" onSubmit={handleSubmit}>
        <div className="auth-field">
          <label htmlFor="login-id">Email or username</label>
          <input
            id="login-id"
            type="text"
            autoComplete="username"
            autoCapitalize="off"
            autoCorrect="off"
            spellCheck="false"
            value={identifier}
            onChange={e => setIdentifier(e.target.value)}
            disabled={loading}
            required
          />
        </div>

        <div className="auth-field">
          <label htmlFor="login-pw">Password</label>
          <input
            id="login-pw"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={e => setPassword(e.target.value)}
            disabled={loading}
            required
          />
        </div>

        {error && <div className="error-box">{error}</div>}

        <button
          type="submit"
          className="btn btn-primary"
          disabled={loading || !identifier || !password}
        >
          {loading ? 'Signing in…' : 'Log In'}
        </button>
      </form>

      <p className="auth-alt">
        No account?{' '}
        <button type="button" className="auth-link" onClick={() => navigate('register')}>
          Sign up
        </button>
      </p>

      <button type="button" className="auth-back" onClick={() => navigate('welcome')}>
        ← Back
      </button>
    </div>
  )
}
