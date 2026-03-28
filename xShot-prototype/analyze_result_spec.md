# AnalyzeResult JSON Contract — Demo v1 Spec

> **Status: frozen for Demo v1.**
> Field names, types, and required/optional designations below are locked.
> CV internals and stub implementations may change freely without altering this contract.

---

## API flow

```
POST /analyze          (multipart: video file + calibration_points JSON)
→ { "job_id": "..." }

GET /jobs/{job_id}
→ { "status": "processing" }   (poll until completed or failed)
→ AnalyzeResult                (when status = "completed" or "failed")
```

---

## Top-level shape

| Field            | Type              | `completed` | `failed` | Notes |
|------------------|-------------------|-------------|----------|-------|
| `job_id`         | string            | required    | required | Echoed from the upload response. |
| `status`         | `"completed"` \| `"failed"` | required | required | |
| `error`          | string            | omitted     | required | Never present on `completed`. |
| `summary`        | Summary           | required    | omitted  | Not present when `status = "failed"`. |
| `shot_points`    | ShotPoint[]       | required    | omitted  | May be empty; not present when `status = "failed"`. |
| `zone_aggregates`| ZoneAggregate[]   | required    | omitted  | Derived from `shot_points`; not present when `status = "failed"`. |
| `mapping`        | Mapping           | required    | omitted  | Not present when `status = "failed"`. |

---

## Summary

All fields required.

| Field          | Type    | Notes |
|----------------|---------|-------|
| `total_shots`  | integer | Count of all detected shot attempts. |
| `made`         | integer | |
| `missed`       | integer | |
| `accuracy_pct` | number  | 0–100, two decimal places. 0.00 when `total_shots = 0`. |

---

## ShotPoint

| Field           | Type       | Required | Notes |
|-----------------|------------|----------|-------|
| `shot_id`       | string     | yes      | Unique within the job (e.g. `"s001"`). |
| `result`        | `"made"` \| `"missed"` | yes | |
| `origin.pixel`  | PixelCoord | yes      | Always present; raw image coords are the primary truth. |
| `origin.court`  | CourtCoord \| null | yes | `null` if homography could not be applied for this shot. |
| `zone`          | ZoneInfo \| null   | yes | `null` only when `origin.court` is `null`. When `origin.court` is present but does not match any polygon, `zone.polygon_id = "unknown"` and `zone.range_class = "unknown"`. |

### PixelCoord

| Field         | Type    | Required | Notes |
|---------------|---------|----------|-------|
| `u`           | number  | yes      | Horizontal pixel in source frame. |
| `v`           | number  | yes      | Vertical pixel in source frame. |
| `frame_index` | integer | no       | 0-based frame number within the video. |

### CourtCoord

| Field | Type   | Required | Notes |
|-------|--------|----------|-------|
| `x`   | number | yes      | Normalized 0–1: 0 = left sideline, 1 = right sideline. |
| `y`   | number | yes      | Normalized 0–1: **y = 0 near hoop/backboard**, y = 1 far end. |

> If raw homography output has y inverted, flip it once in the mapping layer.
> `CourtCoord` values are always in this canonical convention; polygons are defined in this same space.

### ZoneInfo

| Field         | Type   | Required | Notes |
|---------------|--------|----------|-------|
| `polygon_id`  | string | yes      | Canonical zone ID (see taxonomy below). |
| `range_class` | enum   | yes      | `"mid_range"` \| `"three_point"` \| `"extended"` \| `"unknown"` |
| `label`       | string | yes      | Human-readable display label (e.g. `"Left corner"`). |

Classification priority (first match wins): **extended → three-point → mid-range → unknown**.

---

## ZoneAggregate

Derived by the backend from `shot_points`. Zones with zero attempts may be omitted (stubs may include all).

| Field          | Type    | Required | Notes |
|----------------|---------|----------|-------|
| `polygon_id`   | string  | yes      | Matches a `ZoneInfo.polygon_id`. |
| `range_class`  | enum    | yes      | Same values as `ZoneInfo.range_class`. |
| `label`        | string  | yes      | Same display label as the matching `ZoneInfo`. |
| `attempts`     | integer | yes      | |
| `made`         | integer | yes      | |
| `accuracy_pct` | number  | yes      | 0.00 when `attempts = 0`. |

---

## Mapping

Supports versioning and provides an audit trail for calibration and y-flip decisions.

| Field                 | Type                   | Required | Notes |
|-----------------------|------------------------|----------|-------|
| `court_norm_version`  | string                 | yes      | Identifies the normalized court convention (e.g. `"1.0"`). |
| `polygon_version`     | string                 | yes      | Identifies the polygon definition set (e.g. `"1.0"`). |
| `y_flip_applied`      | boolean                | yes      | `true` if raw homography y was inverted before storing `origin.court`. |
| `calibration_points`  | CalibrationPoint[]     | no       | Echo of user-provided clicks (debugging / replay). Omitted when not available. |
| `homography_matrix`   | number[][] \| null (3×3) | yes    | Raw homography matrix (debugging / replay). `null` when calibration was not performed. |

### CalibrationPoint

| Field       | Type       | Notes |
|-------------|------------|-------|
| `pixel`     | PixelCoord | u, v only (no `frame_index` required here). |
| `court_ref` | CourtCoord | Canonical known court point the user identified. |

---

## Zone taxonomy

These are the 11 canonical `polygon_id` values and their display labels, matching the prototype Heatmap screen.
4 mid-range + 5 three-point + 1 extended + 1 unknown fallback = 11 total.

### Mid-range

| polygon_id            | label          |
|-----------------------|----------------|
| `mid_center`          | Center         |
| `mid_baseline`        | Baseline       |
| `mid_left_wing`       | Left wing      |
| `mid_right_wing`      | Right wing     |

### Three-point

| polygon_id            | label          |
|-----------------------|----------------|
| `three_left_corner`   | Left corner    |
| `three_right_corner`  | Right corner   |
| `three_left_wing`     | Left wing      |
| `three_right_wing`    | Right wing     |
| `three_top_key`       | Top of the key |

### Extended range

| polygon_id       | label          |
|------------------|----------------|
| `extended`       | Extended range |

### Fallback

| polygon_id | label   |
|------------|---------|
| `unknown`  | Unknown |

---

## Stub contract guarantees

- When `status = "completed"`: `summary`, `shot_points`, `zone_aggregates`, and `mapping` are all present; `error` is omitted.
- When `status = "failed"`: `error` is present; `summary`, `shot_points`, `zone_aggregates`, and `mapping` are all omitted (not null — the keys do not appear).
- `zone = null` only when `origin.court = null`. A shot with a valid `origin.court` that falls outside all polygons must carry `zone` with `polygon_id = "unknown"` and `range_class = "unknown"`.
- A stub may return hardcoded `shot_points` with `origin.court = null` and `zone = null` to represent shots where calibration has not yet been applied.
- All `polygon_id` values in a stub response must come from the 11-entry taxonomy table above.
- Calibration failure (bad homography) and analysis failure (CV pipeline error) both surface as `status = "failed"` with a descriptive `error` string; they are not distinguished at the contract level in Demo v1.

---

## Minimal example (stub, two shots)

```json
{
  "job_id": "job_abc123",
  "status": "completed",
  "summary": {
    "total_shots": 2,
    "made": 1,
    "missed": 1,
    "accuracy_pct": 50.00
  },
  "shot_points": [
    {
      "shot_id": "s001",
      "result": "made",
      "origin": {
        "pixel": { "u": 640, "v": 480, "frame_index": 120 },
        "court": { "x": 0.22, "y": 0.18 }
      },
      "zone": {
        "polygon_id": "three_left_corner",
        "range_class": "three_point",
        "label": "Left corner"
      }
    },
    {
      "shot_id": "s002",
      "result": "missed",
      "origin": {
        "pixel": { "u": 720, "v": 390, "frame_index": 310 },
        "court": null
      },
      "zone": null
    }
  ],
  "zone_aggregates": [
    {
      "polygon_id": "three_left_corner",
      "range_class": "three_point",
      "label": "Left corner",
      "attempts": 1,
      "made": 1,
      "accuracy_pct": 100.00
    }
  ],
  "mapping": {
    "court_norm_version": "1.0",
    "polygon_version": "1.0",
    "y_flip_applied": false,
    "calibration_points": [
      {
        "pixel": { "u": 100, "v": 50 },
        "court_ref": { "x": 0.0, "y": 0.0 }
      }
    ],
    "homography_matrix": null
  }
}
```

> `homography_matrix` is `null` here because this is a stub with no real calibration.
> In a live response it will be a 3×3 array of numbers.
