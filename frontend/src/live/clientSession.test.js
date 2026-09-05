import assert from 'node:assert/strict'
import { describe, it } from 'node:test'

import {
  COUNTDOWN_STEP_MS,
  STOP_ACK_TIMEOUT_MS,
  TELEMETRY_MS,
  createLiveClientSession,
  rttAndOffset,
} from './clientSession.js'

function createFakeTimers() {
  let now = 0
  let nextId = 1
  const timers = []

  function clearId(id) {
    const i = timers.findIndex(t => t.id === id)
    if (i >= 0) timers.splice(i, 1)
  }

  return {
    now: () => now,
    setTimeout(fn, ms) {
      const id = nextId++
      timers.push({ id, fn, at: now + ms, interval: false })
      return id
    },
    clearTimeout: clearId,
    setInterval(fn, ms) {
      const id = nextId++
      timers.push({ id, fn, at: now + ms, interval: true, every: ms })
      return id
    },
    clearInterval: clearId,
    activeIntervals() {
      return timers.filter(t => t.interval).length
    },
    advance(ms) {
      const target = now + ms
      let guard = 0
      while (guard++ < 10000) {
        const due = timers
          .filter(t => t.at <= target)
          .sort((a, b) => a.at - b.at || a.id - b.id)
        if (!due.length) {
          now = target
          return
        }
        const t = due[0]
        now = t.at
        if (t.interval) {
          t.at = now + t.every
          t.fn()
        } else {
          clearId(t.id)
          t.fn()
        }
      }
      throw new Error('fake timer loop')
    },
  }
}

function harness({ open = true } = {}) {
  const timers = createFakeTimers()
  let socketOpen = open
  const sent = []
  const capture = { start: 0, stop: 0 }
  const nav = { session: 0, upload: 0, last: null }
  const phases = []
  const errors = []
  const countdowns = []
  const conns = []
  const session = createLiveClientSession({
    now: timers.now,
    setTimeout: (...a) => timers.setTimeout(...a),
    clearTimeout: (id) => timers.clearTimeout(id),
    setInterval: (...a) => timers.setInterval(...a),
    clearInterval: (id) => timers.clearInterval(id),
    waitMs: async (ms) => { timers.advance(ms) },
    send: (obj) => { sent.push(obj) },
    isOpen: () => socketOpen,
    startCapture: () => { capture.start += 1 },
    stopCapture: () => { capture.stop += 1 },
    onPhase: (p) => { phases.push(p) },
    onCountdown: (v) => { countdowns.push(v) },
    onConn: (c) => { conns.push(c) },
    onNavigateSession: (msg) => { nav.session += 1; nav.last = msg },
    onNavigateUpload: () => { nav.upload += 1 },
    onError: (msg) => { errors.push(msg) },
    resetFrameId: () => {},
    resetStats: () => {},
  })
  return {
    session,
    timers,
    sent,
    capture,
    nav,
    phases,
    errors,
    countdowns,
    conns,
    setOpen(v) { socketOpen = v },
  }
}

async function startThroughCountdown(h) {
  h.session.handlePrepared({ live_session_id: 'sid', resumed: false })
  await h.session.requestStart()
  h.timers.advance(COUNTDOWN_STEP_MS * 4)
}

describe('FIX-01 pending Stop', () => {
  it('sends Stop immediately when the socket is open', async () => {
    const h = harness()
    await startThroughCountdown(h)
    h.session.handleGoAck()
    h.sent.length = 0
    h.session.requestStop()
    assert.equal(h.session.pendingStop, true)
    assert.equal(h.session.phase, 'stopping')
    assert.equal(h.capture.stop, 1)
    assert.deepEqual(h.sent.map(m => m.type), ['stop'])
    assert.equal(h.session.captureStarts, 1)
  })

  it('keeps Stop intent when the socket is closed', async () => {
    const h = harness()
    await startThroughCountdown(h)
    h.session.handleGoAck()
    h.setOpen(false)
    h.sent.length = 0
    h.session.requestStop()
    assert.equal(h.session.pendingStop, true)
    assert.equal(h.sent.length, 0)
    assert.equal(h.session.shouldReconnect(), true)
    assert.equal(h.capture.start, 1)
    h.setOpen(true)
    h.session.handlePrepared({ live_session_id: 'sid', resumed: true })
    assert.deepEqual(h.sent.map(m => m.type), ['stop'])
    assert.equal(h.capture.start, 1)
    assert.equal(h.session.phase, 'stopping')
  })

  it('Stop during scheduled reconnect still sends Stop and does not recapture', async () => {
    const h = harness()
    await startThroughCountdown(h)
    h.session.handleGoAck()
    h.setOpen(false)
    h.session.handleDisconnect()
    h.session.requestStop()
    assert.equal(h.session.pendingStop, true)
    assert.equal(h.session.shouldReconnect(), true)
    h.setOpen(true)
    h.session.handlePrepared({ resumed: true })
    assert.ok(h.sent.some(m => m.type === 'stop'))
    assert.equal(h.capture.start, 1)
    h.session.handleGoAck()
    assert.equal(h.capture.start, 1)
  })

  it('reconnect after pending Stop sends Stop and does not restart capture', async () => {
    const h = harness()
    await startThroughCountdown(h)
    h.session.handleGoAck()
    const starts = h.capture.start
    h.setOpen(false)
    h.session.requestStop()
    h.session.handleDisconnect()
    h.setOpen(true)
    h.session.handlePrepared({ resumed: true })
    assert.ok(h.sent.filter(m => m.type === 'stop').length >= 1)
    assert.equal(h.capture.start, starts)
    assert.equal(h.session.hasTelemetryInterval, false)
  })

  it('leaves stopping after session_complete ack', async () => {
    const h = harness()
    await startThroughCountdown(h)
    h.session.handleGoAck()
    h.session.requestStop()
    h.session.handleSessionComplete({ result: { summary: {} }, session_id: 'hist' })
    assert.equal(h.nav.session, 1)
    assert.equal(h.session.phase, 'stopping')
    assert.equal(h.session.completed, true)
    assert.equal(h.session.shouldReconnect(), false)
  })

  it('leaves stopping after a reasonable timeout', async () => {
    const h = harness()
    await startThroughCountdown(h)
    h.session.handleGoAck()
    h.session.requestStop()
    h.timers.advance(STOP_ACK_TIMEOUT_MS)
    assert.equal(h.nav.upload, 1)
    assert.equal(h.session.completed, true)
    assert.notEqual(h.session.phase, 'stopping')
  })
})

describe('FIX-02 countdown generation', () => {
  it('sends GO on the current open socket after countdown', async () => {
    const h = harness()
    h.session.handlePrepared({})
    await h.session.requestStart()
    h.timers.advance(COUNTDOWN_STEP_MS * 4)
    assert.deepEqual(h.sent.map(m => m.type), ['go'])
    assert.equal(h.capture.start, 0)
    assert.equal(h.session.phase, 'countdown')
  })

  it('uses the socket that is open at GO time after a swap', async () => {
    const timers = createFakeTimers()
    let sink = 'a'
    const sentA = []
    const sentB = []
    const session = createLiveClientSession({
      now: timers.now,
      setTimeout: (...a) => timers.setTimeout(...a),
      clearTimeout: (id) => timers.clearTimeout(id),
      setInterval: (...a) => timers.setInterval(...a),
      clearInterval: (id) => timers.clearInterval(id),
      waitMs: async (ms) => { timers.advance(ms) },
      send: (obj) => { (sink === 'a' ? sentA : sentB).push(obj) },
      isOpen: () => true,
    })
    session.handlePrepared({})
    await session.requestStart()
    timers.advance(COUNTDOWN_STEP_MS * 2)
    sink = 'b'
    timers.advance(COUNTDOWN_STEP_MS * 2)
    assert.equal(sentA.length, 0)
    assert.deepEqual(sentB.map(m => m.type), ['go'])
  })

  it('stale countdown does not send GO', async () => {
    const h = harness()
    h.session.handlePrepared({})
    await h.session.requestStart()
    const gen = h.session.countdownGen
    h.session.handleDisconnect()
    assert.notEqual(h.session.countdownGen, gen)
    h.timers.advance(COUNTDOWN_STEP_MS * 4)
    assert.equal(h.sent.filter(m => m.type === 'go').length, 0)
    assert.equal(h.capture.start, 0)
  })

  it('does not start capture or frames before go_ack', async () => {
    const h = harness()
    await startThroughCountdown(h)
    assert.equal(h.session.goSent, true)
    assert.equal(h.session.goAcked, false)
    assert.equal(h.capture.start, 0)
    h.session.handleGoAck()
    assert.equal(h.capture.start, 1)
    assert.equal(h.session.phase, 'live')
  })

  it('sends GO only once', async () => {
    const h = harness()
    await startThroughCountdown(h)
    h.timers.advance(COUNTDOWN_STEP_MS * 4)
    assert.equal(h.sent.filter(m => m.type === 'go').length, 1)
    h.session.handleGoAck()
    h.session.handleGoAck()
    assert.equal(h.sent.filter(m => m.type === 'go').length, 1)
  })
})

describe('FIX-07 telemetry interval', () => {
  it('Start / go_ack creates one interval', async () => {
    const h = harness()
    await startThroughCountdown(h)
    h.session.handleGoAck()
    assert.equal(h.session.telemetryStarts, 1)
    assert.equal(h.timers.activeIntervals(), 1)
    h.timers.advance(TELEMETRY_MS)
    assert.ok(h.sent.some(m => m.type === 'ping'))
    assert.ok(h.sent.some(m => m.type === 'client_stats'))
  })

  it('disconnect clears the interval', async () => {
    const h = harness()
    await startThroughCountdown(h)
    h.session.handleGoAck()
    h.session.handleDisconnect()
    assert.equal(h.session.hasTelemetryInterval, false)
    assert.equal(h.timers.activeIntervals(), 0)
  })

  it('reconnect creates a single new interval', async () => {
    const h = harness()
    await startThroughCountdown(h)
    h.session.handleGoAck()
    h.session.handleDisconnect()
    h.session.handlePrepared({ resumed: true })
    assert.equal(h.session.telemetryStarts, 2)
    assert.equal(h.timers.activeIntervals(), 1)
  })

  it('multiple reconnects do not stack intervals', async () => {
    const h = harness()
    await startThroughCountdown(h)
    h.session.handleGoAck()
    for (let i = 0; i < 4; i += 1) {
      h.session.handleDisconnect()
      h.session.handlePrepared({ resumed: true })
    }
    assert.equal(h.session.telemetryStarts, 5)
    assert.equal(h.timers.activeIntervals(), 1)
  })

  it('Stop and unmount clear telemetry', async () => {
    const h = harness()
    await startThroughCountdown(h)
    h.session.handleGoAck()
    h.session.requestStop()
    assert.equal(h.session.hasTelemetryInterval, false)
    assert.equal(h.timers.activeIntervals(), 0)
    h.session.dispose()
    assert.equal(h.timers.activeIntervals(), 0)
  })
})

describe('PATCH-01 Ping/Pong clock', () => {
  it('first Ping and matching Pong compute RTT from msg.t', async () => {
    const h = harness()
    await startThroughCountdown(h)
    h.session.handleGoAck()
    const ping = h.sent.filter(m => m.type === 'ping').at(-1)
    assert.equal(typeof ping.t, 'number')
    assert.equal(ping.t, h.session.pendingPingT)
    h.timers.advance(12)
    const out = h.session.handlePong({ t: ping.t, server_t: ping.t + 4 })
    assert.ok(out)
    assert.equal(out.rtt_ms, 12)
    assert.equal(h.session.lastRtt, 12)
    assert.ok(h.sent.some(m => m.type === 'clock_offset' && m.rtt_ms === 12))
  })

  it('Ping after 30s uses a new timestamp', async () => {
    const h = harness()
    await startThroughCountdown(h)
    h.session.handleGoAck()
    const first = h.sent.filter(m => m.type === 'ping').at(-1).t
    h.timers.advance(TELEMETRY_MS)
    const second = h.sent.filter(m => m.type === 'ping').at(-1).t
    assert.equal(second, first + TELEMETRY_MS)
    assert.notEqual(second, first)
  })

  it('repeated Ping cycles do not inflate latency', async () => {
    const h = harness()
    await startThroughCountdown(h)
    h.session.handleGoAck()
    const rtts = []
    for (let i = 0; i < 3; i += 1) {
      const ping = h.sent.filter(m => m.type === 'ping').at(-1)
      h.timers.advance(8)
      const out = h.session.handlePong({ t: ping.t, server_t: ping.t })
      rtts.push(out.rtt_ms)
      h.timers.advance(TELEMETRY_MS - 8)
    }
    assert.deepEqual(rtts, [8, 8, 8])
    assert.ok(Math.max(...rtts) < 50)
  })

  it('reconnect starts a fresh ping timestamp', async () => {
    const h = harness()
    await startThroughCountdown(h)
    h.session.handleGoAck()
    const firstId = h.session.pendingPingId
    const firstT = h.session.pendingPingT
    h.session.handleDisconnect()
    assert.equal(h.session.pendingPingT, null)
    h.session.handlePrepared({ resumed: true })
    const next = h.sent.filter(m => m.type === 'ping').at(-1)
    assert.equal(h.session.pendingPingId, next.ping_id)
    assert.notEqual(next.ping_id, firstId)
    h.session.handlePong({ t: firstT, ping_id: firstId, server_t: firstT })
    assert.equal(h.session.lastOffset, null)
    const out = h.session.handlePong({ t: next.t, ping_id: next.ping_id, server_t: next.t })
    assert.ok(out)
  })

  it('stale Pong does not change offset', async () => {
    const h = harness()
    await startThroughCountdown(h)
    h.session.handleGoAck()
    const first = h.sent.filter(m => m.type === 'ping').at(-1).t
    h.session.handlePong({ t: first, server_t: first })
    const offset = h.session.lastOffset
    h.timers.advance(TELEMETRY_MS)
    const ignored = h.session.handlePong({ t: first, server_t: first - 5000 })
    assert.equal(ignored, null)
    assert.equal(h.session.lastOffset, offset)
  })

  it('does not mix epoch milliseconds with monotonic milliseconds', () => {
    const mono = rttAndOffset({ pingT: 1000, pongAt: 1016, serverT: 1002 })
    assert.equal(mono.rtt_ms, 16)
    const mixed = rttAndOffset({ pingT: 1000, pongAt: Date.now(), serverT: 1002 })
    assert.ok(mixed.rtt_ms > 1e11)
    const hNow = 5000
    const ok = rttAndOffset({ pingT: hNow, pongAt: hNow + 9, serverT: hNow })
    assert.equal(ok.rtt_ms, 9)
  })
})

describe('PATCH-02 prepared resumed flag', () => {
  it('prepared resumed=true restarts capture once', async () => {
    const h = harness()
    await startThroughCountdown(h)
    h.session.handleGoAck()
    assert.equal(h.capture.start, 1)
    h.session.handleDisconnect()
    h.session.handlePrepared({ resumed: true })
    assert.equal(h.capture.start, 2)
    assert.equal(h.session.goAcked, true)
    assert.ok(h.conns.includes('live'))
  })

  it('prepared resumed=false does not recapture before a new GO', async () => {
    const h = harness()
    await startThroughCountdown(h)
    h.session.handleGoAck()
    const starts = h.capture.start
    h.sent.length = 0
    const countdownMark = h.countdowns.length
    h.session.handleDisconnect()
    h.session.handlePrepared({ resumed: false })
    assert.equal(h.capture.start, starts)
    assert.equal(h.session.goAcked, false)
    assert.ok(h.sent.some(m => m.type === 'go'))
    assert.ok(h.conns.includes('reconnecting'))
    assert.ok(!h.conns.slice(-1).includes('live'))
    assert.equal(h.countdowns.slice(countdownMark).includes(3), false)
    assert.equal(h.countdowns.slice(countdownMark).includes(2), false)
    assert.equal(h.countdowns.slice(countdownMark).includes(1), false)
  })

  it('frames stay gated until the new go_ack after resumed=false', async () => {
    const h = harness()
    await startThroughCountdown(h)
    h.session.handleGoAck()
    h.session.handleDisconnect()
    h.session.handlePrepared({ resumed: false })
    assert.equal(h.session.goAcked, false)
    assert.equal(h.session.handleShotDecided(), false)
    const starts = h.capture.start
    h.session.handleGoAck()
    assert.equal(h.session.goAcked, true)
    assert.equal(h.capture.start, starts + 1)
    assert.equal(h.session.handleShotDecided(), true)
    assert.equal(h.session.statsResets, 1)
  })
})

describe('FINAL-02 go_error retry', () => {
  it('go_error on first start shows a retryable phase, not stuck countdown', async () => {
    const h = harness()
    await startThroughCountdown(h)
    h.session.handleGoError({ message: 'Could not create the live session. Try Start again.' })
    assert.equal(h.session.phase, 'go_error')
    assert.notEqual(h.session.phase, 'countdown')
    assert.equal(h.session.goAcked, false)
    assert.equal(h.session.reactivateWithoutCountdown, false)
    assert.ok(h.errors.some(e => e && String(e).includes('Try Start again')))
    assert.notEqual(h.conns.at(-1), 'live')
  })

  it('retry after first-start go_error sends a new GO and waits for go_ack', async () => {
    const h = harness()
    await startThroughCountdown(h)
    h.session.handleGoError({ message: 'fail' })
    h.sent.length = 0
    h.session.retryStart()
    h.timers.advance(COUNTDOWN_STEP_MS * 4)
    assert.deepEqual(h.sent.filter(m => m.type === 'go').map(m => m.type), ['go'])
    assert.equal(h.capture.start, 0)
    h.session.handleGoAck()
    assert.equal(h.capture.start, 1)
    assert.equal(h.session.phase, 'live')
  })

  it('go_error during reactivation clears reactivateWithoutCountdown', async () => {
    const h = harness()
    await startThroughCountdown(h)
    h.session.handleGoAck()
    h.session.handleDisconnect()
    h.session.handlePrepared({ resumed: false })
    assert.equal(h.session.reactivateWithoutCountdown, true)
    h.session.handleGoError({ message: 'fail' })
    assert.equal(h.session.phase, 'go_error')
    assert.equal(h.session.reactivateWithoutCountdown, false)
    assert.equal(h.session.retryFromReactivate, true)
  })

  it('retry after reactivation sends one GO and no extra countdown', async () => {
    const h = harness()
    await startThroughCountdown(h)
    h.session.handleGoAck()
    h.session.handleDisconnect()
    h.session.handlePrepared({ resumed: false })
    h.session.handleGoError({ message: 'fail' })
    const threes = h.countdowns.filter(v => v === 3).length
    h.sent.length = 0
    h.session.retryStart()
    h.session.retryStart()
    assert.deepEqual(h.sent.filter(m => m.type === 'go').map(m => m.type), ['go'])
    assert.equal(h.countdowns.filter(v => v === 3).length, threes)
    assert.equal(h.capture.start, 1)
    h.session.handleGoAck()
    assert.equal(h.capture.start, 2)
  })

  it('Stop works from the go_error state', async () => {
    const h = harness()
    await startThroughCountdown(h)
    h.session.handleGoError({ message: 'fail' })
    h.sent.length = 0
    h.session.requestStop()
    assert.equal(h.session.phase, 'stopping')
    assert.deepEqual(h.sent.map(m => m.type), ['stop'])
  })
})


