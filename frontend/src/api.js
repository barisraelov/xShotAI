/**
 * API wrappers.
 *
 * Base URL comes from VITE_API_URL (see auth.js / .env). When it's empty the
 * paths stay relative and go through the Vite dev proxy to localhost:8000.
 *
 * POST /analyze            (multipart) → { job_id }   — sends Bearer token if logged in
 * GET  /jobs/:id                       → { status } | AnalyzeResult
 * GET  /sessions                       → [SessionSummary]  (auth)
 * GET  /sessions/:id                   → SessionDetail     (auth)
 */

import { API_BASE, authHeaders, handleUnauthorized } from './auth'

async function authedGet(path, label) {
  const res = await fetch(`${API_BASE}${path}`, { headers: { ...authHeaders() } })
  if (res.status === 401) { handleUnauthorized(); throw new Error('Session expired — please log in again') }
  if (!res.ok) throw new Error(`${label} failed: ${res.status}`)
  return res.json()
}

export async function postAnalyze(file, calibrationPoints = null, fail = false) {
  const form = new FormData()
  form.append('video', file)
  if (calibrationPoints != null) form.append('calibration_points', calibrationPoints)
  if (fail) form.append('fail', '1')

  // No explicit Content-Type — the browser sets the multipart boundary itself.
  const res = await fetch(`${API_BASE}/analyze`, {
    method: 'POST',
    headers: { ...authHeaders() },
    body: form,
  })

  if (res.status === 401) { handleUnauthorized(); throw new Error('Session expired — please log in again') }
  if (!res.ok) throw new Error(`Upload failed: ${res.status}`)
  return res.json() // { job_id }
}

export async function getJob(jobId) {
  const res = await fetch(`${API_BASE}/jobs/${jobId}`, {
    headers: { ...authHeaders() },
  })
  if (res.status === 401) { handleUnauthorized(); throw new Error('Session expired — please log in again') }
  if (!res.ok) throw new Error(`Poll failed: ${res.status}`)
  return res.json() // { status: "processing" } | AnalyzeResult
}

// Saved analysis history for the logged-in user.
export function getSessions() {
  return authedGet('/sessions', 'Load history') // [{ id, created_at, total_shots, made, missed, accuracy_pct }]
}

export function getSession(sessionId) {
  return authedGet(`/sessions/${sessionId}`, 'Load session') // { ...summary, job_id, result: AnalyzeResult }
}
