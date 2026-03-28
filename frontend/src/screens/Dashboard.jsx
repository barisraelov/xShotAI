import BottomNav from '../components/BottomNav'
import './Dashboard.css'

export default function Dashboard({ navigate, result }) {
  const summary = result?.summary ?? null

  return (
    <div className="screen-enter">
      <div className="top-bar">
        <div className="logo"><span className="logo-icon">🏀</span> xShot AI</div>
        <div className="top-actions">
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

      {!summary && (
        <p className="dashboard-hint">Upload a video to see your shot analysis here.</p>
      )}

      <BottomNav active="dashboard" navigate={navigate} />
    </div>
  )
}
