import { useEffect, useState } from 'react'
import BottomNav from '../components/BottomNav'
import CourtMap from '../components/CourtMap'
import Logo from '../components/Logo'
import { isAuthed } from '../auth'
import { getSession, getSessions } from '../api'
import './Statistics.css'

// "—" for anything that would otherwise be NaN/Infinity (0 sessions, 0 shots).
function fmt1(v) {
  return v == null || !Number.isFinite(v) ? '—' : v.toFixed(1)
}
function fmtPct1(v) {
  return v == null || !Number.isFinite(v) ? '—' : `${v.toFixed(1)}%`
}

// e.g. "Sep 4, 2026 · 5:41 PM" — same format as the Dashboard history list.
function formatDateTime(iso) {
  const d = new Date(iso)
  if (isNaN(d)) return ''
  const date = d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })
  const time = d.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })
  return `${date} · ${time}`
}

// Highest-accuracy session with 5 or more shots. Ties break on more shots
// attempted, then on the more recent session. Returns null if no session
// qualifies (min. 5 shots).
function pickBestSession(sessions) {
  let best = null
  for (const s of sessions) {
    const shots = Number(s.total_shots) || 0
    if (shots < 5) continue
    if (!best) { best = s; continue }
    const acc = Number(s.accuracy_pct) || 0
    const bestAcc = Number(best.accuracy_pct) || 0
    if (acc !== bestAcc) { if (acc > bestAcc) best = s; continue }
    const bestShots = Number(best.total_shots) || 0
    if (shots !== bestShots) { if (shots > bestShots) best = s; continue }
    if (new Date(s.created_at) > new Date(best.created_at)) best = s
  }
  return best
}

// Aggregate + per-session-average stats from a list of SessionSummary rows.
function computeStats(sessions) {
  const n = sessions.length
  const totalAttempts = sessions.reduce((sum, s) => sum + (Number(s.total_shots) || 0), 0)
  const totalMade     = sessions.reduce((sum, s) => sum + (Number(s.made) || 0), 0)

  return {
    n,
    totalAttempts,
    totalMade,
    // Aggregate accuracy across every shot ever taken.
    overallAccuracy: totalAttempts > 0 ? (totalMade / totalAttempts) * 100 : null,
    // Per-session averages.
    avgShots:    n > 0 ? totalAttempts / n : null,
    avgMakes:    n > 0 ? totalMade / n : null,
    avgAccuracy: n > 0
      ? sessions.reduce((sum, s) => sum + (Number(s.accuracy_pct) || 0), 0) / n
      : null,
  }
}

// CourtMap's 4 real zone ids (see components/CourtMap.jsx — matches what
// backend court_mapper.classify_zone() actually produces).
const ZONE_IDS = ['two_left', 'two_right', 'three_left', 'three_right']

// Sum attempts/made per zone across every session's full result.zone_aggregates,
// then derive each zone's all-time accuracy_pct. Sessions with no court mapping
// (zone_aggregates empty/absent) simply contribute nothing — safe no-op.
function aggregateZones(sessionResults) {
  const totals = Object.fromEntries(
    ZONE_IDS.map(id => [id, { attempts: 0, made: 0, label: null }]),
  )

  for (const result of sessionResults) {
    const zones = Array.isArray(result?.zone_aggregates) ? result.zone_aggregates : []
    for (const z of zones) {
      const bucket = totals[z?.polygon_id]
      if (!bucket) continue // ignore anything outside the 4 known zone ids
      bucket.attempts += Number(z.attempts) || 0
      bucket.made     += Number(z.made) || 0
      bucket.label = bucket.label ?? z.label ?? null
    }
  }

  return ZONE_IDS.map(id => {
    const t = totals[id]
    return {
      polygon_id: id,
      attempts: t.attempts,
      made: t.made,
      accuracy_pct: t.attempts > 0 ? (t.made / t.attempts) * 100 : null,
      label: t.label,
    }
  })
}

export default function Statistics({ navigate }) {
  const [sessions, setSessions] = useState([])
  const [loading,  setLoading]  = useState(false)
  const [error,    setError]    = useState(null)

  const [zoneAggregates, setZoneAggregates] = useState([])
  const [zoneLoading,    setZoneLoading]    = useState(false)

  const [openingBest,   setOpeningBest]   = useState(false)
  const [openBestError, setOpenBestError] = useState(null)

  // 1. Session summaries (date, total_shots, made, accuracy_pct) — cheap, one call.
  useEffect(() => {
    if (!isAuthed()) return
    let cancelled = false
    setLoading(true)
    setError(null)
    getSessions()
      .then(list => { if (!cancelled) setSessions(Array.isArray(list) ? list : []) })
      .catch(err => { if (!cancelled) setError(err.message) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [])

  // 2. Full per-session results, to sum zone_aggregates for the all-time shot
  // chart. The list endpoint doesn't carry zone data, so this fans out one
  // detail fetch per session; a session that fails to load is just skipped
  // rather than failing the whole aggregate.
  useEffect(() => {
    if (!isAuthed() || sessions.length === 0) { setZoneAggregates([]); return }
    let cancelled = false
    setZoneLoading(true)
    Promise.allSettled(sessions.map(s => getSession(s.id)))
      .then(outcomes => {
        if (cancelled) return
        const results = outcomes
          .filter(o => o.status === 'fulfilled')
          .map(o => o.value?.result)
        setZoneAggregates(aggregateZones(results))
      })
      .finally(() => { if (!cancelled) setZoneLoading(false) })
    return () => { cancelled = true }
  }, [sessions])

  const stats = computeStats(sessions)
  const bestSession = pickBestSession(sessions)

  async function openBestSession(id) {
    if (openingBest) return
    setOpeningBest(true)
    setOpenBestError(null)
    try {
      const data = await getSession(id)
      // Same shape a fresh analysis produces — Session.jsx just works.
      navigate('session', { result: data.result, jobId: data.id, error: null })
    } catch (err) {
      setOpenBestError("Couldn't open that session. Please try again.")
      setOpeningBest(false)
    }
  }

  return (
    <div className="screen-enter">
      <div className="top-bar">
        <Logo onClick={() => navigate('dashboard')} />
        <div className="top-actions"><div className="avatar" /></div>
      </div>

      <h1 className="page-title">Statistics</h1>

      {!isAuthed() && (
        <p className="dashboard-hint">Log in to see your all-time shooting stats.</p>
      )}

      {isAuthed() && loading && (
        <p className="dashboard-hint">Loading statistics…</p>
      )}

      {isAuthed() && !loading && (
        <>
          {error && (
            <p className="dashboard-hint">Statistics aren't available right now.</p>
          )}

          {!error && stats.n === 0 && (
            <p className="dashboard-hint">
              No sessions yet — analyze a video to start building your stats.
            </p>
          )}

          <div className="section-title">All-Time Totals</div>
          <div className="stat-grid-3">
            <div className="stat-card">
              <div className="stat-label">Shots Attempted</div>
              <div className="stat-value">{stats.totalAttempts}</div>
            </div>
            <div className="stat-card">
              <div className="stat-label">Shots Made</div>
              <div className="stat-value" style={{ color: 'var(--green)' }}>{stats.totalMade}</div>
            </div>
            <div className="stat-card">
              <div className="stat-label">Overall Accuracy</div>
              <div className="stat-value" style={{ color: 'var(--orange)' }}>
                {fmtPct1(stats.overallAccuracy)}
              </div>
            </div>
          </div>

          <div className="section-title">Per-Session Averages</div>
          <div className="stat-grid-3">
            <div className="stat-card">
              <div className="stat-label">Avg Shots / Session</div>
              <div className="stat-value">{fmt1(stats.avgShots)}</div>
            </div>
            <div className="stat-card">
              <div className="stat-label">Avg Makes / Session</div>
              <div className="stat-value" style={{ color: 'var(--green)' }}>
                {fmt1(stats.avgMakes)}
              </div>
            </div>
            <div className="stat-card">
              <div className="stat-label">Avg Accuracy / Session</div>
              <div className="stat-value" style={{ color: 'var(--orange)' }}>
                {fmtPct1(stats.avgAccuracy)}
              </div>
            </div>
          </div>

          <div className="section-title">Best Session</div>
          {bestSession ? (
            <button
              className="best-session-card"
              onClick={() => openBestSession(bestSession.id)}
              disabled={openingBest}
            >
              <div className="best-session-main">
                <div className="best-session-date">{formatDateTime(bestSession.created_at)}</div>
                <div className="best-session-stat">
                  {bestSession.made}/{bestSession.total_shots}
                  <span className="best-session-pct"> · {fmtPct1(bestSession.accuracy_pct)}</span>
                </div>
              </div>
              <div className="best-session-go">{openingBest ? '…' : 'View Session →'}</div>
            </button>
          ) : (
            <p className="dashboard-hint">
              No qualifying sessions yet (min. 5 shots required).
            </p>
          )}
          {openBestError && <div className="error-box">{openBestError}</div>}

          <div className="section-title">All-Time Shot Chart</div>
          {zoneLoading && <p className="dashboard-hint">Loading shot chart…</p>}
          <CourtMap zoneAggregates={zoneAggregates} />
        </>
      )}

      <BottomNav active="statistics" navigate={navigate} />
    </div>
  )
}
