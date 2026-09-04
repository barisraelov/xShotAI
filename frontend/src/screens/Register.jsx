import { useState } from 'react'
import Logo from '../components/Logo'
import { register } from '../auth'
import './Login.css'

export default function Register({ navigate }) {
  const [email, setEmail] = useState('')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState(null)
  const [loading, setLoading] = useState(false)

  async function handleSubmit(e) {
    e.preventDefault()
    if (loading) return
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
          <input
            id="reg-pw"
            type="password"
            autoComplete="new-password"
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
          disabled={loading || !email || !username || !password}
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
