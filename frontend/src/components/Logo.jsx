import markUrl from '../assets/xshot-mark.svg'

/**
 * Brand mark. Pass `onClick` (typically `() => navigate('dashboard')`) to make
 * it a clickable "go home" link — renders as a <button> with cursor:pointer.
 * Omit it for a plain, non-interactive mark.
 */
export default function Logo({ onClick }) {
  const content = (
    <>
      <img src={markUrl} alt="" className="logo-mark" width={32} height={32} decoding="async" />
      <span className="logo-wordmark">
        <span className="logo-name">xShot</span>
        <span className="logo-suffix">AI</span>
      </span>
    </>
  )

  if (onClick) {
    return (
      <button type="button" className="logo logo-link" onClick={onClick} aria-label="Go to dashboard">
        {content}
      </button>
    )
  }

  return (
    <div className="logo" aria-label="xShot AI">
      {content}
    </div>
  )
}
