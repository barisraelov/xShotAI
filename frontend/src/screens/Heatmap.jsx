import Logo from '../components/Logo'
import CourtMap from '../components/CourtMap'
import ZoneGrid from '../components/ZoneGrid'
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

  const { summary, shot_points, zone_aggregates } = result
  const plottable = shot_points.filter(s => s.origin?.court !== null).length

  return (
    <div className="screen-enter">
      <div className="top-bar">
        <Logo />
        <button className="icon-btn" onClick={() => navigate('session')}>←</button>
      </div>

      <div className="heatmap-topline">
        <div className="pill">
          <b>{summary.made}</b> made · <b>{summary.total_shots}</b> attempts
        </div>
        <div className="pill" style={{ fontSize: '0.78rem' }}>
          {plottable} plotted
        </div>
      </div>

      <CourtMap shotPoints={shot_points} />

      <div className="heatmap-legend">
        <span className="legend-dot dot-made" /> Made
        <span className="legend-dot dot-missed" style={{ marginLeft: '16px' }} /> Missed
      </div>

      <div className="section-title">Zones</div>
      <ZoneGrid zoneAggregates={zone_aggregates} />

      <BottomNav active="heatmap" navigate={navigate} />
    </div>
  )
}
