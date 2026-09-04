import './CourtMap.css'

// The 10 mappable zones from the backend's 11-zone taxonomy (all but the
// "unknown" fallback, which has no natural court position and is simply not
// drawn — see xShot-prototype/analyze_result_spec.md).
//
// Positions approximate real court geometry (extended > three-point > mid-range
// as distance from the hoop at svg (50,52) shrinks; left/right split by svgCx)
// using simple rectangular bands rather than the true curved 3pt arc, so the
// fills stay easy to reason about — the actual arc/paint/backboard remain
// exactly as drawn in the "Court lines on top" block below. Draw order matters:
// corners are listed last so they paint over the small edge of the mid-wing
// bands they visually take priority over (see ZONE_PATHS).
const ZONES = [
  { id: 'extended',           svgCx: 50, svgCy: 9.5 },
  { id: 'three_left_wing',    svgCx: 19, svgCy: 21 },
  { id: 'three_top_key',      svgCx: 50, svgCy: 21 },
  { id: 'three_right_wing',   svgCx: 81, svgCy: 21 },
  { id: 'mid_left_wing',      svgCx: 19, svgCy: 35.5 },
  { id: 'mid_center',         svgCx: 50, svgCy: 35.5 },
  { id: 'mid_right_wing',     svgCx: 81, svgCy: 35.5 },
  { id: 'mid_baseline',       svgCx: 50, svgCy: 50 },
  { id: 'three_left_corner',  svgCx: 10, svgCy: 45 },
  { id: 'three_right_corner', svgCx: 90, svgCy: 45 },
]

// Zone fill paths (viewBox "0 0 100 60", hoop at cx=50 cy=52, court box x:4-96 y:4-56).
const ZONE_PATHS = {
  extended:           'M 4 4  L 96 4  L 96 15 L 4 15  Z',
  three_left_wing:    'M 4 15 L 34 15 L 34 27 L 4 27  Z',
  three_top_key:      'M 34 15 L 66 15 L 66 27 L 34 27 Z',
  three_right_wing:   'M 66 15 L 96 15 L 96 27 L 66 27 Z',
  mid_left_wing:       'M 4 27 L 34 27 L 34 44 L 4 44  Z',
  mid_center:          'M 34 27 L 66 27 L 66 44 L 34 44 Z',
  mid_right_wing:      'M 66 27 L 96 27 L 96 44 L 66 44 Z',
  mid_baseline:        'M 16 44 L 84 44 L 84 56 L 16 56 Z',
  three_left_corner:   'M 4 34  L 16 34 L 16 56 L 4 56  Z',
  three_right_corner:  'M 96 34 L 84 34 L 84 56 L 96 56 Z',
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
            <text key={z.id} x={z.svgCx} y={z.svgCy + 1}
              textAnchor="middle" fontSize="3" fill="rgba(255,255,255,0.30)">
              —
            </text>
          )
          return (
            <g key={z.id}>
              <text x={z.svgCx} y={z.svgCy - 1.6}
                textAnchor="middle" fontSize="3" fontWeight="bold"
                fill="rgba(255,255,255,0.92)">
                {agg.accuracy_pct.toFixed(0)}%
              </text>
              <text x={z.svgCx} y={z.svgCy + 2.1}
                textAnchor="middle" fontSize="2.3"
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
