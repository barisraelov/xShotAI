# Real-Time Feedback — frozen decisions

IDs `LIVE-01` … `LIVE-25` are stable. Use them in tests, technical logs, and the
trial report. They are **not** user-facing copy.

Example log line:

```json
{
  "trace_code": "LIVE-11",
  "event": "frame_dropped",
  "frame_id": 142,
  "queue_size": 6,
  "live_session_id": "...",
  "shot_id": 4
}
```

| ID | Decision |
| --- | --- |
| LIVE-01 | Shared stateful engine for Upload and Live (`start` / `process_frame` / `finalize`, `ShotDecided`). |
| LIVE-02 | No change to make/miss, sampling, state machine, cooldown, scoring, feedback, insights, recommendations. No new N-frame shot window. No new make/miss timeout. Unknown `total_frames` uses `min(down+50, up+180)` — do not change `shot_frame_end`. |
| LIVE-03 | Live omits court mapping, person-feet-for-location, and weak-hoop (`collect_weak_detections=False`). Player detection used by the existing engine stays. |
| LIVE-04 | One serial `process_frame` worker per `live_session_id`. Incoming WebSocket may continue while the worker runs. Frames fed to the engine in ascending `frame_id` only. CV inference must not block the FastAPI event loop. |
| LIVE-05 | Independent JPEG per frame over a persistent WebSocket. No MediaRecorder, WebRTC, or base64-in-JSON. One atomic binary message: small header + JPEG bytes. |
| LIVE-06 | Request `facingMode: environment`, ideal/max 30 FPS. Send every camera-produced frame after GO. No unbounded phone FIFO. No adaptive FPS. |
| LIVE-07 | Ideal 1280×720, no crop, no artificial upscale. Use whatever the camera actually provides and report real width/height/FPS. |
| LIVE-08 | JPEG quality **0.80** fixed for the session. No adaptive quality. |
| LIVE-09 | Header includes `protocol_version`, `live_session_id`, `frame_id`, `capture_timestamp_monotonic_ms`, `width`, `height`, `jpeg_quality`. `frame_id` starts at 0 on GO, monotonic, never renumbered. Duplicate/stale ids are rejected; gaps are logged. |
| LIVE-10 | Per-session RAM queue `maxsize=6`. Not trajectory memory, not rolling history, not the shot window. |
| LIVE-11 | When the queue is full, drop the oldest **waiting** frame (never the in-process frame), keep original `frame_id`, log `LIVE-11`, increment `server_dropped_frames`. |
| LIVE-12 | Overload if (a) 20 server drops in a rolling 2s, or (b) e2e latency >500ms for 1 continuous second. Human copy: `החיבור או העיבוד איטיים כרגע — ייתכן עיכוב בזיהוי.` Recovery: 3s with no new drops and latency <500ms. After 10s continuous overload, prompt Continue/Stop (do not auto-stop). Continue keeps the warning and does not re-prompt in the same event. |
| LIVE-13 | Make/Miss still counts during degraded. Mark metadata `degraded`. Do not change the algorithm. |
| LIVE-14 | 15s rolling **metadata** in RAM only (no JPEG/BGR/video). Session counters listed in the trial spec. |
| LIVE-15 | Ping/Pong clock offset at prepare; resync about every 30s. Use independent server timestamps plus `WebSocket.bufferedAmount` on the client. Reliable vs the 500ms threshold; not 1ms-accurate. |
| LIVE-16 | One `shot_id` everywhere (`s001` …). Uniqueness `(live_session_id, shot_id)`. A closed decision is final. No renumber in `finalize`. |
| LIVE-17 | Keep session 10s after disconnect. Reconnect same `live_session_id` + user. ≤500ms: keep engine. >500ms no open shot: continue, keep decided. >500ms with open shot: cancel only the open shot, keep decided. No reconnect in 10s: auto-complete, save decided only. |
| LIVE-18 | Prepare/countdown create no stats. GO persists an **active** live session. Upsert each `ShotDecided` immediately. Active sessions are not completed history. On finish: existing `generate_feedback` / summary / insights / recommendations, mark completed, show like Skip Location upload. |
| LIVE-19 | Stop: halt capture immediately, atomic `stopping`, drop queued frames, cancel open shot, ignore in-flight worker results via generation/status, then summary from decided shots only. |
| LIVE-20 | Three original short sounds (Make, Miss, delayed-after-reconnect). Unlock audio on Start Live. Dedupe `played_shot_ids` in memory + `sessionStorage`. Ack; server replay must not replay sound. Mute mutes audio only. |
| LIVE-21 | If the event arrives ≤2s from decision: normal make/miss sound. If older: delayed sound + `תוצאה מהזריקה שלפני הניתוק: Make/Miss`. Shot still counts. |
| LIVE-22 | Live Camera beside Upload. Full-bleed camera, `100dvh`, safe areas, `object-fit: contain`, no crop, no detection overlays. HUD: Connection, session time, Attempts/Makes/Misses, last result, Mute, Stop, overload UI. Match existing design system. |
| LIVE-23 | Countdown **after** server `prepared`: 3, 2, 1, GO. No frames / analysis / timer / DB stats before GO. GO then `frame_id=0`. |
| LIVE-24 | Location data shape matches Skip Location (`origin.court` and `zone` stay null). Do not invent `"unknown"` zones. |
| LIVE-25 | Isolated Vercel Preview + Railway staging + separate DB. Never Production. Migrations only on staging. |

## LIVE-25 environment (Staging / Preview only — do not use Production)

Do **not** set these on Vercel Production, Railway Production, or the Production
database. Do **not** copy Production `DATABASE_URL`.

### Vercel Preview (frontend)

| Variable | Required | Notes |
| --- | --- | --- |
| `VITE_API_URL` | **Yes** | Staging backend origin only, e.g. `https://YOUR-STAGING-SERVICE.up.railway.app`. Missing value **blocks Live**; it must never fall back to `xshotai.up.railway.app`. |
| `VITE_VERCEL_ENV` | Recommended | Set to `preview` so Live refuses a Production API URL. |

HTTPS Staging becomes WSS automatically: `https://…` → `wss://…/live`.

See `frontend/.env.staging.example`. `frontend/.env.example` has an empty
`VITE_API_URL` for local Vite proxy.

### Railway Staging (backend)

| Variable | Required | Notes |
| --- | --- | --- |
| `DATABASE_URL` | **Yes** | New empty Staging Postgres. **Never** Production. |
| CORS allowed origins | **Yes** | Include the Vercel Preview URL. |

Live tables: `backend/migrations/001_live_sessions.sql`. Do not run that
file until Staging exists. An empty Staging DB may also rely on
`create_all` at boot. Never run it on Production.

## Binary frame (LIVE-05 / LIVE-09)

```
magic          4 bytes  "XSH1"
header_len     uint16   big-endian
header         UTF-8 JSON
jpeg           remaining bytes
```

JSON control messages (text WebSocket): `auth`, `prepare`, `ping`, `pong`,
`clock_offset`, `go`, `stop`, `continue`, `decision_ack`, plus server events
`prepared`, `go_ack`, `shot_decided`, `status`, `overload_prompt`,
`session_complete`, `error`.
