import { API_BASE, authHeaders } from '../auth'

const CONTACT_EMAIL = 'xshotaiapp@gmail.com'

const delay = ms => new Promise(r => setTimeout(r, ms))

/**
 * Send a contact-form message.
 *
 * Tries `POST /contact`. If that endpoint isn't there yet (404 / 405 / 501 or
 * a network error) it resolves to `{ simulated: true }` after a short delay so
 * the UI can still show a success state. 400 / 422 surface the server's detail.
 */
export async function sendContactMessage({ name, email, subject, message }) {
  const payload = JSON.stringify({ name, email, subject, message })

  let res
  try {
    res = await fetch(`${API_BASE}/contact`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeaders() },
      body: payload,
    })
  } catch {
    await delay(700)
    return { simulated: true }
  }

  if (res.ok) return res.json().catch(() => ({ detail: 'sent' }))
  if (res.status === 404 || res.status === 405 || res.status === 501) {
    await delay(700)
    return { simulated: true }
  }
  if (res.status === 400 || res.status === 422) {
    const data = await res.json().catch(() => ({}))
    throw new Error(data.detail || 'Please check the form and try again.')
  }
  throw new Error(`Couldn't send your message (${res.status}).`)
}

/** `mailto:` link that pre-fills the composed message. */
export function contactMailtoHref({ name, subject, message }) {
  const body = message
    ? `${message}\n\n— ${name || ''}`.trim()
    : ''
  const params = new URLSearchParams()
  if (subject) params.set('subject', `[xShot AI] ${subject}`)
  if (body) params.set('body', body)
  const query = params.toString()
  return `mailto:${CONTACT_EMAIL}${query ? `?${query}` : ''}`
}
