# xShot AI — Claude Instructions

xShot AI is a basketball training analysis app. A player uploads a video → gets shot count, make/miss per shot, and FG%. No manual annotation required.

---

## Team structure (3 members)

| Member | Branch | Responsibility |
|---|---|---|
| 1 — Performance | `performance/runtime` | Speed up analysis (caching, ONNX) — backend only |
| 2 — Feedback | `feature/feedback-visuals` | Visual feedback + Analyzing screen — feedback.py + React |
| **3 — Location/Mobile (THIS)** | `feature/location-mobile` | court_mapper + zone_classifier + responsive CSS + cloud deploy |

> **Before any code change:** read `PROJECT_CONTEXT.md`, `xShot-prototype/analyze_result_spec.md`, `xShot-prototype/next_steps.md`.  
> **After any backend change:** run `python backend/_run_all_validation.py` and verify shots/made/missed are unchanged.

---

## Current release scope

| Capability | Status |
|---|---|
| Shot detection + make/miss + FG% | **REAL** — CV pipeline |
| `origin.court` (court coordinates) | **NULL** — task for member 3 |
| Zone assignment (11 zones) | **NULL / EMPTY** — task for member 3 |
| Responsive mobile UI | **MISSING** — task for member 3 |
| Cloud deployment | **NOT DEPLOYED** — task for member 3 |
| Multi-session, social features | **OUT OF SCOPE** |

---

## 🔴 Frozen API contract

`xShot-prototype/analyze_result_spec.md` is the source of truth and is **locked**.  
**Do not change field names, types, or required/optional rules without explicit user approval.**

---

## Architecture

| Component | File | Role |
|---|---|---|
| Backend API | `backend/main.py` | POST /analyze, GET /jobs/{id} |
| CV pipeline | `backend/cv_pipeline.py` | YOLOv8n rolling-window make/miss classifier |
| Frontend root | `frontend/src/App.jsx` | State machine, DEMO_STUB flag |
| API client | `frontend/src/api.js` | postAnalyze(), getJob() |
| Spec docs | `xShot-prototype/` | Read before touching API or UI contracts |

---

## 🔴 Do NOT touch — Make/Miss Algorithm

The "did the ball go in?" logic lives entirely in `backend/cv_pipeline.py`. **Do not modify these functions without explicit approval:**

| Function | Lines | Role |
|---|---|---|
| `_score()` | 526–557 | Primary make/miss decision |
| `_fit_rim_crossing()` | 351–432 | Parabolic/linear trajectory fit |
| `_check_rim_crossing()` | 435–441 | Rim opening check |
| `_check_two_gate_presence()` | 460–523 | MISS→MAKE two-gate upgrade |

**Safe to touch** (player location only):
- `backend/origin_estimator.py` — computes `origin.pixel`
- `backend/release_estimator.py` — optional plugin for release-point detection
- `backend/court_mapper.py` — maps pixel → court coordinates

---

## Hard rules

- Never surface `Calibrate.jsx` in the main user flow (it's a dormant fallback only)
- Never change the API contract without approval
- Never add features outside the locked scope without a clear request
- Read `xShot-prototype/project_brief.md` before making architectural decisions

---

## 🟡 Member 3 — What to build & where

### Court mapping (backend)

| File | Status | Notes |
|---|---|---|
| `backend/court_mapper.py` | **EXISTS** — has homography via 6 calibration points | Currently requires manual calibration — member 3 should make detection automatic (HoughLines) |
| `backend/zone_classifier.py` | **TO CREATE** | Hit-test origin.court against 11 polygons from spec |
| `backend/cv_pipeline.py` | **EXISTS** — add call after the while loop only | Wire CourtMapper + ZoneClassifier into shot_points |

**11 zones** are defined in `xShot-prototype/analyze_result_spec.md` — read before writing zone_classifier.py.  
**Fields to fill** (already in contract, currently null): `origin.court`, `zone`, `zone_aggregates`, `mapping`.  
**Do NOT add new fields** — only populate existing ones.  
**If detection fails** → return `None` gracefully, never crash.

### Automatic court detection approach
Use `cv2.HoughLinesP` on the first stable frame to detect court boundary lines → derive homography automatically without user calibration.  
Fallback: if auto-detection fails → `origin.court = None`, `zone = None` for all shots.

### Responsive mobile (frontend)

| File | Change |
|---|---|
| `frontend/src/index.css` | Add `@media (max-width: 480px)` base rules |
| `frontend/src/screens/*.css` | Per-screen mobile tweaks |
| `frontend/src/components/BottomNav.jsx` | Already exists — verify it works on small screens |
| `frontend/src/components/CourtMap.jsx` | Improve display when `court` data is available |

Do NOT touch `App.jsx` state machine or `api.js`.

### Cloud deployment

Recommended: **Render.com** (free tier)
- Backend → Web Service (FastAPI + uvicorn + `best.pt`)
- Frontend → Static Site (Vite build)
- Needs: `Dockerfile` at repo root, `BACKEND_URL` env var, CORS update in `main.py`
- Update `frontend/vite.config.js` proxy from `localhost:8000` → cloud URL

---

## Files member 3 may touch

```
backend/court_mapper.py          ✅ modify (make auto-detection)
backend/zone_classifier.py       ✅ create
backend/cv_pipeline.py           ✅ add call AFTER while loop only
backend/requirements.txt         ✅ add deps if needed
frontend/src/index.css           ✅ responsive
frontend/src/screens/*.css       ✅ responsive
frontend/src/components/CourtMap.jsx  ✅ improve
frontend/vite.config.js          ✅ cloud proxy
Dockerfile                       ✅ create
```

## Files member 3 must NOT touch

```
backend/entry_make_miss.py       ❌ member 1
backend/feedback.py              ❌ member 2
backend/main.py                  ❌ no endpoint changes
backend/origin_estimator.py      ❌ locked
frontend/src/App.jsx             ❌ no state machine changes
frontend/src/api.js              ❌ locked
xShot-prototype/analyze_result_spec.md  ❌ FROZEN
```

---

## Court coordinate convention

`CourtCoord`: x ∈ [0,1] left→right, **y ∈ [0,1] where y=0 is near the hoop, y=1 is the far end.**  
This is inverted from screen/image coordinates — always double-check before mapping.

---

## Dev setup

```bash
# Backend
cd backend && uvicorn main:app --reload

# Frontend
cd frontend && npm run dev
```

## Running tests

```bash
# Single clip test
python backend/test_cv.py

# Full validation suite
python backend/_run_all_validation.py
```

---

## Response language

Respond in the language the user writes in (Hebrew or English).
