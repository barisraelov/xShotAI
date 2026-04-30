# xShot AI — Project Context

> **Purpose of this file:** Single anchor for future Cursor sessions.
> Read this first, then read the source-of-truth docs listed in each section before touching code.
> Do not reopen decisions marked as locked without explicit user approval.
>
> **Product framing:** xShot AI is the **main application under development**, not a one-off academic demo. Technical names may still contain `demo` (e.g. URL params, `DEMO_STUB`, `demo_v1_screen_map.md`) — those are legacy identifiers, not a statement that the whole project is “demo-only.”

---

## 1. Product Overview

**xShot AI** is a basketball training analysis app.
A player records a training session with a static camera, uploads the video, and receives:
- Shot attempt count, make/miss per shot, and FG%
- (Future) Shot location on a normalized court map, per-zone accuracy breakdown, and multi-session trends

The primary UX is: upload video → wait for analysis → see session stats.
No manual annotation or real-time tracking is required from the user.

**Target user:** Individual basketball player doing solo or small-group training.
**Deployment (current phase):** Localhost-first development and testing; no cloud hosting required in this phase of the main product.

---

## 2. First product release — goal and locked scope

This is the **live product roadmap**, not a throwaway demo. The first shipped release demonstrates one **real** analytics capability end-to-end:

| Capability | Status in first release |
|---|---|
| Shot attempt detection | **REAL** — CV pipeline |
| Make/miss classification | **REAL** — CV pipeline |
| Total attempts / makes / misses / FG% | **REAL** — derived from per-shot results |
| Shot location on court (origin.court) | **NULL** — not computed yet |
| Zone assignment | **NULL** — requires court coords |
| Per-zone accuracy breakdown | **EMPTY** — requires zone data |
| Multi-session progress | **PLACEHOLDER** — not backed by real data |

**Primary user flow:**
```
Welcome → Dashboard → Upload → Analyzing (polling) → Session
```
- "Shot map" button on Session is hidden when no shot has a non-null `origin.court`
- The Heatmap screen exists but is not reached in the main upload flow unless court data is present

---

## 3. Future Vision (Product Direction)

- **Court mapping:** Automatic court / lane-corner detection → homography → map `origin.pixel` to `origin.court` (normalized 0–1 space). No manual calibration in the main UX.
- **Zone assignment:** Coarse polygon classification (11 canonical zones, see `analyze_result_spec.md`) once court coords are real.
- **Heatmap:** Shot dots plotted on normalized court diagram; per-zone accuracy grid.
- **Multi-session:** Cross-session trends, progress over time, per-zone improvement tracking.
- **Social / competition:** Out of scope for the foreseeable future.

**Manual 4-point click calibration** (`Calibrate.jsx`) is **NOT** the intended product UX.
It exists only as a dormant safety-net fallback. Do not surface it in the main flow.

---

## 4. Architecture

```
פרוייקט גמר-סדנא/
├── backend/                   Python FastAPI + CV pipeline
│   ├── main.py                API server (two endpoints only)
│   ├── cv_pipeline.py         Rolling-window YOLO pipeline (Session 4 scoring upgrade)
│   ├── best.pt                YOLOv8n model — Basketball + Basketball Hoop (6.2 MB)
│   └── requirements.txt       fastapi, uvicorn, opencv-headless, numpy, ultralytics
│
├── frontend/                  React + Vite SPA
│   ├── src/
│   │   ├── App.jsx            Root: state machine (view field), DEMO_STUB, navigate()
│   │   ├── api.js             postAnalyze(), getJob() — proxy to localhost:8000
│   │   ├── index.css          Global design tokens (--orange, --green, --red, etc.)
│   │   ├── screens/           One file per screen
│   │   └── components/        BottomNav, CourtMap, ZoneGrid
│   ├── vite.config.js         Proxy: /analyze + /jobs → localhost:8000
│   └── package.json
│
└── xShot-prototype/           Source-of-truth documentation (HTML prototype + specs)
    ├── project_brief.md        Product decisions, stack, coordinate conventions — READ FIRST
    ├── analyze_result_spec.md  FROZEN API contract — field names, types, required/optional
    ├── demo_v1_screen_map.md   Screen→data map for v1 (filename legacy; describes current app screens)
    └── next_steps.md           Current roadmap with completed vs planned items
```

---

## 5. The Frozen API Contract

**Source of truth:** `xShot-prototype/analyze_result_spec.md`
**Status: LOCKED** for the shipped product API. Do not change field names, types, or required/optional rules without explicit approval.

```
POST /analyze  (multipart: video + optional calibration_points + optional fail)
→ { "job_id": "..." }

GET /jobs/{job_id}
→ { "status": "processing" }          while running
→ AnalyzeResult                        when completed or failed
```

**AnalyzeResult (completed):**
- `job_id`, `status: "completed"`
- `summary`: `total_shots`, `made`, `missed`, `accuracy_pct`
- `shot_points[]`: each has `shot_id`, `result`, `origin.pixel`, `origin.court` (null ok), `zone` (null ok)
- `zone_aggregates[]`: per-zone counts (empty array is valid)
- `mapping`: `court_norm_version`, `polygon_version`, `y_flip_applied`, `homography_matrix`

**AnalyzeResult (failed):**
- `job_id`, `status: "failed"`, `error` string
- No other fields present (not null — keys must be absent)

**Court coordinate convention (locked):**
- Normalized 0–1. `x=0` left sideline, `x=1` right. `y=0` near hoop/backboard, `y=1` far end.
- 11 canonical zone polygon_ids — see spec for full taxonomy.

---

## 6. Current Implementation State

### Backend (`backend/`)

| File | What it does |
|---|---|
| `main.py` | FastAPI app. `POST /analyze` reads video bytes → dispatches `_process_video_task` via BackgroundTasks. `GET /jobs/{id}` returns status or AnalyzeResult. Fail stub via `fail=1` form field. In-memory job store `_jobs`. **Unchanged since Session 3.** |
| `cv_pipeline.py` | **Scoring upgraded (Session 4).** Rolling-window YOLO pipeline. `process_video(path)` → list of ShotPoint dicts. Attempt detection unchanged (state machine). Make/miss now uses multi-point parabolic fit with fallbacks. See Section 9 for current state and known remaining issues. |
| `best.pt` | YOLOv8n model weights (6,256,291 bytes). Classes: 0 = Basketball, 1 = Basketball Hoop. Downloaded from `avishah3/AI-Basketball-Shot-Detection-Tracker`. Must be present in `backend/` for the pipeline to run. |
| `requirements.txt` | `fastapi`, `uvicorn[standard]`, `python-multipart`, `opencv-python-headless`, `numpy`, `ultralytics>=8.3.0` |
| `test_cv.py` | Validation runner — `python test_cv.py <video> [--debug-video]`. Runs `_run_pipeline_verbose()`, prints 4 stages. Writes annotated debug video. |
| `_run_validation.py` | Thin wrapper to handle Hebrew filenames in Windows terminal encoding (runs first `.mp4` in `test_videos/input/`). |
| `_run_all_validation.py` | **Added Session 4.** Runs `test_cv.py` on every `.mp4` in `test_videos/input/`, saves per-clip reports to `test_videos/output/<name>_report.txt` and writes debug videos. Use this for multi-clip validation. |
| `_diag_shot5_clip3.py` | **Added Session 4.** One-off diagnostic script (disposable). Can be deleted. |
| `test_videos/input/` | Drop test `.mp4` clips here before running validation. |
| `test_videos/output/` | Per-clip `*_report.txt` files and annotated `*_debug.mp4` videos written here. |

**cv_pipeline.py tunables (all named constants at top of file):**

| Constant | Value | Purpose |
|---|---|---|
| `YOLO_MODEL_PATH` | `"best.pt"` | Model filename, resolved relative to `backend/` |
| `FRAME_STRIDE` | `2` | Process every Nth frame |
| `BALL_CONF_THRESHOLD` | `0.30` | Min YOLO conf for ball detection |
| `BALL_CONF_NEAR_HOOP` | `0.15` | Lowered threshold when ball is near hoop |
| `HOOP_CONF_THRESHOLD` | `0.50` | Min YOLO conf for hoop detection |
| `BALL_WINDOW` | `30` | Rolling ball position window size |
| `HOOP_WINDOW` | `25` | Rolling hoop position window size |
| `BALL_CLEAN_JUMP_FACTOR` | `4.0` | Max diameter-jumps allowed in <5 frames |
| `BALL_CLEAN_WH_RATIO` | `1.4` | Max w/h ratio for ball bbox (squareness check) |
| `HOOP_CLEAN_JUMP_FACTOR` | `0.5` | Max fraction of diameter hoop can jump in <5 frames |
| `HOOP_CLEAN_WH_RATIO` | `1.3` | Max w/h ratio for hoop bbox |
| `UP_ZONE_X_FACTOR` | `4.0` | Backboard zone half-width in hoop-widths |
| `UP_ZONE_Y_FACTOR` | `2.0` | Backboard zone height in hoop-heights above rim |
| `ATTEMPT_CONFIRM_EVERY` | `10` | Frames between attempt-confirmation polls |
| `ATTEMPT_MAX_FRAME_GAP` | `120` | Max frame gap between up and down for valid attempt |
| `SCORE_RIM_X_FRACTION` | `0.40` | Fraction of hoop half-width that counts as make |
| `SCORE_REBOUND_PX` | `10` | Extra pixel buffer beyond rim edge |
| `SCORE_MAX_CROSSING_GAP` | `FRAME_STRIDE * 3` (=6) | **New Session 4.** Max frame gap for valid Tier 2 linear crossing pair |
| `SCORE_MIN_PARABOLIC_POINTS` | `3` | **New Session 4.** Min above-rim points needed for Tier 1 parabolic fit |
| `MIN_FIRST_SHOT_FRAME` | `5` | **New Session 4.** Ignore attempts with up_frame < this (suppresses start-of-clip false triggers) |

**cv_pipeline.py scoring architecture (Session 4):**

`_score()` is now a thin orchestrator calling three helpers. All scoring logic is contained within these functions — the state machine and rolling windows are untouched:

| Function | Role |
|---|---|
| `_extract_rim_approach_points(ball_pos, hoop_pos, up_frame)` | Collects all above-rim ball detections from up_frame onward. Applies per-frame deduplication (Most Novel Position rule — see Section 16). Returns `(points, rim_y)`. |
| `_fit_rim_crossing(points, rim_y, hoop_pos)` | Three-tier fit: Tier 1 parabolic (≥3 pts), Tier 2 validated linear (2 pts, short gap, falling slope), Tier 3 insufficient data (returns None). Returns `(predicted_cx, tier_label)` for debug logging. |
| `_check_rim_crossing(predicted_cx, hoop_pos)` | Acceptance check: predicted_cx within `hcx ± SCORE_RIM_X_FRACTION*hw ± SCORE_REBOUND_PX`. |
| `_score(ball_pos, hoop_pos, up_frame)` | Orchestrates the three above. Returns `(is_made: bool, detail: str)`. `detail` is logged at INFO level per shot — shows tier, pred_cx, and rim range. |

**cv_pipeline.py internal API:**
- `process_video(path)` → `list[dict]` — public contract, called by `main.py`
- `_run_pipeline_verbose(path)` → `dict` — returns full diagnostic data for validation runner
- `_run_pipeline_inner(path)` → `(list[dict], dict)` — called by both of the above

**Run backend:**
```
cd backend
uvicorn main:app --reload --port 8000
```

### Frontend (`frontend/`)

**State machine** (`App.jsx`): single `useState` object with `view`, `jobId`, `result`, `error`.
`navigate(view, patch)` merges patch into state.

| Screen | File | Type | Data consumed |
|---|---|---|---|
| Welcome | `screens/Welcome.jsx` | Shell | None |
| Dashboard | `screens/Dashboard.jsx` | Shell + optional | `summary` if result in state |
| Upload | `screens/Upload.jsx` | Shell | None; calls `postAnalyze` |
| Analyzing | `screens/Analyzing.jsx` | Polling | Polls `getJob` every 2s; navigates to Session on complete |
| Session | `screens/Session.jsx` | Result | `summary` (real); `zone_aggregates` for tip (empty = no tip); `shot_points` for `hasCourtData` guard |
| Heatmap | `screens/Heatmap.jsx` | Result | `summary`, `shot_points` (plots non-null courts), `zone_aggregates` |
| Progress | `screens/Progress.jsx` | Placeholder | Static — no real data |

**Dev/test helpers:**
- `?demo=session` — loads DEMO_STUB directly into Session screen (no backend needed)
- `?demo=heatmap` — loads DEMO_STUB directly into Heatmap screen (court + zone data visible)
- `?fail=1` — Upload sends `fail=1` form field; backend flips job to failed after 3s

**Run frontend:**
```
cd frontend
npm run dev       # starts at localhost:5173
```

---

## 7. Locked Product Decisions

These were explicitly confirmed by the product owner. Do not reopen them.

1. **AnalyzeResult JSON contract is frozen.** See `analyze_result_spec.md`. Field names, types, and required/optional rules cannot change without explicit approval.
2. **No manual click-based calibration in the main product UX.** `Calibrate.jsx` is dormant code only.
3. **Automatic court/lane detection is the intended product direction** for court mapping — no user interaction required.
4. **Main product flow: Upload → Analyzing → Session.** No calibration screen in the flow.
5. **origin.court and zone are null** for all shots until automatic court detection is implemented (next step 6).
6. **`?demo=session` and `?demo=heatmap`** (URL flags) are preserved for **frontend dev/testing**; they inject hardcoded data and never reach the backend.
7. **Court coordinate convention:** `y=0` near hoop, `y=1` far end; `x=0` left sideline, `x=1` right. Flip `y` once in mapping layer if raw homography is inverted.
8. **Zone taxonomy: 11 canonical polygon_ids.** See `analyze_result_spec.md` for the full list.
9. **Shot map CTA on Session is hidden** when no `shot_points` have non-null `origin.court`.
10. **HSV hoop detection is permanently abandoned.** The YOLO-based pipeline is the only direction. Do not reintroduce colour-based hoop detection.
11. **The pipeline architecture is the avishah3 rolling-window state machine.** Do not revert to track-building. The decision is locked.
12. **The scoring architecture (parabolic fit with fallbacks) is the current direction.** Do not revert to the old 2-point linear interpolation. The decision is locked.
13. **`_score()` and `OriginEstimator` are permanently decoupled.** Neither reads from the other. Their only shared input is the `RichShotEvent` dict. Do not merge them.
14. **`origin.pixel` semantics: trajectory-anchor, not apex.** The previous apex-based `origin.pixel` (highest mid-air point) was semantically wrong for court-zone mapping. The correct anchor is the ball's position near the shot start (`up_frame` window), which is closest to where the shooter stood on the court floor. This is locked as the baseline. See `backend/origin_estimator.py`.
15. **Release-frame detection is a future upgrade path, not a current hard requirement.** Exact release-frame (via pose / hand-ball proximity) improves origin accuracy and unlocks coaching features, but it is not required for court mapping or zone classification. It is implemented as an optional plugin in `OriginEstimator` (Phase 6). Do not make zone classification block on it.
16. **`OriginEstimator`, `CourtMapper`, `ZoneClassifier` are separate modules with clean dict interfaces.** Each lives in its own file. They are called sequentially after shot confirmation and never from inside `_score()` or the state machine loop.

---

## 8. What is Intentionally Postponed

| Item | Status | Notes |
|---|---|---|
| Court / lane-corner auto-detection | Next milestone (step 6) | OpenCV or ML-based; will populate `origin.court` and `zone` |
| Homography computation | Blocked on step 6 | `calibration_points` form field already accepted; backend ignores it now |
| Zone assignment + `zone_aggregates` | Blocked on court coords | Polygon classification logic defined in spec, not yet wired |
| Heatmap with real shot dots | Blocked on court coords | UI exists; `hasCourtData` guard prevents empty screen |
| Multi-session progress screen | Explicitly later | `Progress.jsx` is static placeholder |
| Review mode UI | Explicitly later | Not in current scope |
| Production cloud hosting | Explicitly later | Localhost sufficient for current phase |
| Manual calibration as user feature | Removed from main UX | `Calibrate.jsx` dormant — do not re-surface without approval |
| Near-hoop presence / net pixel-change scoring | Future robustness improvement | Would complement parabolic fit for cases where ball is not visible near rim |
| **Fixed two-gate presence cue** (supplementary make/miss) | **Specified + Clip 6 diagnostic** — rules and geometry in Section 9; not wired to production scoring yet | Requires upper+lower gate hits in order after `_score()` MISS; diagnostic script `_diag_below_rim_gate.py`. |

---

## 9. Current Stopping Point / Next Step

> **Read this section first in every new session before touching any code.**

### Official checkpoint — fixed two-gate presence cue (production)

**Production make/miss update:** Fixed two-gate presence cue is now implemented in `cv_pipeline.py` as a supplementary cue on top of `_score()`.

| Rule | |
|---|---|
| When it runs | Only after a **valid UP→DOWN** shot attempt is confirmed. |
| Predicate | Only if **`_score()` returns MISS**. |
| Evidence | Requires an **upper gate hit** and a **lower gate hit**. |
| Geometry | Upper gate directly above hoop bbox; lower gate directly below hoop bbox; both gates use **exact hoop bbox width and height**. |
| Ordering | Requires **`upper_hit_frame < lower_hit_frame`**. |
| Direction | Can only **upgrade MISS→MAKE**; never downgrades **MAKE→MISS**. |
| Detection source | Uses **production-accepted detections only**. |
| Scope | No dense sampling, no `FRAME_STRIDE` change, no confidence-threshold change, no `AnalyzeResult`/frontend change, `_score()` internals unchanged. |

**Validation result (today):**
- **Clip 1:** unchanged at **5 shots / 5 made / 0 missed**.
- **Clip 6:** improved from canonical baseline **4 / 0 / 4** to **4 / 1 / 3**.
- **s003:** upgraded by `+two_gate` with **upper hit frame 522** and **lower hit frame 536**.
- **s001, s002, s004:** remain **MISS**.
- No unexpected changes in other clips.

### Next investigation (after this checkpoint)

**Release moment / shot-release detection:** treat as a **separate diagnostic/module first**. Do **not** wire release detection into production yet.

### Reference — free-scan component review

Decoupled free-scan outputs under `backend/test_videos/output/<N>_free_scan/` remain a useful cross-component review aid (see **Section 18.10**). Court mapping (`CourtMapper` / `ZoneClassifier`) stays deferred until the agreed detection milestones progress.

### State after Session 7 (current)

| Item | Status |
|---|---|
| make/miss pipeline (parabolic scoring) | **Unchanged — working as of Session 4** |
| `origin.pixel` semantic correction | **Done** — trajectory anchor, not apex |
| Phase 1: `shot_events` enriched with raw trajectory data | **Done** |
| Phase 2: `backend/origin_estimator.py` + `OriginEstimator` | **Done** |
| Clip-1 discrepancy investigation | **Done** — see Section 18.8 |
| `_diag_shot_detection.py` reset-logic bug | **Fixed** — POLL_PENDING replaces RESET_NO_DOWN |
| Human visual review for clips 1–6 | **Done** — see Section 18.9 |
| `_diag_free_scan.py` (decoupled diagnostics) | **Done** — added and run on clips 1–6 |
| Weak-hoop fallback (`cv_pipeline.py`) | **Integrated (Session 8)** — see Section 18.10.2 |
| Fixed two-gate presence cue | **Specified + Clip 6 diagnostic** — see checkpoint above; not production-wired |
| Phase 3: `CourtMapper` (homography, `origin.court`) | **NOT started** |
| Phase 4: `ZoneClassifier` (polygon hit-test, `zone`) | **NOT started** |
| Phase 5: wire Phases 3+4 into pipeline | **NOT started** |
| Phase 6: `ReleaseEstimator` plugin | **Integrated baseline** — step-search person-bbox logic wired via `OriginEstimator` plugin; unresolved falls back to trajectory-anchor |

### Current focus — object-detection improvement (before CourtMapper)

Before returning to **court mapping**, **`CourtMapper`**, **`ZoneClassifier`**, or production shot-location wiring, the active plan is to improve **core object detection in isolated stages** (hoop → ball → pose → release-frame diagnostic). See **Section 18.10** for the full staged track, weak-hoop-fallback status, Clip 6 finding, fallback algorithm parameters, and locked constraints for this phase.

### What must NOT be changed in the next session

- `_score()` and all make/miss helpers — do not touch.
- `AnalyzeResult` JSON contract — frozen. See `xShot-prototype/analyze_result_spec.md`.
- `OriginEstimator` interface — add a `ReleaseEstimator` plugin only via the constructor parameter.
- `shot_events` legacy fields (`frame_index`, `u`, `v`) — kept for `test_cv.py` backward-compat.

### Key architectural cautions for the next session

1. `CourtMapper` and `ZoneClassifier` must be separate files with clean dict interfaces — same pattern as `origin_estimator.py`.
2. Both are called **after** the while loop in `_run_pipeline_inner`, not inside the state machine or `_score()`.
3. If court detection fails for any reason, each shot still emits with `origin.court=None`, `zone=None` — the contract already handles this.
4. Do not introduce a manual calibration UX. Automatic detection is the locked product direction.
5. Read `xShot-prototype/analyze_result_spec.md` before writing any data shape code.

---

## 9b. Stopped Here After Session 4 (make/miss baseline)

**The make/miss scoring has been upgraded from a 2-point linear method to a multi-point parabolic fit with fallbacks. The pipeline has been validated on 5 direct-camera clips. The current baseline is frozen pending collection of better test footage.**

### What was done in Session 4

1. **Multi-clip validation:** Ran the existing pipeline (Session 3 state) on 5 clips. Added `_run_all_validation.py` to process all clips in one run. Identified systematic MAKE→MISS errors caused by the 2-point linear `_score()`.

2. **Root cause analysis:** The 2-point linear method fails when (a) the ball is lost near the rim and a false positive is picked up as the "below rim" point, or (b) the two chosen points span a large frame gap and extrapolate poorly. Confirmed via per-shot diagnostic logging.

3. **Scoring upgrade — `_score()` replaced:**
   - Old: scan backward, take 1 above-rim + 1 below-rim point, fit a line, predict x at rim.
   - New: collect all above-rim detections from `up_frame` onward, apply deduplication, then use a 3-tier fit: (Tier 1) quadratic cy(t) + linear cx(t) with parabolic extrapolation; (Tier 2) validated linear crossing pair with frame-gap and slope checks; (Tier 3) return False if insufficient data.
   - Each shot logs the tier used, predicted_cx, and rim range at INFO level.

4. **Per-frame deduplication — Most Novel Position rule:**
   - YOLO sometimes detects two objects in the same inference frame: the real ball in flight and a stationary false positive (e.g., a ball on the ground, net, or logo). Both enter `ball_pos` and corrupt the fit.
   - Fix: in `_extract_rim_approach_points`, when multiple detections share the same frame index, keep the one whose (cx, cy) is most spatially distant from its nearest neighbour at any other frame. A stationary ghost repeats at ~0px distance; a real ball in flight has a distance of tens of pixels from adjacent-frame detections. Tiebreaker: prefer lower cy (farther above rim).
   - This is a no-op for frames with a single detection.

5. **False-trigger guard:** Added `MIN_FIRST_SHOT_FRAME = 5`. Attempts with `up_frame < 5` are silently discarded. This eliminates the clip 4 false trigger (up_frame=2) without affecting real early shots (clip 5 up_frame=10 passes).

### Validation results on 5 clips (current baseline)

| Clip | Duration | Resolution | Shots | Makes | Misses | Notes |
|---|---|---|---|---|---|---|
| 1.mp4 | 15.1s | 1170×654 (screen rec) | 5 | **5** | 0 | Perfect. Hoop 74×71px conf 0.57–0.93 |
| 2.mp4 | 14.1s | 1164×648 | 3 | 1 | 2 | s001/s003 have only 1 above-rim detection; video starts mid-shot (s001) and s003 had rim-rolling bounce. Known limitation. |
| 3.mp4 | 17.6s | 412×744 (vertical) | 6 | 3 | 3 | Small hoop (27×30px). s002/s004 have 1 above-rim pt each. s005 deduplication improved (5pts→3pts) but pred_cx=208 still 6px outside narrow rim zone. |
| 4.mp4 | 9.5s | 1914×1072 | 2 | 1 | 1 | False trigger at frame 2 removed. s001 (frame 30) has 1 above-rim pt. |
| 5.mp4 | 7.5s | 1190×674 | 1 | 0 | 1 | 3 above-rim pts, parabolic rejected (no valid crossing). Ball not detected near hoop (0 near-hoop detections). |

**Ground truth note:** Clips 1, 2, 3 were confirmed all-makes. Clips 4 and 5 partially confirmed. The remaining errors in clips 2, 3, 4, 5 are attributed to: start-of-clip shots (no lead-in), very small hoop in pixels, ball invisible near rim due to camera angle, and fast consecutive shots.

### Baseline assessment

The pipeline performs well when:
- Camera has a stable diagonal/elevated angle facing the hoop
- The clip has enough lead-in before the first shot (~1s minimum)
- The hoop is reasonably large in pixels (≥50px wide)
- Shots are spaced apart enough for the state machine to reset

Remaining error patterns:
- `no_crossing(1pts)` — only 1 above-rim detection: ball not visible enough near rim. Not fixable without more ball detections.
- `no_crossing(Npts)` where N≥3 — parabolic fit geometry failed (rare, requires per-shot investigation).
- Near-miss on small hoop — pred_cx falls just outside the narrow acceptance zone; may benefit from a future dynamic acceptance scaling based on hoop pixel size.

### Immediate next task

**Collect new test videos** under better-controlled conditions:
- Stable camera at suitable diagonal/elevated angle toward the hoop
- Sufficient clip duration and lead-in before the first shot
- Enough spacing between consecutive shots
- Reasonable lighting and ball visibility

Once better footage is available, re-validate and decide whether further scoring improvement is needed before moving to Step 6 (automatic court detection).

---

## 10. Next Recommended Tasks (in order)

**Immediate engineering track:** Before Phases 3–5 below, the active plan is **object-detection improvement** (hoop → ball → pose → release-frame diagnostics) — see **Section 18.10**. Phases 3–5 remain the **long-term** mapping roadmap unless priorities change.

### Long-term goals (product direction)

The ultimate goal of this development track is:
1. **Shot location by court zone** — detect where on the court each shot was taken from.
2. **Zone-based stats** — per-zone FG%, make/miss breakdown, shown on Heatmap screen.
3. **Multi-session progress** — zone accuracy over time, shooting trends.
4. **Player feedback / coaching** — identify weak zones, track improvement, give actionable cues.

The current modular architecture (make/miss decoupled from origin/zone) is designed to support all of these without blocking or reworking each other.

---

### NEXT — Phase 3: `backend/court_mapper.py`

See Section 9 "Exact next step" for full details.
Goal: automatic court detection → homography → `origin.court` populated.
This is Step 6 from `xShot-prototype/next_steps.md`.

---

### THEN — Phase 4: `backend/zone_classifier.py`

Goal: 11-polygon hit-test on `origin.court` → `zone` + `zone_aggregates`.
Depends on Phase 3.

---

### THEN — Phase 5: Wire into pipeline and validate

Connect Phase 3 + Phase 4 into `_run_pipeline_inner` and `main.py`.
Validate on real footage. Unlocks: Heatmap screen, Session zone tip.

---

### Phase 6 — `ReleaseEstimator` plugin (integrated baseline, future refinement)

Baseline release-step logic is integrated (person-bbox contact/exit search).  
Future improvements still target pose / hand-ball proximity refinement.  
See Section 17.5 for plug-in contract. Not required for Phases 3–5.

---

### ALSO — Collect better test footage and re-validate make/miss

See Section 9b for target conditions. Run `python _run_all_validation.py` on the new clips.

---

### FUTURE — Scoring robustness improvements (if needed)

If re-validation on better footage still shows systematic make/miss errors:
- **Dynamic acceptance scaling:** scale `SCORE_RIM_X_FRACTION` based on hoop pixel size — a 27px hoop needs a wider relative fraction than a 74px hoop.
- **Near-hoop presence evidence:** if the ball is detected inside the hoop region below the rim, use that as supplementary evidence of a make.
- **Net pixel-change detection:** look at frame-difference intensity in the rim/net area right after the ball crosses — a make disturbs the net; a miss usually doesn't.
- **Fixed two-gate presence cue:** Formal rules (upper/lower gates anchored to hoop bbox, temporal order, MISS-only predicate) and Clip 6 diagnostic results — **Section 9**. Supplementary signal only; **`_score()`** remains primary. Production wiring requires explicit approval.

---

## 11. Architecture Principles / Constraints

- **Contract-first:** The AnalyzeResult JSON shape is the interface between frontend and backend. CV internals change freely; the contract does not.
- **Layered data:** Each shot stores `origin.pixel` (raw), `origin.court` (mapped), and `zone` (classified). Never store only zone. Coordinates are the long-term source of truth.
- **Incremental CV:** The CV pipeline is a separate module (`cv_pipeline.py`). Replace its internals without changing `main.py` or the API contract.
- **State machine, not router:** The frontend uses a single `useState` object in `App.jsx`. All navigation goes through `navigate(view, patch)`. Do not introduce React Router without discussion.
- **No dense heatmap:** The heatmap shows discrete shot-origin dots, not a continuous density map.
- **Localhost-first is enough for the current phase.** No auth, no multi-user, no cloud requirement yet.
- **Camera assumptions:** Static camera, elevated/diagonal angle facing the hoop, standard orange ball, decent gym lighting. The CV pipeline is tuned for this.
- **Rolling-window, not track-building:** The pipeline maintains rolling lists of the last N detections (not structured track objects). This tolerates YOLO detection gaps and is the correct architecture for this use case.
- **Scoring helpers are separable:** `_extract_rim_approach_points`, `_fit_rim_crossing`, `_check_rim_crossing` are independent functions reusable for future trajectory analysis. Do not collapse them back into a monolithic `_score()`.
- **Shot-location pipeline is separate from make/miss:** `OriginEstimator → CourtMapper → ZoneClassifier` form an independent downstream chain. They receive only the `RichShotEvent` dict; they never read from `_score()`, `_extract_rim_approach_points`, or any scoring helper. If any stage in this chain fails, the shot still emits with `origin.court=None`, `zone=None` — exactly as today.
- **`OriginEstimator` is swappable:** The trajectory-anchor baseline is the default. A `ReleaseEstimator` plugin can be injected via `OriginEstimator(release_estimator=...)` without touching the pipeline. The plugin returns `None` to delegate to the baseline. See `backend/origin_estimator.py`.

---

## 12. Key File Reference

| Path | Role |
|---|---|
| `xShot-prototype/project_brief.md` | Product decisions, stack choices, coordinate conventions |
| `xShot-prototype/analyze_result_spec.md` | **FROZEN** API contract — read before touching any data shapes |
| `xShot-prototype/demo_v1_screen_map.md` | Screen-to-data mapping for the v1 app (filename legacy) |
| `xShot-prototype/next_steps.md` | Roadmap: completed vs next vs later |
| `backend/main.py` | FastAPI server, job store, background task dispatch — unchanged |
| `backend/cv_pipeline.py` | **Phase 1+2 updated (Session 5).** Rolling-window YOLO pipeline. `shot_events` now carries raw trajectory data; `origin.pixel` uses `OriginEstimator`. |
| `backend/origin_estimator.py` | **New (Session 5).** `OriginEstimator` — trajectory-anchor baseline for `origin.pixel`. Phase 6 release+pose plugin hook built in. |
| `backend/best.pt` | YOLOv8n model weights (6.2 MB). **Must be present.** Classes: 0 = Basketball, 1 = Basketball Hoop. |
| `backend/requirements.txt` | Python dependencies |
| `backend/test_cv.py` | Validation runner using `_run_pipeline_verbose()`. Stage 3 shows apex markers; Stage 4 JSON shows trajectory-anchor origin. |
| `backend/_run_all_validation.py` | **New Session 4.** Multi-clip validation runner. Use this for all future validation runs. |
| `backend/_run_validation.py` | Legacy single-clip wrapper for Hebrew filename encoding on Windows |
| `backend/test_videos/input/` | Place test clips here |
| `backend/test_videos/output/` | Per-clip `*_report.txt` and `*_debug.mp4` saved here |
| `frontend/src/App.jsx` | Root component — state machine, DEMO_STUB, screen routing |
| `frontend/src/api.js` | `postAnalyze()`, `getJob()` — proxy to port 8000 |
| `frontend/src/index.css` | Design tokens (CSS variables), global styles |
| `frontend/src/screens/Session.jsx` | Primary result screen — real summary stats |
| `frontend/src/screens/Heatmap.jsx` | Court map + zone grid (only shown when court data exists) |
| `frontend/src/screens/Calibrate.jsx` | **DORMANT** — manual calibration fallback, not in flow |
| `frontend/vite.config.js` | Proxy: `/analyze`, `/jobs` → `http://localhost:8000` |

---

## 13. Notes for Future Cursor Sessions

- **Always read `analyze_result_spec.md` before touching any data shape.** It is frozen.
- **Always read `next_steps.md`** to understand current milestone and what comes next.
- **Do not propose manual calibration as a primary UX feature.** It is not the product direction.
- **Do not reopen decisions listed in Section 7** without explicit user request.
- **The DEMO_STUB in `App.jsx`** contains realistic hardcoded data including court coords and zones — useful for frontend testing via `?demo=session` or `?demo=heatmap` even while the backend returns null courts.
- **`xShot-prototype/index.html` is wired to the real backend** for the primary flow: `Welcome/Dashboard → Upload → Analyzing (polling) → Session (summary from API)`.
- **Standalone prototype must be served over HTTP**: use `xShot-prototype/serve.py` and open `http://localhost:8080` (not `file://.../index.html`), to avoid browser CORS restrictions from an opaque `Origin`.
- **Backend CORS update for prototype origin**: `backend/main.py` allows calls from `http://localhost:8080` and `http://127.0.0.1:8080` so `/analyze` and `/jobs` work from the standalone prototype.
- **No future product direction surfaced in real flow**: Session tip + “Shot map” CTA remain gated by court/zone data (currently `origin.court` and `zone_aggregates` are empty until Step 6), so Heatmap/court-dependent UI is not reached automatically.
- **CV pipeline parameters** are all named constants at the top of `cv_pipeline.py` — tune them there, not inline.
- **The frontend has no tests and the backend has no tests.** When adding features, validate against real footage (`_run_all_validation.py`) and the dev URL params before considering anything done.
- **Do not introduce new screens or navigation patterns** without mapping them against `demo_v1_screen_map.md` and confirming with the user.
- **`zone_aggregates: []`** (empty) is valid per the contract spec. The Session screen handles it gracefully (tip disappears). The ZoneGrid handles it gracefully (renders nothing).
- **Do not attempt to reintroduce HSV hoop detection or track-based ball tracking.** Both are permanently replaced.
- **Do not revert `_score()` to 2-point linear interpolation.** The parabolic approach is locked.
- **The validation workflow is:** drop clips in `backend/test_videos/input/` → `python _run_all_validation.py` → read `test_videos/output/*_report.txt` → optionally open `*_debug.mp4` to confirm hoop box position and shot markers.
- **Windows Hebrew filename encoding issue:** PowerShell garbles Hebrew filenames. Use `_run_all_validation.py` for multi-clip runs (uses subprocess with PIPE, encoding-safe). `_run_validation.py` handles the old single Hebrew-named clip.
- **`best.pt` must be in `backend/`** for the pipeline to run. If it is missing, `_run_pipeline_inner()` raises a clear RuntimeError with the download URL.
- **Each shot's INFO log line shows the scoring tier:** `parabolic(Npts)`, `linear(Xf)`, or `no_crossing(Npts)`. This is the first thing to check when diagnosing a wrong make/miss result.
- **`no_crossing(1pts)` means the ball was only detected once above the rim** for that shot. This is a ball-visibility / camera-angle issue, not a scoring logic issue. The fix is better footage conditions, not code changes.
- **`origin.pixel` is now a trajectory-anchor, not the apex.** The `_find_apex` function still exists and is used by `test_cv.py` for debug video markers (visual only). The `AnalyzeResult` contract's `origin.pixel` comes from `OriginEstimator.estimate()` — the ball's last position below the hoop line before `up_frame`. Do not revert this to apex.
- **`shot_events` in `diag` now carries extra raw fields:** `ball_points_window`, `ball_pos_snapshot`, `up_frame`, `down_frame`, `hoop_stable`. These are internal only and never written to `AnalyzeResult`. They exist to feed `OriginEstimator` (and future `CourtMapper`, `ZoneClassifier`).
- **To upgrade origin estimation in the future (Phase 6):** change one line in `cv_pipeline.py` — pass a `ReleaseEstimator` to `OriginEstimator(release_estimator=...)`. No other changes needed. See `backend/origin_estimator.py` for the plugin contract.
- **Do not call `OriginEstimator` from inside `_score()` or from the state machine loop.** It is called only in the `shot_points` building loop after the full while loop completes.

---

## 14. Research Findings (Session 2 — CV Validation)

This section records findings from initial internet research. The research recommendations were acted on in Session 3 — see Section 15.

### 14.1 Community Consensus on Hoop Detection

Every high-accuracy open-source basketball shot detection project (2022–2024) uses **YOLO for rim/hoop detection**, not HSV colour segmentation. The reason: orange appears in too many places in a gym.

### 14.2 Reference Project — avishah3 / AI-Basketball-Shot-Detection-Tracker

**GitHub:** `avishah3/AI-Basketball-Shot-Detection-Tracker` (242 stars, July 2023)
**Accuracy:** 95% score detection, 97% shot detection.
**Architecture adopted by xShot AI in Session 3** — rolling-window state machine, `detect_up`/`detect_down`, `clean_ball_pos()`, `clean_hoop_pos()`, `in_hoop_region()`.

### 14.3 Roboflow Dataset

**URL:** `https://universe.roboflow.com/basketball-hoop-tsdku/basketball-hoop-images`
**Size:** 3,600 images, classes `basketball` + `rim`, CC BY 4.0.
**Status:** `best.pt` from avishah3 (trained on this dataset) was used directly — no retraining needed.

### 14.4 ScoreActuary (Academic — Highest Known Accuracy)

**Paper:** ACM Multimedia 2022, NTHU, Taiwan
**Accuracy:** 99.59% make/miss. Key insight: hoop-centric trajectory normalization.
**Status:** Too complex for current scope; noted as future reference.

### 14.5 Beijing Courts System (Production-Deployed)

**Method:** YOLO hoop + frame-difference motion in hoop region for make/miss.
**Status:** Noted as potential future Option F (net pixel-change detection) if parabolic scoring still fails on certain footage. Not adopted yet.

### 14.6 arturchichorro/bballvision (2024)

**Model:** `bballvision.pt` (79 MB), 5 classes: ball, made, person, rim, shoot.
**Make/miss logic:** `is_made_shot()` — mathematically identical to avishah3's original `score()`.
**Status:** Secondary reference only. The `shoot` action class approach is too fragile and the 79 MB model too slow for our use case.

---

## 15. Research Findings (Session 3 — CV Pipeline Rebuild)

### 15.1 What Was Implemented

The entire `cv_pipeline.py` was rewritten from scratch. The old architecture (HSV hoop scan → nearest-neighbour track builder → parabolic arc filter → proximity box make/miss) was replaced with the avishah3 rolling-window state machine.

**Why the old architecture failed:**
The track-builder required ≥8 consecutive detections per shot. At FRAME_STRIDE=2 on a 30fps clip, a 1-second shot arc yields ~15 inference frames. On the screen recording, YOLO only detected the ball for 2–5 of those frames per arc, producing only short fragments — none meeting the 8-detection threshold. Result: zero shots detected.

**Why the new architecture works:**
No tracks. Each detection is appended to a rolling window of the last 30 positions. The state machine (`detect_up`/`detect_down`) only needs to see the ball enter one zone then another — it tolerates large detection gaps.

**Validation result on screen recording (15s, 1170×654):**

```
Hoop:   detected 228/228 inference frames, centre (184, 173), conf 0.57–0.93
Ball:   146/152 detections accepted (96%), 29 near-hoop (used lower conf 0.15)
Shots:  5 detected — 4 made, 1 missed (s005 wrong — fixed in Session 4)
```

---

## 16. Research and Changes (Session 4 — Scoring Upgrade)

### 16.1 Problem Identified

The original `_score()` used 2-point linear interpolation. After extending to 5 test clips, 4 MAKE→MISS errors were found, all caused by the same root cause: the ball being lost near the rim, so the "crossing pair" spanned a large frame gap and/or included a false positive. Linear extrapolation across such a pair produces wildly wrong predictions.

### 16.2 Scoring Architecture Redesign

`_score()` was restructured into three separable helpers (see Section 6 for the API):

**`_extract_rim_approach_points`**: Collects all above-rim ball detections from up_frame onward (ascending + descending phase). Including ascending-phase detections improves the fit when YOLO loses the ball during descent near the rim.

**Per-frame deduplication (Most Novel Position rule):** YOLO can fire on two objects in the same frame — the real ball and a stationary false positive. The ghost repeats at ~0px distance from its own detections at other frames. The real ball is at a unique position each frame. When multiple detections share a frame index, the one whose position is most spatially novel (farthest from all other-frame detections) is kept. A stationary false positive at cx=186, cy=242 appearing across frames 266, 268, 272 was correctly identified and removed from the s005 point set in clip 3, changing the result from `no_crossing(5pts)` (corrupted discriminant) to `parabolic(3pts)` (real prediction).

**`_fit_rim_crossing`** — Three-tier logic:
- **Tier 1 (parabolic):** fits cy(t)=at²+bt+c, solves for t_rim, fits cx(t)=dt+e, predicts cx. Sanity-checked: t_rim must be near the data range, predicted_cx must be within `max(hw*6, 100)` pixels of hoop centre.
- **Tier 2 (validated linear):** uses the 2 closest-to-rim points. Validates: frame gap ≤ SCORE_MAX_CROSSING_GAP, slope is falling (dy > 0), result within sanity bound.
- **Tier 3:** returns None → caller defaults to miss.

**Bank shot limitation (acknowledged, not fixed):** A bank shot has a trajectory break at the backboard contact point. The parabolic fit uses the full above-rim arc including pre-contact points. This is a known limitation. Bank shots are rare in typical training footage; accepting this limitation for now is reasonable. A future improvement would detect the trajectory break and fit only the post-contact segment.

### 16.3 Validation Results After Session 4

| Clip | Before (Session 3) | After (Session 4) | Change |
|---|---|---|---|
| 1.mp4 | 4M / 1m | **5M / 0m** | s005 fixed (parabolic 4pts) |
| 2.mp4 | 3M / 0m | 1M / 2m | s001/s003 regressed — only 1 above-rim pt each; old code used below-rim pts, new code doesn't. Root cause: start-of-clip + ball barely visible. |
| 3.mp4 | 4M / 2m | 3M / 3m | s003/s006 fixed (parabolic 12pts). s002/s004 regressed (1pt). s005 improved (dedup: 5pts→3pts, now parabolic, but pred_cx 6px outside narrow rim zone). |
| 4.mp4 | 3 shots (1 false trigger) | **2 shots, 1M/1m** | False trigger at frame 2 removed by MIN_FIRST_SHOT_FRAME guard. |
| 5.mp4 | 1m | 1m | Unchanged. Ball not visible near rim (0 near-hoop detections). |

### 16.4 Clip-by-clip Analysis (User Assessment)

- **Clip 1:** Excellent. Clean angle, good lead-in, pipeline is now very strong.
- **Clip 2:** s001 starts mid-shot (video begins with ball already in flight — only 1 above-rim detection). s003 ball touched rim multiple times before going in (multi-contact bounce — single parabola assumption breaks down). Both are edge cases.
- **Clip 3:** Several errors from a combination of small hoop (27px) and ball visibility gaps. The remaining `no_crossing(1pts)` shots are genuine data scarcity, not scoring logic failures.
- **Clip 4:** Similar to clip 2 s001 — video starts mid-shot. The real second shot (frame 174) was correctly identified as MADE.
- **Clip 5:** Second shot not detected at all — the next shot started too quickly after the first make, and the state machine had not reset. Only 1 shot registered.

### 16.5 Current Baseline Condition

The pipeline is performing well under intended **reference** shooting conditions:
- Suitable camera angle (stable, diagonal/elevated, hoop clearly visible)
- Sufficient lead-in before the first shot
- Adequate spacing between consecutive shots
- Good ball visibility throughout the arc

The next step is to collect footage that matches these conditions and re-validate.

---

## 17. Architecture Changes (Session 5 — Shot-Origin Pipeline)

### 17.1 Agreed Direction

Shot-location / zone classification does **not** require exact release-frame detection as a hard prerequisite.  The agreed two-layer strategy is:

- **Baseline (now):** trajectory-anchor `OriginEstimator` — ball position near shot start, no pose dependency.
- **Future upgrade (Phase 6):** optional `ReleaseEstimator` plugin injected into `OriginEstimator` with confidence gating.  Fallback to baseline when absent or low-confidence.

### 17.2 Semantic Correction — `origin.pixel`

The previous implementation used `_find_apex` (ball's highest mid-air point) as `origin.pixel`.  This was semantically wrong for court-zone mapping: the apex is mid-air, not on the court floor.

**Corrected semantics:** `origin.pixel` now comes from `OriginEstimator.estimate()`.  The trajectory-anchor baseline finds the ball's last detected position **below the hoop line before `up_frame`** — the closest observable proxy to where the ball was at release from the shooter's hands.

`_find_apex` is preserved in `cv_pipeline.py` and still drives the debug-video markers in `test_cv.py`.  It is no longer used for `AnalyzeResult.shot_points[].origin.pixel`.

### 17.3 Internal Data Flow

```
Video
  └─ YOLO detection loop
       └─ Shot state machine  ──────────────────────────────────────────────┐
            ├─ _score()         ← make/miss (unchanged, decoupled)           │
            └─ RichShotEvent    ← raw data: ball_points_window,              │
                                            ball_pos_snapshot,               │
                                            up_frame, down_frame,            │
                                            hoop_stable, result              │
                                                                             │
  ┌──────────────────────────────────────────────────────────────────────────┘
  └─ OriginEstimator.estimate(shot_event)
       ├─ ReleaseEstimator plugin (Phase 6 baseline integrated)
       └─ Trajectory-anchor baseline fallback (when release unresolved/low-confidence)
            └─ origin.pixel  ──→  CourtMapper (Phase 3)
                                       └─ origin.court  ──→  ZoneClassifier (Phase 4)
                                                                  └─ zone, zone_aggregates
```

**Key decoupling rule:** `_score()` and `OriginEstimator` are siblings fed by the same `RichShotEvent`. Neither calls the other.

### 17.4 What Was Implemented in Session 5

| Item | Status |
|---|---|
| Phase 1: enrich `shot_events` with raw trajectory data | **Done** |
| Phase 2: `backend/origin_estimator.py` — trajectory-anchor baseline | **Done** |
| `cv_pipeline.py`: `origin.pixel` now from `OriginEstimator` | **Done** |
| `test_cv.py`: comment updated to clarify apex vs origin semantics | **Done** |
| `PROJECT_CONTEXT.md`: architecture direction locked | **Done** |
| Phase 3: `CourtMapper` (homography) | Pending |
| Phase 4: `ZoneClassifier` (polygon hit-test) | Pending |
| Phase 5: wire phases 3+4 into pipeline | Pending |
| Phase 6: `ReleaseEstimator` plugin | **Integrated baseline** (step-search person-bbox), future pose-based refinement |

### 17.5 Future Phase 6 Plug-in Contract

To upgrade origin estimation to release-frame + pose:

1. Create `backend/release_estimator.py` implementing a class with:
   ```python
   def estimate(self, shot_event: dict) -> dict | None:
       # return {"u": int, "v": int, "frame_index": int} when confident
       # return None to delegate to trajectory-anchor baseline
   ```
2. Change one line in `cv_pipeline.py`:
   ```python
   _origin_estimator = OriginEstimator(release_estimator=MyReleaseEstimator())
   ```
3. No other files need to change.

Candidate approaches for Phase 6 (in order of complexity):
- **Ball-velocity inflection:** detect first frame of upward acceleration — ball only, no pose, simplest.
- **Hand-ball proximity (MediaPipe):** release = first frame where `distance(wrist, ball) > threshold`. Matches `srz08/basketball-shot-analysis` pattern.
- **Pose + velocity joint cue:** combines wrist distance + outbound velocity direction — most accurate.

---

## 18. Diagnostic Checkpoint — Post Human Visual Review

> **Read this section first in every new session that continues shot-location work.**
> Human visual review for clips 1–6 is complete. Production architecture decisions remain locked and must still respect all constraints in Section 18.5.

### 18.1 What Was Added (Diagnostic Phase)

Four standalone diagnostic scripts were added to `backend/`. None are wired into the production pipeline.

| File | Purpose |
|---|---|
| `backend/_diag_court_lines.py` | Evaluate court-line / keypoint visibility per clip. Runs Canny + Hough, attempts lane-pair identification and corner estimation, writes annotated images and a review-checklist report. |
| `backend/_diag_pose_windows.py` | Evaluate pose-window feasibility around detected shot events. Runs YOLOv8n-pose on frames `[up_frame−20, up_frame+5]` per shot, identifies shooter, estimates release frame and feet/ankle anchor, compares against current trajectory-anchor. Writes annotated video and full PoseEvent JSON per shot. |
| `backend/_diag_shot_detection.py` | **Added in the session following Section 18.2.** Full per-frame shot-detection debug. Re-runs YOLO and replicates the state machine with rich visual overlays: live hoop box, UP zone rectangle, per-frame ball circles (green=accepted / dark-red=low-conf / orange=cleaned), ball zone label (IN-UP / BELOW / ABOVE / SIDE), state panel, and event banner. Writes annotated `debug_video.mp4` + JPEG key frames + `shot_diag_report.txt` per clip. See Section 18.7 for results. |
| `backend/_diag_free_scan.py` | **Added in Session 7.** Decoupled component diagnostics (hoop/ball/pose) independent of shot confirmation. Writes three annotated frame sets (`hoop_scan`, `ball_scan`, `pose_scan`) and `free_scan_report.txt` per clip. See Section 18.9. |
| `backend/_diag_hoop_threshold.py` | **Diagnostic only.** Sweeps candidate hoop confidence thresholds; writes to `test_videos/output_threshold_tuning/`. Does not change production. |
| `backend/_diag_weak_hoop_fallback.py` | **Diagnostic only.** Tests weak-hoop overlap / intersection consensus for a fallback hoop center. Writes to `test_videos/output_weak_hoop_fallback/`. **Not wired into production.** See Section 18.10. |

`yolov8n-pose.pt` (~6 MB) was auto-downloaded to `backend/` on first run of `_diag_pose_windows.py`.

**Outputs** live in `backend/test_videos/output/`:

| Directory | Contents |
|---|---|
| `<N>_court_diag/` | `frame_raw.jpg`, `frame_edges.jpg`, `frame_lines_all.jpg`, `frame_analysis.jpg`, `court_report.txt` |
| `<N>_pose_diag/` | `s00N_pose_window.mp4`, `s00N_pose_data.json`, `pose_report.txt` |
| `<N>_shot_diag/` | `debug_video.mp4`, `frame_NNNNN[_EVENT].jpg` key frames, `shot_diag_report.txt` |
| `<N>_free_scan/` | `hoop_scan/frame_*.jpg`, `ball_scan/frame_*.jpg`, `pose_scan/frame_*.jpg`, `free_scan_report.txt` |

To re-run:
```
cd backend
python _diag_court_lines.py           # all clips
python _diag_pose_windows.py          # all clips
python _diag_shot_detection.py        # all clips  ← NEW
python _diag_free_scan.py             # all clips  ← NEW (Session 7)
```
Or pass a single clip path as an argument to any script.

### 18.2 Diagnostic Run Results (Current Footage)

> **Clips 2–6 are new footage** added after Session 4. The old Session 4 clips were deleted. Do not compare these results to the Session 4 shot-count baseline.

**Shot detection on current clips:**

| Clip | Shots detected | Hoop detected | Notes |
|---|---|---|---|
| 1.mp4 | 5 | Yes (conf 0.93) | Same as original Session 4 clip 1 |
| 2.mp4 | 0 | Yes (conf 0.81) | New footage — pipeline has not been tuned for it |
| 3.mp4 | 0 | Yes (conf 0.88) | New footage |
| 4.mp4 | 0 | No hoop | New footage — different camera conditions |
| 5.mp4 | 0 | No hoop | New footage |
| 6.mp4 | 0 | Yes (conf 0.57) | New footage |

The zero shot counts in clips 2–6 are themselves a diagnostic finding — these clips have not yet been validated with the current pipeline. Tuning and validation on new footage is a prerequisite before the court-location pipeline can be evaluated on them.

**Court-line preliminary verdicts (auto-scored, not yet visually confirmed):**

| Clip | Auto verdict | Total lines | Lane found | Corners | Key concern |
|---|---|---|---|---|---|
| 1 | STRONG | 323 | Yes (sep 310px = 4.2× hoop) | 436 | Left lane line at x=7 — likely frame edge |
| 2 | STRONG | 331 | Yes (sep 352px = 7.8× hoop) | 526 | Corner count 526 >> expected 4 — likely noise |
| 3 | STRONG | 36  | Yes (sep 129px = 4.4× hoop) | 26  | Left lane line at x=1 — likely frame edge; vertical mobile footage |
| 4 | NO_LINES | — | No | — | No hoop detected — no analysis possible |
| 5 | NO_LINES | — | No | — | No hoop detected — no analysis possible |
| 6 | STRONG | 54  | Yes (sep 348px = 12.4× hoop) | 56  | Separation 93% of frame width — suspicious; hoop conf only 0.57 |

**Critical concern:** In clips 1 and 3 the algorithm identified a lane line at pixel x=7 and x=1 respectively. These are at or within a few pixels of the left frame edge, strongly suggesting the algorithm is detecting the **frame border itself** as a vertical line rather than a real court lane boundary. The corner counts of 436 and 526 (clips 1, 2) are orders of magnitude higher than the 4 real corners a lane should produce, indicating the corner estimation is dominated by noise intersections. The STRONG verdicts are therefore preliminary and likely overoptimistic.

**Pose preliminary verdicts (clip 1 only — only clip with detected shots):**

| Shot | Result | Verdict | Shooter ID | Ankle conf | Release frame | Feet–traj dist |
|---|---|---|---|---|---|---|
| s001 | made | SHOOTER_NOT_FOUND | No | Low | None | N/A |
| s002 | made | PARTIAL_FEET | Yes | OK | None | 719 px |
| s003 | made | NO_FEET | Yes | Low | None | N/A |
| s004 | made | NO_FEET | Yes | Low | None | N/A |
| s005 | made | PARTIAL_FEET | Yes | OK | None | 254 px |

No release frame was detected in any shot. The 719px feet–trajectory distance for s002 (in a 1170px-wide frame) is suspicious and likely indicates a wrong shooter identification or a trajectory anchor near the top of the frame. These numbers require visual confirmation before drawing conclusions.

**Scope note:** Pose was meaningfully tested on only 5 shots from clip 1. The "WEAK" auto-recommendation from the cross-clip summary should not be treated as a general conclusion about pose viability. A larger shot set is needed.

### 18.3 Product-Oriented Shot-Location Direction (Under Evaluation)

The architecture being evaluated for production (see Section 17 for full design):

```
ShotEvent
  └─ PoseEstimator  (YOLOv8n-pose, shot windows only)
       ├─ Shooter identification (wrist-ball proximity)
       ├─ ReleaseEstimator  (last frame with wrist near ball)
       └─ PlayerAnchorEstimator  (feet/ankle midpoint)
            ↓
       OriginEstimator  (priority: feet anchor > release > trajectory baseline)
            ↓
       CourtMapper  (Tier 1: homography from court lines
                    Tier 2: hoop-anchor coarse transform
                    Tier 3: None)
            ↓
       ZoneClassifier  (11-polygon hit-test)
```

Tiered location confidence strategy:
- **Tier 1A** — full homography + feet anchor (highest accuracy)
- **Tier 1B** — full homography + trajectory anchor
- **Tier 2A** — hoop-anchor transform + feet anchor (coarse but useful)
- **Tier 2B** — hoop-anchor transform + trajectory anchor
- **Tier 3**  — `origin.court = None` (graceful failure, always valid per contract)

Future coaching potential from stored `PoseEvent` data (not in current scope):
knee bend angle, elbow position at release, body alignment, landing balance, release consistency across sessions.

### 18.4 Required Next Steps Before Any Implementation

1. **Human visual review for clips 1–6 is complete.** Use Section 18.9 as the updated interpretation baseline.
2. **Next required review is decoupled component review (`_diag_free_scan.py` outputs):**
   - Review `test_videos/output/<N>_free_scan/free_scan_report.txt` for N=1..6
   - Inspect selected frames from:
     - `test_videos/output/<N>_free_scan/hoop_scan/frame_*.jpg`
     - `test_videos/output/<N>_free_scan/ball_scan/frame_*.jpg`
     - `test_videos/output/<N>_free_scan/pose_scan/frame_*.jpg`
3. **Produce the component table before any production implementation:**
   `Clip | Hoop | Ball | Pose | Court | Failure reason | filming/threshold/model issue`
4. **Architecture decision after this table:** confirm CourtMapper tier priority and OriginEstimator/pose priority with evidence from both chain-based and decoupled diagnostics.

### 18.7 Shot-Detection Debug Results (New Footage — Clips 2–6)

> This section records findings from running `_diag_shot_detection.py` on the current clip set.
> Human visual review of the debug videos and key frames is still required before any pipeline tuning.

**Summary table (corrected after Session 6 diagnostic fix — see Section 18.8):**

| Clip | Resolution | Duration | Hoop det | Ball det | IN-UP | UP↑ | DN↓ | Pnd | Shots | Diagnosis |
|---|---|---|---|---|---|---|---|---|---|---|
| 1.mp4 | 1170×654 | 15.1s | 228 | 134 | 27 | 5 | 5 | 10 | 5 | **Correct** — 5 shots, 5 made |
| 2.mp4 | 1268×698 | 3.1s | 95 | 11 | 4 | 1 | 1 | 2 | 0 | Clip ends before confirmation poll fires after DOWN (gap=20f, clip ends f=93, next poll f=100) |
| 3.mp4 | 376×670 | 17.7s | 266 | 4 | 0 | 0 | 0 | 0 | 0 | Ball almost invisible (4 accepted) |
| 4.mp4 | 374×666 | 30.3s | 0 | 105 | 0 | 0 | 0 | 0 | 0 | No hoop |
| 5.mp4 | 376×668 | 28.2s | 0 | 9 | 0 | 0 | 0 | 0 | 0 | No hoop, minimal ball |
| 6.mp4 | 374×670 | 24.9s | 1 | 61 | 0 | 0 | 0 | 0 | 0 | Hoop detected once then lost |

**Column "Pnd"** = POLL_PENDING: polls that fired while UP was waiting for DOWN. UP persists across polls (not reset) — this is correct production behaviour.

**Root causes for zero confirmed shots (per clip):**

- **Clip 2 (3.1s, landscape):** Hoop stably detected. Ball sparse (11 accepted). UP fires at f=72, DOWN fires at f=92 (gap=20 frames — within the 120-frame max). **Root cause: the clip ends at f=93, but the next confirmation poll is at f=100. The poll never fires after DOWN triggers, so the shot is never confirmed.** The shot was real. Fix: add ≥0.5s of trailing footage, or implement an end-of-clip flush pass in the pipeline.

- **Clip 3 (17.7s, portrait 376×670):** Hoop stably detected (266 accepted). Ball barely visible — only 4 accepted ball detections, zero in the UP zone. The state machine never triggered UP. Root cause: at 376×670 with a 29×25px hoop, the ball in flight is too small for the model.

- **Clip 4 (30.3s, portrait 374×666):** YOLO fired only 2 raw hoop detections, both below the 0.50 threshold. State machine never ran. Ball was detected (105 accepted) but `hoop_pos` was always empty. 2 raw hoop detections below threshold — lowering `HOOP_CONF_THRESHOLD` may help.

- **Clip 5 (28.2s, portrait 376×668):** YOLO fired zero times on the hoop class. Only 9 balls accepted. Complete model failure — the hoop is not recognisable in this footage.

- **Clip 6 (24.9s, portrait 374×670):** A single hoop detection at conf=0.568. After that, `hoop_pos` expired (HOOP_WINDOW=25 inference frames ≈ 1.7s). State machine dormant for remaining 99% of clip. 61 balls accepted during hoop-absent periods.

**Clip usability tiers:**

- **Tier 1 — Unsuitable (clips 4, 5):** No hoop detected. Cannot contribute to validation without changing the scene setup.
- **Tier 2 — Borderline / needs tuning (clips 3, 6):** Hoop detectable in principle but ball nearly invisible (clip 3) or hoop drops out immediately (clip 6). May be recoverable with lower thresholds or better camera angle.
- **Tier 3 — Worth tuning (clip 2):** Hoop stable, ball reaches UP zone. Failure is specifically in UP→DOWN timing. The debug video will show whether a threshold or window change can fix it.
- **Clip 1 remains the only end-to-end working clip.**

**Note on false UP triggers in clip 1:** The event log shows 12 UP triggers and 10 RESET_NO_DOWN. Many UP triggers are caused by the ball being dribbled through the UP zone area (not actual shots). This is existing behavior from the original algorithm — the rolling window's `ball_pos[-1]` can be a stale dribble position when the state machine polls. This affects shot count accuracy but not correctness on true shots.

### 18.8 Clip-1 Discrepancy — Root Cause Found and Fixed (Session 6)

> **Status: RESOLVED.** The discrepancy described in the handoff note (Section 5 of the Session 6 handoff) has been fully explained and corrected. No production code was changed.

**The discrepancy:** `_diag_shot_detection.py` reported 2 shots for clip 1; `test_cv.py` / `cv_pipeline._run_pipeline_inner()` reported 5 shots.

**Root cause:** A single indentation difference in the confirmation-poll reset logic.

In `cv_pipeline.py` (production):
```python
if frame_idx % ATTEMPT_CONFIRM_EVERY == 0:
    if up and down and up_frame < down_frame:
        ...confirm/reject shot...
        up = False       # ← 16 spaces — INSIDE the `if up and down` block
        down = False     # ← 16 spaces
```
`up` and `down` are only reset when a complete UP→DOWN pair is processed. When UP has fired but DOWN has not yet arrived, `up` **persists** across polls — the state machine waits silently until DOWN fires (up to `ATTEMPT_MAX_FRAME_GAP=120` frames).

In `_diag_shot_detection.py` (old, buggy):
```python
if frame_idx % cv_pipeline.ATTEMPT_CONFIRM_EVERY == 0:
    if up and down and up_frame < down_frame:
        ...confirm/reject shot...
    elif up and not down:
        reset_no_down_count += 1   # ← logged "RESET_NO_DOWN"
    up = False       # ← 12 spaces — UNCONDITIONAL reset at every poll
    down = False     # ← 12 spaces
```
`up` was reset unconditionally at every poll, discarding any in-progress shot where DOWN had not yet fired. Most basketball shots take 14–44 real frames from UP to DOWN on clip 1 — all were silently discarded.

**Consequence:** Shots 1–3 and 5 in clip 1 (arc gaps 14f, 18f, 28f, 44f) were all missed by the broken diagnostic. Only shot 4 (gap=10f) and shot 5 (gap=8f in the broken run) were occasionally captured. The "RESET_NO_DOWN" events logged were false — no reset actually happens in production.

**Fix applied to `_diag_shot_detection.py`:**
- `up = False; down = False` moved inside the `if up and down` block (16-space indent, matching production).
- `elif up and not down:` now logs `POLL_PENDING` (informational only — UP is still waiting for DOWN, not being reset).
- Renamed `reset_no_down_count` → `poll_pending_count`.
- Root-cause analysis updated, including a new case for "clip ends before poll fires" (the accurate diagnosis for clip 2).
- Summary table column renamed Rst → Pnd.

**Verified results after fix:**
- Clip 1: **5 shots, 5 made** — identical to `test_cv.py`. Event log matches exactly.
- Clip 2: **0 shots** — correct; DOWN fires at f=92 (gap=20f) but clip ends at f=93, next poll would be f=100. Shot was real, clip is too short.
- Clips 3–6: unchanged (all 0 shots, same root causes as before).

**No production code was changed.** `cv_pipeline.py`, `AnalyzeResult` contract, `OriginEstimator`, and all tunables are untouched.

### 18.9 Session 7 Checkpoint — milestone presentation, visual review complete, decoupled diagnostics

**Product stage update:**
- A milestone presentation (e.g. academic / stakeholder review) completed successfully.
- **xShot AI is the main product under active development** — not a disposable demo codebase.
- This does **not** unlock any contract or architecture changes: all locked decisions in Sections 5, 7, 11, and 18.5 still apply.

**Human visual review status:**
- Human visual review for clips 1–6 is complete.
- Main interpretation: most failures are explained by filming/input conditions, not by a fundamental failure of the current system.

**Clip-level summary (human-reviewed interpretation):**
- **Clip 1:** Strong positive reference. Hoop, ball, UP/DOWN, shot detection, and make/miss all work well (**5 shots, 5 made**). Pose/skeleton signal appears promising, but higher-level pose usage is still incomplete (shooter selection reliability, robust feet anchor, release-frame detection).
- **Clip 2:** Not a true detection failure. Clip is too short. UP and DOWN occur, but the video ends before the next confirmation poll. Future options: require trailing footage, or later evaluate an end-of-clip flush path.
- **Clip 3:** Not a strong negative signal. Ball is black/hard to detect, so ball detections are weak and the chain falls before UP.
- **Clip 4:** Ball detections exist, but hoop detection fails. Hoop is visible to humans but appears difficult for the model under this filming condition (angle, thin rim, outdoor/no-net appearance, or low clarity).
- **Clip 5:** Hard footage, similar to clip 4 but worse. Outdoor/no-net/angle/visibility limitations should not be treated as proof that the core pipeline is bad.
- **Clip 6:** Ball detections are relatively good; hoop is detected somewhat but not stably enough. Unstable hoop detection causes the shot chain to fail.

**Main conclusion (encouraging finding):**
- The current system appears healthy under good filming conditions.
- Most failures in clips 2–6 are explainable by input conditions: short clip, black/difficult ball, small/distant ball, outdoor hoop, no/weak net, thin/small rim, vertical/remote footage, unstable hoop detection, and cluttered background.

**Diagnostic architecture insight:**
- Previous diagnostics were too chain-dependent:
  `stable hoop -> UP-zone -> UP/DOWN -> confirmed shot -> pose window`.
- If an early component fails, later components may never be evaluated. This can hide strengths (for example, pose can be good in a clip even when no shot is confirmed).

**New diagnostic-only tool added and run:**
- `backend/_diag_free_scan.py` was added as a **diagnostic-only** script and successfully run.
- Purpose: decoupled component diagnostics for hoop, ball, and pose so each component can be evaluated independently even when the shot pipeline fails.
- Generated outputs:
  - `backend/test_videos/output/1_free_scan/`
  - `backend/test_videos/output/2_free_scan/`
  - `backend/test_videos/output/3_free_scan/`
  - `backend/test_videos/output/4_free_scan/`
  - `backend/test_videos/output/5_free_scan/`
  - `backend/test_videos/output/6_free_scan/`
- Each folder contains:
  - `hoop_scan/`
  - `ball_scan/`
  - `pose_scan/`
  - `free_scan_report.txt`
- Visual outputs are the primary deliverable; `free_scan_report.txt` is secondary summary context.

**Production isolation and performance caution:**
- `_diag_free_scan.py` is strictly diagnostic and must **not** be wired into production.
- It must not affect app behavior, `AnalyzeResult`, make/miss scoring, frontend flow, or the production CV pipeline.
- It is intentionally heavier/slower (broad diagnostics, annotated frame export, pose sampling, report generation). This is acceptable for investigation only.
- The final product path must stay fast by using lightweight/targeted logic in production (selected detector outputs, confidence gating, and limited pose windows only when required).

**Current immediate next step (before production changes):**
- Review `*_free_scan/free_scan_report.txt` and selected `hoop_scan/`, `ball_scan/`, `pose_scan/` frames.
- Produce the comparison table:
  `Clip | Hoop | Ball | Pose | Court | Failure reason | filming/threshold/model issue`.
- Do not implement production `CourtMapper`, `ZoneClassifier`, threshold changes, end-of-clip flush, or pose integration before this review table is finalized.

### 18.10 Object-detection improvement plan, weak-hoop fallback, and Clip 6 finding

> **Read this section when continuing detection work or before mapping/court-line production changes.**  
> Documentation only — constants here describe **diagnostic scripts** and **intent**, not committed production values unless explicitly wired later.

#### 18.10.1 Staged detection-improvement track (before CourtMapper / ZoneClassifier)

The broader sequence **before** returning to court mapping, `CourtMapper`, `ZoneClassifier`, or production shot-location mapping:

| Stage | Focus | Notes |
|---|---|---|
| **1 — Hoop** | Hoop detection quality and diagnostics | Primary hoop threshold **candidate**: `0.46` (not committed in `cv_pipeline.py` until approved). Weak-hoop fallback explored via `_diag_weak_hoop_fallback.py`. Goal: understand and improve hoop signal **before** mapping. |
| **2 — Ball** | Ball detection | Planned **after** hoop work. Investigate ball threshold tuning and stronger ball diagnostics. Possible future experiments: threshold sweeps, `imgsz`, SAHI, or other ball-specific approaches. **Keep separate from hoop changes** so effects are attributable. |
| **3 — Pose / skeleton** | Keypoint reliability | Planned **after** ball. Improve wrist/ankle/player keypoint quality. **Separate diagnostic stage** — do not mix with hoop or ball experiments in the same run. |
| **4 — Release-frame diagnostic** | Release timing | Planned **after** ball and pose are better understood. Likely approach: wrist–ball proximity and separation over time. Remains **diagnostic / optional first** — no production wiring until validated. |

Ordered roadmap for this phase: **Hoop diagnostics → Ball diagnostics → Pose diagnostics → Release-frame diagnostic →** then deeper shot-chain and mapping work.

#### 18.10.2 Weak-hoop fallback — status (integrated into production, Session 8)

- The weak-hoop fallback is now **wired into `cv_pipeline.py`** as an isolated, self-disabling extension.
- It activates **only** when `hoop_accepted_count < HOOP_FALLBACK_REGULAR_MIN (10)` AND the normal pass produced no shots — clips with strong regular hoop signal (e.g. clip 1: 228 accepted) are **completely unaffected**.
- Three new named constants control it: `HOOP_FALLBACK_CONF_MIN = 0.20`, `HOOP_FALLBACK_MIN_FRAMES = 5`, `HOOP_FALLBACK_REGULAR_MIN = 10`.
- Two new isolated functions added: `_compute_hoop_fallback_consensus()` and `_run_state_machine_with_fallback()`.
- The YOLO inference call now uses `conf=HOOP_FALLBACK_CONF_MIN` so weak hoop boxes are visible in the loop; per-class thresholds are applied in code as before.
- `all_ball_raw` accumulates all accepted ball detections during the main pass for state-machine replay (no second YOLO pass).
- `weak_hoop_raw` accumulates hoop boxes in `[HOOP_FALLBACK_CONF_MIN, HOOP_CONF_THRESHOLD)` for consensus computation.
- **`_score()`, make/miss helpers, `AnalyzeResult` contract, `OriginEstimator`, `CourtMapper`, `ZoneClassifier` are untouched.**

**Baseline results after integration (Session 8):**

| Clip | Before (shots/made/missed) | After (shots/made/missed) | What changed |
|---|---|---|---|
| 1.mp4 | 5 / 5 / 0 | **5 / 5 / 0** | No change — fallback not triggered (228 regular hoop frames) |
| 2.mp4 | 0 / 0 / 0 | **0 / 0 / 0** | No change — fallback not triggered (95 regular hoop frames) |
| 3.mp4 | 0 / 0 / 0 | **0 / 0 / 0** | No change — fallback not triggered (266 regular hoop frames) |
| 4.mp4 | 0 / 0 / 0 | **0 / 0 / 0** | Fallback attempted, not triggered — only 2 unique-frame weak boxes (need ≥ 5) |
| 5.mp4 | 0 / 0 / 0 | **0 / 0 / 0** | Fallback attempted, not triggered — 0 weak hoop detections |
| 6.mp4 | 0 / 0 / 0 | **4 / 0 / 4** | **Fallback activated** — consensus at (124, 170) from 57 weak frames; 4 shots confirmed via state-machine replay |

**Clip 6 make/miss note:** All 4 shots are classified as missed in production. Three have `no_crossing(1pts)` (only 1 above-rim ball detection — ball not visible near rim); one has a linear scoring attempt (`pred_cx=105.5`) that narrowly falls outside the rim acceptance window (`[106.3..141.8]`). **Fixed two-gate diagnostic (`_diag_below_rim_gate.py`):** would upgrade **one** shot (s003) to MAKE vs baseline **4 / 0 / 4** — see **Section 9** for rules and frame-level evidence. Ball-visibility limits remain the dominant factor for hard misses.

**Next investigation:** release moment / shot-release detection as a **standalone diagnostic module** first (Section 9).

#### 18.10.3 Clip 6 — important positive finding

- Under the regular production hoop threshold, Clip 6 previously looked like **unstable / near–no-hoop** (single high-conf detection then loss).
- The weak-hoop fallback diagnostic showed that the model **does** detect the hoop **weakly but repeatedly**: many low-confidence boxes that **overlap strongly** in image space.
- Intersection of those boxes yields a **tight consensus region** and a **stable consensus hoop center**; **human visual review** indicated the center **lands on the real rim/hoop**.
- **Conclusion:** the fallback **concept is promising** for hoop localization on static-camera footage where the rim position is fixed — subject always to per-clip visual confirmation.

#### 18.10.4 Current diagnostic fallback algorithm (`_diag_weak_hoop_fallback.py`)

Parameters are **named constants in the script** (diagnostic defaults for the next run):

| Parameter | Value | Role |
|---|---|---|
| Primary hoop threshold candidate | `0.46` | Detections at or above this are treated as “primary” in the diagnostic overlay. |
| Weak fallback minimum confidence | `0.20` | Minimum confidence to consider a hoop box as a weak candidate. |
| Minimum weak detections | `5` | At least this many weak boxes, from **different frame indices** (best box per frame after dedup), required before a fallback can be declared. |
| Overlap rule | intersection | Weak boxes must share a **non-empty axis-aligned intersection** (common overlap region). The **center of that intersection** is the **fallback consensus hoop center**. If the full intersection is empty due to jitter, the script may search smaller subsets (still diagnostic logic only). |
| Search scope | whole clip | Fallback considers weak boxes **across the full clip**, consistent with **static camera** and **fixed hoop** position in frame. |

Median center may be shown as a **secondary** reference when geometry fails; the **main experiment** is **overlap / intersection–based** consensus.

#### 18.10.5 `FALLBACK_FRAME_WINDOW = 50` (named constant)

- `FALLBACK_FRAME_WINDOW = 50` exists as a **named constant** in `_diag_weak_hoop_fallback.py`.
- It is **not** wired into the fallback **decision** logic in the current script.
- It does **not** mean the algorithm searches only within 50 frames, and it **must not** be read as limiting global hoop search today.
- **Intended future use (if any):** visual/context output, annotations, or a **local diagnostic window** — not as a rule that caps where weak boxes may be collected across the clip unless explicitly redesigned and documented.

#### 18.10.6 Future note — diagnostic shot-chain simulation

- The fallback hoop center might later be exercised in a **diagnostic shot-chain simulation** (e.g. on Clip 6) to see whether a stable synthetic hoop position helps UP/DOWN and shot detection.
- This is **not** necessarily the immediate next step; it sits alongside the staged plan in §18.10.1.

#### 18.10.7 Future principle — multiple visible hoops

When **more than one** hoop is visible:

- Do **not** assume the **highest-confidence** detection is always the **shot target** hoop.
- A reasonable default is to prefer a **stronger / more stable** hoop candidate when ambiguous.
- If **ball trajectory** clearly aims at a **weaker** hoop candidate, that weaker candidate should be treated as the **target hoop for that shot**.
- This matters for future court mapping: **`shot → target hoop → mapping context`** must stay consistent with which hoop defined the play.

#### 18.10.8 Future options (diagnostic only, not current implementation)

> **Decision checkpoint (current):** Do not block progress now on Clip 3 ball-detection improvement or on pose-detection improvement. Continue using currently usable clips. Revisit these options only if the same failure patterns repeat on better-quality footage.

##### Ball detection — future options (deferred)

- **Threshold sweep / lower-confidence diagnostics:** Run controlled threshold sweeps (including lower confidence ranges) and review false positives frame-by-frame before any production change.
- **Higher inference image size (`imgsz`):** Test whether larger inference resolution improves small-ball recall enough to justify runtime cost.
- **Alternative existing basketball/ball YOLO models:** Benchmark against the current model before considering fine-tuning.
- **Crop/tile-based inference for small balls:** Keep as **diagnostic-only** experiment first (e.g., localized crops/tiles around likely play regions), not production wiring.
- **Temporal filtering / tracking:** Consider only when there are enough real detections to bridge short gaps; do not use interpolation to invent long missing trajectory segments.
- **Fine-tuning (last resort):** Only if dark/small/low-contrast ball failures recur on better footage; collect targeted positives + hard negatives and validate recall vs false positives.
- **Footage-first controls:** Before model changes, verify camera distance, lighting, contrast, and framing are not the dominant bottleneck.

##### Pose / skeleton — future options (deferred)

- **Larger pose model candidates:** Evaluate `yolov8s-pose` / `yolov8m-pose` against current runtime and keypoint quality.
- **Higher inference image size (`imgsz`):** Test whether wrist/ankle consistency improves on distant or vertical footage.
- **Player-focused cropping:** If full-frame pose is inconsistent, test crop-first diagnostics around the visible player.
- **Lower-confidence threshold diagnostics:** Explore confidence thresholds in diagnostic runs to measure recall/precision trade-offs before any production decision.
- **Temporal smoothing/interpolation:** Use only for short pose gaps when adjacent frames are reliable; do not over-smooth weak tracks.
- **Filming/visibility interpretation rule:** Missing pose in poor framing/visibility should be treated first as footage limitation, not automatically as model failure.
- **Feature gating principle:** Keep shooter-ID, release-frame, and feet-anchor outputs confidence-gated; if confidence is low, fall back gracefully to existing non-pose baseline behavior.

#### 18.10.9 Locked constraints (detection phase)

- Do **not** touch `_score()` or any make/miss helpers.
- Do **not** change the frozen `AnalyzeResult` contract.
- Do **not** implement `CourtMapper` / `ZoneClassifier` or production shot-location mapping **yet**.
- Do **not** prioritize production court-line mapping work **right now**; court-line diagnostics (`_diag_court_lines.py`) remain **off production path** until detection stages justify it.
- Do **not** wire any diagnostic script into production **without explicit approval**.
- Each detection-improvement stage (hoop, ball, pose, release) should stay **isolated** and **measured separately** so regressions are traceable.

#### 18.10.10 Latest session decisions (current checkpoint)

**Current decisions (locked for now):**
- **Strict weak-hoop fallback is integrated and tested.** Baseline before fallback: `1.mp4 = 5/5/0`, `2–6.mp4 = 0/0/0`.
- **Post-fallback status:** `1.mp4` stayed stable at `5/5/0` (no harm), `6.mp4` improved to `4 shots` (`0 made / 4 missed`), and is the clear successful fallback case.
- `4.mp4` remains `0` because only **2 unique weak-hoop frames** were found (below current `>=5` requirement). `5.mp4` remains poor-footage / low-priority.
- **Clip 3 remains a known stress case** (dark/small/low-contrast ball, sparse detections). Do **not** block progress on clip 3 now.
- **Do not** fine-tune, switch models, use SAHI, or add tracking solely for clip 3 at this stage.
- **Pose/release is not a blocker now.** Pose quality is strongly filming/framing dependent; keep pose/release as a future diagnostic stream.

**Performance / architecture direction (current):**
- Current YOLO path already detects **ball + hoop in one inference pass**.
- Splitting ball/hoop inference is **not** the main speed win now.
- Better future speed path: run pose only around suspected shot windows (not continuously), treat hoop as a static anchor after detection/fallback, and keep ball as the denser continuous signal.

**Future options (not prioritized now):**
- **Two-tier fallback idea discussed, not implemented now.**
- Keep as future option only:
  - **Strong fallback:** `>=5` weak detections with overlap/intersection consensus (current strict path).
  - **Possible weak fallback (future):** `2–4` weak detections accepted only with extra evidence (e.g., ball trajectory moving toward the same candidate hoop area).
- Revisit clip-3-focused ball improvements only if the same failure repeats on better-quality footage.

**Next investigation (current):**
- **Release moment / shot-release refinement:** production baseline is now integrated via bounded per-shot person-bbox step-search (Section 18.10.11). Next work is confidence/refinement diagnostics (especially unresolved cases) without changing `_score()`/make-miss.

**Supplementary make/miss cue — fixed two-gate:** Rules, geometry, and production checkpoint are documented under **Section 9**. `_score()` stays primary; two-gate is MISS→MAKE supplementary only.

#### 18.10.11 Release-moment implementation checkpoint (current)

**Status update (implemented):**
- The validated release-step behavior from `backend/test_videos/output/1_release_step_diag/` is now integrated through the `OriginEstimator` plug-in path.
- Production wiring point: `backend/release_estimator.py` (new) injected by `backend/cv_pipeline.py` into `OriginEstimator(release_estimator=...)`.
- `_score()`/make-miss/state-machine loop/`AnalyzeResult`/frontend remain unchanged.

**Why this change was required:**
- The previous release diagnostic frequently selected `physical_release_candidate` too close to `up_frame` (already near airborne UP→DOWN trajectory), which was too late for physical-release semantics.

**Integrated algorithm (source-of-truth behavior):**
1. Start at `up_frame` (already confirmed shot event).
2. Jump backward by `25` frames each step: `up`, `up-25`, `up-50`, ...
3. At each backward step, detect ball (`best.pt`) and person (`yolov8n.pt`) and check contact:
   - ball center inside shooter person bbox, OR
   - ball bbox overlaps shooter person bbox.
4. Stop backward search at first contact frame.
5. From that contact frame, jump forward by `5` frames each step.
6. First forward step where ball is no longer inside/overlapping shooter bbox is selected `release_frame` (`physical_release_candidate.frame_index`).
7. Emit release window: `[release_frame - 12, release_frame + 5]`.

**Model / runtime boundaries:**
- Ball detector: `best.pt` (class `0`).
- Person detector: `yolov8n.pt` (COCO person class `0`).
- Person detection is run only on bounded per-shot candidate frames (not in the main per-frame state-machine loop).

**Separation of responsibilities (locked):**
- **Person bbox cue (implemented baseline):** coarse but stable release-area/contact-exit timing.
- **Pose/keypoint cue (future refinement):** wrist/hand-ball separation and form/coaching-quality signals.

**Carry-forward reliability rule:**
- If evidence is insufficient, do not force a fake near-`up_frame` release; return unresolved/low-confidence fallback behavior rather than a misleading late release.

### 18.5 Locked Constraints (Carry Forward)

These constraints apply to all future sessions working on shot-location:

- Do **not** touch `_score()` or any make/miss helpers.
- Do **not** change the frozen `AnalyzeResult` contract (`xShot-prototype/analyze_result_spec.md`).
- Do **not** wire `_diag_court_lines.py` or `_diag_pose_windows.py` into the production pipeline.
- Do **not** wire `_diag_shot_detection.py`, `_diag_free_scan.py`, `_diag_hoop_threshold.py`, or `_diag_weak_hoop_fallback.py` into the production pipeline **without explicit approval**.
- Do **not** make final architecture decisions before the decoupled component review in Section 18.4 is complete.
- If court/pose confidence is low, fail gracefully: `origin.court = None`, `zone = None`.
- Keep all new modules isolated and swappable (same pattern as `origin_estimator.py`).
- `CourtMapper`, `ZoneClassifier`, `PlayerAnchorEstimator` are called **after** the while loop in `_run_pipeline_inner`, never from inside `_score()` or the state machine.
- Do **not** implement `CourtMapper` / `ZoneClassifier` **yet**; complete the **object-detection improvement track** in Section 18.10 first unless the product owner explicitly reprioritizes.

### 18.6 Handoff Note for New Sessions

A new Cursor chat can continue this work by:

1. Reading this file (`PROJECT_CONTEXT.md`) top to bottom, especially Sections 9, 17, 18, and **18.10** (object-detection improvement plan and weak-hoop fallback).
2. Reading `xShot-prototype/analyze_result_spec.md` (frozen API contract) before touching any data shape.
3. Reading `xShot-prototype/next_steps.md` for the full roadmap.
4. Asking the user to confirm the visual review outcome (Section 18.4) before writing any production code.
5. Not re-opening any decision locked in Section 7.

**Key diagnostic outputs for review (all in `backend/test_videos/output/`):**
- `<N>_shot_diag/debug_video.mp4` — per-frame state machine debug video (see Section 18.7)
- `<N>_shot_diag/shot_diag_report.txt` — event log + root cause + review checklist
- `<N>_court_diag/frame_analysis.jpg` — court-line detection overlay
- `1_pose_diag/s00N_pose_window.mp4` — pose window for each shot in clip 1
- `<N>_free_scan/hoop_scan/frame_*.jpg` — independent hoop visibility/detectability scan
- `<N>_free_scan/ball_scan/frame_*.jpg` — independent ball visibility/detectability scan
- `<N>_free_scan/pose_scan/frame_*.jpg` — independent pose/skeleton viability scan
- `<N>_below_rim_gate/` — two-gate presence diagnostic (`_diag_below_rim_gate.py`): `gate_diag_report.txt`, per-shot `s***_gate_diag.mp4`
- `<N>_free_scan/free_scan_report.txt` — per-clip cross-component summary

The diagnostic scripts (`_diag_shot_detection.py`, `_diag_court_lines.py`, `_diag_pose_windows.py`, `_diag_free_scan.py`, `_diag_below_rim_gate.py`) can be re-run at any time on new footage without touching the production pipeline.
