# Next steps (planning — no code until approved)

## Completed

1. **`AnalyzeResult` JSON contract — frozen (Demo v1).** Field names, types, and required/optional rules live in [analyze_result_spec.md](analyze_result_spec.md) (`shot_points[]` with `origin.pixel`, `origin.court`, `zone`, top-level `mapping`, etc.). Treat that file as the API contract unless Demo v1 is explicitly reopened.

   **Binding view-model for screens:** [demo_v1_screen_map.md](demo_v1_screen_map.md) maps each prototype-aligned screen to shell vs result and to which contract fields it consumes.

2. **UI skeleton** — all screens and state machine matching [demo_v1_screen_map.md](demo_v1_screen_map.md). Flow: Welcome → Dashboard → Upload → Analyzing → Session result (+ Heatmap for coarse points/zones when court data is available).

3. **FastAPI skeleton** — `POST /analyze` (multipart) → `job_id`; `GET /jobs/{id}` → status + result; stub result matching [analyze_result_spec.md](analyze_result_spec.md). Includes `?fail=1` test path that exercises the full `completed` vs `failed` contract from the UI.

4. **UI wired to backend** end-to-end with stub (no real CV). Vite proxy routes `/analyze` and `/jobs` to port 8000.

5. **Real make/miss CV** — shot attempt detection + make/miss classification using YOLOv8n ball tracking + hoop-region detection. `origin.court` and `zone` remain `null` on all shot points until automatic court detection (step 6) is implemented. Session summary (total attempts, makes, misses, FG%) is derived from actual per-shot results.

## Then (order)

6. **Automatic court / lane-corner detection → homography → real coarse shot zones.**
   - Detect court lane corners (or other reliable court features) from the video frame automatically — no user interaction required.
   - Compute homography to map `origin.pixel` → `origin.court` (normalized 0–1 space per the frozen spec).
   - Apply polygon zone assignment to produce `zone` and `zone_aggregates`.
   - This is the primary product direction for court mapping. Manual click-based calibration is **not** the intended product UX.
   - Dormant fallback: `Calibrate.jsx` (manual 4-point click UI) exists in the codebase as a safety net only. Do not surface it in the main flow unless automatic detection fails and a manual override is explicitly approved.

7. **Richer heatmap and cross-session progress** — once `origin.court` is real for historical shots, build the per-zone accuracy history view and multi-session trend screen.

## Explicitly later

- Review mode UI (small, non-primary).
- Progress across sessions, compare, social/stats of others.
- Production cloud hosting.
