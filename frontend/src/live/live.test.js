import assert from 'node:assert/strict'
import { describe, it } from 'node:test'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

import { packFrame, PROTOCOL_VERSION, JPEG_QUALITY } from './protocol.js'
import { createLiveGate } from './gate.js'
import {
  classifyDecisionSound,
  delayedBannerText,
  createPlayedSet,
  playDecisionSound,
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

describe('LIVE-19 / LIVE-22 Stop and warning copy', () => {
  it('sends stop and keeps overload copy', () => {
    const jsx = readFileSync(join(here, '..', 'screens', 'Live.jsx'), 'utf8')
    assert.match(jsx, /type: 'stop'/)
    assert.match(jsx, /enterStopping/)
    assert.match(jsx, /Start Live/)
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
})
