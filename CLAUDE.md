# xShot AI — Claude Instructions

xShot AI is a basketball training analysis app. A player uploads a video → gets shot count, make/miss per shot, and FG%. No manual annotation required.

---

## Current release scope

| Capability | Status |
|---|---|
| Shot detection + make/miss + FG% | **REAL** — CV pipeline |
| `origin.court` (court coordinates) | **NULL** — not computed yet |
| Zone assignment, heatmap | **NULL / EMPTY** — requires court coords |
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
