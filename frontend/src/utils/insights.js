/**
 * "Did you know?" facts derived from a user's saved session history.
 *
 * `computeInsights(sessions)` returns every Hebrew fact string whose criteria
 * are met (possibly empty). `pickInsight(sessions)` returns one of them at
 * random, or the encouraging fallback when none apply / there's too little
 * history. Everything is null / NaN / 0-0 safe.
 *
 * `sessions` items are SessionSummary shaped:
 *   { id, created_at, total_shots, made, missed, accuracy_pct }
 */

const MONTHS_SHORT = [
  'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
  'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
]

export const INSIGHT_FALLBACK = 'המשך להתאמן כדי לחשוף עובדות ושיאים אישיים!'

// A finite, non-negative integer count — anything else (null, NaN, "x",
// Infinity, negatives) collapses to 0.
function count(v) {
  const n = Number(v)
  return Number.isFinite(n) && n > 0 ? n : 0
}

// UTC ISO -> viewer-local YYYY-MM-DD.
function dayKey(iso) {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

// "2026-09-07" -> "7 Sep 2026" (day-first, engine-independent).
function dayKeyLabel(key) {
  const [y, m, d] = String(key).split('-').map(Number)
  if (!y || !m || !d || m < 1 || m > 12) return String(key)
  return `${d} ${MONTHS_SHORT[m - 1]} ${y}`
}

// Local calendar-day math on a YYYY-MM-DD key.
function shiftDay(key, delta) {
  const [y, m, d] = String(key).split('-').map(Number)
  const dt = new Date(y, m - 1, d)
  dt.setDate(dt.getDate() + delta)
  const yy = dt.getFullYear()
  const mm = String(dt.getMonth() + 1).padStart(2, '0')
  const dd = String(dt.getDate()).padStart(2, '0')
  return `${yy}-${mm}-${dd}`
}

export function computeInsights(sessions) {
  const list = Array.isArray(sessions)
    ? sessions.filter(s => s && typeof s === 'object')
    : []
  if (list.length < 2) return []

  const attemptsByDay = new Map() // dayKey -> total attempts that day (0-0 days still get a key)
  let sumMade = 0
  let sumAttempts = 0

  for (const s of list) {
    const attempts = count(s.total_shots)
    const made = Math.min(count(s.made), attempts)
    sumMade += made
    sumAttempts += attempts
    const k = dayKey(s.created_at)
    if (k) attemptsByDay.set(k, (attemptsByDay.get(k) || 0) + attempts)
  }

  const facts = []

  // 1 — day with the most shot attempts.
  let bestDay = null
  let bestDayAttempts = 0
  for (const [k, att] of attemptsByDay) {
    if (att > bestDayAttempts) {
      bestDayAttempts = att
      bestDay = k
    }
  }
  if (bestDay && bestDayAttempts > 0) {
    facts.push(`בתאריך ${dayKeyLabel(bestDay)} זרקת ${bestDayAttempts} פעמים שזה הכי הרבה`)
  }

  // 2 — best accuracy among sessions with at least 5 attempts.
  let bestPct = -1
  for (const s of list) {
    const attempts = count(s.total_shots)
    if (attempts < 5) continue
    const pct = (Math.min(count(s.made), attempts) / attempts) * 100
    if (Number.isFinite(pct) && pct > bestPct) bestPct = pct
  }
  if (bestPct >= 0) {
    facts.push(`האחוז הגבוה ביותר שזרקת עם לפחות 5 זריקות הוא ${Math.round(bestPct)}%`)
  }

  // 3 — cumulative shooting % above the NBA True Shooting benchmark (58%).
  if (sumAttempts > 0) {
    const overall = (sumMade / sumAttempts) * 100
    if (Number.isFinite(overall) && overall > 58) {
      facts.push('הידעת שאחוז הזריקות שלך גבוה מה-NBA (ממוצע True Shooting של 58%)')
    }
  }

  // 4 — consecutive calendar days with a session, ending today or yesterday.
  const today = dayKey(new Date().toISOString())
  let cursor = null
  if (attemptsByDay.has(today)) cursor = today
  else if (attemptsByDay.has(shiftDay(today, -1))) cursor = shiftDay(today, -1)
  let streak = 0
  while (cursor && attemptsByDay.has(cursor)) {
    streak += 1
    cursor = shiftDay(cursor, -1)
  }
  if (streak >= 2) {
    facts.push(`אתה נמצא כבר ברצף של ${streak} ימים של זריקות לסל 🔥`)
  }

  return facts
}

export function pickInsight(sessions) {
  const facts = computeInsights(sessions)
  if (facts.length === 0) return INSIGHT_FALLBACK
  return facts[Math.floor(Math.random() * facts.length)]
}
