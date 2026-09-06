import Logo from '../components/Logo'
import CourtMap from '../components/CourtMap'
import BottomNav from '../components/BottomNav'
import './Heatmap.css'

export default function Heatmap({ navigate, result }) {
  if (!result) {
    return (
      <div className="screen-enter">
        <div style={{ padding: '40px 20px', color: 'var(--text-muted)' }}>No analysis data.</div>
        <BottomNav active="heatmap" navigate={navigate} />
      </div>
    )
  }

  const { summary, zone_aggregates } = result

  return (
    <div className="screen-enter">
      <div className="top-bar">
        <Logo onClick={() => navigate('dashboard')} />
        <button className="icon-btn" onClick={() => navigate('session')}>←</button>
      </div>

      <div className="heatmap-topline">
        <div className="pill">
          <b>{summary.made}</b> made · <b>{summary.total_shots}</b> attempts · <b>{summary.accuracy_pct.toFixed(0)}%</b>
        </div>
      </div>

      <CourtMap zoneAggregates={zone_aggregates} />

      <div className="heatmap-legend">
        <span className="legend-swatch" style={{ background: 'rgba(52,211,153,0.5)' }} /> ≥60%
        <span className="legend-swatch" style={{ background: 'rgba(251,191,36,0.5)', marginLeft: 12 }} /> 35–59%
        <span className="legend-swatch" style={{ background: 'rgba(248,113,113,0.5)', marginLeft: 12 }} /> &lt;35%
      </div>

      <BottomNav active="heatmap" navigate={navigate} />
    </div>
  )
}
