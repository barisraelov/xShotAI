import './AppFooter.css'

/** Subtle persistent footer with placeholder Terms / Contact links. */
export default function AppFooter({ navigate }) {
  return (
    <footer className="app-footer">
      <button type="button" className="app-footer-link" onClick={() => navigate('terms')}>
        Terms &amp; Conditions
      </button>
      <span className="app-footer-dot" aria-hidden="true">·</span>
      <button type="button" className="app-footer-link" onClick={() => navigate('contact')}>
        Contact
      </button>
    </footer>
  )
}
