import Logo from '../components/Logo'
import './Placeholder.css'

/**
 * Generic "coming soon" screen for not-yet-built views (Profile, Terms,
 * Contact). `onBack` defaults to returning to the dashboard.
 */
export default function Placeholder({ navigate, title, blurb, icon = '🚧' }) {
  return (
    <div className="screen-enter">
      <div className="top-bar">
        <Logo onClick={() => navigate('dashboard')} />
      </div>

      <div className="placeholder-wrap">
        <div className="placeholder-card">
          <div className="placeholder-icon" aria-hidden="true">{icon}</div>
          <h1 className="placeholder-title">{title}</h1>
          <p className="placeholder-blurb">{blurb}</p>

          <div className="placeholder-skeleton" aria-hidden="true">
            <span /><span /><span />
          </div>

          <button
            type="button"
            className="btn btn-primary placeholder-back"
            onClick={() => navigate('dashboard')}
          >
            ← Back
          </button>
        </div>
      </div>
    </div>
  )
}
