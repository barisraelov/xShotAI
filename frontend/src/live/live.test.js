import assert from 'node:assert/strict'
import { describe, it } from 'node:test'
import { readFileSync, statSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

import { packFrame, PROTOCOL_VERSION, JPEG_QUALITY } from './protocol.js'
import { createLiveGate } from './gate.js'
import {
  classifyDecisionSound,
  delayedBannerText,
  createPlayedSet,
  playDecisionSound,
  playGoSound,
  DELAYED_MS,
} from './audio.js'

const here = dirname(fileURLToPath(import.meta.url))

describe('LIVE-23 GO gate', () => {
  it('does not send frames before GO', () => {
    const gate = createLiveGate()
    assert.equal(gate.canSendFrames(), false)
    assert.equal(gate.canStartTimer(), false)
    gate.enterCountdown()
    assert.equal(gate.canSendFrames(), false)
    gate.enterLive()
    assert.equal(gate.canSendFrames(), true)
    assert.equal(gate.canStartTimer(), true)
    gate.enterStopping()
    assert.equal(gate.canSendFrames(), false)
  })
})

describe('LIVE-05 protocol', () => {
  it('packs XSH1 + header fields', () => {
    const jpeg = Uint8Array.from([1, 2, 3])
    const packed = packFrame({
      protocol_version: PROTOCOL_VERSION,
      live_session_id: 'sid',
      frame_id: 0,
      capture_timestamp_monotonic_ms: 10,
      width: 1280,
      height: 720,
      jpeg_quality: JPEG_QUALITY,
    }, jpeg)
    assert.equal(packed[0], 88)
    assert.equal(packed[1], 83)
    assert.equal(packed[2], 72)
    assert.equal(packed[3], 49)
    assert.equal(JPEG_QUALITY, 0.8)
  })
})

describe('LIVE-20 / LIVE-21 audio', () => {
  it('dedupes shot_id in memory and storage', () => {
    const storage = {
      data: {},
      getItem(k) { return this.data[k] ?? null },
      setItem(k, v) { this.data[k] = String(v) },
    }
    const played = createPlayedSet('sess-1', storage)
    const sounds = { make: { currentTime: 0, play: async () => {} }, miss: { currentTime: 0, play: async () => {} }, delayed: { currentTime: 0, play: async () => {} } }
    const first = playDecisionSound(sounds, {
      shotId: 's001', result: 'made', decidedAtUnixMs: Date.now(), muted: false, played, nowMs: Date.now(),
    })
    const second = playDecisionSound(sounds, {
      shotId: 's001', result: 'made', decidedAtUnixMs: Date.now(), muted: false, played, nowMs: Date.now(),
    })
    assert.equal(first.already, false)
    assert.equal(second.already, true)
    const again = createPlayedSet('sess-1', storage)
    assert.equal(again.has('s001'), true)
  })

  it('uses delayed sound after 2s and keeps the banner copy', () => {
    assert.equal(classifyDecisionSound(0, DELAYED_MS), 'normal')
    assert.equal(classifyDecisionSound(0, DELAYED_MS + 1), 'delayed')
    assert.equal(delayedBannerText('made'), 'תוצאה מהזריקה שלפני הניתוק: Make')
    assert.equal(delayedBannerText('missed'), 'תוצאה מהזריקה שלפני הניתוק: Miss')
  })

  it('mute skips playback but still records the shot', () => {
    const played = createPlayedSet('sess-2', {
      getItem() { return null },
      setItem() {},
    })
    const sounds = {
      make: { currentTime: 0, play() { throw new Error('should not play') } },
      miss: { currentTime: 0, play() { throw new Error('should not play') } },
      delayed: { currentTime: 0, play() { throw new Error('should not play') } },
    }
    const out = playDecisionSound(sounds, {
      shotId: 's002', result: 'missed', decidedAtUnixMs: Date.now(), muted: true, played, nowMs: Date.now(),
    })
    assert.equal(out.muted, true)
    assert.equal(played.has('s002'), true)
  })
})

describe('Live GO / Make / Miss cues', () => {
  const soundsDir = join(here, '..', '..', 'public', 'sounds')

  function clip(label) {
    return {
      currentTime: 1,
      plays: 0,
      play() {
        this.plays += 1
        this.currentTime = 0
        return Promise.resolve()
      },
      label,
    }
  }

  it('GO cue plays go.wav once and does not touch Make/Miss', () => {
    const sounds = { go: clip('go'), make: clip('make'), miss: clip('miss'), delayed: clip('delayed') }
    const first = playGoSound(sounds, { muted: false })
    const second = playGoSound(sounds, { muted: false })
    assert.equal(first.played, true)
    assert.equal(second.played, true)
    assert.equal(sounds.go.plays, 2)
    assert.equal(sounds.make.plays, 0)
    assert.equal(sounds.miss.plays, 0)
  })

  it('does not play GO when muted', () => {
    const sounds = { go: clip('go'), make: clip('make'), miss: clip('miss') }
    const out = playGoSound(sounds, { muted: true })
    assert.equal(out.played, false)
    assert.equal(out.muted, true)
    assert.equal(sounds.go.plays, 0)
  })

  it('GO audio failure does not throw', () => {
    const sounds = {
      go: { currentTime: 0, play() { throw new Error('audio failed') } },
    }
    assert.doesNotThrow(() => playGoSound(sounds, { muted: false }))
    assert.equal(playGoSound(null, { muted: false }).played, false)
  })

  it('Make plays only the make (swish) clip', () => {
    const sounds = { go: clip('go'), make: clip('make'), miss: clip('miss'), delayed: clip('delayed') }
    const played = createPlayedSet('m1', { getItem() { return null }, setItem() {} })
    playDecisionSound(sounds, {
      shotId: 's010', result: 'made', decidedAtUnixMs: Date.now(), muted: false, played, nowMs: Date.now(),
    })
    assert.equal(sounds.make.plays, 1)
    assert.equal(sounds.miss.plays, 0)
    assert.equal(sounds.go.plays, 0)
    assert.equal(sounds.delayed.plays, 0)
  })

  it('Miss plays only the miss (buzzer) clip', () => {
    const sounds = { go: clip('go'), make: clip('make'), miss: clip('miss'), delayed: clip('delayed') }
    const played = createPlayedSet('m2', { getItem() { return null }, setItem() {} })
    playDecisionSound(sounds, {
      shotId: 's011', result: 'missed', decidedAtUnixMs: Date.now(), muted: false, played, nowMs: Date.now(),
    })
    assert.equal(sounds.miss.plays, 1)
    assert.equal(sounds.make.plays, 0)
    assert.equal(sounds.go.plays, 0)
  })

  it('Mute silences GO, Make, and Miss', () => {
    const sounds = {
      go: clip('go'),
      make: { currentTime: 0, play() { throw new Error('make') } },
      miss: { currentTime: 0, play() { throw new Error('miss') } },
      delayed: { currentTime: 0, play() { throw new Error('delayed') } },
    }
    const played = createPlayedSet('m3', { getItem() { return null }, setItem() {} })
    assert.equal(playGoSound(sounds, { muted: true }).muted, true)
    const make = playDecisionSound(sounds, {
      shotId: 's012', result: 'made', decidedAtUnixMs: Date.now(), muted: true, played, nowMs: Date.now(),
    })
    const miss = playDecisionSound(sounds, {
      shotId: 's013', result: 'missed', decidedAtUnixMs: Date.now(), muted: true, played, nowMs: Date.now(),
    })
    assert.equal(make.muted, true)
    assert.equal(miss.muted, true)
    assert.equal(sounds.go.plays, 0)
  })

  it('GO overlay in Live.jsx plays only when countdown is GO', () => {
    const jsx = readFileSync(join(here, '..', 'screens', 'Live.jsx'), 'utf8')
    assert.match(jsx, /playGoSound/)
    assert.match(jsx, /countdown !== 'GO'/)
    const audio = readFileSync(join(here, 'audio.js'), 'utf8')
    assert.match(audio, /new Audio\('\/sounds\/go\.wav'\)/)
    assert.match(audio, /new Audio\('\/sounds\/make\.wav'\)/)
    assert.match(audio, /new Audio\('\/sounds\/miss\.wav'\)/)
  })

  it('sound files exist, are non-empty, and delayed.wav is unchanged', () => {
    const go = statSync(join(soundsDir, 'go.wav'))
    const make = statSync(join(soundsDir, 'make.wav'))
    const miss = statSync(join(soundsDir, 'miss.wav'))
    const delayed = statSync(join(soundsDir, 'delayed.wav'))
    assert.equal(go.size, 6218)
    assert.ok(make.size > 1000)
    assert.ok(miss.size > 1000)
    assert.equal(delayed.size, 11508)
    assert.notEqual(make.size, go.size)
  })
})

describe('LIVE-19 / LIVE-22 Stop and warning copy', () => {
  it('sends stop and keeps overload copy', () => {
    const jsx = readFileSync(join(here, '..', 'screens', 'Live.jsx'), 'utf8')
    const session = readFileSync(join(here, 'clientSession.js'), 'utf8')
    assert.match(jsx, /requestStop/)
    assert.match(session, /type: 'stop'/)
    assert.match(session, /enterStopping/)
    assert.match(jsx, /Start Live/)
    assert.match(jsx, /Try Start Again/)
    assert.match(jsx, /unlockSounds/)
    assert.match(jsx, /facingMode: \{ ideal: 'environment' \}/)
    assert.match(jsx, /image\/jpeg', JPEG_QUALITY/)
    assert.match(jsx, /החיבור או העיבוד איטיים כרגע/)
  })
})

describe('LIVE-22 contain / full viewport CSS', () => {
  it('uses contain and 100dvh without crop', () => {
    const css = readFileSync(join(here, '..', 'screens', 'Live.css'), 'utf8')
    assert.match(css, /object-fit:\s*contain/)
    assert.match(css, /100dvh/)
    assert.doesNotMatch(css, /object-fit:\s*cover/)
  })

  it('countdown overlay is dark, large, and above the HUD', () => {
    const css = readFileSync(join(here, '..', 'screens', 'Live.css'), 'utf8')
    assert.match(css, /\.live-countdown[\s\S]*z-index:\s*6/)
    assert.match(css, /rgba\(0,\s*0,\s*0,\s*0\.72\)/)
    assert.match(css, /\.live-countdown-num/)
  })
})

describe('Live diagnostics UI', () => {
  it('session screen shows Live diagnostics from session_complete', () => {
    const jsx = readFileSync(join(here, '..', 'screens', 'Session.jsx'), 'utf8')
    assert.match(jsx, /Live diagnostics/)
    assert.match(jsx, /liveDiagnostics/)
    assert.match(jsx, /start_path/)
  })

  it('does not await unlockSounds on Start', () => {
    const jsx = readFileSync(join(here, '..', 'screens', 'Live.jsx'), 'utf8')
    assert.match(jsx, /void unlockSounds/)
    assert.doesNotMatch(jsx, /await unlockSounds/)
  })
})
