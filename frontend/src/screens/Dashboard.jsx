import { useEffect, useState } from 'react'
import Logo from '../components/Logo'
import { isAuthed } from '../auth'
import { getSession, getSessions } from '../api'
import { getLevelInfo } from '../utils/levels'
import './Dashboard.css'

// e.g. "Sep 4, 2026 · 3:42 PM" — date + time, both in the viewer's locale and
// local timezone (Date parses the UTC `created_at` and formats it locally).
function formatDate(iso) {
  const d = new Date(iso)
  if (isNaN(d)) return ''
  const date = d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })
  const time = d.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })
  return `${date} · ${time}`
}

export default function Dashboard({ navigate, result }) {
  const summary = result?.summary ?? null

  const [sessions, setSessions] = useState([])
  const [histLoading, setHistLoading] = useState(false)
  const [histError, setHistError] = useState(null)   // list load — shown as a muted note
  const [openError, setOpenError] = useState(null)   // row click — actionable, shown prominently
  const [openingId, setOpeningId] = useState(null)

  // Level is derived from cumulative made shots across every saved session.
  // Empty / still-loading history just yields Level 1 (0 shots) — never throws.
  const totalMadeShots = sessions.reduce((sum, s) => sum + (Number(s?.made) || 0), 0)
  const levelInfo = getLevelInfo(totalMadeShots)

  useEffect(() => {
    if (!isAuthed()) return
    let cancelled = false
    setHistLoading(true)
    setHistError(null)
    getSessions()
      .then(list => { if (!cancelled) setSessions(Array.isArray(list) ? list : []) })
      .catch(err => { if (!cancelled) setHistError(err.message) })
      .finally(() => { if (!cancelled) setHistLoading(false) })
    return () => { cancelled = true }
  }, [])

  async function openSession(id) {
    if (openingId) return
    setOpeningId(id)
    setOpenError(null)
    try {
      const data = await getSession(id)
      // Same shape a fresh analysis produces — session/heatmap screens just work.
      navigate('session', { result: data.result, jobId: data.id, error: null })
    } catch (err) {
      setOpenError("Couldn't open that session. Please try again.")
      setOpeningId(null)
    }
  }

  return (
    <div className="screen-enter">
      <div className="top-bar">
        <Logo onClick={() => navigate('dashboard')} />
        <div className="top-actions">
          <div className="avatar" />
        </div>
      </div>

      {isAuthed() && (
        <div className="level-card">
          <div className="level-card-top">
            <span className="level-badge">LVL {levelInfo.level}</span>
            <span className="level-title">{levelInfo.title}</span>
            {levelInfo.isMaxLevel && <span className="level-max">MAX</span>}
          </div>

          <div
            className="level-bar"
            role="progressbar"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={levelInfo.progressPercent}
          >
            <div
              className="level-bar-fill"
              style={{ width: `${levelInfo.progressPercent}%` }}
            />
          </div>

          <div className="level-progress-text">
            {levelInfo.isMaxLevel
              ? `Max level · ${levelInfo.totalMadeShots} made shots`
              : `${levelInfo.currentLevelShots} / ${
                  levelInfo.currentLevelShots + levelInfo.nextLevelShots
                } shots to Level ${levelInfo.level + 1}`}
          </div>
        </div>
      )}

      <button className="big-cta" onClick={() => navigate('upload')}>
        <span>▶ Upload training video</span>
        <span>→</span>
      </button>

      {summary && (
        <>
          <div className="section-title">Last analysis</div>
          <div className="stat-grid-2">
            <div className="stat-card">
              <div className="stat-label">Shots detected</div>
              <div className="stat-value">{summary.total_shots}</div>
            </div>
            <div className="stat-card">
              <div className="stat-label">Made</div>
              <div className="stat-value" style={{ color: 'var(--green)' }}>{summary.made}</div>
            </div>
            <div className="stat-card">
              <div className="stat-label">Missed</div>
              <div className="stat-value" style={{ color: 'var(--red)' }}>{summary.missed}</div>
            </div>
            <div className="stat-card">
              <div className="stat-label">Accuracy</div>
              <div className="stat-value">{summary.accuracy_pct.toFixed(0)}%</div>
            </div>
          </div>
          <div className="dashboard-cta-row">
            <button className="btn" onClick={() => navigate('session')}>View session</button>
            <button className="btn" onClick={() => navigate('heatmap')}>Shot map</button>
          </div>
        </>
      )}

      {!summary && !isAuthed() && (
        <p className="dashboard-hint">Upload a video to see your shot analysis here.</p>
      )}

      {isAuthed() && (
        <>
          <div className="section-title">Past sessions</div>

          {histLoading && <p className="dashboard-hint">Loading history…</p>}
          {openError && <div className="error-box">{openError}</div>}

          {!histLoading && sessions.length === 0 && (
            <p className="dashboard-hint">
              {histError
                ? "Session history isn't available right now."
                : 'No past sessions yet — analyze a video to start your history.'}
            </p>
          )}

          {sessions.length > 0 && (
            <ul className="history-list">
              {sessions.map(s => (
                <li key={s.id}>
                  <button
                    className="history-row"
                    onClick={() => openSession(s.id)}
                    disabled={!!openingId}
                  >
                    <span className="history-date">{formatDate(s.created_at)}</span>
                    <span className="history-stat">
                      {s.made}/{s.total_shots}
                      <span className="history-pct"> · {Math.round(s.accuracy_pct)}%</span>
                    </span>
                    <span className="history-go">{openingId === s.id ? '…' : '→'}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </>
      )}

    </div>
  )
}
