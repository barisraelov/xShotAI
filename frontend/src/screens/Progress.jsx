import BottomNav from '../components/BottomNav'
import Logo from '../components/Logo'

export default function Progress({ navigate }) {
  return (
    <div className="screen-enter">
      <div className="top-bar">
        <Logo />
        <div className="top-actions"><div className="avatar" /></div>
      </div>

      <div style={{ padding: '40px 20px', textAlign: 'center' }}>
        <div style={{ fontSize: '2.5rem', marginBottom: '16px' }}>📈</div>
        <div style={{ fontWeight: 700, fontSize: '1.1rem', marginBottom: '8px' }}>Progress tracking</div>
        <div style={{ color: 'var(--text-muted)', fontSize: '0.9rem', lineHeight: 1.6 }}>
          Cross-session trends will appear here after you complete multiple sessions.
        </div>
      </div>

      <BottomNav active="progress" navigate={navigate} />
    </div>
  )
}
