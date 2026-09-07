import { useEffect, useMemo, useRef, useState } from 'react'
import Logo from '../components/Logo'
import { isAuthed } from '../auth'
import { getSession, getSessions } from '../api'
import './History.css'

// created_at is a UTC ISO string; the date filter/grouping is by the viewer's
// LOCAL calendar day, so both sides key off the same local YYYY-MM-DD.
function localDayKey(iso) {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

// "2026-09-07" -> "Sep 7, 2026" (parsed as local midnight, no TZ shift).
function dayLabel(key) {
  const d = new Date(`${key}T00:00:00`)
  if (Number.isNaN(d.getTime())) return key
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })
}

function formatTime(iso) {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  return d.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })
}

export default function History({ navigate }) {
  const [sessions, setSessions] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  const [filterDate, setFilterDate] = useState('') // '' = all days
  const [openingId, setOpeningId] = useState(null)
  const [openError, setOpenError] = useState(null)

  // Only auto-pick the default date once; after that the user's choice
  // (including clearing back to "all") is left alone.
  const didInitDate = useRef(false)

  const todayKey = localDayKey(new Date().toISOString())

  useEffect(() => {
    if (!isAuthed()) return undefined
    let cancelled = false
    setLoading(true)
    setError(null)
    getSessions()
      .then(list => { if (!cancelled) setSessions(Array.isArray(list) ? list : []) })
      .catch(err => { if (!cancelled) setError(err.message) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [])

  // Sessions arrive newest-first — group into days (newest day first), each with
  // a rolled-up made / total / accuracy for the day.
  const dayGroups = useMemo(() => {
    const map = new Map() // key -> { key, sessions: [] }
    for (const s of sessions) {
      const key = localDayKey(s.created_at)
      if (!key) continue
      if (!map.has(key)) map.set(key, { key, sessions: [] })
      map.get(key).sessions.push(s)
    }
    return [...map.values()]
      .sort((a, b) => (a.key < b.key ? 1 : a.key > b.key ? -1 : 0))
      .map(g => {
        const made = g.sessions.reduce((n, s) => n + (Number(s.made) || 0), 0)
        const total = g.sessions.reduce((n, s) => n + (Number(s.total_shots) || 0), 0)
        return {
          ...g,
          label: dayLabel(g.key),
          made,
          total,
          pct: total > 0 ? Math.round((made / total) * 100) : 0,
        }
      })
  }, [sessions])

  // Default the view to the most recent day that has sessions. dayGroups is
  // sorted newest-day-first, so [0].key is that date. Runs once.
  useEffect(() => {
    if (didInitDate.current || dayGroups.length === 0) return
    didInitDate.current = true
    setFilterDate(dayGroups[0].key)
  }, [dayGroups])

  const visibleGroups = filterDate
    ? dayGroups.filter(g => g.key === filterDate)
    : dayGroups
  const visibleCount = visibleGroups.reduce((n, g) => n + g.sessions.length, 0)

  async function openSession(id) {
    if (openingId) return
    setOpeningId(id)
    setOpenError(null)
    try {
      const data = await getSession(id)
      // Same payload shape a fresh analysis produces — session/heatmap just work.
      navigate('session', { result: data.result, jobId: data.id, error: null })
    } catch (err) {
      setOpenError("Couldn't open that session. Please try again.")
      setOpeningId(null)
    }
  }

  const ready = isAuthed() && !loading && !error

  return (
    <div className="screen-enter">
      <div className="top-bar">
        <Logo onClick={() => navigate('dashboard')} />
      </div>

      <h1 className="page-title">Session History</h1>

      {!isAuthed() && (
        <p className="dashboard-hint">Log in to see your session history.</p>
      )}

      {isAuthed() && loading && (
        <p className="dashboard-hint">Loading sessions…</p>
      )}

      {isAuthed() && !loading && error && (
        <p className="dashboard-hint">Session history isn't available right now.</p>
      )}

      {ready && sessions.length === 0 && (
        <div className="hist-empty">
          <p className="dashboard-hint">You haven't recorded any sessions yet.</p>
          <button className="btn btn-primary" onClick={() => navigate('upload')}>
            Upload your first session
          </button>
        </div>
      )}

      {ready && sessions.length > 0 && (
        <>
          <div className="hist-controls">
            <input
              type="date"
              className="hist-date"
              aria-label="Filter sessions by date"
              value={filterDate}
              max={todayKey}
              onChange={e => setFilterDate(e.target.value)}
            />
            {filterDate && (
              <button
                type="button"
                className="hist-clear"
                onClick={() => setFilterDate('')}
              >
                ✕ Clear filter
              </button>
            )}
          </div>

          <p className="hist-summary">
            {filterDate
              ? `Showing ${visibleCount} session${visibleCount === 1 ? '' : 's'} from ${dayLabel(filterDate)}`
              : `All sessions (${sessions.length} total)`}
          </p>

          {openError && <div className="error-box">{openError}</div>}

          {visibleGroups.length === 0 && (
            <div className="hist-empty">
              <p className="dashboard-hint">No sessions recorded on this date.</p>
              <button
                type="button"
                className="btn"
                onClick={() => setFilterDate('')}
              >
                Show all sessions
              </button>
            </div>
          )}

          {visibleGroups.map(g => (
            <div className="hist-group" key={g.key}>
              <div className="hist-group-head">
                <span className="hist-group-date">{g.label}</span>
                <span className="hist-group-total">
                  Total: {g.made}/{g.total} · {g.pct}%
                </span>
              </div>

              <ul className="hist-list">
                {g.sessions.map(s => (
                  <li key={s.id}>
                    <button
                      className="hist-row"
                      onClick={() => openSession(s.id)}
                      disabled={!!openingId}
                    >
                      <span className="hist-row-time">{formatTime(s.created_at)}</span>
                      <span className="hist-row-stat">
                        {s.made}/{s.total_shots}
                        <span className="hist-row-pct">
                          {' '}· {Math.round(Number(s.accuracy_pct) || 0)}%
                        </span>
                      </span>
                      <span className="hist-row-go">
                        {openingId === s.id ? '…' : '→'}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </>
      )}
    </div>
  )
}
