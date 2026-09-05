"""Build a completed AnalyzeResult from shot_points (Upload and Live)."""

from __future__ import annotations

from typing import Optional

from feedback import generate_feedback


def build_real_result(
    job_id: str,
    shot_points: list[dict],
    homography_list: Optional[list] = None,
) -> dict:
    """
    Derive the full AnalyzeResult from real shot_points produced by cv_pipeline.
    When calibration was provided, origin.court, zone, and zone_aggregates are
    populated; otherwise they remain null / empty (graceful degradation).
    """
    total = len(shot_points)
    made = sum(1 for s in shot_points if s["result"] == "made")
    missed = total - made
    accuracy = round(made / total * 100, 2) if total > 0 else 0.0

    zone_map: dict = {}
    for s in shot_points:
        z = s.get("zone")
        if not z:
            continue
        pid = z["polygon_id"]
        if pid not in zone_map:
            zone_map[pid] = {
                "polygon_id": pid,
                "range_class": z["range_class"],
                "label": z["label"],
                "attempts": 0,
                "made": 0,
            }
        zone_map[pid]["attempts"] += 1
        if s["result"] == "made":
            zone_map[pid]["made"] += 1

    zone_aggregates = []
    for z in zone_map.values():
        z["accuracy_pct"] = (
            round(z["made"] / z["attempts"] * 100, 2) if z["attempts"] > 0 else 0.0
        )
        zone_aggregates.append(z)

    out = {
        "job_id": job_id,
        "status": "completed",
        "summary": {
            "total_shots": total,
            "made": made,
            "missed": missed,
            "accuracy_pct": accuracy,
        },
        "shot_points": shot_points,
        "zone_aggregates": zone_aggregates,
        "mapping": {
            "court_norm_version": "1.0",
            "polygon_version": "1.0",
            "y_flip_applied": False,
            "homography_matrix": homography_list,
        },
    }
    out["feedback"] = generate_feedback(out)
    return out
