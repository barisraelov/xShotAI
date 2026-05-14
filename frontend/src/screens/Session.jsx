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

export default function Session({ navigate, result }) {
  if (!result) {
    return (
      <div className="screen-enter">
        <div style={{ padding: '40px 20px', color: 'var(--text-muted)' }}>No session data.</div>
        <BottomNav active="dashboard" navigate={navigate} />
      </div>
    )
  }

  const { summary, zone_aggregates, shot_points } = result
  const weak         = weakestZone(zone_aggregates)
  const breakdown    = zoneBreakdown(shot_points)
  const accuracyDeg  = `${(summary.accuracy_pct / 100 * 360).toFixed(1)}deg`
  const hasCourtData = shot_points?.some(s => s.origin?.court !== null)

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

      {hasCourtData && (
        <div style={{ display: 'flex', gap: '10px', padding: '0 20px 24px', flexWrap: 'wrap' }}>
          <button className="btn" onClick={() => navigate('heatmap')} style={{ flex: 1 }}>
            Shot map
          </button>
        </div>
      )}

      <BottomNav active="session" navigate={navigate} />
    </div>
  )
}
