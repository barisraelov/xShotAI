import './CourtMap.css'

// The backend's court_mapper.classify_zone() only ever produces these 4
// polygon ids (two_left/two_right/three_left/three_right) — NOT the 11-zone
// taxonomy in analyze_result_spec.md, which is aspirational/demo-only until
// zone_classifier.py exists. Keep this list matching the real classifier
// output so zone_aggregates from a live analysis actually lights up.
const ZONES = [
  { id: 'three_left',  svgCx: 22, svgCy: 24 },
  { id: 'three_right', svgCx: 78, svgCy: 24 },
  { id: 'two_left',    svgCx: 29, svgCy: 44 },
  { id: 'two_right',   svgCx: 71, svgCy: 44 },
]

// Zone fill paths (viewBox "0 0 100 60", hoop at cx=50 cy=52)
// Arc midpoint at t=0.5: (50, 22). Left half: Q33,22 → (50,22). Right half: Q67,22 → (84,38).
const ZONE_PATHS = {
  three_left:  'M 4 56 L 4 4 L 50 4 L 50 22 Q 33 22 16 38 L 16 56 Z',
  three_right: 'M 96 56 L 96 4 L 50 4 L 50 22 Q 67 22 84 38 L 84 56 Z',
  two_left:    'M 50 56 L 16 56 L 16 38 Q 33 22 50 22 Z',
  two_right:   'M 50 56 L 84 56 L 84 38 Q 67 22 50 22 Z',
}

function zoneColor(accuracy, attempts) {
  if (!attempts) return 'rgba(255,255,255,0.04)'
  if (accuracy >= 60) return 'rgba(52, 211, 153, 0.22)'
  if (accuracy >= 35) return 'rgba(251, 191, 36, 0.18)'
  return 'rgba(248, 113, 113, 0.20)'
}

// CourtCoord -> percentage position within .court-container (which stretches
// the 100x60 SVG viewBox to fill it via preserveAspectRatio="none", so a
// viewBox unit maps 1:1 to a container percentage point).
// x: 0 = left sideline -> 1 = right sideline, mapped onto the court rect (x 4..96).
// y: 0 = near the hoop (svg y=52) -> 1 = far end / half-court (svg y=4).
function courtPositionPct({ x, y }) {
  const left = 4 + Math.min(Math.max(x, 0), 1) * 92
  const top  = (52 - Math.min(Math.max(y, 0), 1) * 48) / 60 * 100
  return { left: `${left}%`, top: `${top}%` }
}

export default function CourtMap({ zoneAggregates, shotPoints }) {
  const byId = Object.fromEntries((zoneAggregates ?? []).map(z => [z.polygon_id, z]))
  const dots = (shotPoints ?? []).filter(s => s?.origin?.court)

  return (
    <div className="court-container">
      <svg
        className="court-svg"
        viewBox="0 0 100 60"
        preserveAspectRatio="none"
        aria-hidden="true"
      >
        {/* Zone fills */}
        {ZONES.map(z => {
          const agg = byId[z.id]
          return (
            <path key={z.id} d={ZONE_PATHS[z.id]}
              fill={zoneColor(agg?.accuracy_pct, agg?.attempts)} stroke="none">
              <title>{agg?.label ?? z.id}</title>
            </path>
          )
        })}

        {/* Court lines on top */}
        <rect x="4" y="4" width="92" height="52" rx="6"
          fill="none" stroke="rgba(255,255,255,0.20)" strokeWidth="0.8" />
        <line x1="50" y1="4" x2="50" y2="56"
          stroke="rgba(255,255,255,0.10)" strokeWidth="0.6" strokeDasharray="2,2" />
        <rect x="34" y="30" width="32" height="22" rx="2.5"
          fill="none" stroke="rgba(255,255,255,0.14)" strokeWidth="0.8" />
        <path d="M34 30 Q50 16 66 30"
          fill="none" stroke="rgba(255,255,255,0.14)" strokeWidth="0.8" />
        <path d="M42 52 Q50 44 58 52"
          fill="none" stroke="rgba(255,255,255,0.16)" strokeWidth="0.8" />
        <rect x="47.5" y="50" width="5" height="0.8" rx="0.4"
          fill="rgba(255,255,255,0.22)" />
        <circle cx="50" cy="52" r="1.6"
          fill="none" stroke="rgba(255,255,255,0.26)" strokeWidth="0.8" />
        <path d="M16 56 V38" fill="none" stroke="rgba(255,255,255,0.18)" strokeWidth="0.8" />
        <path d="M84 56 V38" fill="none" stroke="rgba(255,255,255,0.18)" strokeWidth="0.8" />
        <path d="M16 38 Q50 6 84 38"
          fill="none" stroke="rgba(255,255,255,0.18)" strokeWidth="0.8" />

        {/* Zone stats labels — percentage + made/attempts, e.g. "33%" / "1/3" */}
        {ZONES.map(z => {
          const agg = byId[z.id]
          if (!agg?.attempts) return (
            <text key={z.id} x={z.svgCx} y={z.svgCy}
              textAnchor="middle" fontSize="3.8" fill="rgba(255,255,255,0.30)">
              —
            </text>
          )
          return (
            <g key={z.id}>
              <text x={z.svgCx} y={z.svgCy - 2}
                textAnchor="middle" fontSize="4.2" fontWeight="bold"
                fill="rgba(255,255,255,0.90)">
                {agg.accuracy_pct.toFixed(0)}%
              </text>
              <text x={z.svgCx} y={z.svgCy + 3}
                textAnchor="middle" fontSize="3.2"
                fill="rgba(255,255,255,0.55)">
                {agg.made}/{agg.attempts}
              </text>
            </g>
          )
        })}
      </svg>

      {/* Individual shot markers — only for shots with a mapped court position. */}
      {dots.map((s, i) => (
        <div
          key={s.shot_id ?? i}
          className={`shot-dot ${s.result === 'made' ? 'dot-made' : 'dot-missed'}`}
          style={courtPositionPct(s.origin.court)}
          title={`${s.shot_id ?? `Shot ${i + 1}`} — ${s.result}`}
        />
      ))}
    </div>
  )
}
