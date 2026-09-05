/** Live client session controller (FIX-01 / FIX-02 / FIX-07 / PATCH-01 / PATCH-02). Inject timers/IO for tests. */

export const COUNTDOWN_STEP_MS = 700
export const STOP_ACK_TIMEOUT_MS = 12000
export const TELEMETRY_MS = 30000
export const COUNTDOWN_STEPS = [3, 2, 1, 'GO']

export function monotonicNow() {
  if (typeof performance !== 'undefined' && typeof performance.now === 'function') {
    return performance.now()
  }
  return 0
}

/** RTT/offset from one monotonic clock. Never mix Date.now() epoch ms into this. */
export function rttAndOffset({ pingT, pongAt, serverT }) {
  const rtt = pongAt - pingT
  return {
    rtt_ms: rtt,
    offset_ms: pingT + rtt / 2 - serverT,
  }
}

export function createLiveClientSession(deps = {}) {
  const send = deps.send || (() => {})
  const isOpen = deps.isOpen || (() => false)
  const startCapture = deps.startCapture || (() => {})
  const stopCapture = deps.stopCapture || (() => {})
  const onPhase = deps.onPhase || (() => {})
  const onCountdown = deps.onCountdown || (() => {})
  const onConn = deps.onConn || (() => {})
  const onError = deps.onError || (() => {})
  const onNavigateSession = deps.onNavigateSession || (() => {})
  const onNavigateUpload = deps.onNavigateUpload || (() => {})
  const resetFrameId = deps.resetFrameId || (() => {})
  const resetStats = deps.resetStats || (() => {})
  const getStats = deps.getStats || (() => ({ captured: 0, sent: 0, dropped: 0 }))
  const enterLive = deps.enterLive || (() => {})
  const enterCountdown = deps.enterCountdown || (() => {})
  const enterStopping = deps.enterStopping || (() => {})
  const resetGate = deps.resetGate || (() => {})
  const now = deps.now || monotonicNow
  const sto = deps.setTimeout || setTimeout
  const cto = deps.clearTimeout || clearTimeout
  const siv = deps.setInterval || setInterval
  const civ = deps.clearInterval || clearInterval
  const waitMs = deps.waitMs || ((ms) => new Promise(r => sto(r, ms)))

  let pendingStop = false
  let startRequested = false
  let prepared = false
  let goSent = false
  let goAcked = false
  let completed = false
  let disposed = false
  let reactivateWithoutCountdown = false
  let retryFromReactivate = false
  let countdownGen = 0
  let countdownTimer = null
  let stopTimer = null
  let telemetryTimer = null
  let telemetryStarts = 0
  let captureStarts = 0
  let sent = []
  let phase = 'preview'
  let pendingPing = null
  let lastRtt = null
  let lastOffset = null
  let statsResets = 0
  let pingId = 0

  function recordSend(obj) {
    sent.push(obj)
    send(obj)
  }

  function setPhase(next) {
    phase = next
    onPhase(next)
  }

  function cancelCountdownTimers() {
    if (countdownTimer != null) {
      cto(countdownTimer)
      countdownTimer = null
    }
  }

  function invalidateCountdown() {
    countdownGen += 1
    cancelCountdownTimers()
    onCountdown(null)
  }

  function stopTelemetry() {
    if (telemetryTimer != null) {
      civ(telemetryTimer)
      telemetryTimer = null
    }
  }

  function sendPing() {
    if (!isOpen() || pendingStop || completed || disposed) return null
    pingId += 1
    const t = now()
    pendingPing = { t, ping_id: pingId }
    recordSend({ type: 'ping', t, ping_id: pingId })
    return pendingPing
  }

  function startTelemetry() {
    stopTelemetry()
    if (pendingStop || completed || disposed) return
    telemetryStarts += 1
    sendPing()
    telemetryTimer = siv(() => {
      if (!isOpen() || pendingStop || completed || disposed) return
      sendPing()
      const stats = getStats()
      recordSend({
        type: 'client_stats',
        frames_captured: stats.captured,
        frames_sent: stats.sent,
        frames_dropped_client: stats.dropped,
      })
    }, TELEMETRY_MS)
  }

  function haltLocal() {
    invalidateCountdown()
    stopCapture()
    stopTelemetry()
    pendingPing = null
  }

  function ensureStopTimeout() {
    if (stopTimer != null) return
    stopTimer = sto(() => {
      stopTimer = null
      if (completed || disposed) return
      onError('Stop timed out — returning without a live summary.')
      completed = true
      haltLocal()
      setPhase('preview')
      resetGate()
      onNavigateUpload()
    }, STOP_ACK_TIMEOUT_MS)
  }

  function sendStopIfOpen() {
    if (!isOpen()) return false
    recordSend({ type: 'stop' })
    return true
  }

  function sendGo(gen) {
    if (gen !== countdownGen) return
    if (pendingStop || completed || disposed) return
    if (goAcked) return
    if (goSent) return
    if (!isOpen()) {
      onError('Connection lost during countdown.')
      setPhase('preview')
      resetGate()
      return
    }
    goSent = true
    recordSend({ type: 'go' })
  }

  function requestGoHandshake() {
    if (pendingStop || completed || disposed) return
    if (goAcked || goSent) return
    if (!isOpen()) {
      onError('Connection lost — cannot activate Live.')
      onConn('reconnecting')
      return
    }
    goSent = true
    recordSend({ type: 'go' })
  }

  function startCountdown() {
    if (pendingStop || !startRequested || completed || disposed) return
    if (reactivateWithoutCountdown) return
    invalidateCountdown()
    const gen = countdownGen
    enterCountdown()
    setPhase('countdown')
    let i = 0
    const step = () => {
      if (gen !== countdownGen || pendingStop || completed || disposed) return
      if (reactivateWithoutCountdown) return
      if (i >= COUNTDOWN_STEPS.length) {
        sendGo(gen)
        return
      }
      const value = COUNTDOWN_STEPS[i]
      onCountdown(value)
      i += 1
      countdownTimer = sto(step, COUNTDOWN_STEP_MS)
    }
    step()
  }

  function beginCapture() {
    if (pendingStop || !goAcked || completed || disposed) return
    captureStarts += 1
    startCapture()
  }

  function wrappedResetStats() {
    statsResets += 1
    resetStats()
  }

  return {
    get pendingStop() { return pendingStop },
    get startRequested() { return startRequested },
    get goSent() { return goSent },
    get goAcked() { return goAcked },
    get countdownGen() { return countdownGen },
    get phase() { return phase },
    get telemetryStarts() { return telemetryStarts },
    get captureStarts() { return captureStarts },
    get hasTelemetryInterval() { return telemetryTimer != null },
    get sent() { return sent },
    get completed() { return completed },
    get pendingPingT() { return pendingPing ? pendingPing.t : null },
    get pendingPingId() { return pendingPing ? pendingPing.ping_id : null },
    get lastRtt() { return lastRtt },
    get lastOffset() { return lastOffset },
    get statsResets() { return statsResets },
    get reactivateWithoutCountdown() { return reactivateWithoutCountdown },
    get retryFromReactivate() { return retryFromReactivate },

    shouldReconnect() {
      if (disposed || completed) return false
      return true
    },

    sendPing,

    handlePong(msg) {
      if (!pendingPing || !msg) return null
      if (msg.ping_id != null && msg.ping_id !== pendingPing.ping_id) return null
      if (msg.ping_id == null && msg.t !== pendingPing.t) return null
      const serverT = msg.server_t
      if (typeof serverT !== 'number') return null
      const pingT = pendingPing.t
      const pongAt = now()
      const out = rttAndOffset({ pingT, pongAt, serverT })
      lastRtt = out.rtt_ms
      lastOffset = out.offset_ms
      pendingPing = null
      recordSend({ type: 'clock_offset', offset_ms: out.offset_ms, rtt_ms: out.rtt_ms })
      return out
    },

    async requestStart() {
      if (pendingStop || completed || disposed) return
      startRequested = true
      onError(null)
      const deadline = now() + 20000
      while (!prepared && now() < deadline && !pendingStop && !disposed) {
        await waitMs(100)
      }
      if (pendingStop || disposed) return
      if (!isOpen() || !prepared) {
        onError('Waiting for server…')
        return
      }
      startCountdown()
    },

    requestStop() {
      if (completed || disposed) return
      pendingStop = true
      startRequested = false
      haltLocal()
      enterStopping()
      setPhase('stopping')
      onConn('stopping')
      sendStopIfOpen()
      ensureStopTimeout()
    },

    handleDisconnect() {
      stopTelemetry()
      stopCapture()
      invalidateCountdown()
      pendingPing = null
      if (goSent && !goAcked) goSent = false
      if (!pendingStop && !completed && !disposed) {
        onConn('reconnecting')
      }
    },

    handlePrepared(msg) {
      prepared = true
      const resumed = !!(msg && msg.resumed === true)
      if (pendingStop) {
        enterStopping()
        setPhase('stopping')
        sendStopIfOpen()
        ensureStopTimeout()
        return
      }
      if (resumed) {
        if (goAcked) {
          onConn('live')
          setPhase('live')
          startTelemetry()
          stopCapture()
          beginCapture()
          return
        }
        onConn('prepared')
        if (startRequested) startCountdown()
        return
      }
      if (goAcked || reactivateWithoutCountdown || goSent) {
        stopCapture()
        stopTelemetry()
        goAcked = false
        goSent = false
        reactivateWithoutCountdown = true
        resetGate()
        onConn('reconnecting')
        setPhase('countdown')
        onCountdown(null)
        requestGoHandshake()
        return
      }
      onConn('prepared')
      if (startRequested) startCountdown()
    },

    handleGoAck() {
      if (pendingStop) {
        sendStopIfOpen()
        ensureStopTimeout()
        return
      }
      if (goAcked) {
        startTelemetry()
        return
      }
      const skipHudReset = reactivateWithoutCountdown
      goAcked = true
      goSent = true
      reactivateWithoutCountdown = false
      retryFromReactivate = false
      resetFrameId()
      if (!skipHudReset) wrappedResetStats()
      enterLive()
      setPhase('live')
      onConn('live')
      onCountdown('GO')
      sto(() => onCountdown(null), 450)
      beginCapture()
      startTelemetry()
    },

    handleGoError(msg) {
      const wasReactivate = reactivateWithoutCountdown
      goSent = false
      goAcked = false
      reactivateWithoutCountdown = false
      retryFromReactivate = wasReactivate
      startRequested = true
      invalidateCountdown()
      stopCapture()
      stopTelemetry()
      pendingPing = null
      resetGate()
      onConn('prepared')
      setPhase('go_error')
      onCountdown(null)
      onError((msg && msg.message) || 'Could not start the live session. Try Start again.')
    },

    retryStart() {
      if (pendingStop || completed || disposed) return
      if (phase !== 'go_error' && phase !== 'preview') return
      onError(null)
      if (!isOpen() || !prepared) {
        onError('Waiting for server…')
        setPhase('go_error')
        return
      }
      if (retryFromReactivate) {
        reactivateWithoutCountdown = true
        requestGoHandshake()
        return
      }
      startRequested = true
      startCountdown()
    },

    handleSessionComplete(msg) {
      completed = true
      pendingStop = false
      haltLocal()
      if (stopTimer != null) {
        cto(stopTimer)
        stopTimer = null
      }
      enterStopping()
      setPhase('stopping')
      if (!goAcked) {
        resetGate()
        onNavigateUpload()
        return
      }
      onNavigateSession(msg)
    },

    handleShotDecided() {
      return !pendingStop && goAcked && !completed
    },

    dispose() {
      disposed = true
      pendingStop = true
      startRequested = false
      haltLocal()
      if (stopTimer != null) {
        cto(stopTimer)
        stopTimer = null
      }
    },
  }
}
