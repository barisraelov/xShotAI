/**
 * User level & tier progression.
 *
 * Level is derived from the player's cumulative made shots across every saved
 * training session.
 *
 *   Level 1  : 0   – 9    made shots   (Rookie)
 *   Level 2  : 10  – 24
 *   Level 3  : 25  – 44
 *   Level 4  : 45  – 64
 *   Level 5  : 65  – 84
 *   ...       (+20 per level)
 *   Level 20 : 365+          (Max level)
 */

export const MAX_LEVEL = 20

// Cumulative made-shots needed to *reach* each level (index 0 → Level 1).
// L1 = 0, L2 = 10, L3 = 25, then +20 per level up to L20 = 365.
export const LEVEL_THRESHOLDS = Array.from({ length: MAX_LEVEL }, (_, i) => {
  if (i === 0) return 0
  if (i === 1) return 10
  if (i === 2) return 25
  return 25 + (i - 2) * 20
})

/** Tier title for a given level (1–20). */
export function tierTitle(level) {
  if (level <= 1) return 'Rookie'
  if (level <= 5) return 'Rhythm Shooter'
  if (level <= 10) return 'Spot-Up Guy'
  if (level <= 15) return 'Sharpshooter'
  return 'Cheat Code'
}

/**
 * @param {number} totalMadeShots  cumulative made shots (any non-number, NaN or
 *                                 negative value is treated as 0)
 * @returns {{
 *   level: number,               // 1–20
 *   title: string,               // tier title
 *   currentLevelShots: number,   // made shots earned within the current level
 *   nextLevelShots: number,      // made shots still needed to advance (0 at max)
 *   progressPercent: number,     // 0–100 toward the next level (100 at max)
 *   isMaxLevel: boolean,
 *   totalMadeShots: number,      // the sanitised input
 * }}
 */
export function getLevelInfo(totalMadeShots) {
  const made = Math.max(0, Math.floor(Number(totalMadeShots) || 0))

  // Highest threshold the player has cleared → that's their level.
  let level = 1
  for (let i = 0; i < LEVEL_THRESHOLDS.length; i += 1) {
    if (made >= LEVEL_THRESHOLDS[i]) level = i + 1
    else break
  }

  const isMaxLevel = level >= MAX_LEVEL
  const currentBase = LEVEL_THRESHOLDS[level - 1]

  if (isMaxLevel) {
    return {
      level: MAX_LEVEL,
      title: tierTitle(MAX_LEVEL),
      currentLevelShots: made - currentBase,
      nextLevelShots: 0,
      progressPercent: 100,
      isMaxLevel: true,
      totalMadeShots: made,
    }
  }

  const nextBase = LEVEL_THRESHOLDS[level]
  const span = nextBase - currentBase
  const currentLevelShots = made - currentBase
  const nextLevelShots = nextBase - made
  const progressPercent = Math.min(
    100,
    Math.max(0, Math.round((currentLevelShots / span) * 100)),
  )

  return {
    level,
    title: tierTitle(level),
    currentLevelShots,
    nextLevelShots,
    progressPercent,
    isMaxLevel: false,
    totalMadeShots: made,
  }
}
