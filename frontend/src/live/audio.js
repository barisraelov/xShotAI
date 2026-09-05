export const DELAYED_MS = 2000

export function classifyDecisionSound(decidedAtUnixMs, nowMs = Date.now()) {
  if (decidedAtUnixMs == null) return 'normal'
  return (nowMs - Number(decidedAtUnixMs)) > DELAYED_MS ? 'delayed' : 'normal'
}

export function delayedBannerText(result) {
  const label = result === 'made' ? 'Make' : 'Miss'
  return `תוצאה מהזריקה שלפני הניתוק: ${label}`
}

export function createPlayedSet(liveSessionId, storage) {
  const key = `xshot_played_${liveSessionId}`
  const store = storage || {
    getItem() { return null },
    setItem() {},
  }
  let mem
  try {
    mem = new Set(JSON.parse(store.getItem(key) || '[]'))
  } catch {
    mem = new Set()
  }
  function persist() {
    try { store.setItem(key, JSON.stringify([...mem])) } catch { /* private mode */ }
  }
  return {
    has(id) { return mem.has(id) },
    add(id) {
      mem.add(id)
      persist()
    },
  }
}

export function loadSounds() {
  const make = new Audio('/sounds/make.wav')
  const miss = new Audio('/sounds/miss.wav')
  const delayed = new Audio('/sounds/delayed.wav')
  for (const a of [make, miss, delayed]) {
    a.preload = 'auto'
  }
  return { make, miss, delayed }
}

export async function unlockSounds(sounds) {
  for (const audio of Object.values(sounds)) {
    try {
      audio.muted = true
      await audio.play()
      audio.pause()
      audio.currentTime = 0
      audio.muted = false
    } catch {
      try { audio.muted = false } catch { /* ignore */ }
    }
  }
}

export function playDecisionSound(sounds, { shotId, result, decidedAtUnixMs, muted, played, nowMs }) {
  if (!shotId || played.has(shotId)) {
    return { played: false, kind: null, already: true }
  }
  played.add(shotId)
  const kind = classifyDecisionSound(decidedAtUnixMs, nowMs)
  if (muted) {
    return { played: false, kind, already: false, muted: true }
  }
  const clip = kind === 'delayed' ? sounds.delayed : (result === 'made' ? sounds.make : sounds.miss)
  try {
    clip.currentTime = 0
    clip.play().catch(() => {})
  } catch { /* ignore */ }
  return { played: true, kind, already: false, muted: false }
}
