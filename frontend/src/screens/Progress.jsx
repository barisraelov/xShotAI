import { useEffect, useMemo, useState } from 'react'
import BottomNav from '../components/BottomNav'
import Logo from '../components/Logo'
import { isAuthed } from '../auth'
import { getSession, getSessions } from '../api'
import './Progress.css'

const WINDOW_OPTIONS = [
  { id: 5,     label: 'Last 5 sessions' },
  { id: 10,    label: 'Last 10 sessions' },
  { id: 20,    label: 'Last 20 sessions' },
  { id: 100,   label: 'Last 100 sessions' },
  { id: 'all', label: 'All sessions' },
]

// ids match the 4 real zones CourtMap/court_mapper.classify_zone() produce.
const ZONE_OPTIONS = [
  { id: 'overall',     label: 'Overall' },
  { id: 'two_left',    label: '2pt Left' },
  { id: 'two_right',   label: '2pt Right' },
  { id: 'three_left',  label: '3pt Left' },
  { id: 'three_right', label: '3pt Right' },
]

function formatShortDate(iso) {
  const d = new Date(iso)
  if (isNaN(d)) return ''
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}

// Chart geometry, in SVG viewBox units. The plot area is stretched to fill
// its container via preserveAspectRatio="none" (same technique CourtMap uses
// for its shot dots), so viewBox-unit% == container-relative % — that's what
// lets the HTML tooltip overlay line up with the SVG points below.
const VB_W = 320, VB_H = 180
const PAD = { l: 30, r: 10, t: 12, b: 24 }
const PLOT_W = VB_W - PAD.l - PAD.r
const PLOT_H = VB_H - PAD.t - PAD.b

function xAt(i, n) {
  return n <= 1 ? PAD.l + PLOT_W / 2 : PAD.l + (i / (n - 1)) * PLOT_W
}
function yAt(pct) {
  return PAD.t + (1 - pct / 100) * PLOT_H
}

// Up to `max` evenly-spaced indices from [0, n-1], always including both ends.
function pickTicks(n, max = 5) {
  if (n <= 0) return []
  if (n <= max) return Array.from({ length: n }, (_, i) => i)
  const set = new Set()
  for (let k = 0; k < max; k++) set.add(Math.round((k / (max - 1)) * (n - 1)))
  return [...set].sort((a, b) => a - b)
}

// Feedback lines often embed session-specific numbers (accuracy%, streak
// lengths, arc px, ...) via string interpolation on the backend, so the exact
// same theme rarely repeats verbatim. Collapsing digits to "#" groups those
// together (e.g. "Strong session accuracy at 72% (18/25 makes)." and
// "...at 81% (20/25 makes)." both key to the same underlying insight).
function normalizeFeedbackText(text) {
  return String(text).toLowerCase().replace(/\d+(\.\d+)?/g, '#').replace(/\s+/g, ' ').trim()
}

// Top `topN` most-frequent feedback lines (by normalized theme) across every
// session's feedback[field] array. A theme repeated more than once within a
// single session's own list only counts once for that session. Ties keep
// their first-seen order (Array.sort is stable) rather than resolving
// arbitrarily.
function topFeedback(sessionResults, field, topN = 2) {
  const buckets = new Map() // normalized key -> { text, count }
  for (const result of sessionResults) {
    const items = Array.isArray(result?.feedback?.[field]) ? result.feedback[field] : []
    const seenInSession = new Set()
    for (const raw of items) {
      if (typeof raw !== 'string' || !raw.trim()) continue
      const key = normalizeFeedbackText(raw)
      if (seenInSession.has(key)) continue
      seenInSession.add(key)
      const bucket = buckets.get(key)
      if (bucket) bucket.count += 1
      else buckets.set(key, { text: raw.trim(), count: 1 })
    }
  }
  return [...buckets.values()].sort((a, b) => b.count - a.count).slice(0, topN)
}

export default function Progress({ navigate }) {
  const [sessions, setSessions] = useState([])
  const [loading,  setLoading]  = useState(false)
  const [error,    setError]    = useState(null)

  // Full per-session results (for zone_aggregates) — fetched once, reused
  // across zone-filter switches so toggling zones never re-fetches.
  const [details,        setDetails]        = useState({})
  const [detailsLoading, setDetailsLoading] = useState(false)

  const [windowSize, setWindowSize] = useState(10)
  const [zone,       setZone]       = useState('overall')
  const [activeIdx,  setActiveIdx]  = useState(null)

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

  useEffect(() => {
    if (!isAuthed() || sessions.length === 0) return
    let cancelled = false
    setDetailsLoading(true)
    Promise.allSettled(sessions.map(s => getSession(s.id)))
      .then(outcomes => {
        if (cancelled) return
        const map = {}
        outcomes.forEach((o, i) => {
          if (o.status === 'fulfilled') map[sessions[i].id] = o.value?.result
        })
        setDetails(map)
      })
      .finally(() => { if (!cancelled) setDetailsLoading(false) })
    return () => { cancelled = true }
  }, [sessions])

  // Sessions come back newest-first; take the N most recent, then reverse so
  // the chart reads oldest -> newest, left to right.
  const chronological = useMemo(() => {
    const n = windowSize === 'all' ? sessions.length : windowSize
    return [...sessions].slice(0, n).reverse()
  }, [sessions, windowSize])

  // One point per session in the window. value is null (gap in the line) when
  // that session has no data for the selected zone (or 0 shots overall).
  const points = useMemo(() => {
    return chronological.map(s => {
      if (zone === 'overall') {
        const attempts = Number(s.total_shots) || 0
        return attempts > 0
          ? { session: s, value: s.accuracy_pct, made: s.made, attempts }
          : { session: s, value: null, made: null, attempts: null }
      }
      const zones = details[s.id]?.zone_aggregates
      const entry = Array.isArray(zones) ? zones.find(z => z?.polygon_id === zone) : null
      return entry && entry.attempts > 0
        ? { session: s, value: entry.accuracy_pct, made: entry.made, attempts: entry.attempts }
        : { session: s, value: null, made: null, attempts: null }
    })
  }, [chronological, zone, details])

  const n = points.length
  const coords = points.map((p, i) => ({ ...p, x: xAt(i, n), y: p.value == null ? null : yAt(p.value) }))

  // Contiguous runs of non-null points -> one polyline/area per run, so a
  // session with no data for the selected zone breaks the line cleanly.
  const segments = []
  let run = []
  coords.forEach(c => {
    if (c.value == null) { if (run.length) segments.push(run); run = [] }
    else run.push(c)
  })
  if (run.length) segments.push(run)

  const hasAnyData = coords.some(c => c.value != null)
  const ticks = pickTicks(n)
  const active = activeIdx != null ? coords[activeIdx] : null

  // Coaching Patterns — aggregated across every fetched session regardless of
  // the chart's window/zone filters (feedback isn't zone-scoped on the
  // backend, and "recurring patterns" should mean the whole history).
  const feedbackResults = useMemo(
    () => sessions.map(s => details[s.id]).filter(Boolean),
    [sessions, details],
  )
  const topInsights = useMemo(() => topFeedback(feedbackResults, 'insights', 2), [feedbackResults])
  const topRecommendations = useMemo(
    () => topFeedback(feedbackResults, 'recommendations', 2),
    [feedbackResults],
  )

  return (
    <div className="screen-enter">
      <div className="top-bar">
        <Logo onClick={() => navigate('dashboard')} />
        <div className="top-actions"><div className="avatar" /></div>
      </div>

      <h1 className="page-title">Progress</h1>

      {!isAuthed() && (
        <p className="dashboard-hint">Log in to track your accuracy over time.</p>
      )}

      {isAuthed() && loading && (
        <p className="dashboard-hint">Loading sessions…</p>
      )}

      {isAuthed() && !loading && error && (
        <p className="dashboard-hint">Progress data isn't available right now.</p>
      )}

      {isAuthed() && !loading && !error && sessions.length === 0 && (
        <p className="dashboard-hint">
          No sessions yet — complete a shooting session to start tracking your progress.
        </p>
      )}

      {isAuthed() && !loading && !error && sessions.length > 0 && (
        <>
          <div className="filter-bar">
            <span className={`filter-select-wrap${windowSize !== 10 ? ' active' : ''}`}>
              <select
                className="filter-select"
                aria-label="Session window"
                value={windowSize}
                onChange={e => {
                  const v = e.target.value
                  setWindowSize(v === 'all' ? 'all' : Number(v))
                  setActiveIdx(null)
                }}
              >
                {WINDOW_OPTIONS.map(opt => (
                  <option key={opt.id} value={opt.id}>{opt.label}</option>
                ))}
              </select>
            </span>

            <span className={`filter-select-wrap${zone !== 'overall' ? ' active' : ''}`}>
              <select
                className="filter-select"
                aria-label="Court zone"
                value={zone}
                onChange={e => { setZone(e.target.value); setActiveIdx(null) }}
              >
                {ZONE_OPTIONS.map(opt => (
                  <option key={opt.id} value={opt.id}>{opt.label}</option>
                ))}
              </select>
            </span>
          </div>

          {zone !== 'overall' && detailsLoading && (
            <p className="dashboard-hint">Loading zone data…</p>
          )}

          <div className="progress-chart-card">
            <div className="progress-chart-plot" onClick={() => setActiveIdx(null)}>
              <svg
                className="progress-chart-svg"
                viewBox={`0 0 ${VB_W} ${VB_H}`}
                preserveAspectRatio="none"
                aria-hidden="true"
              >
                {/* Y gridlines + labels */}
                {[0, 25, 50, 75, 100].map(pct => (
                  <g key={pct}>
                    <line
                      x1={PAD.l} x2={VB_W - PAD.r} y1={yAt(pct)} y2={yAt(pct)}
                      stroke="rgba(255,255,255,0.08)" strokeWidth="0.6"
                    />
                    <text
                      x={PAD.l - 4} y={yAt(pct) + 2.5}
                      textAnchor="end" fontSize="7" fill="rgba(255,255,255,0.35)"
                    >
                      {pct}%
                    </text>
                  </g>
                ))}

                {/* X tick labels (sparse — full date lives in the tooltip) */}
                {ticks.map(i => {
                  const c = coords[i]
                  const anchor = i === 0 ? 'start' : i === n - 1 ? 'end' : 'middle'
                  return (
                    <text
                      key={i}
                      x={c.x} y={VB_H - 6}
                      textAnchor={anchor} fontSize="7" fill="rgba(255,255,255,0.35)"
                    >
                      {formatShortDate(c.session.created_at)}
                    </text>
                  )
                })}

                {/* Area fill + line per contiguous run of real data */}
                {segments.map((seg, si) => {
                  const linePts = seg.map(c => `${c.x},${c.y}`).join(' ')
                  const areaPts =
                    `${seg[0].x},${yAt(0)} ` + linePts + ` ${seg[seg.length - 1].x},${yAt(0)}`
                  return (
                    <g key={si}>
                      {seg.length > 1 && (
                        <polyline points={areaPts} fill="rgba(255,107,44,0.14)" stroke="none" />
                      )}
                      <polyline
                        points={linePts}
                        fill="none"
                        stroke="var(--orange)"
                        strokeWidth="2"
                        strokeLinejoin="round"
                        strokeLinecap="round"
                      />
                    </g>
                  )
                })}

                {/* Data points */}
                {coords.map((c, i) => c.value == null ? null : (
                  <circle
                    key={i}
                    className={`progress-dot${activeIdx === i ? ' active' : ''}`}
                    cx={c.x} cy={c.y} r={activeIdx === i ? 4 : 3}
                    fill={activeIdx === i ? '#fff' : 'var(--orange)'}
                    stroke="var(--bg-card)" strokeWidth="1.5"
                    onClick={e => { e.stopPropagation(); setActiveIdx(activeIdx === i ? null : i) }}
                    onMouseEnter={() => setActiveIdx(i)}
                  />
                ))}
              </svg>

              {active && (
                <div
                  className={`progress-tooltip${(active.y / VB_H) < 0.22 ? ' flip-below' : ''}`}
                  style={{ left: `${(active.x / VB_W) * 100}%`, top: `${(active.y / VB_H) * 100}%` }}
                >
                  <div className="progress-tooltip-date">{formatShortDate(active.session.created_at)}</div>
                  <div className="progress-tooltip-stat">
                    {active.made}/{active.attempts} · {Math.round(active.value)}%
                  </div>
                </div>
              )}
            </div>
          </div>

          {!hasAnyData && (
            <p className="dashboard-hint">
              No data for {ZONE_OPTIONS.find(z => z.id === zone)?.label.toLowerCase()} in the selected sessions.
            </p>
          )}

          <div className="section-title">Coaching Patterns</div>

          {detailsLoading && (
            <p className="dashboard-hint">Loading coaching patterns…</p>
          )}

          {!detailsLoading && (
            <div className="coaching-grid">
              <div className="coaching-card">
                <div className="coaching-card-title">Key Insights</div>
                {topInsights.length === 0 && (
                  <p className="coaching-empty">No recurring insights yet.</p>
                )}
                {topInsights.map((item, i) => (
                  <div className="coaching-item" key={i}>
                    <p className="coaching-item-text">{item.text}</p>
                    <span className="coaching-badge">
                      Seen in {item.count} session{item.count === 1 ? '' : 's'}
                    </span>
                  </div>
                ))}
              </div>

              <div className="coaching-card">
                <div className="coaching-card-title">Top Recommendations</div>
                {topRecommendations.length === 0 && (
                  <p className="coaching-empty">No recurring recommendations yet.</p>
                )}
                {topRecommendations.map((item, i) => (
                  <div className="coaching-item" key={i}>
                    <p className="coaching-item-text">{item.text}</p>
                    <span className="coaching-badge">
                      Seen in {item.count} session{item.count === 1 ? '' : 's'}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </>
      )}

      <BottomNav active="progress" navigate={navigate} />
    </div>
  )
}
