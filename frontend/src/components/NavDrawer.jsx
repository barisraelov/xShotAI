import { useEffect } from 'react'
import './NavDrawer.css'

const LINKS = [
  { view: 'dashboard',  icon: '🏠', label: 'Dashboard' },
  { view: 'statistics', icon: '📊', label: 'Statistics' },
  { view: 'progress',   icon: '📈', label: 'Progress' },
  { view: 'profile',    icon: '👤', label: 'Profile' },
]

/**
 * Slide-out navigation drawer + dim backdrop.
 *
 * Controlled by `open` / `onClose`. Closes on backdrop click, the ✕ button, or
 * the Escape key. `user` is `{ username, email }` (may be null while loading);
 * `levelInfo` comes from utils/levels.getLevelInfo.
 */
export default function NavDrawer({
  open,
  onClose,
  navigate,
  activeView,
  user,
  levelInfo,
  onLogout,
}) {
  useEffect(() => {
    if (!open) return undefined
    function onKey(e) {
      if (e.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    const prevOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.removeEventListener('keydown', onKey)
      document.body.style.overflow = prevOverflow
    }
  }, [open, onClose])

  function go(view) {
    onClose()
    navigate(view)
  }

  return (
    <div className={`nav-drawer-root${open ? ' is-open' : ''}`} aria-hidden={!open}>
      <div className="nav-drawer-backdrop" onClick={onClose} />

      <aside
        className="nav-drawer"
        role="dialog"
        aria-modal="true"
        aria-label="Main menu"
      >
        <div className="nav-drawer-head">
          <button
            type="button"
            className="nav-drawer-close"
            onClick={onClose}
            aria-label="Close menu"
          >
            ✕
          </button>

          <div className="nav-drawer-user">
            <div className="nav-drawer-avatar" aria-hidden="true">
              {(user?.username?.[0] || '?').toUpperCase()}
            </div>
            <div className="nav-drawer-id">
              <span className="nav-drawer-username">
                {user?.username || 'Signed in'}
              </span>
              <span className="nav-drawer-email">{user?.email || ''}</span>
            </div>
          </div>

          {levelInfo && (
            <div className="nav-drawer-tier">
              <span className="nav-drawer-lvl">LVL {levelInfo.level}</span>
              <span className="nav-drawer-title">{levelInfo.title}</span>
            </div>
          )}
        </div>

        <nav className="nav-drawer-links">
          {LINKS.map(l => (
            <button
              key={l.view}
              type="button"
              className={`nav-drawer-link${activeView === l.view ? ' is-active' : ''}`}
              onClick={() => go(l.view)}
            >
              <span className="nav-drawer-link-icon" aria-hidden="true">{l.icon}</span>
              {l.label}
            </button>
          ))}
        </nav>

        {onLogout && (
          <div className="nav-drawer-foot">
            <button
              type="button"
              className="nav-drawer-logout"
              onClick={() => {
                onClose()
                onLogout()
              }}
            >
              Log out
            </button>
          </div>
        )}
      </aside>
    </div>
  )
}
