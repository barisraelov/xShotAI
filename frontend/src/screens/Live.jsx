import { useEffect, useRef, useState } from 'react'
import { getToken, isAuthed } from '../auth'
import { createLiveGate } from '../live/gate'
import { packFrame, frameHeader, JPEG_QUALITY } from '../live/protocol'
import {
  delayedBannerText,
  loadSounds,
  playDecisionSound,
  unlockSounds,
  createPlayedSet,
} from '../live/audio'
import { liveWsUrl, liveConfigBlocked } from '../live/wsUrl'
import { createLiveClientSession } from '../live/clientSession'
import './Live.css'

const BUFFER_LIMIT = 512 * 1024
const HUMAN_OVERLOAD = 'החיבור או העיבוד איטיים כרגע — ייתכן עיכוב בזיהוי.'

function formatTime(ms) {
  const s = Math.max(0, Math.floor(ms / 1000))
  const m = Math.floor(s / 60)
  return `${m}:${String(s % 60).padStart(2, '0')}`
}

function connLabel(state) {
  if (state === 'live') return 'Connected'
  if (state === 'prepared') return 'Ready'
  if (state === 'connecting' || state === 'preview') return 'Connecting'
  if (state === 'reconnecting') return 'Reconnecting'
  if (state === 'stopping') return 'Stopping'
  return 'Offline'
}

export default function Live({ navigate }) {
  const videoRef = useRef(null)
  const wsRef = useRef(null)
  const gateRef = useRef(createLiveGate())
  const soundsRef = useRef(null)
  const playedRef = useRef(null)
  const frameIdRef = useRef(0)
  const encodingRef = useRef(false)
  const captureStopRef = useRef(null)
  const liveSessionIdRef = useRef(null)
  const goAtRef = useRef(null)
  const statsRef = useRef({ captured: 0, sent: 0, dropped: 0 })
  const reconnectTimer = useRef(null)
  const mutedRef = useRef(false)
  const handlerRef = useRef(null)
  const sessionRef = useRef(null)

  const [phase, setPhase] = useState('preview')
  const [countdown, setCountdown] = useState(null)
  const [conn, setConn] = useState('preview')
  const [attempts, setAttempts] = useState(0)
  const [makes, setMakes] = useState(0)
  const [misses, setMisses] = useState(0)
  const [last, setLast] = useState(null)
  const [muted, setMuted] = useState(false)
  const [degraded, setDegraded] = useState(false)
  const [prompt, setPrompt] = useState(false)
  const [banner, setBanner] = useState(null)
  const [err, setErr] = useState(null)
  const [tick, setTick] = useState(0)
  const [trackInfo, setTrackInfo] = useState(null)

  if (!sessionRef.current) {
    sessionRef.current = createLiveClientSession({
      send(obj) {
        const ws = wsRef.current
        if (ws && ws.readyState === 1) ws.send(JSON.stringify(obj))
      },
      isOpen() {
        return wsRef.current?.readyState === 1
      },
      startCapture() {
        startCapture()
      },
      stopCapture() {
        captureStopRef.current?.()
      },
      onPhase: setPhase,
      onCountdown: setCountdown,
      onConn: setConn,
      onError: setErr,
      onNavigateSession(msg) {
        navigate('session', {
          result: msg.result,
          jobId: msg.session_id || liveSessionIdRef.current,
          error: null,
        })
      },
      onNavigateUpload() {
        navigate('upload')
      },
      resetFrameId() {
        frameIdRef.current = 0
        goAtRef.current = Date.now()
      },
      resetStats() {
        statsRef.current = { captured: 0, sent: 0, dropped: 0 }
      },
      getStats() {
        return statsRef.current
      },
      enterLive() {
        gateRef.current.enterLive()
      },
      enterCountdown() {
        gateRef.current.enterCountdown()
      },
      enterStopping() {
        gateRef.current.enterStopping()
      },
      resetGate() {
        gateRef.current.reset()
      },
    })
  }

  useEffect(() => { mutedRef.current = muted }, [muted])

  useEffect(() => {
    soundsRef.current = loadSounds()
  }, [])

  useEffect(() => {
    if (!isAuthed()) {
      navigate('login')
      return undefined
    }
    const blocked = liveConfigBlocked()
    if (blocked) {
      setErr(blocked.message)
      return undefined
    }
    let stream
    let cancelled = false
    async function openCamera() {
      try {
        stream = await navigator.mediaDevices.getUserMedia({
          audio: false,
          video: {
            facingMode: { ideal: 'environment' },
            width: { ideal: 1280 },
            height: { ideal: 720 },
            frameRate: { ideal: 30, max: 30 },
          },
        })
        if (cancelled) {
          stream.getTracks().forEach(t => t.stop())
          return
        }
        const video = videoRef.current
        if (video) {
          video.srcObject = stream
          await video.play().catch(() => {})
        }
        const track = stream.getVideoTracks()[0]
        const settings = track?.getSettings?.() || {}
        setTrackInfo({
          width: settings.width || video?.videoWidth,
          height: settings.height || video?.videoHeight,
          fps: settings.frameRate,
        })
      } catch (e) {
        setErr(e.message || 'Camera permission denied')
      }
    }
    openCamera()
    connectWs()
    return () => {
      cancelled = true
      sessionRef.current?.dispose()
      stream?.getTracks().forEach(t => t.stop())
      captureStopRef.current?.()
      clearTimeout(reconnectTimer.current)
      try { wsRef.current?.close() } catch { /* ignore */ }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (phase !== 'live') return undefined
    const id = setInterval(() => setTick(t => t + 1), 250)
    return () => clearInterval(id)
  }, [phase])

  function handleMessage(msg) {
    const session = sessionRef.current
    if (msg.type === 'prepared') {
      liveSessionIdRef.current = msg.live_session_id
      playedRef.current = createPlayedSet(msg.live_session_id, window.sessionStorage)
      session.handlePrepared(msg)
    } else if (msg.type === 'pong') {
      session.handlePong(msg)
    } else if (msg.type === 'go_ack') {
      session.handleGoAck()
    } else if (msg.type === 'go_error') {
      session.handleGoError(msg)
    } else if (msg.type === 'shot_decided') {
      if (!session.handleShotDecided()) return
      const played = playedRef.current || createPlayedSet(liveSessionIdRef.current, window.sessionStorage)
      playedRef.current = played
      const sounds = soundsRef.current
      const out = sounds
        ? playDecisionSound(sounds, {
            shotId: msg.shot_id,
            result: msg.result,
            decidedAtUnixMs: msg.decided_at_unix_ms,
            muted: mutedRef.current,
            played,
          })
        : { kind: null, already: true }
      if (wsRef.current?.readyState === 1) {
        wsRef.current.send(JSON.stringify({ type: 'decision_ack', shot_id: msg.shot_id }))
      }
      if (!out.already) {
        setAttempts(n => n + 1)
        if (msg.result === 'made') setMakes(n => n + 1)
        else setMisses(n => n + 1)
        setLast(msg.result)
        if (out.kind === 'delayed') setBanner(delayedBannerText(msg.result))
      }
    } else if (msg.type === 'status') {
      setDegraded(!!msg.degraded)
      if (!msg.degraded) setPrompt(false)
    } else if (msg.type === 'overload_prompt') {
      setPrompt(true)
      setDegraded(true)
    } else if (msg.type === 'session_complete') {
      session.handleSessionComplete(msg)
    } else if (msg.type === 'error') {
      setErr(msg.message || 'Live connection error')
    }
  }

  handlerRef.current = handleMessage

  function connectWs() {
    const blocked = liveConfigBlocked()
    if (blocked) {
      setErr(blocked.message)
      return
    }
    setConn(liveSessionIdRef.current ? 'reconnecting' : 'connecting')
    let ws
    try {
      ws = new WebSocket(liveWsUrl())
    } catch (e) {
      setErr(e.message || 'Live is not configured')
      return
    }
    ws.binaryType = 'arraybuffer'
    wsRef.current = ws
    ws.onopen = () => {
      ws.send(JSON.stringify({ type: 'auth', access_token: getToken() }))
      const prepare = { type: 'prepare' }
      if (liveSessionIdRef.current) prepare.live_session_id = liveSessionIdRef.current
      ws.send(JSON.stringify(prepare))
      sessionRef.current?.sendPing()
    }
    ws.onmessage = (ev) => {
      if (typeof ev.data !== 'string') return
      try { handlerRef.current?.(JSON.parse(ev.data)) } catch { /* ignore */ }
    }
    ws.onclose = () => {
      sessionRef.current?.handleDisconnect()
      if (!sessionRef.current?.shouldReconnect()) return
      setConn('reconnecting')
      reconnectTimer.current = setTimeout(connectWs, 250)
    }
  }

  function startCapture() {
    captureStopRef.current?.()
    const video = videoRef.current
    const canvas = document.createElement('canvas')
    const ctx = canvas.getContext('2d', { alpha: false })
    let stopped = false
    captureStopRef.current = () => { stopped = true }

    const onFrame = (now, metadata) => {
      if (stopped) return
      const loop = () => {
        if (video.requestVideoFrameCallback) video.requestVideoFrameCallback(onFrame)
        else requestAnimationFrame(() => onFrame(performance.now()))
      }
      if (!gateRef.current.canSendFrames() || sessionRef.current?.pendingStop) {
        loop()
        return
      }
      statsRef.current.captured += 1
      const id = frameIdRef.current
      frameIdRef.current += 1
      const ws = wsRef.current
      if (!ws || ws.readyState !== 1 || encodingRef.current || ws.bufferedAmount > BUFFER_LIMIT) {
        statsRef.current.dropped += 1
        loop()
        return
      }
      const w = video.videoWidth
      const h = video.videoHeight
      if (!w || !h) {
        loop()
        return
      }
      canvas.width = w
      canvas.height = h
      ctx.drawImage(video, 0, 0, w, h)
      encodingRef.current = true
      const tEnc = performance.now()
      canvas.toBlob((blob) => {
        encodingRef.current = false
        if (stopped || !blob || !gateRef.current.canSendFrames() || sessionRef.current?.pendingStop) {
          if (!blob) statsRef.current.dropped += 1
          return
        }
        blob.arrayBuffer().then((buf) => {
          if (stopped || !gateRef.current.canSendFrames() || sessionRef.current?.pendingStop) return
          const header = frameHeader({
            liveSessionId: liveSessionIdRef.current,
            frameId: id,
            captureTs: metadata?.expectedDisplayTime || now || performance.now(),
            width: w,
            height: h,
            jpegQuality: JPEG_QUALITY,
            bufferedAmount: ws.bufferedAmount,
          })
          ws.send(packFrame(header, new Uint8Array(buf)))
          statsRef.current.sent += 1
          if (performance.now() - tEnc > 80) {
            /* encode duration tracked for LIVE-06; no adaptive quality */
          }
        }).catch(() => { statsRef.current.dropped += 1 })
      }, 'image/jpeg', JPEG_QUALITY)
      loop()
    }

    if (video.requestVideoFrameCallback) video.requestVideoFrameCallback(onFrame)
    else requestAnimationFrame(() => onFrame(performance.now()))
  }

  async function handleStart() {
    setErr(null)
    if (soundsRef.current) await unlockSounds(soundsRef.current)
    await sessionRef.current.requestStart()
  }

  function handleStop() {
    sessionRef.current.requestStop()
  }

  function handleContinue() {
    setPrompt(false)
    if (wsRef.current?.readyState === 1) {
      wsRef.current.send(JSON.stringify({ type: 'continue' }))
    }
  }

  const elapsed = goAtRef.current && phase === 'live' ? Date.now() - goAtRef.current : 0
  void tick

  return (
    <div className="live-root">
      <video
        ref={videoRef}
        className="live-video"
        playsInline
        muted
        autoPlay
      />

      <div className="live-hud">
        <div className="live-meta">
          <div className={`live-conn${conn === 'live' ? ' ok' : conn === 'reconnecting' ? ' warn' : ''}`}>
            {connLabel(conn)}
          </div>
          <div className="live-time">{phase === 'live' ? formatTime(elapsed) : '0:00'}</div>
          {trackInfo && (
            <div className="live-time">
              {trackInfo.width}×{trackInfo.height}
              {trackInfo.fps ? ` · ${Math.round(trackInfo.fps)}fps` : ''}
            </div>
          )}
        </div>
        <div className="live-stats">
          <div className="live-stat">
            <div className="live-stat-value">{attempts}</div>
            <div className="live-stat-label">Attempts</div>
          </div>
          <div className="live-stat">
            <div className="live-stat-value">{makes}</div>
            <div className="live-stat-label">Makes</div>
          </div>
          <div className="live-stat">
            <div className="live-stat-value">{misses}</div>
            <div className="live-stat-label">Misses</div>
          </div>
        </div>
      </div>

      {degraded && (
        <div className="live-banner">{HUMAN_OVERLOAD}</div>
      )}
      {banner && !degraded && (
        <div className="live-banner">{banner}</div>
      )}

      {countdown != null && (
        <div className="live-countdown">{countdown}</div>
      )}

      {err && <div className="error-box live-err">{err}</div>}

      {prompt && (
        <div className="live-prompt">
          <p>החיבור או העיבוד מתקשים לעמוד בקצב. להמשיך או לסיים את הסשן?</p>
          <div className="live-prompt-actions">
            <button className="btn" type="button" onClick={handleContinue}>Continue</button>
            <button className="btn btn-primary" type="button" onClick={handleStop}>Stop</button>
          </div>
        </div>
      )}

      {phase === 'preview' && !liveConfigBlocked() && (
        <button className="btn btn-primary live-start" type="button" onClick={handleStart}>
          Start Live
        </button>
      )}

      <div className="live-actions">
        <div className={`live-last${last ? ` ${last}` : ''}`}>
          {last === 'made' ? 'Make' : last === 'missed' ? 'Miss' : '—'}
        </div>
        <div className="live-btn-row">
          <button
            className="live-icon-btn"
            type="button"
            aria-label={muted ? 'Unmute' : 'Mute'}
            onClick={() => setMuted(m => !m)}
          >
            {muted ? '🔇' : '🔊'}
          </button>
          <button className="live-stop" type="button" onClick={handleStop}>Stop</button>
        </div>
      </div>
    </div>
  )
}
