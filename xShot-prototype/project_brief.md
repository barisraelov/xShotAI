# xShot AI — Project brief (source of truth)

## Product
- **What:** Smart basketball feedback from training video — upload → analyze → session stats + tips (full vision later).
- **Demo v1 core:** **Make/miss** per shot + **session summary** (counts, accuracy).
- **Demo v1 also:** **Coarse shot location** — not heatmap, not pixel-perfect: **shot points + zones** via **polygons on normalized court**.

## Stack (agreed)
- **Frontend:** React (Vite-style SPA), component-based state — not raw HTML prototype for ongoing work.
- **Backend:** Python **FastAPI** + **uvicorn**. CV lives in Python services layer.

## Demo runtime
- **Localhost** on presenter laptop is enough; 24/7 cloud not required for v1.
- Optional: same Wi‑Fi IP or tunnel if remote viewing needed.

## Court / mapping
- **Coordinates:** `origin.court` in **`normalized_0_1`**: `x` left sideline→right; **`y=0` near hoop/backboard**, `y=1` far from hoop.
- If homography output is inverted: **flip `y` once in mapping layer only** — polygons unchanged.
- **Calibration v1:** semi-automatic (user clicks known court points on first frame) → homography → map shot origin.
- **Zones:** coarse **polygons** on normalized court; classification order: extended → three-point → mid-range → unknown.

## Shot data model (non-negotiable layering)
Per shot store **all three:**
1. **`origin.pixel`** — raw (u, v, frame_index).
2. **`origin.court`** — mapped normalized coords.
3. **`zone`** — display/classification layer derived from polygons (include `polygon_id` / layer labels).

Do **not** persist only zone; coordinates are the long-term source of truth.

## Zone taxonomy (UI-aligned)
- **Mid-range:** center, baseline, left wing, right wing.
- **Three-point:** left corner, right corner, left wing, right wing, top of the key.
- **Extended range:** deep threes (coarse).

## API shape (planning-level)
- Job flow: upload → analyze → poll job → **stable `AnalyzeResult` JSON** (summary + `shot_points` + zones aggregate + mapping metadata).
- Stub pipeline acceptable first; replace CV internals without breaking contract.

## Out of scope for Demo v1
- Dense heatmap, full court line detection, competition/social, multi-user permissions, production hosting.

## Prototype note
- Existing **`xShot-prototype/`** (HTML) = **reference UI + flow + zones layout** only; product build moves to **React**.
