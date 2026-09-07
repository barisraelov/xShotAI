import { useState } from 'react'
import Logo from '../components/Logo'
import { changePassword } from '../auth'
import './Profile.css'

const NEW_PW_MIN = 8

// The backend user payload currently has no dedicated name fields, so derive
// First / Last from `username` (split on space / . / _ / -). Real
// `first_name` / `last_name` are used as-is if the API ever adds them.
function splitName(user) {
  if (user?.first_name || user?.last_name) {
    return { first: user.first_name || '—', last: user.last_name || '—' }
  }
  const raw = String(user?.username || '').trim()
  if (!raw) return { first: '—', last: '—' }
  const parts = raw.split(/[\s._-]+/).filter(Boolean)
  return { first: parts[0] || raw, last: parts.slice(1).join(' ') || '—' }
}

export default function Profile({ navigate, user, levelInfo }) {
  const name = splitName(user)

  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [alert, setAlert] = useState(null) // { tone: 'success'|'error'|'info', text }

  function validate() {
    if (!currentPassword || !newPassword || !confirmPassword) {
      return 'Please fill in all fields.'
    }
    if (newPassword.length < NEW_PW_MIN) {
      return `New password must be at least ${NEW_PW_MIN} characters.`
    }
    if (newPassword !== confirmPassword) {
      return 'Passwords do not match.'
    }
    if (newPassword === currentPassword) {
      return 'New password must be different from the current one.'
    }
    return null
  }

  async function handleSubmit(e) {
    e.preventDefault()
    if (submitting) return

    const problem = validate()
    if (problem) {
      setAlert({ tone: 'error', text: problem })
      return
    }

    setAlert(null)
    setSubmitting(true)
    try {
      const res = await changePassword({ currentPassword, newPassword })
      setAlert({ tone: 'success', text: res?.detail || 'Password updated successfully.' })
      setCurrentPassword('')
      setNewPassword('')
      setConfirmPassword('')
    } catch (err) {
      setAlert({ tone: err.unavailable ? 'info' : 'error', text: err.message })
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="screen-enter">
      <div className="top-bar">
        <Logo onClick={() => navigate('dashboard')} />
      </div>

      <h1 className="page-title">Profile &amp; Account</h1>

      {/* ── User details ── */}
      <div className="pf-card">
        <div className="pf-card-title">User details</div>
        <dl className="pf-fields">
          <div className="pf-field">
            <dt>First name</dt>
            <dd>{name.first}</dd>
          </div>
          <div className="pf-field">
            <dt>Last name</dt>
            <dd>{name.last}</dd>
          </div>
          <div className="pf-field">
            <dt>Email address</dt>
            <dd>{user?.email || '—'}</dd>
          </div>
        </dl>
      </div>

      {/* ── Level & tier ── */}
      {levelInfo && (
        <div className="pf-card pf-level">
          <div className="pf-level-top">
            <span className="pf-lvl">LVL {levelInfo.level}</span>
            <span className="pf-level-title">{levelInfo.title}</span>
            {levelInfo.isMaxLevel && <span className="pf-max">MAX</span>}
          </div>
          <div
            className="pf-level-bar"
            role="progressbar"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={levelInfo.progressPercent}
          >
            <div
              className="pf-level-bar-fill"
              style={{ width: `${levelInfo.progressPercent}%` }}
            />
          </div>
          <div className="pf-level-text">
            {levelInfo.totalMadeShots} made shots
            {levelInfo.isMaxLevel
              ? ' · Max level'
              : ` · ${levelInfo.currentLevelShots} / ${
                  levelInfo.currentLevelShots + levelInfo.nextLevelShots
                } to Level ${levelInfo.level + 1}`}
          </div>
        </div>
      )}

      {/* ── Change password ── */}
      <form className="pf-card pf-form" onSubmit={handleSubmit}>
        <div className="pf-card-title">Security · Change password</div>

        {alert && (
          <div className={`pf-alert pf-alert--${alert.tone}`} role="status">
            {alert.text}
          </div>
        )}

        <label className="pf-input-field">
          <span>Current password</span>
          <input
            type="password"
            autoComplete="current-password"
            value={currentPassword}
            onChange={e => setCurrentPassword(e.target.value)}
            disabled={submitting}
          />
        </label>

        <label className="pf-input-field">
          <span>New password</span>
          <input
            type="password"
            autoComplete="new-password"
            value={newPassword}
            onChange={e => setNewPassword(e.target.value)}
            disabled={submitting}
          />
        </label>

        <label className="pf-input-field">
          <span>Confirm new password</span>
          <input
            type="password"
            autoComplete="new-password"
            value={confirmPassword}
            onChange={e => setConfirmPassword(e.target.value)}
            disabled={submitting}
          />
        </label>

        <button
          type="submit"
          className="btn btn-primary pf-submit"
          disabled={submitting || !currentPassword || !newPassword || !confirmPassword}
        >
          {submitting ? 'Updating…' : 'Update Password'}
        </button>
      </form>
    </div>
  )
}
