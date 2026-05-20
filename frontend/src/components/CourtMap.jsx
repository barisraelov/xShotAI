import './CourtMap.css'

const ZONES = [
  { id: 'three_left',  label: '3pt Left',  svgCx: 22, svgCy: 24 },
  { id: 'three_right', label: '3pt Right', svgCx: 78, svgCy: 24 },
  { id: 'two_left',    label: '2pt Left',  svgCx: 29, svgCy: 44 },
  { id: 'two_right',   label: '2pt Right', svgCx: 71, svgCy: 44 },
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

export default function CourtMap({ zoneAggregates }) {
  const byId = Object.fromEntries((zoneAggregates ?? []).map(z => [z.polygon_id, z]))

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
            <path
              key={z.id}
              d={ZONE_PATHS[z.id]}
              fill={zoneColor(agg?.accuracy_pct, agg?.attempts)}
              stroke="none"
            />
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

        {/* Zone stats labels */}
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
    </div>
  )
}
