import { useEffect, useState } from 'react'
import BottomNav from '../components/BottomNav'
import Logo from '../components/Logo'
import { isAuthed, logout } from '../auth'
import { getSession, getSessions } from '../api'
import './Dashboard.css'

function formatDate(iso) {
  const d = new Date(iso)
  if (isNaN(d)) return ''
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })
}

export default function Dashboard({ navigate, result }) {
  const summary = result?.summary ?? null

  const [sessions, setSessions] = useState([])
  const [histLoading, setHistLoading] = useState(false)
  const [histError, setHistError] = useState(null)
  const [openingId, setOpeningId] = useState(null)

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

  function handleLogout() {
    logout()
    navigate('welcome')
  }

  async function openSession(id) {
    if (openingId) return
    setOpeningId(id)
    setHistError(null)
    try {
      const data = await getSession(id)
      // Same shape a fresh analysis produces — session/heatmap screens just work.
      navigate('session', { result: data.result, jobId: data.id, error: null })
    } catch (err) {
      setHistError(err.message)
      setOpeningId(null)
    }
  }

  return (
    <div className="screen-enter">
      <div className="top-bar">
        <Logo />
        <div className="top-actions">
          {isAuthed() && (
            <button className="logout-btn" onClick={handleLogout}>Log out</button>
          )}
          <div className="avatar" />
        </div>
      </div>

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
          {histError && <div className="error-box">{histError}</div>}

          {!histLoading && !histError && sessions.length === 0 && (
            <p className="dashboard-hint">No past sessions yet — analyze a video to start your history.</p>
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

      <BottomNav active="dashboard" navigate={navigate} />
    </div>
  )
}
