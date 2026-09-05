/** Live client session controller (FIX-01 / FIX-02 / FIX-07). Inject timers/IO for tests. */

export const COUNTDOWN_STEP_MS = 700
export const STOP_ACK_TIMEOUT_MS = 12000
export const TELEMETRY_MS = 30000
export const COUNTDOWN_STEPS = [3, 2, 1, 'GO']

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
  const now = deps.now || (() => Date.now())
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
  let countdownGen = 0
  let countdownTimer = null
  let stopTimer = null
  let telemetryTimer = null
  let telemetryStarts = 0
  let captureStarts = 0
  let sent = []
  let phase = 'preview'

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

  function startTelemetry() {
    stopTelemetry()
    if (pendingStop || completed || disposed) return
    telemetryStarts += 1
    telemetryTimer = siv(() => {
      if (!isOpen() || pendingStop || completed || disposed) return
      const t = now()
      recordSend({ type: 'ping', t })
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

  function startCountdown() {
    if (pendingStop || !startRequested || completed || disposed) return
    invalidateCountdown()
    const gen = countdownGen
    enterCountdown()
    setPhase('countdown')
    let i = 0
    const step = () => {
      if (gen !== countdownGen || pendingStop || completed || disposed) return
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

    shouldReconnect() {
      if (disposed || completed) return false
      return true
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
      if (goSent && !goAcked) goSent = false
      if (!pendingStop && !completed && !disposed) {
        onConn('reconnecting')
      }
    },

    handlePrepared(msg) {
      prepared = true
      if (pendingStop) {
        enterStopping()
        setPhase('stopping')
        sendStopIfOpen()
        ensureStopTimeout()
        return
      }
      if (goAcked) {
        onConn('live')
        setPhase('live')
        startTelemetry()
        beginCapture()
        return
      }
      onConn('prepared')
      if (startRequested) {
        startCountdown()
      }
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
      goAcked = true
      goSent = true
      resetFrameId()
      resetStats()
      enterLive()
      setPhase('live')
      onConn('live')
      onCountdown('GO')
      sto(() => onCountdown(null), 450)
      beginCapture()
      startTelemetry()
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
