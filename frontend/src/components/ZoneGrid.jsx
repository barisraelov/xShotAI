import './ZoneGrid.css'

const RANGE_ORDER = ['mid_range', 'three_point', 'extended']
const RANGE_LABELS = { mid_range: 'Mid-range', three_point: 'Three-point', extended: 'Extended range' }

export default function ZoneGrid({ zoneAggregates }) {
  if (!zoneAggregates?.length) return null

  // Group by range_class, preserving order
  const groups = {}
  for (const z of zoneAggregates) {
    if (!groups[z.range_class]) groups[z.range_class] = []
    groups[z.range_class].push(z)
  }

  return (
    <>
      {RANGE_ORDER.filter(r => groups[r]).map(rangeClass => (
        <div key={rangeClass}>
          <h3 className="zone-block-title">{RANGE_LABELS[rangeClass]}</h3>
          <div className="zones-grid">
            {groups[rangeClass].map(zone => {
              const pct = zone.accuracy_pct
              const deg = `${(pct / 100 * 360).toFixed(1)}deg`
              return (
                <div
                  key={zone.polygon_id}
                  className={`zone-card${zone.polygon_id === 'extended' || zone.polygon_id === 'three_top_key' ? ' wide' : ''}`}
                >
                  <div className="zmeta">
                    <div className="zname">{zone.label}</div>
                    <div className="zval">{pct.toFixed(0)}%</div>
                    <div className="zattempts">{zone.made}/{zone.attempts}</div>
                  </div>
                  <div className="zone-ring" style={{ '--zone-deg': deg }} />
                </div>
              )
            })}
          </div>
        </div>
      ))}
    </>
  )
}
