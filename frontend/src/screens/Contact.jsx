import { useEffect, useState } from 'react'
import Logo from '../components/Logo'
import { sendContactMessage } from '../utils/contact'
import './Contact.css'

const SUBJECTS = [
  'General Inquiry',
  'Bug Report / Feedback',
  'Feature Request',
  'Account Support',
  'Other',
]

const MSG_MIN = 10
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

function deriveName(user) {
  if (user?.first_name || user?.last_name) {
    return [user.first_name, user.last_name].filter(Boolean).join(' ')
  }
  return user?.username || ''
}

export default function Contact({ navigate, prevView, user }) {
  const backTo = prevView && prevView !== 'contact' ? prevView : 'dashboard'

  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [subject, setSubject] = useState(SUBJECTS[0])
  const [message, setMessage] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState(null)
  const [sent, setSent] = useState(false)

  // Pre-fill from the signed-in user once it loads, without clobbering edits.
  useEffect(() => {
    if (!user) return
    setName(n => n || deriveName(user))
    setEmail(e => e || user.email || '')
  }, [user])

  function validate() {
    if (!name.trim() || !email.trim() || !subject || !message.trim()) {
      return 'Please fill in all fields.'
    }
    if (!EMAIL_RE.test(email.trim())) {
      return 'Please enter a valid email address.'
    }
    if (message.trim().length < MSG_MIN) {
      return `Your message should be at least ${MSG_MIN} characters.`
    }
    return null
  }

  async function handleSubmit(e) {
    e.preventDefault()
    if (submitting) return

    const problem = validate()
    if (problem) {
      setError(problem)
      return
    }

    setError(null)
    setSubmitting(true)
    try {
      await sendContactMessage({
        name: name.trim(),
        email: email.trim(),
        subject,
        message: message.trim(),
      })
      setSent(true)
    } catch (err) {
      setError(err.message)
    } finally {
      setSubmitting(false)
    }
  }

  function sendAnother() {
    setMessage('')
    setSubject(SUBJECTS[0])
    setError(null)
    setSent(false)
  }

  return (
    <div className="screen-enter">
      <div className="top-bar contact-topbar">
        <button
          type="button"
          className="contact-back"
          onClick={() => navigate(backTo)}
        >
          ← Back
        </button>
        <Logo onClick={() => navigate('dashboard')} />
      </div>

      <h1 className="page-title">Contact Us</h1>
      <p className="contact-subtitle">
        Have a question, feedback, or need support? Reach out to the xShot AI
        team.
      </p>

      <div className="contact-direct">
        <div className="contact-direct-row">
          <span className="contact-direct-label">Email</span>
          <a className="contact-direct-link" href="mailto:xshotaiapp@gmail.com">
            xshotaiapp@gmail.com
          </a>
        </div>
        <p className="contact-direct-note">
          Typical response time: within 24–48 hours.
        </p>
      </div>

      {sent ? (
        <div className="contact-card contact-sent">
          <div className="contact-sent-icon" aria-hidden="true">✅</div>
          <p className="contact-sent-text">
            Thank you! Your message has been sent. We&rsquo;ll get back to you
            shortly.
          </p>
          <div className="contact-sent-actions">
            <button type="button" className="btn" onClick={sendAnother}>
              Send another message
            </button>
            <button
              type="button"
              className="btn btn-primary"
              onClick={() => navigate('dashboard')}
            >
              Back to dashboard
            </button>
          </div>
        </div>
      ) : (
        <form className="contact-card contact-form" onSubmit={handleSubmit} noValidate>
          {error && (
            <div className="contact-alert" role="alert">
              {error}
            </div>
          )}

          <label className="contact-field">
            <span>Name</span>
            <input
              type="text"
              autoComplete="name"
              value={name}
              onChange={e => setName(e.target.value)}
              disabled={submitting}
            />
          </label>

          <label className="contact-field">
            <span>Email address</span>
            <input
              type="email"
              autoComplete="email"
              autoCapitalize="off"
              autoCorrect="off"
              spellCheck="false"
              value={email}
              onChange={e => setEmail(e.target.value)}
              disabled={submitting}
            />
          </label>

          <label className="contact-field">
            <span>Subject</span>
            <select
              value={subject}
              onChange={e => setSubject(e.target.value)}
              disabled={submitting}
            >
              {SUBJECTS.map(s => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
          </label>

          <label className="contact-field">
            <span>Message</span>
            <textarea
              rows="5"
              placeholder="Tell us how we can help..."
              value={message}
              onChange={e => setMessage(e.target.value)}
              disabled={submitting}
            />
          </label>

          <button
            type="submit"
            className="btn btn-primary contact-submit"
            disabled={submitting}
          >
            {submitting ? (
              <>
                <span className="contact-spinner" aria-hidden="true" />
                Sending…
              </>
            ) : (
              'Send Message'
            )}
          </button>
        </form>
      )}

      <button
        type="button"
        className="contact-back contact-back--foot"
        onClick={() => navigate(backTo)}
      >
        ← Back
      </button>
    </div>
  )
}
