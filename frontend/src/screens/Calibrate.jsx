import { useEffect, useRef, useState } from 'react'
import Logo from '../components/Logo'
import { postAnalyze } from '../api'
import './Calibrate.css'

/**
 * 6 calibration points — paint corners (4) + 3-pt arc elbow points (2).
 * The backend CourtMapper expects them in exactly this sequence.
 *
 * "Left" and "Right" refer to the top-down court diagram shown to the user.
 * The hoop is at the BOTTOM of that diagram.
 */
const REFS = [
  {
    label: 'Paint corner — bottom left',
    hint:  'Where the baseline meets the LEFT edge of the coloured key (nearest to the hoop)',
  },
  {
    label: 'Paint corner — bottom right',
    hint:  'Where the baseline meets the RIGHT edge of the coloured key (nearest to the hoop)',
  },
  {
    label: 'Paint corner — top left',
    hint:  'Where the free-throw line meets the LEFT edge of the coloured key',
  },
  {
    label: 'Paint corner — top right',
    hint:  'Where the free-throw line meets the RIGHT edge of the coloured key',
  },
  {
    label: '3-pt arc — left elbow',
    hint:  'The point on the 3-point arc directly above the LEFT paint edge (same width as the key, further from hoop)',
  },
  {
    label: '3-pt arc — right elbow',
    hint:  'The point on the 3-point arc directly above the RIGHT paint edge (same width as the key, further from hoop)',
  },
]

/** Extract the first readable frame from a video File as an offscreen canvas. */
function extractFrame(file) {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file)
    const video = document.createElement('video')
    video.muted = true
    video.playsInline = true
    video.preload = 'auto'

    video.onerror = () => {
      URL.revokeObjectURL(url)
      reject(new Error('Cannot load video — try a different file.'))
    }

    const capture = () => {
      const tmp = document.createElement('canvas')
      tmp.width  = video.videoWidth  || 1280
      tmp.height = video.videoHeight || 720
      tmp.getContext('2d').drawImage(video, 0, 0)
      URL.revokeObjectURL(url)
      resolve({ frameCanvas: tmp, w: tmp.width, h: tmp.height })
    }

    video.onseeked = () => {
      // requestAnimationFrame ensures the browser has painted the decoded frame
      // before we capture — without it the canvas is often black.
      requestAnimationFrame(capture)
    }

    video.onloadeddata = () => {
      // onloadeddata fires when the first frame is available.
      // Seek slightly forward so we get a real frame (not a black keyframe).
      const target = video.duration > 0 ? Math.min(0.5, video.duration * 0.05) : 0
      if (video.currentTime === target) {
        // Already there — onseeked won't fire, capture directly.
        requestAnimationFrame(capture)
      } else {
        video.currentTime = target
      }
    }

    video.src = url
    video.load()
  })
}

/** Redraw the frame and all click markers onto the visible canvas. */
function redraw(canvas, frameCanvas, clicks) {
  const ctx = canvas.getContext('2d')
  ctx.drawImage(frameCanvas, 0, 0)

  clicks.forEach(({ u, v }, i) => {
    const r = Math.max(10, Math.round(frameCanvas.width / 55))

    ctx.beginPath()
    ctx.arc(u, v, r, 0, 2 * Math.PI)
    ctx.fillStyle = 'rgba(255, 107, 44, 0.88)'
    ctx.fill()

    ctx.strokeStyle = '#fff'
    ctx.lineWidth = Math.max(2, Math.round(r / 5))
    ctx.stroke()

    ctx.fillStyle = '#fff'
    ctx.font = `bold ${Math.round(r * 1.15)}px sans-serif`
    ctx.textAlign = 'center'
    ctx.textBaseline = 'middle'
    ctx.fillText(String(i + 1), u, v)
  })
}

/**
 * Mini court SVG (top-down, hoop at bottom) showing the 4 paint corners.
 * Numbered dots highlight the next point to click: orange = next, green = done.
 */
function CourtGuide({ nextIndex }) {
  // All 6 calibration points in SVG coords (viewBox 0 0 100 70, hoop at bottom-center)
  const pts = [
    { x: 36, y: 60, label: '1' },  // bottom-left  (baseline × left paint edge)
    { x: 64, y: 60, label: '2' },  // bottom-right (baseline × right paint edge)
    { x: 36, y: 42, label: '3' },  // top-left     (free-throw line × left)
    { x: 64, y: 42, label: '4' },  // top-right    (free-throw line × right)
    { x: 36, y: 38, label: '5' },  // left elbow   (3-pt arc above left paint edge)
    { x: 64, y: 38, label: '6' },  // right elbow  (3-pt arc above right paint edge)
  ]

  return (
    <svg viewBox="0 0 100 70" className="court-guide-svg" aria-hidden="true">
      {/* Outer boundary */}
      <rect x="4" y="4" width="92" height="62" rx="3"
        fill="none" stroke="rgba(255,255,255,0.15)" strokeWidth="0.8" />
      {/* Paint fill */}
      <rect x="36" y="42" width="28" height="20"
        fill="rgba(255,255,255,0.06)" stroke="rgba(255,255,255,0.30)" strokeWidth="1" />
      {/* Free-throw arc */}
      <path d="M36 42 Q50 30 64 42"
        fill="none" stroke="rgba(255,255,255,0.18)" strokeWidth="0.8" />
      {/* Restricted area arc */}
      <path d="M42 62 Q50 56 58 62"
        fill="none" stroke="rgba(255,255,255,0.14)" strokeWidth="0.8" />
      {/* 3-pt straight lines */}
      <line x1="12" y1="66" x2="12" y2="52" stroke="rgba(255,255,255,0.10)" strokeWidth="0.8" />
      <line x1="88" y1="66" x2="88" y2="52" stroke="rgba(255,255,255,0.10)" strokeWidth="0.8" />
      {/* 3-pt arc */}
      <path d="M12 52 Q50 10 88 52"
        fill="none" stroke="rgba(255,255,255,0.10)" strokeWidth="0.8" />
      {/* Hoop */}
      <circle cx="50" cy="63" r="2"
        fill="none" stroke="rgba(255,255,255,0.28)" strokeWidth="0.8" />
      {/* Backboard */}
      <rect x="47" y="65.5" width="6" height="0.8" rx="0.4"
        fill="rgba(255,255,255,0.22)" />
      {/* Label: "Hoop" arrow-hint */}
      <text x="50" y="5" textAnchor="middle" fontSize="4"
        fill="rgba(255,255,255,0.30)">↑ mid-court</text>

      {/* Reference point dots */}
      {pts.map((p, i) => {
        const done = i < nextIndex
        const next = i === nextIndex
        return (
          <g key={i}>
            <circle
              cx={p.x} cy={p.y} r={next ? 5.5 : 4.5}
              fill={done ? 'var(--green)' : next ? 'var(--orange)' : 'rgba(255,255,255,0.18)'}
              stroke={next ? '#fff' : 'none'}
              strokeWidth={next ? 1 : 0}
            />
            <text
              x={p.x} y={p.y + 0.4}
              textAnchor="middle" dominantBaseline="middle"
              fontSize="4.5" fontWeight="bold"
              fill={done || next ? '#fff' : 'rgba(255,255,255,0.45)'}
            >
              {p.label}
            </text>
          </g>
        )
      })}
    </svg>
  )
}

export default function Calibrate({ navigate, file }) {
  const canvasRef = useRef(null)
  const frameRef  = useRef(null)   // { frameCanvas, w, h }

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

  // Redraw whenever clicks change or frame becomes ready
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
      navigate('analyzing', { jobId: job_id, result: null, error: null, file: null })
    } catch (e) {
      setErr(e.message)
      setSubmitting(false)
    }
  }

  function handleConfirm() {
    // Send as [[u,v], ...] — CourtMapper expects 6 pairs in fixed order
    const pts = clicks.map(px => [px.u, px.v])
    submit(JSON.stringify(pts))
  }

  function handleSkip() {
    submit(null)  // no calibration — origin.court and zone will be null
  }

  if (!file) return null

  const complete = clicks.length === REFS.length
  const nextRef  = REFS[clicks.length]

  return (
    <div className="screen-enter calibrate-screen">
      <div className="top-bar">
        <Logo />
        <button className="icon-btn" onClick={() => navigate('upload')} aria-label="Cancel">✕</button>
      </div>

      <div className="calibrate-prompt-bar">
        <h2>Mark 6 court points</h2>
        {!ready && !err && (
          <p className="calibrate-instruction">Extracting frame…</p>
        )}
        {ready && !complete && (
          <p className="calibrate-instruction">
            Tap <strong>{nextRef.label}</strong>
            <span className="calibrate-count"> ({clicks.length + 1}&thinsp;/&thinsp;{REFS.length})</span>
            <br />
            <span style={{ fontSize: '0.79rem', color: 'var(--text-muted)' }}>{nextRef.hint}</span>
          </p>
        )}
        {complete && (
          <p className="calibrate-instruction done">All 6 points marked ✓</p>
        )}
      </div>

      {/* Court reference guide */}
      <div className="calibrate-guide-row">
        <CourtGuide nextIndex={clicks.length} />
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
          onClick={() => setClicks([])}
          disabled={clicks.length === 0 || submitting}
        >
          Reset
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
