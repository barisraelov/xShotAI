export default function BottomNav({ active, navigate }) {
  return (
    <nav className="bottom-nav">
      <button
        className={active === 'dashboard' ? 'active' : ''}
        onClick={() => navigate('dashboard')}
      >
        🏠 Dashboard
      </button>
      <button
        className={active === 'heatmap' ? 'active' : ''}
        onClick={() => navigate('heatmap')}
      >
        🔥 Shot map
      </button>
      <button
        className={active === 'progress' ? 'active' : ''}
        onClick={() => navigate('progress')}
      >
        📈 Progress
      </button>
    </nav>
  )
}
