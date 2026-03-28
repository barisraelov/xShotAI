/**
 * API wrappers — all calls go through Vite proxy to localhost:8000
 *
 * POST /analyze  (multipart)  → { job_id }
 * GET  /jobs/:id              → { status } | AnalyzeResult
 */

export async function postAnalyze(file, calibrationPoints = null, fail = false) {
  const form = new FormData()
  form.append('video', file)
  if (calibrationPoints != null) form.append('calibration_points', calibrationPoints)
  if (fail) form.append('fail', '1')
  const res = await fetch('/analyze', { method: 'POST', body: form })
  if (!res.ok) throw new Error(`Upload failed: ${res.status}`)
  return res.json() // { job_id }
}

export async function getJob(jobId) {
  const res = await fetch(`/jobs/${jobId}`)
  if (!res.ok) throw new Error(`Poll failed: ${res.status}`)
  return res.json() // { status: "processing" } | AnalyzeResult
}
