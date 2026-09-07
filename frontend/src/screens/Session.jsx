import { useState } from 'react'
import Logo from '../components/Logo'
import CourtMap from '../components/CourtMap'
import VisualFeedback, { VisualSessionSummary } from '../components/VisualFeedback'
import { updateSessionDate } from '../api'
import './Session.css'

const MONTHS_SHORT = [
  'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
  'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
]

// UTC ISO -> local YYYY-MM-DD (for <input type="date"> and its max).
function isoToDayKey(iso) {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

// "6 Sep 2026 · 10:52 PM" — day-first, engine-independent month name.
function formatSessionDate(iso) {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  const date = `${d.getDate()} ${MONTHS_SHORT[d.getMonth()]} ${d.getFullYear()}`
  const time = d.toLocaleTimeString(undefined, {
    hour: '2-digit', minute: '2-digit',
  })
  return `${date} · ${time}`
}

// UTC ISO -> local "HH:MM" (for <input type="time">).
function isoToTimeKey(iso) {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  const hh = String(d.getHours()).padStart(2, '0')
  const mm = String(d.getMinutes()).padStart(2, '0')
  return `${hh}:${mm}`
}

// Combine a local day ("YYYY-MM-DD") + local time ("HH:MM") into a UTC ISO
// timestamp, so the exact local hour/minute the user picked is what gets stored.
function combineDayTime(dayKey, timeKey) {
  const [y, m, d] = dayKey.split('-').map(Number)
  const [hh, mm] = (timeKey || '00:00').split(':').map(Number)
  const local = new Date(y, m - 1, d, hh || 0, mm || 0, 0, 0)
  return Number.isNaN(local.getTime()) ? null : local.toISOString()
}

/** Inline "edit session date & time" control shown in the Session header. */
function SessionDateEditor({ sessionId, sessionDate, onSaved }) {
  const todayKey = isoToDayKey(new Date().toISOString())

  const [displayIso, setDisplayIso] = useState(sessionDate)
  const [editing, setEditing] = useState(false)
  const [draftDay, setDraftDay] = useState(isoToDayKey(sessionDate))
  const [draftTime, setDraftTime] = useState(isoToTimeKey(sessionDate))
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)

  function startEdit() {
    setDraftDay(isoToDayKey(displayIso))
    setDraftTime(isoToTimeKey(displayIso))
    setError(null)
    setEditing(true)
  }
  function cancel() {
    setEditing(false)
    setError(null)
  }

  async function save() {
    if (saving) return
    if (!draftDay) {
      setError('Please pick a date.')
      return
    }
    if (!draftTime) {
      setError('Please pick a time.')
      return
    }
    const newIso = combineDayTime(draftDay, draftTime)
    if (!newIso) {
      setError('That date and time are not valid.')
      return
    }
    if (new Date(newIso).getTime() > Date.now()) {
      setError('Session date and time cannot be in the future.')
      return
    }
    setSaving(true)
    setError(null)
    try {
      const updated = await updateSessionDate(sessionId, newIso)
      const savedIso = updated?.created_at || newIso
      setDisplayIso(savedIso)
      setEditing(false)
      onSaved?.(savedIso)
    } catch (err) {
      setError('Failed to update date. Please try again.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="session-date-row">
      {editing ? (
        <div className="session-date-edit">
          <input
            type="date"
            className="session-date-input"
            lang="en-GB"
            value={draftDay}
            max={todayKey}
            onChange={e => setDraftDay(e.target.value)}
            disabled={saving}
            aria-label="Session date"
          />
          <input
            type="time"
            className="session-time-input"
            value={draftTime}
            onChange={e => setDraftTime(e.target.value)}
            disabled={saving}
            aria-label="Session time"
          />
          <button
            type="button"
            className="btn btn-primary session-date-save"
            onClick={save}
            disabled={saving}
          >
            {saving ? <span className="session-date-spinner" aria-hidden="true" /> : 'Save'}
          </button>
          <button
            type="button"
            className="session-date-cancel"
            onClick={cancel}
            disabled={saving}
          >
            Cancel
          </button>
        </div>
      ) : (
        <>
          <span className="session-date-value">{formatSessionDate(displayIso)}</span>
          <button
            type="button"
            className="session-date-edit-btn"
            onClick={startEdit}
            aria-label="Edit session date and time"
            title="Edit session date and time"
          >
            ✏️
          </button>
        </>
      )}
      {error && <span className="session-date-error" role="alert">{error}</span>}
    </div>
  )
}

// Find the zone with the most attempts and lowest accuracy to produce a tip
function weakestZone(zoneAggregates) {
  if (!zoneAggregates?.length) return null
  const withAttempts = zoneAggregates.filter(z => z.attempts > 0)
  if (!withAttempts.length) return null
  return [...withAttempts].sort(
    (a, b) => a.accuracy_pct - b.accuracy_pct || b.attempts - a.attempts
  )[0]
}

// Shared category labels so an Insight and the Recommendation it drives carry
// the same badge + colour (Evidence → Insight → Recommendation).
const FB_CATEGORIES = {
  consistency: 'Consistency',
  fatigue: 'Fatigue',
  timing: 'Timing',
  sequence: 'Sequence',
  arc: 'Arc',
  accuracy: 'Accuracy',
}

function feedbackCategory(text) {
  const t = String(text).toLowerCase()
  if (t.includes('target arc') || t.includes('consistent') || t.includes('varied') || t.includes('stable'))
    return 'consistency'
  if (t.includes('second half') || t.includes('later in the session') || t.includes('lift') ||
      t.includes('flatten') || t.includes('breather') || t.includes('energy') ||
      t.includes('hydration') || t.includes('fatigue'))
    return 'fatigue'
  if (t.includes('rhythm') || t.includes('release timing') || t.includes('slow the motion') ||
      t.includes('footwork') || t.includes('timing'))
    return 'timing'
  if (t.includes('streak') || t.includes('finished hot') || t.includes('cold finish') ||
      t.includes('consecutive') || t.includes('reset') || t.includes('misses'))
    return 'sequence'
  if (t.includes('higher arc') || t.includes('did not clearly') || t.includes('arc'))
    return 'arc'
  if (t.includes('accuracy') || t.includes('makes') || t.includes('fundamentals') ||
      t.includes('high-percentage') || t.includes('volume'))
    return 'accuracy'
  return null
}

function CategoryBadge({ cat }) {
  if (!cat) return null
  return <span className={`fb-cat fb-cat--${cat}`}>{FB_CATEGORIES[cat]}</span>
}

function TopTakeaways({ insights }) {
  if (!insights.length) return null
  return (
    <section className="feedback-story-section">
      <div className="story-kicker">Key takeaways</div>
      <h3 className="story-title">What stood out most</h3>
      <div className="takeaway-list">
        {insights.slice(0, 3).map((line, i) => (
          <div className="takeaway-card" key={i}>
            <span className="takeaway-num">{i + 1}</span>
            <p>
              <CategoryBadge cat={feedbackCategory(line)} />
              {line}
            </p>
          </div>
        ))}
      </div>
    </section>
  )
}

function FeedbackPanel({ title, subtitle, children, defaultOpen = true }) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <section className="feedback-panel">
      <button
        type="button"
        className="feedback-panel-toggle"
        onClick={() => setOpen(v => !v)}
        aria-expanded={open}
      >
        <span>
          <span className="story-kicker">{subtitle}</span>
          <span className="feedback-panel-title">{title}</span>
        </span>
        <span className={`panel-chevron${open ? ' is-open' : ''}`}>⌄</span>
      </button>
      {open && <div className="feedback-panel-body">{children}</div>}
    </section>
  )
}

// Derive 2pt / 3pt stats directly from shot_points zone data
function zoneBreakdown(shotPoints) {
  if (!shotPoints?.some(s => s.zone)) return null
  const twos   = shotPoints.filter(s => s.zone?.range_class === 'two_point')
  const threes = shotPoints.filter(s => s.zone?.range_class === 'three_point')
  const calc   = arr => ({
    attempts: arr.length,
    made:     arr.filter(s => s.result === 'made').length,
  })
  return { twos: calc(twos), threes: calc(threes) }
}

export default function Session({
  navigate,
  result,
  liveDiagnostics,
  sessionId,
  sessionDate,
  onSessionDateChange,
}) {
  if (!result) {
    return (
      <div className="screen-enter">
        <div style={{ padding: '40px 20px', color: 'var(--text-muted)' }}>No session data.</div>
      </div>
    )
  }

  const { summary, zone_aggregates, shot_points, feedback } = result
  const weak         = weakestZone(zone_aggregates)
  const breakdown    = zoneBreakdown(shot_points)
  const accuracyDeg  = `${(summary.accuracy_pct / 100 * 360).toFixed(1)}deg`
  const hasCourtData = shot_points?.some(s => s.origin?.court !== null)

  const fbSummary  = feedback?.summary
  const fbInsights = Array.isArray(feedback?.insights) ? feedback.insights : []
  const fbRecs     = Array.isArray(feedback?.recommendations) ? feedback.recommendations : []
  const showFeedback =
    feedback &&
    (fbSummary?.headline ||
      fbSummary?.body ||
      fbInsights.length > 0 ||
      fbRecs.length > 0)

  return (
    <div className="screen-enter">
      <div className="top-bar">
        <Logo onClick={() => navigate('dashboard')} />
      </div>

      {sessionId && sessionDate && (
        <SessionDateEditor
          sessionId={sessionId}
          sessionDate={sessionDate}
          onSaved={onSessionDateChange}
        />
      )}

      <section className="session-summary-section" aria-label="Session summary">
        <div className="story-kicker">Session summary</div>
        <h2 className="story-title">You completed a shooting session.</h2>

        <div className="stats-hero">
          <div>
            <div className="big">{summary.total_shots}</div>
            <div className="lbl">Shots</div>
          </div>
          <div>
            <div className="big" style={{ color: 'var(--green)' }}>{summary.made}</div>
            <div className="lbl">Made</div>
          </div>
          <div>
            <div className="big" style={{ color: 'var(--red)' }}>{summary.missed}</div>
            <div className="lbl">Missed</div>
          </div>
        </div>

        <div className="accuracy-row">
          <div className="accuracy-ring-wrap">
            <div
              className="accuracy-ring-big"
              style={{ '--accuracy-deg': accuracyDeg }}
            />
            <span className="accuracy-pct">{summary.accuracy_pct.toFixed(0)}%</span>
          </div>
          <div className="accuracy-label">Accuracy</div>
        </div>

        {showFeedback && (fbSummary?.headline || fbSummary?.body) && (
          <div className="feedback-card feedback-card--summary">
            {fbSummary?.headline && (
              <div className="feedback-headline">{fbSummary.headline}</div>
            )}
            {fbSummary?.body && <p className="feedback-body">{fbSummary.body}</p>}
          </div>
        )}

        <VisualSessionSummary result={result} />

        {/* Zone-level chart only — individual shot markers are omitted here
            until court-mapped shot coordinates are more reliable. */}
        <section className="court-chart-section" aria-label="Shot chart">
          <div className="court-chart-title">Shot chart</div>
          <CourtMap zoneAggregates={zone_aggregates} />
        </section>

        {weak && (
          <div className="tip-box">
            💡 <strong>Tip:</strong> Work on your <strong>{weak.label}</strong> shots —
            currently at {weak.accuracy_pct.toFixed(0)}% ({weak.made}/{weak.attempts} made).
          </div>
        )}

        {breakdown && (
          <div className="zone-breakdown">
            <div className="zone-breakdown-title">Shot breakdown</div>
            <div className="zone-breakdown-row">
              <div className="zone-card">
                <div className="zone-card-label">2-point</div>
                <div className="zone-card-stat">
                  {breakdown.twos.made}<span className="zone-card-denom">/{breakdown.twos.attempts}</span>
                </div>
                <div className="zone-card-pct">
                  {breakdown.twos.attempts > 0
                    ? `${Math.round(breakdown.twos.made / breakdown.twos.attempts * 100)}%`
                    : '—'}
                </div>
              </div>
              <div className="zone-card">
                <div className="zone-card-label">3-point</div>
                <div className="zone-card-stat">
                  {breakdown.threes.made}<span className="zone-card-denom">/{breakdown.threes.attempts}</span>
                </div>
                <div className="zone-card-pct">
                  {breakdown.threes.attempts > 0
                    ? `${Math.round(breakdown.threes.made / breakdown.threes.attempts * 100)}%`
                    : '—'}
                </div>
              </div>
            </div>
          </div>
        )}
      </section>

      {liveDiagnostics && (
        <section className="live-diag" aria-label="Live diagnostics">
          <div className="story-kicker">Live diagnostics</div>
          <h3 className="story-title">Session counters</h3>
          <dl className="live-diag-grid">
            <div><dt>start_path</dt><dd>{String(liveDiagnostics.start_path ?? '—')}</dd></div>
            <div><dt>generation</dt><dd>{liveDiagnostics.generation ?? '—'}</dd></div>
            <div><dt>session_s</dt><dd>{liveDiagnostics.session_s ?? '—'}</dd></div>
            <div><dt>frames_received</dt><dd>{liveDiagnostics.frames_received ?? 0}</dd></div>
            <div><dt>frames_decoded</dt><dd>{liveDiagnostics.frames_decoded ?? 0}</dd></div>
            <div><dt>frames_processed</dt><dd>{liveDiagnostics.frames_processed ?? 0}</dd></div>
            <div><dt>frames_dropped_queue</dt><dd>{liveDiagnostics.frames_dropped_queue ?? 0}</dd></div>
            <div><dt>frames_rejected_invalid</dt><dd>{liveDiagnostics.frames_rejected_invalid ?? 0}</dd></div>
            <div><dt>ball_detections</dt><dd>{liveDiagnostics.ball_detections ?? 0}</dd></div>
            <div><dt>hoop_detections</dt><dd>{liveDiagnostics.hoop_detections ?? 0}</dd></div>
            <div><dt>person_detections</dt><dd>{liveDiagnostics.person_detections ?? 0}</dd></div>
            <div><dt>shots_started</dt><dd>{liveDiagnostics.shots_started ?? 0}</dd></div>
            <div><dt>shots_decided_make</dt><dd>{liveDiagnostics.shots_decided_make ?? 0}</dd></div>
            <div><dt>shots_decided_miss</dt><dd>{liveDiagnostics.shots_decided_miss ?? 0}</dd></div>
            <div><dt>reconnect_count</dt><dd>{liveDiagnostics.reconnect_count ?? 0}</dd></div>
            <div><dt>inference ball_hoop</dt><dd>{liveDiagnostics.inference_calls?.ball_hoop ?? 0}</dd></div>
            <div><dt>inference contact</dt><dd>{liveDiagnostics.inference_calls?.contact ?? 0}</dd></div>
            <div><dt>avg_latency_ms</dt><dd>{liveDiagnostics.average_latency ?? '—'}</dd></div>
            <div><dt>p95_latency_ms</dt><dd>{liveDiagnostics.p95_latency ?? '—'}</dd></div>
            <div><dt>max_latency_ms</dt><dd>{liveDiagnostics.max_latency ?? '—'}</dd></div>
          </dl>
          {liveDiagnostics.state_transitions && Object.keys(liveDiagnostics.state_transitions).length > 0 && (
            <p className="live-diag-transitions">
              state_transitions:{' '}
              {Object.entries(liveDiagnostics.state_transitions).map(([k, v]) => `${k}×${v}`).join(', ')}
            </p>
          )}
        </section>
      )}

      {showFeedback && (
        <section className="feedback-section" aria-label="Session feedback">
          <TopTakeaways insights={fbInsights} />

          <FeedbackPanel
            title="Visual Analysis"
            subtitle="Visual evidence"
            defaultOpen
          >
            <p className="vf-intro">The charts below show why the top takeaways were generated.</p>
            <VisualFeedback result={result} />
          </FeedbackPanel>

          <FeedbackPanel
            title="Detailed Coaching"
            subtitle="Full coaching notes"
            defaultOpen
          >
            {fbInsights.length > 0 && (
              <>
                <div className="section-title">Insights</div>
                <div className="feedback-card">
                  <ul className="feedback-list">
                    {fbInsights.map((line, i) => (
                      <li key={i}>
                        <CategoryBadge cat={feedbackCategory(line)} />
                        {line}
                      </li>
                    ))}
                  </ul>
                </div>
              </>
            )}
            {fbRecs.length > 0 && (
              <>
                <div className="section-title">Recommendations</div>
                <div className="feedback-card">
                  <ul className="feedback-list">
                    {fbRecs.map((line, i) => (
                      <li key={i}>
                        <CategoryBadge cat={feedbackCategory(line)} />
                        {line}
                      </li>
                    ))}
                  </ul>
                </div>
              </>
            )}
          </FeedbackPanel>
        </section>
      )}

      {hasCourtData && (
        <div style={{ display: 'flex', gap: '10px', padding: '0 20px 24px', flexWrap: 'wrap' }}>
          <button className="btn" onClick={() => navigate('heatmap')} style={{ flex: 1 }}>
            🔥 Shot map
          </button>
        </div>
      )}

    </div>
  )
}
