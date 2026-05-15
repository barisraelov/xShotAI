import './CourtMap.css'

/**
 * Maps normalized court coords (x: 0–1, y: 0–1 where y=0 is near hoop)
 * to CSS percentage positions within the court div.
 *
 * SVG viewBox is 100×60. Hoop sits at SVG y≈52; far end at SVG y≈4.
 * Court x spans SVG x=4 (left) to x=96 (right).
 */
function courtToCSS(x, y) {
  const cssLeft = 4 + x * 92           // maps 0→4%, 1→96% of viewBox width 100
  const cssvTop = 52 - y * 48          // maps y=0→SVG52, y=1→SVG4 (hoop at bottom)
  return {
    left: `${cssLeft}%`,
    top:  `${(cssvTop / 60) * 100}%`,
  }
}

export default function CourtMap({ shotPoints }) {
  const plottable = (shotPoints ?? []).filter(s => s.origin?.court !== null)

  return (
    <div className="court-container">
      <svg
        className="court-svg"
        viewBox="0 0 100 60"
        preserveAspectRatio="none"
        aria-hidden="true"
      >
        <defs>
          <linearGradient id="courtLine" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0" stopColor="rgba(255,255,255,0.22)" />
            <stop offset="1" stopColor="rgba(255,255,255,0.12)" />
          </linearGradient>
        </defs>
        {/* Outer boundary */}
        <rect x="4" y="4" width="92" height="52" rx="6"
          fill="none" stroke="url(#courtLine)" strokeWidth="0.8" />
        {/* Paint / 3-second area */}
        <rect x="34" y="30" width="32" height="22" rx="2.5"
          fill="none" stroke="rgba(255,255,255,0.14)" strokeWidth="0.8" />
        {/* Free throw arc */}
        <path d="M34 30 Q50 16 66 30"
          fill="none" stroke="rgba(255,255,255,0.14)" strokeWidth="0.8" />
        {/* Restricted area arc */}
        <path d="M42 52 Q50 44 58 52"
          fill="none" stroke="rgba(255,255,255,0.16)" strokeWidth="0.8" />
        {/* Backboard */}
        <rect x="47.5" y="50" width="5" height="0.8" rx="0.4"
          fill="rgba(255,255,255,0.22)" />
        {/* Hoop circle */}
        <circle cx="50" cy="52" r="1.6"
          fill="none" stroke="rgba(255,255,255,0.26)" strokeWidth="0.8" />
        {/* Three-point line: corners */}
        <path d="M16 56 V38" fill="none" stroke="rgba(255,255,255,0.10)" strokeWidth="0.8" />
        <path d="M84 56 V38" fill="none" stroke="rgba(255,255,255,0.10)" strokeWidth="0.8" />
        {/* Three-point arc */}
        <path d="M16 38 Q50 6 84 38"
          fill="none" stroke="rgba(255,255,255,0.10)" strokeWidth="0.8" />
      </svg>

      {plottable.map(shot => {
        const { x, y } = shot.origin.court
        const pos = courtToCSS(x, y)
        const made = shot.result === 'made'
        return (
          <span
            key={shot.shot_id}
            className={`shot-dot ${made ? 'dot-made' : 'dot-missed'}`}
            style={pos}
            title={`${shot.shot_id}: ${shot.result}${shot.zone ? ` · ${shot.zone.label}` : ''}`}
          />
        )
      })}
    </div>
  )
}
