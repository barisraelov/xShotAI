/**
 * Auth layer — token storage + the /auth/* calls.
 *
 * Token is kept in localStorage under `xshot_token`. `login` / `register` use
 * the OAuth2 password flow (application/x-www-form-urlencoded). `api.js` pulls
 * `API_BASE`, `authHeaders`, and `handleUnauthorized` from here.
 */

export const API_BASE = import.meta.env.VITE_API_URL || ''

const TOKEN_KEY = 'xshot_token'

export function getToken() {
  try { return localStorage.getItem(TOKEN_KEY) } catch { return null }
}

export function setToken(token) {
  try { localStorage.setItem(TOKEN_KEY, token) } catch { /* private mode */ }
}

export function clearToken() {
  try { localStorage.removeItem(TOKEN_KEY) } catch { /* ignore */ }
}

export function isAuthed() {
  return !!getToken()
}

/** Authorization header for authenticated requests (empty when logged out). */
export function authHeaders() {
  const t = getToken()
  return t ? { Authorization: `Bearer ${t}` } : {}
}

// ── 401 handling ────────────────────────────────────────────────────────────
// App.jsx registers a handler that navigates to the login screen. api.js calls
// handleUnauthorized() when an authenticated request comes back 401.

let _onUnauthorized = null

export function setUnauthorizedHandler(fn) {
  _onUnauthorized = fn
}

export function handleUnauthorized() {
  clearToken()
  if (_onUnauthorized) _onUnauthorized()
}

// ── /auth calls ────────────────────────────────────────────────────────────

/**
 * OAuth2 password login. `identifier` may be the account email or username.
 * Resolves to the access token; throws Error('Invalid email or password') on 401.
 */
export async function login(identifier, password) {
  const body = new URLSearchParams({ username: identifier, password })
  const res = await fetch(`${API_BASE}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body,
  })

  if (res.status === 401) throw new Error('Invalid email or password')
  if (res.status === 403) {
    // Account exists and the password is right, but the email is unverified.
    const data = await res.json().catch(() => ({}))
    throw new Error(data.detail || 'Please verify your email before logging in')
  }
  if (!res.ok) throw new Error(`Login failed (${res.status})`)

  const data = await res.json()
  setToken(data.access_token)
  return data.access_token
}

/**
 * Create an account. Throws with the backend's message on 400 (email/username
 * taken), or a validation message on 422.
 *
 * Resolves to `{ verified, email }`:
 *   verified === false → a confirmation email was sent; the caller should show a
 *                        "check your inbox" state and NOT treat the user as
 *                        logged in (login is blocked until they verify).
 *   verified === true  → the backend has email verification disabled (no SMTP
 *                        configured), the account is already active, and this
 *                        function has logged the user in.
 */
export async function register({ email, username, password }) {
  const res = await fetch(`${API_BASE}/auth/register`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, username, password }),
  })

  if (res.status === 400) {
    const data = await res.json().catch(() => ({}))
    throw new Error(data.detail || 'Email or username already taken')
  }
  if (res.status === 422) throw new Error('Please enter a valid email and a password')
  if (!res.ok) throw new Error(`Sign up failed (${res.status})`)

  const user = await res.json().catch(() => ({}))
  if (user && user.is_verified === false) {
    return { verified: false, email }
  }

  // Verification disabled server-side — account is live, log straight in.
  await login(email, password)
  return { verified: true, email }
}

/**
 * Confirm an email address from the link in the verification email.
 * Resolves to the success message, or throws with the backend's error detail
 * when the token is missing / invalid / expired.
 */
export async function verifyEmail(token) {
  const res = await fetch(
    `${API_BASE}/auth/verify-email?token=${encodeURIComponent(token)}`,
  )
  const data = await res.json().catch(() => ({}))
  if (!res.ok) {
    throw new Error(data.detail || 'Verification link is invalid or has expired')
  }
  return data.detail || 'Email verified successfully'
}

/** Current user profile, or throws (401 handled by the caller / api layer). */
export async function me() {
  const res = await fetch(`${API_BASE}/auth/me`, { headers: { ...authHeaders() } })
  if (res.status === 401) {
    handleUnauthorized()
    throw new Error('Session expired')
  }
  if (!res.ok) throw new Error(`Failed to load profile (${res.status})`)
  return res.json()
}

export function logout() {
  clearToken()
}
