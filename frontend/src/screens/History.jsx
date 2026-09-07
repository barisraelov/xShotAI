import { useEffect, useMemo, useRef, useState } from 'react'
import Logo from '../components/Logo'
import { isAuthed } from '../auth'
import { deleteSession, getSession, getSessions } from '../api'
import { sessionTitle } from '../utils/sessions'
import ConfirmDialog from '../components/ConfirmDialog'
import './History.css'

const DELETE_CONFIRM_MESSAGE =
  'Are you sure you want to delete this session? This action cannot be undone ' +
  'and will update your shooting stats.'

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

const MONTHS_SHORT = [
  'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
  'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
]

// "2026-09-07" -> "7 Sep 2026" — day-first, built from the key string itself
// so it's deterministic across engines and immune to any TZ shift.
function dayLabel(key) {
  const [y, m, d] = String(key).split('-').map(Number)
  if (!y || !m || !d || m < 1 || m > 12) return key
  return `${d} ${MONTHS_SHORT[m - 1]} ${y}`
}

// Compact chip label for the date bar: "Today" / "Yesterday" / "6 Sep".
function chipLabel(key, todayKey, yesterdayKey) {
  if (key === todayKey) return 'Today'
  if (key === yesterdayKey) return 'Yesterday'
  const [y, m, d] = String(key).split('-').map(Number)
  if (!y || !m || !d || m < 1 || m > 12) return key
  return `${d} ${MONTHS_SHORT[m - 1]}`
}

function formatTime(iso) {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  return d.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })
}

export default function History({ navigate, onSessionDeleted }) {
  const [sessions, setSessions] = useState([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  const [filterDate, setFilterDate] = useState('') // '' = all days
  const [openingId, setOpeningId] = useState(null)
  const [openError, setOpenError] = useState(null)

  const [pendingDelete, setPendingDelete] = useState(null) // session obj | null
  const [deleting, setDeleting] = useState(false)
  const [deleteError, setDeleteError] = useState(null)

  // Only auto-pick the default date once; after that the user's choice
  // (including clearing back to "all") is left alone.
  const didInitDate = useRef(false)
  const activeChipRef = useRef(null)

  const todayKey = localDayKey(new Date().toISOString())
  const yesterdayKey = localDayKey(new Date(Date.now() - 86_400_000).toISOString())

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

  // Keep the selected day pill in view as the filter changes (e.g. the
  // one-time default jump to the most recent day, or picking an older day
  // that sits off the right edge of the scroll bar).
  useEffect(() => {
    activeChipRef.current?.scrollIntoView({
      behavior: 'smooth', inline: 'center', block: 'nearest',
    })
  }, [filterDate])

  async function openSession(id) {
    if (openingId) return
    setOpeningId(id)
    setOpenError(null)
    try {
      const data = await getSession(id)
      // Same payload shape a fresh analysis produces — session/heatmap just work.
      navigate('session', {
        result: data.result,
        jobId: data.id,
        sessionId: data.id,
        sessionDate: data.created_at,
        sessionTitle: data.title,
        error: null,
      })
    } catch (err) {
      setOpenError("Couldn't open that session. Please try again.")
      setOpeningId(null)
    }
  }

  async function confirmDelete() {
    if (deleting || !pendingDelete) return
    const id = pendingDelete.id
    setDeleting(true)
    setDeleteError(null)
    try {
      await deleteSession(id)
      setSessions(prev => prev.filter(s => s.id !== id))
      onSessionDeleted?.(id)
      setPendingDelete(null)
    } catch (err) {
      setDeleteError('Could not delete this session. Please try again.')
    } finally {
      setDeleting(false)
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
          <div
            className="hist-datebar"
            role="tablist"
            aria-label="Filter sessions by day"
          >
            <button
              type="button"
              role="tab"
              aria-selected={!filterDate}
              className={`hist-chip hist-chip--all${!filterDate ? ' is-active' : ''}`}
              ref={!filterDate ? activeChipRef : null}
              onClick={() => setFilterDate('')}
            >
              <span className="hist-chip-label">All</span>
              <span className="hist-chip-sub">
                {sessions.length} total
              </span>
            </button>

            {dayGroups.map(g => {
              const active = filterDate === g.key
              const n = g.sessions.length
              return (
                <button
                  key={g.key}
                  type="button"
                  role="tab"
                  aria-selected={active}
                  className={`hist-chip${active ? ' is-active' : ''}`}
                  ref={active ? activeChipRef : null}
                  onClick={() => setFilterDate(g.key)}
                >
                  <span className="hist-chip-label">
                    {chipLabel(g.key, todayKey, yesterdayKey)}
                  </span>
                  <span className="hist-chip-sub">
                    {n} session{n === 1 ? '' : 's'}
                  </span>
                </button>
              )
            })}
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
                  <li className="hist-li" key={s.id}>
                    <button
                      className="hist-row"
                      onClick={() => openSession(s.id)}
                      disabled={!!openingId}
                    >
                      <span className="hist-row-main">
                        <span className="hist-row-title">{sessionTitle(s)}</span>
                        <span className="hist-row-time">{formatTime(s.created_at)}</span>
                      </span>
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
                    <button
                      type="button"
                      className="hist-del-btn"
                      onClick={() => { setDeleteError(null); setPendingDelete(s) }}
                      disabled={deleting}
                      aria-label={`Delete session ${sessionTitle(s)}`}
                      title="Delete session"
                    >
                      🗑️
                    </button>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </>
      )}

      {deleteError && <div className="error-box">{deleteError}</div>}

      <ConfirmDialog
        open={!!pendingDelete}
        title="Delete Session?"
        message={DELETE_CONFIRM_MESSAGE}
        confirmLabel="Delete"
        busy={deleting}
        onCancel={() => { setPendingDelete(null); setDeleteError(null) }}
        onConfirm={confirmDelete}
      />
    </div>
  )
}
