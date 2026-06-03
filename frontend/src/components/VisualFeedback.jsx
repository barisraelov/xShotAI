/**
 * VisualFeedback — presentational layer over result.feedback + result.shot_points.
 *
 * Pure React + CSS/SVG. No CV, no API calls, no new runtime cost.
 * Player-facing copy never exposes pixels; raw values are only used internally
 * to derive relative / descriptive language. Every card ties back to a real
 * generated insight so the experience reads as one system:
 *   Data → Visual → Insight → Recommendation.
 *
 * Each sub-card is defensive: if its data is missing it simply does not render
 * (the Consistency card shows a graceful fallback instead).
 */

// ── Data helpers (all read-only, O(n)) ──────────────────────────────────────

function parseArc(shot) {
  const h = shot?.trajectory?.arc_height_px
  return typeof h === 'number' && isFinite(h) && h > 0 ? h : null
}

function arcSeries(shotPoints) {
  const out = []
  shotPoints.forEach((s, i) => {
    const arc = parseArc(s)
    if (arc != null) out.push({ index: i + 1, arc, made: s.result === 'made' })
  })
  return out
}

function mean(arr) {
  return arr.length ? arr.reduce((a, b) => a + b, 0) / arr.length : 0
}

function outcomes(shotPoints) {
  return shotPoints.map(s => s.result).filter(r => r === 'made' || r === 'missed')
}

// Find the real generated insight that a card visualises (keyword match,
// case-insensitive). Returns the insight text or null — never invents copy.
function findInsight(insights, keywords) {
  if (!Array.isArray(insights)) return null
  const lowered = keywords.map(k => k.toLowerCase())
  return insights.find(t => {
    const lt = String(t).toLowerCase()
    return lowered.some(k => lt.includes(k))
  }) || null
}

// ── Shared derivations ──────────────────────────────────────────────────────

function classifyConsistency(series) {
  if (series.length < 3) return { level: null }
  const arcs = series.map(d => d.arc)
  const m = mean(arcs)
  const spread = m > 0 ? (Math.max(...arcs) - Math.min(...arcs)) / m : 0
  if (spread < 0.2)
    return { level: 'Consistent', cls: 'is-good', spread,
      stability: 'High', variation: 'Low',
      explanation: 'Your release arc stayed stable from shot to shot.' }
  if (spread < 0.35)
    return { level: 'Some variation', cls: 'is-mid', spread,
      stability: 'Moderate', variation: 'Moderate',
      explanation: 'Your release arc shifted a little between shots.' }
  return { level: 'Inconsistent', cls: 'is-bad', spread,
    stability: 'Low', variation: 'High',
    explanation: 'Your release arc changed a lot between shots.' }
}

function fatigueInfo(metrics, shotPoints) {
  const firstArc = metrics?.first_half_mean_arc_height_px
  const secondArc = metrics?.second_half_mean_arc_height_px

  let mode = null, first = 0, second = 0
  if (typeof firstArc === 'number' && typeof secondArc === 'number') {
    mode = 'arc'; first = firstArc; second = secondArc
  } else {
    const o = outcomes(shotPoints)
    if (o.length >= 4) {
      mode = 'acc'
      const k = Math.floor(o.length / 2)
      const a = o.slice(0, k), b = o.slice(k)
      first = (a.filter(x => x === 'made').length / a.length) * 100
      second = (b.filter(x => x === 'made').length / b.length) * 100
    }
  }
  if (!mode) return null

  const delta = second - first
  const threshold = mode === 'arc' ? Math.max(first * 0.1, 1) : 10
  const trend = delta <= -threshold ? 'down' : delta >= threshold ? 'up' : 'flat'
  const noun = mode === 'arc' ? 'Arc' : 'Accuracy'
  const trendText = {
    down: `${noun} decreased later in the session`,
    up: `${noun} improved later in the session`,
    flat: `${noun} held steady through the session`,
  }[trend]

  // Relative magnitude + severity (never pixels).
  const usePts = !(first > 0)
  const pct = usePts ? Math.round(Math.abs(delta)) : Math.round((Math.abs(delta) / first) * 100)
  const unit = usePts ? ' pts' : '%'
  let severity = null
  if (trend !== 'flat') {
    const sev = pct < 8 ? 'Minor' : pct < 18 ? 'Moderate' : 'Strong'
    const dir = trend === 'down' ? 'decline' : 'improvement'
    severity = { word: `${sev} ${dir}`, sevClass: sev.toLowerCase(), pct, unit }
  }
  return { mode, first, second, trend, trendText, severity }
}

// Accuracy-dominant scoring. Weights: accuracy 0.80, consistency 0.10,
// fatigue 0.05, finish/streak 0.05. The non-accuracy factors fine-tune the
// score within a narrow band rather than overpowering a good shooting day.
function sessionScore({ summary, consistency, fatigue, metrics }) {
  const acc = Math.max(0, Math.min(100, Number(summary?.accuracy_pct) || 0))

  const consComp =
    consistency.level === 'Consistent' ? 100
      : consistency.level === 'Some variation' ? 70
      : consistency.level === 'Inconsistent' ? 45
      : 70 // unknown → neutral, never punitive

  const fatComp =
    fatigue?.trend === 'up' ? 100
      : fatigue?.trend === 'flat' ? 80
      : fatigue?.trend === 'down' ? 55
      : 80 // unknown → neutral

  let finishComp = 75
  const endType = metrics?.ending_streak_type
  const endLen = metrics?.ending_streak_length
  if (endType === 'made' && endLen >= 2) finishComp = 100
  else if (endType === 'missed' && endLen >= 2) finishComp = 40
  if ((metrics?.longest_make_streak ?? 0) >= 4) finishComp = Math.max(finishComp, 90)

  const score = Math.max(0, Math.min(100, Math.round(
    acc * 0.80 + consComp * 0.10 + fatComp * 0.05 + finishComp * 0.05
  )))

  const grade =
    score >= 90 ? 'A'
      : score >= 83 ? 'A-'
      : score >= 78 ? 'B+'
      : score >= 72 ? 'B'
      : score >= 66 ? 'B-'
      : score >= 60 ? 'C+'
      : score >= 54 ? 'C'
      : score >= 48 ? 'C-'
      : score >= 40 ? 'D'
      : 'E'

  let label, cls
  if (score >= 78) { label = 'Strong Session'; cls = 'is-good' }
  else if (score >= 64) { label = 'Solid Session'; cls = 'is-good' }
  else if (score >= 50) { label = 'Developing Session'; cls = 'is-mid' }
  else { label = 'Keep Building'; cls = 'is-bad' }

  return { score, label, grade, cls }
}

function shootingProfile({ summary, consistency, fatigue, metrics }) {
  const traits = []
  const push = (label, tone) => {
    if (!traits.some(t => t.label === label)) traits.push({ label, tone })
  }

  const acc = Number(summary?.accuracy_pct) || 0
  if (acc >= 70) push('Good Accuracy', 'good')
  else if (acc >= 45) push('Developing Accuracy', 'mid')
  else push('Accuracy Needs Reps', 'bad')

  if (consistency.level === 'Consistent') push('Consistent Release', 'good')
  else if (consistency.level === 'Some variation') push('Variable Release', 'mid')
  else if (consistency.level === 'Inconsistent') push('Variable Release', 'bad')

  const madeArc = metrics?.trajectory_mean_arc_height_made_px
  const missedArc = metrics?.trajectory_mean_arc_height_missed_px
  if (typeof madeArc === 'number' && typeof missedArc === 'number') {
    if (madeArc > missedArc * 1.05) push('High Arc on Makes', 'good')
    else if (missedArc > madeArc * 1.05) push('Arc Not Driving Makes', 'mid')
  }

  if (fatigue?.trend === 'down') push('Fatigue Detected', 'bad')
  else if (fatigue?.trend === 'up') push('Builds Momentum', 'good')

  const endType = metrics?.ending_streak_type
  const endLen = metrics?.ending_streak_length
  if (endType === 'made' && endLen >= 2) push('Strong Finish', 'good')
  else if (endType === 'missed' && endLen >= 2) push('Cold Finish', 'bad')

  return traits.slice(0, 6)
}

// ── Presentational pieces ────────────────────────────────────────────────────

function VfCard({ title, hint, className = '', children }) {
  return (
    <div className={`vf-card ${className}`}>
      <div className="vf-card-head">
        <span className="vf-card-title">{title}</span>
        {hint && <span className="vf-card-hint">{hint}</span>}
      </div>
      {children}
    </div>
  )
}

// Footer that shows the real insight this visual supports.
function InsightLink({ text }) {
  if (!text) return null
  return (
    <p className="vf-insight">
      <span className="vf-insight-tag">Insight</span>
      {text}
    </p>
  )
}

// Session Score (high-level summary) -----------------------------------------
function SessionScoreCard({ summary, consistency, fatigue, metrics }) {
  const { score, label, grade, cls } = sessionScore({ summary, consistency, fatigue, metrics })
  return (
    <VfCard title="Session score" hint="overall" className="vf-standalone vf-score-hero">
      <div className="vf-hero-row">
        <div className={`vf-hero-num ${cls}`}>
          {score}
          <span className="vf-hero-den">/100</span>
        </div>
        <div className="vf-hero-meta">
          <span className={`vf-hero-grade ${cls}`}>{grade}</span>
          <span className="vf-hero-label">{label}</span>
        </div>
      </div>
      <div className="vf-score-meter">
        <div className={`vf-score-meter-fill ${cls}`} style={{ width: `${score}%` }} />
      </div>
      <p className="vf-hero-foot">Accuracy-led — fine-tuned by consistency, finish &amp; fatigue.</p>
    </VfCard>
  )
}

// Shooting Profile (trait chips) ---------------------------------------------
function ShootingProfile({ traits }) {
  if (!traits.length) return null
  return (
    <VfCard title="Your shooting profile" hint="this session" className="vf-standalone">
      <div className="vf-traits">
        {traits.map(t => (
          <span key={t.label} className={`vf-trait tone-${t.tone}`}>{t.label}</span>
        ))}
      </div>
    </VfCard>
  )
}

// Consistency (with explanation) ---------------------------------------------
function ConsistencyCard({ consistency, insight }) {
  if (consistency.level == null) {
    return (
      <VfCard title="Consistency">
        <div className="vf-score vf-score--empty">
          <span className="vf-pill is-neutral">—</span>
          <span className="vf-muted">Not enough trajectory data yet.</span>
        </div>
      </VfCard>
    )
  }
  const fill = Math.max(8, Math.min(100, (1 - Math.min(consistency.spread, 0.5) / 0.5) * 100))
  return (
    <VfCard title="Consistency" hint="release arc">
      <div className="vf-score">
        <span className={`vf-pill ${consistency.cls}`}>{consistency.level}</span>
        <div className="vf-score-meter">
          <div className={`vf-score-meter-fill ${consistency.cls}`} style={{ width: `${fill}%` }} />
        </div>
      </div>
      <div className="vf-stat-row">
        <span className="vf-stat-key">Release stability</span>
        <span className={`vf-stat-val ${consistency.cls}`}>{consistency.stability}</span>
      </div>
      <p className="vf-explain">{consistency.explanation}</p>
      <InsightLink text={insight} />
    </VfCard>
  )
}

// Shot Sequence / Streaks -----------------------------------------------------
function ShotSequence({ shotPoints, metrics, insight }) {
  const seq = shotPoints
    .map((s, i) => ({ index: i + 1, made: s.result === 'made', valid: s.result === 'made' || s.result === 'missed' }))
    .filter(s => s.valid)
  if (!seq.length) return null

  const longestMake = metrics?.longest_make_streak
  const longestMiss = metrics?.longest_miss_streak
  const endType = metrics?.ending_streak_type
  const endLen = metrics?.ending_streak_length

  return (
    <VfCard title="Shot sequence" hint={`${seq.length} shots`}>
      <div className="vf-seq" role="img" aria-label="Sequence of makes and misses">
        {seq.map(s => (
          <span
            key={s.index}
            className={`vf-dot ${s.made ? 'is-made' : 'is-missed'}`}
            title={`Shot ${s.index}: ${s.made ? 'made' : 'missed'}`}
          />
        ))}
      </div>
      <div className="vf-chips">
        {typeof longestMake === 'number' && longestMake > 0 && (
          <span className="vf-chip is-made">Best make streak · {longestMake}</span>
        )}
        {typeof longestMiss === 'number' && longestMiss > 0 && (
          <span className="vf-chip is-missed">Longest cold streak · {longestMiss}</span>
        )}
        {endType && typeof endLen === 'number' && endLen > 1 && (
          <span className={`vf-chip ${endType === 'made' ? 'is-made' : 'is-missed'}`}>
            Ended on {endLen} {endType === 'made' ? 'makes' : 'misses'}
          </span>
        )}
      </div>
      <InsightLink text={insight} />
    </VfCard>
  )
}

// Arc Timeline ----------------------------------------------------------------
function ArcTimeline({ series, insight }) {
  if (series.length < 2) return null
  const arcs = series.map(d => d.arc)
  const min = Math.min(...arcs)
  const max = Math.max(...arcs)
  const m = mean(arcs)
  const span = max - min
  const heightPct = arc => (span > 0 ? 18 + 82 * ((arc - min) / span) : 60)
  const relWord = arc =>
    arc > m * 1.08 ? 'above average' : arc < m * 0.92 ? 'below average' : 'around average'

  return (
    <VfCard title="Arc consistency timeline" hint={`${series.length} shots`}>
      <div className="vf-timeline" role="img" aria-label="Arc height per shot across the session">
        {series.map(d => (
          <div
            className="vf-bar-col"
            key={d.index}
            title={`Shot ${d.index} · ${relWord(d.arc)} arc · ${d.made ? 'made' : 'missed'}`}
          >
            <div className={`vf-bar ${d.made ? 'is-made' : 'is-missed'}`} style={{ height: `${heightPct(d.arc)}%` }} />
          </div>
        ))}
      </div>
      <div className="vf-legend">
        <span><i className="vf-swatch is-made" /> Made</span>
        <span><i className="vf-swatch is-missed" /> Missed</span>
      </div>
      <p className="vf-caption">Taller bars = a higher release arc on that shot.</p>
      <InsightLink text={insight} />
    </VfCard>
  )
}

// Made vs Missed Arc (no pixels — relative + descriptive) ---------------------
function ArcComparison({ metrics, series, insight }) {
  let madeAvg = metrics?.trajectory_mean_arc_height_made_px
  let missedAvg = metrics?.trajectory_mean_arc_height_missed_px

  if (typeof madeAvg !== 'number' || typeof missedAvg !== 'number') {
    const made = series.filter(d => d.made).map(d => d.arc)
    const missed = series.filter(d => !d.made).map(d => d.arc)
    if (made.length < 2 || missed.length < 2) return null
    madeAvg = mean(made)
    missedAvg = mean(missed)
  }

  const max = Math.max(madeAvg, missedAvg) || 1
  const lower = Math.min(madeAvg, missedAvg) || 1
  const pctDiff = Math.round((Math.abs(madeAvg - missedAvg) / lower) * 100)
  const even = Math.abs(madeAvg - missedAvg) / lower < 0.05

  const word = avg => (even ? '≈ Even' : avg === max ? 'Higher arc' : 'Lower arc')
  const rows = [
    { label: 'Made', value: madeAvg, cls: 'is-made' },
    { label: 'Missed', value: missedAvg, cls: 'is-missed' },
  ]

  let note
  if (even) note = 'Arc height was similar on makes and misses.'
  else if (madeAvg > missedAvg) note = `Made shots had a ~${pctDiff}% higher arc than misses.`
  else note = `Misses had a ~${pctDiff}% higher arc — height alone didn’t drive makes.`

  return (
    <VfCard title="Made vs missed arc" hint="relative height">
      <div className="vf-cmp">
        {rows.map(r => (
          <div className="vf-cmp-row" key={r.label}>
            <span className="vf-cmp-label">{r.label}</span>
            <div className="vf-cmp-track">
              <div className={`vf-cmp-fill ${r.cls}`} style={{ width: `${Math.max(6, (r.value / max) * 100)}%` }} />
            </div>
            <span className={`vf-cmp-word ${r.value === max && !even ? 'is-hi' : ''}`}>{word(r.value)}</span>
          </div>
        ))}
      </div>
      <p className="vf-note">{note}</p>
      <InsightLink text={insight} />
    </VfCard>
  )
}

// Fatigue: first half vs second half (no pixels) -----------------------------
function FatigueSplit({ fatigue, insight }) {
  if (!fatigue) return null
  const { mode, first, second, trend, trendText } = fatigue
  const max = Math.max(first, second) || 1
  const showPct = mode === 'acc'

  return (
    <VfCard title="Fatigue check" hint={mode === 'arc' ? 'arc by half' : 'accuracy by half'}>
      <div className="vf-half">
        {[{ label: '1st half', v: first }, { label: '2nd half', v: second }].map(h => (
          <div className="vf-half-col" key={h.label}>
            <div className="vf-half-track">
              <div className="vf-half-fill" style={{ height: `${Math.max(8, (h.v / max) * 100)}%` }} />
            </div>
            {showPct && <div className="vf-half-val">{Math.round(h.v)}%</div>}
            <div className="vf-half-label">{h.label}</div>
          </div>
        ))}
      </div>
      {fatigue.severity && (
        <div className="vf-stat-row">
          <span className="vf-stat-key">Change</span>
          <span className={`vf-sev sev-${fatigue.severity.sevClass} vf-trend-${trend}`}>
            {fatigue.severity.word} · ~{fatigue.severity.pct}{fatigue.severity.unit}
          </span>
        </div>
      )}
      <p className={`vf-note vf-trend-${trend}`}>
        {trend === 'down' ? '▼ ' : trend === 'up' ? '▲ ' : '■ '}{trendText}
      </p>
      <InsightLink text={insight} />
    </VfCard>
  )
}

// ── Root helpers / exports ───────────────────────────────────────────────────

function visualData(result) {
  const shotPoints = Array.isArray(result?.shot_points) ? result.shot_points : []
  const metrics = result?.feedback?.metrics ?? {}
  const insights = result?.feedback?.insights ?? []

  const series = arcSeries(shotPoints)
  const consistency = classifyConsistency(series)
  const fatigue = fatigueInfo(metrics, shotPoints)
  const traits = shootingProfile({ summary: result?.summary, consistency, fatigue, metrics })

  return { shotPoints, metrics, insights, series, consistency, fatigue, traits }
}

export function VisualSessionSummary({ result }) {
  const data = visualData(result)
  if (!data.shotPoints.length) return null

  return (
    <>
      <SessionScoreCard
        summary={result?.summary}
        consistency={data.consistency}
        fatigue={data.fatigue}
        metrics={data.metrics}
      />
      <ShootingProfile traits={data.traits} />
    </>
  )
}

export default function VisualFeedback({ result }) {
  const data = visualData(result)
  if (!data.shotPoints.length) return null

  return (
    <div className="vf-section">
      <div className="vf-grid">
        <ConsistencyCard
          consistency={data.consistency}
          insight={findInsight(data.insights, ['varied', 'consistent'])}
        />
        <ShotSequence
          shotPoints={data.shotPoints}
          metrics={data.metrics}
          insight={findInsight(data.insights, ['streak', 'finished hot', 'cold finish', 'consecutive'])}
        />
        <ArcTimeline
          series={data.series}
          insight={findInsight(data.insights, ['varied', 'arc'])}
        />
        <ArcComparison
          metrics={data.metrics}
          series={data.series}
          insight={findInsight(data.insights, ['higher arc', 'did not clearly'])}
        />
        <FatigueSplit
          fatigue={data.fatigue}
          insight={findInsight(data.insights, ['second half', 'later in the session'])}
        />
      </div>
    </div>
  )
}
