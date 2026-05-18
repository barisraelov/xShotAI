import BottomNav from '../components/BottomNav'
import Logo from '../components/Logo'
import './Session.css'

// Find the zone with the most attempts and lowest accuracy to produce a tip
function weakestZone(zoneAggregates) {
  if (!zoneAggregates?.length) return null
  const withAttempts = zoneAggregates.filter(z => z.attempts > 0)
  if (!withAttempts.length) return null
  return [...withAttempts].sort(
    (a, b) => a.accuracy_pct - b.accuracy_pct || b.attempts - a.attempts
  )[0]
}

export default function Session({ navigate, result }) {
  if (!result) {
    return (
      <div className="screen-enter">
        <div style={{ padding: '40px 20px', color: 'var(--text-muted)' }}>No session data.</div>
        <BottomNav active="dashboard" navigate={navigate} />
      </div>
    )
  }

  const { summary, zone_aggregates, shot_points, feedback } = result
  const weak = weakestZone(zone_aggregates)
  const accuracyDeg = `${(summary.accuracy_pct / 100 * 360).toFixed(1)}deg`
  const hasCourtData = shot_points?.some(s => s.origin?.court !== null)

  const fbSummary = feedback?.summary
  const fbInsights = Array.isArray(feedback?.insights) ? feedback.insights : []
  const fbRecs = Array.isArray(feedback?.recommendations) ? feedback.recommendations : []
  const showFeedback =
    feedback &&
    (fbSummary?.headline ||
      fbSummary?.body ||
      fbInsights.length > 0 ||
      fbRecs.length > 0)

  return (
    <div className="screen-enter">
      <div className="top-bar">
        <Logo />
        <button className="icon-btn" onClick={() => navigate('dashboard')}>☰</button>
      </div>

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

      {weak && (
        <div className="tip-box">
          💡 <strong>Tip:</strong> Work on your <strong>{weak.label}</strong> shots —
          currently at {weak.accuracy_pct.toFixed(0)}% ({weak.made}/{weak.attempts} made).
        </div>
      )}

      {showFeedback && (
        <section className="feedback-section" aria-label="Session feedback">
          <div className="section-title">Feedback</div>
          {(fbSummary?.headline || fbSummary?.body) && (
            <div className="feedback-card feedback-card--summary">
              {fbSummary?.headline && (
                <div className="feedback-headline">{fbSummary.headline}</div>
              )}
              {fbSummary?.body && <p className="feedback-body">{fbSummary.body}</p>}
            </div>
          )}
          {fbInsights.length > 0 && (
            <>
              <div className="section-title">Insights</div>
              <div className="feedback-card">
                <ul className="feedback-list">
                  {fbInsights.map((line, i) => (
                    <li key={i}>{line}</li>
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
                    <li key={i}>{line}</li>
                  ))}
                </ul>
              </div>
            </>
          )}
        </section>
      )}

      {hasCourtData && (
        <div style={{ display: 'flex', gap: '10px', padding: '0 20px 24px', flexWrap: 'wrap' }}>
          <button className="btn" onClick={() => navigate('heatmap')} style={{ flex: 1 }}>
            🔥 Shot map
          </button>
        </div>
      )}

      <BottomNav active="session" navigate={navigate} />
    </div>
  )
}
