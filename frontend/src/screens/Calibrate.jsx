/**
 * DORMANT — not in the main navigation flow.
 *
 * Manual click-based calibration is NOT the intended product UX.
 * The product direction is automatic court / lane-corner detection → homography.
 * This file is retained as a safety-net fallback only.
 * Do not import or route to this screen unless automatic detection has failed
 * and a manual override is explicitly approved.
 *
 * See next_steps.md step 6 for the automatic detection roadmap.
 */
import { useEffect, useRef, useState } from 'react'
import { postAnalyze } from '../api'
import './Calibrate.css'

/**
 * 4 canonical court reference points in normalized_0_1 space.
 * y=0 near hoop/backboard, y=1 far end; x=0 left sideline, x=1 right.
 * Matches the CourtCoord convention frozen in analyze_result_spec.md.
 */
const REFS = [
  { label: 'Left baseline corner',  court_ref: { x: 0.0, y: 0.0 } },
  { label: 'Right baseline corner', court_ref: { x: 1.0, y: 0.0 } },
  { label: 'Left far corner',       court_ref: { x: 0.0, y: 1.0 } },
  { label: 'Right far corner',      court_ref: { x: 1.0, y: 1.0 } },
]

/** Extract the first readable frame from a video File as an offscreen canvas. */
function extractFrame(file) {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file)
    const video = document.createElement('video')
    video.muted = true
    video.playsInline = true
    video.preload = 'metadata'

    video.onerror = () => {
      URL.revokeObjectURL(url)
      reject(new Error('Cannot load video — try a different file.'))
    }

    video.onloadedmetadata = () => {
      // Seek slightly past 0 to avoid blank frames on some codecs
      video.currentTime = Math.min(0.1, video.duration / 2)
    }

    video.onseeked = () => {
      const tmp = document.createElement('canvas')
      tmp.width  = video.videoWidth  || 1280
      tmp.height = video.videoHeight || 720
      tmp.getContext('2d').drawImage(video, 0, 0)
      URL.revokeObjectURL(url)
      resolve({ frameCanvas: tmp, w: tmp.width, h: tmp.height })
    }

    video.src = url
  })
}

/** Redraw the frame and all click markers onto the visible canvas. */
function redraw(canvas, frameCanvas, clicks) {
  const ctx = canvas.getContext('2d')
  ctx.drawImage(frameCanvas, 0, 0)

  clicks.forEach(({ u, v }, i) => {
    const r = Math.max(10, Math.round(frameCanvas.width / 55))

    // Filled circle
    ctx.beginPath()
    ctx.arc(u, v, r, 0, 2 * Math.PI)
    ctx.fillStyle = 'rgba(255, 107, 44, 0.88)'
    ctx.fill()

    // White border
    ctx.strokeStyle = '#fff'
    ctx.lineWidth = Math.max(2, Math.round(r / 5))
    ctx.stroke()

    // Number label
    ctx.fillStyle = '#fff'
    ctx.font = `bold ${Math.round(r * 1.15)}px sans-serif`
    ctx.textAlign = 'center'
    ctx.textBaseline = 'middle'
    ctx.fillText(String(i + 1), u, v)
  })
}

export default function Calibrate({ navigate, file }) {
  const canvasRef  = useRef(null)
  const frameRef   = useRef(null)   // { frameCanvas, w, h }

  const [ready,      setReady]      = useState(false)
  const [clicks,     setClicks]     = useState([])
  const [submitting, setSubmitting] = useState(false)
  const [err,        setErr]        = useState(null)

  // Guard: if somehow reached without a file, send back to Upload
  useEffect(() => {
    if (!file) navigate('upload')
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  // Extract first frame on mount
  useEffect(() => {
    if (!file) return
    extractFrame(file)
      .then(({ frameCanvas, w, h }) => {
        frameRef.current = { frameCanvas, w, h }
        const canvas = canvasRef.current
        if (canvas) { canvas.width = w; canvas.height = h }
        setReady(true)
      })
      .catch(e => setErr(e.message))
  }, [file]) // eslint-disable-line react-hooks/exhaustive-deps

  // Redraw whenever clicks change or frame first becomes ready
  useEffect(() => {
    const f = frameRef.current
    const canvas = canvasRef.current
    if (!ready || !f || !canvas) return
    canvas.width  = f.w
    canvas.height = f.h
    redraw(canvas, f.frameCanvas, clicks)
  }, [ready, clicks])

  function handleCanvasClick(e) {
    if (clicks.length >= REFS.length || !ready) return
    const canvas = canvasRef.current
    const rect   = canvas.getBoundingClientRect()
    const scaleX = canvas.width  / rect.width
    const scaleY = canvas.height / rect.height
    const u = Math.round((e.clientX - rect.left) * scaleX)
    const v = Math.round((e.clientY - rect.top)  * scaleY)
    setClicks(prev => [...prev, { u, v }])
  }

  async function submit(calibrationPointsJson) {
    setSubmitting(true)
    setErr(null)
    try {
      const { job_id } = await postAnalyze(file, calibrationPointsJson)
      // Clear file from state immediately — no need to hold the large object
      navigate('analyzing', { jobId: job_id, result: null, error: null, file: null })
    } catch (e) {
      setErr(e.message)
      setSubmitting(false)
    }
  }

  function handleConfirm() {
    const pts = clicks.map((px, i) => ({
      pixel:     { u: px.u, v: px.v },
      court_ref: REFS[i].court_ref,
    }))
    submit(JSON.stringify(pts))
  }

  function handleSkip() {
    submit(null)  // omit calibration_points; backend treats as null per spec
  }

  if (!file) return null

  const complete = clicks.length === REFS.length
  const nextRef  = REFS[clicks.length]

  return (
    <div className="screen-enter calibrate-screen">
      <div className="top-bar">
        <div className="logo"><span className="logo-icon">🏀</span> xShot AI</div>
        <button className="icon-btn" onClick={() => navigate('upload')} aria-label="Cancel">✕</button>
      </div>

      <div className="calibrate-prompt-bar">
        <h2>Mark court reference points</h2>
        {!complete && !err && ready && (
          <p className="calibrate-instruction">
            Tap: <strong>{nextRef.label}</strong>
            <span className="calibrate-count"> ({clicks.length + 1}&thinsp;/&thinsp;{REFS.length})</span>
          </p>
        )}
        {!ready && !err && (
          <p className="calibrate-instruction">Extracting first frame…</p>
        )}
        {complete && (
          <p className="calibrate-instruction done">All 4 points marked ✓</p>
        )}
      </div>

      <div className="canvas-zone">
        {err && <div className="error-box" style={{ margin: '12px' }}>{err}</div>}
        <canvas
          ref={canvasRef}
          className={`court-canvas${ready && !complete ? ' active' : ''}`}
          onClick={handleCanvasClick}
          style={{ display: ready ? 'block' : 'none' }}
        />
        {!ready && !err && <div className="canvas-placeholder" />}
      </div>

      <div className="calibrate-row">
        <button
          className="btn"
          onClick={() => setClicks(prev => prev.slice(0, -1))}
          disabled={clicks.length === 0 || submitting}
        >
          ↩ Undo
        </button>
        <button
          className="btn"
          onClick={handleSkip}
          disabled={submitting}
        >
          Skip
        </button>
      </div>

      <div className="calibrate-confirm">
        <button
          className={`btn${complete ? ' btn-primary' : ''}`}
          onClick={handleConfirm}
          disabled={!complete || submitting}
        >
          {submitting ? 'Uploading…' : 'Confirm & Analyze'}
        </button>
      </div>
    </div>
  )
}
