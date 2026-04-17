import { useRef, useState } from 'react'
import BottomNav from '../components/BottomNav'
import Logo from '../components/Logo'
import { postAnalyze } from '../api'
import './Upload.css'

// ?fail=1 — trigger the stub failure path end-to-end (test only)
const isFail = new URLSearchParams(window.location.search).get('fail') === '1'

export default function Upload({ navigate }) {
  const fileRef = useRef(null)
  const [file, setFile] = useState(null)
  const [uploading, setUploading] = useState(false)
  const [err, setErr] = useState(null)

  function handleFile(e) {
    const f = e.target.files?.[0]
    if (f) { setFile(f); setErr(null) }
  }

  async function handleContinue() {
    if (!file) { setErr('Please select a video file first.'); return }
    setUploading(true)
    setErr(null)
    try {
      const { job_id } = await postAnalyze(file, null, isFail)
      navigate('analyzing', { jobId: job_id, result: null, error: null })
    } catch (e) {
      setErr(e.message)
      setUploading(false)
    }
  }

  return (
    <div className="screen-enter">
      <div className="top-bar">
        <Logo />
        <div className="top-actions"><div className="avatar" /></div>
      </div>

      <h1 className="page-title">Upload training video</h1>
      <p className="page-sub">Select a recorded session to analyze</p>

      <div
        className={`upload-drop${file ? ' has-file' : ''}`}
        onClick={() => fileRef.current?.click()}
      >
        {file ? (
          <>
            <div className="upload-icon">✅</div>
            <div className="upload-filename">{file.name}</div>
            <div className="upload-size">{(file.size / 1024 / 1024).toFixed(1)} MB — tap to change</div>
          </>
        ) : (
          <>
            <div className="upload-icon">📤</div>
            <div className="upload-cta">Tap to select a video</div>
            <div className="upload-hint">MP4, MOV or AVI</div>
          </>
        )}
        <input
          ref={fileRef}
          type="file"
          accept="video/*"
          style={{ display: 'none' }}
          onChange={handleFile}
        />
      </div>

      <div className="req-list">
        <h3>Requirements</h3>
        <ul>
          <li>Camera facing the hoop (elevated / diagonal angle)</li>
          <li>60 fps recommended</li>
          <li>Static camera — no panning</li>
        </ul>
      </div>

      {err && <div className="error-box">{err}</div>}

      <div className="footer-cta">
        <button
          className="btn btn-primary"
          onClick={handleContinue}
          disabled={uploading}
        >
          {uploading ? 'Uploading…' : isFail ? 'Analyze (fail test)' : 'Analyze'}
        </button>
      </div>

      <BottomNav active="upload" navigate={navigate} />
    </div>
  )
}
