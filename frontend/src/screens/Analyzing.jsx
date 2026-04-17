import { useEffect, useRef, useState } from 'react'
import Logo from '../components/Logo'
import { getJob } from '../api'
import './Analyzing.css'

const POLL_INTERVAL = 2000 // ms

// Animated progress bar: runs from 0→90 while processing, snaps to 100 on complete
function useAnimatedProgress(done) {
  const [pct, setPct] = useState(0)
  useEffect(() => {
    if (done) { setPct(100); return }
    const id = setInterval(() => {
      setPct(p => p < 88 ? p + 3 : p)
    }, 300)
    return () => clearInterval(id)
  }, [done])
  return pct
}

export default function Analyzing({ navigate, jobId, setState }) {
  const [status, setStatus] = useState('processing')
  const [pollErr, setPollErr] = useState(null)
  const intervalRef = useRef(null)

  const done = status === 'completed' || status === 'failed'
  const pct = useAnimatedProgress(done)

  useEffect(() => {
    if (!jobId) return

    async function poll() {
      try {
        const data = await getJob(jobId)
        if (data.status === 'processing') return // keep polling

        clearInterval(intervalRef.current)
        setStatus(data.status)

        if (data.status === 'completed') {
          setState(s => ({ ...s, result: data, error: null }))
          // brief pause so user sees 100% before navigating
          setTimeout(() => navigate('session'), 600)
        } else {
          setState(s => ({ ...s, error: data.error ?? 'Analysis failed', result: null }))
        }
      } catch (e) {
        clearInterval(intervalRef.current)
        setPollErr(e.message)
        setStatus('failed')
        setState(s => ({ ...s, error: e.message, result: null }))
      }
    }

    intervalRef.current = setInterval(poll, POLL_INTERVAL)
    poll() // fire immediately too
    return () => clearInterval(intervalRef.current)
  }, [jobId]) // eslint-disable-line react-hooks/exhaustive-deps

  return (
    <div className="screen-enter analyzing-screen">
      <div className="top-bar">
        <Logo />
      </div>

      <div className="analyzing-center">
        <h2>Analyzing <span>shot video</span>…</h2>
      </div>

      <div className="progress-track">
        <div className="progress-fill" style={{ width: `${pct}%` }} />
      </div>

      {status === 'failed' ? (
        <div className="error-box" style={{ margin: '24px 20px' }}>
          {pollErr ?? 'Analysis failed — please try again.'}
        </div>
      ) : (
        <ul className="checklist">
          <li>Detecting player skeleton</li>
          <li>Tracking ball trajectory</li>
          <li>Classifying shot attempts</li>
          <li>Mapping to court zones</li>
        </ul>
      )}

      {status === 'failed' && (
        <div style={{ padding: '0 20px' }}>
          <button className="btn btn-primary" onClick={() => navigate('upload')}>
            Try again
          </button>
        </div>
      )}
    </div>
  )
}
