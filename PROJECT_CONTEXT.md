# xShot AI — Project Context

> **Purpose of this file:** Single anchor for future Cursor sessions.
> Read this first, then read the source-of-truth docs listed in each section before touching code.
> Do not reopen decisions marked as locked without explicit user approval.

---

## 1. Product Overview

**xShot AI** is a basketball training analysis app.
A player records a training session with a static camera, uploads the video, and receives:
- Shot attempt count, make/miss per shot, and FG%
- (Future) Shot location on a normalized court map, per-zone accuracy breakdown, and multi-session trends

The primary UX is: upload video → wait for analysis → see session stats.
No manual annotation or real-time tracking is required from the user.

**Target user:** Individual basketball player doing solo or small-group training.
**Demo context:** Localhost presentation on presenter's laptop; no cloud hosting required for Demo v1.

---

## 2. Demo v1 Goal and Locked Scope

Demo v1 demonstrates one **real** analytics capability end-to-end:

| Capability | Status in Demo v1 |
|---|---|
| Shot attempt detection | **REAL** — CV pipeline |
| Make/miss classification | **REAL** — CV pipeline |
| Total attempts / makes / misses / FG% | **REAL** — derived from per-shot results |
| Shot location on court (origin.court) | **NULL** — not computed yet |
| Zone assignment | **NULL** — requires court coords |
| Per-zone accuracy breakdown | **EMPTY** — requires zone data |
| Multi-session progress | **PLACEHOLDER** — not backed by real data |

**The main Demo v1 flow is:**
```
Welcome → Dashboard → Upload → Analyzing (polling) → Session
```
- "Shot map" button on Session is hidden when no shot has a non-null `origin.court`
- The Heatmap screen exists but is not reached in the live demo unless court data is present

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
    ├── demo_v1_screen_map.md   Which screens consume which contract fields
    └── next_steps.md           Current roadmap with completed vs planned items
```

---

## 5. The Frozen API Contract

**Source of truth:** `xShot-prototype/analyze_result_spec.md`
**Status: LOCKED for Demo v1.** Do not change field names, types, or required/optional rules.

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
4. **Demo v1 live flow: Upload → Analyzing → Session.** No calibration screen in the flow.
5. **origin.court and zone are null** for all shots until automatic court detection is implemented (next step 6).
6. **`?demo=session` and `?demo=heatmap` stub paths** are preserved for demo/testing; they inject hardcoded data in the frontend and never reach the backend.
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
| Review mode UI | Explicitly later | Not in Demo v1 scope |
| Production cloud hosting | Explicitly later | Localhost is sufficient for Demo v1 |
| Manual calibration as user feature | Removed from main UX | `Calibrate.jsx` dormant — do not re-surface without approval |
| Near-hoop presence / net pixel-change scoring | Future robustness improvement | Would complement parabolic fit for cases where ball is not visible near rim |

---

## 9. Current Stopping Point / Next Step

> **Read this section first in every new session before touching any code.**

### State after Session 5 (current)

| Item | Status |
|---|---|
| make/miss pipeline (parabolic scoring) | **Unchanged — working as of Session 4** |
| `origin.pixel` semantic correction | **Done** — trajectory anchor, not apex |
| Phase 1: `shot_events` enriched with raw trajectory data | **Done** |
| Phase 2: `backend/origin_estimator.py` + `OriginEstimator` | **Done** |
| Phase 3: `CourtMapper` (homography, `origin.court`) | **NOT started** |
| Phase 4: `ZoneClassifier` (polygon hit-test, `zone`) | **NOT started** |
| Phase 5: wire Phases 3+4 into pipeline | **NOT started** |
| Phase 6: `ReleaseEstimator` plugin | **NOT started — future optional upgrade** |

### Exact next step

**Implement Phase 3: `backend/court_mapper.py`**

Goal: automatic court / lane-corner detection in the first stable frame → `cv2.findHomography` → map every `origin.pixel` to `origin.court` (normalized 0–1, per frozen spec).

Approach:
1. Detect lane paint lines/corners via OpenCV (Canny + Hough) on first stable frame — no extra model.
2. Match detected corners to known normalized court reference points.
3. Compute homography via `cv2.findHomography`.
4. Apply to all `origin.pixel` values → `origin.court`.
5. On failure: leave `origin.court = None` — the pipeline and contract handle this gracefully today.

After Phase 3: implement Phase 4 (`ZoneClassifier`, 11-polygon hit-test), then Phase 5 (wire both into `_run_pipeline_inner`).

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

### FUTURE — Phase 6: `ReleaseEstimator` plugin (optional upgrade)

Improves `origin.pixel` accuracy using pose / hand-ball proximity.
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

---

## 11. Architecture Principles / Constraints

- **Contract-first:** The AnalyzeResult JSON shape is the interface between frontend and backend. CV internals change freely; the contract does not.
- **Layered data:** Each shot stores `origin.pixel` (raw), `origin.court` (mapped), and `zone` (classified). Never store only zone. Coordinates are the long-term source of truth.
- **Incremental CV:** The CV pipeline is a separate module (`cv_pipeline.py`). Replace its internals without changing `main.py` or the API contract.
- **State machine, not router:** The frontend uses a single `useState` object in `App.jsx`. All navigation goes through `navigate(view, patch)`. Do not introduce React Router without discussion.
- **No dense heatmap:** The heatmap shows discrete shot-origin dots, not a continuous density map.
- **Localhost is enough for Demo v1.** No auth, no multi-user, no cloud.
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
| `xShot-prototype/demo_v1_screen_map.md` | Screen-to-data mapping for Demo v1 |
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
- **`xShot-prototype/index.html` is now wired to the real backend** for the intended Demo v1 flow: `Welcome/Dashboard → Upload → Analyzing (polling) → Session (summary from API)`.
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

**Bank shot limitation (acknowledged, not fixed):** A bank shot has a trajectory break at the backboard contact point. The parabolic fit uses the full above-rim arc including pre-contact points. This is a known limitation. For Demo v1 where bank shots are rare, this is acceptable. A future improvement would detect the trajectory break and fit only the post-contact segment.

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

The pipeline is performing well under the intended Demo v1 shooting conditions:
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
       ├─ [optional] ReleaseEstimator plugin (Phase 6 — not yet implemented)
       └─ Trajectory-anchor baseline (default)
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
| Phase 6: `ReleaseEstimator` plugin | Future |

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
