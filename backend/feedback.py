"""
Rule-based coaching-style feedback derived from AnalyzeResult only.
Uses summary.* and shot_points — no CV / LLM.
"""

from __future__ import annotations

from typing import Any


def _shot_outcomes(shot_points: list[dict]) -> list[str]:
    out: list[str] = []
    for s in shot_points:
        r = s.get("result")
        if r in ("made", "missed"):
            out.append(r)
    return out


def _ending_streak(outcomes: list[str]) -> tuple[str, int] | None:
    if not outcomes:
        return None
    last = outcomes[-1]
    n = 0
    for o in reversed(outcomes):
        if o != last:
            break
        n += 1
    return last, n


def _longest_streak(outcomes: list[str], target: str) -> int:
    best = cur = 0
    for o in outcomes:
        if o == target:
            cur += 1
            best = max(best, cur)
        else:
            cur = 0
    return best


# Minimum shots with arc_height_px before session-level arc insights.
_MIN_ARC_SHOTS_FOR_INSIGHTS = 3
# Minimum arc samples to compare first vs second half (needs ≥1 per half).
_MIN_ARC_SHOTS_FOR_FATIGUE = 4
# Minimum labeled makes/misses each for make-vs-miss arc comparison.
_MIN_ARC_PER_RESULT_GROUP = 2
# Relative spread (max−min)/mean above this → inconsistent arc height.
_ARC_INCONSISTENT_SPREAD_RATIO = 0.35
# First→second half arc change ≥ this fraction of first-half mean → fatigue trend.
_ARC_HALF_DELTA_RATIO = 0.10
# Make vs miss group means differ by this fraction of the lower mean.
_MADE_MISS_ARC_DELTA_RATIO = 0.08
# Minimum shots with valid apex timing for timing insights.
_MIN_APEX_TIMING_SHOTS = 3
# Normalized apex timing spread thresholds (0–1 scale).
_APEX_TIMING_INCONSISTENT_SPREAD = 0.25
_APEX_TIMING_CONSISTENT_SPREAD = 0.12


def _parse_arc_height_px(shot: dict) -> float | None:
    traj = shot.get("trajectory")
    if not isinstance(traj, dict):
        return None
    raw = traj.get("arc_height_px")
    if raw is None:
        return None
    try:
        h = float(raw)
    except (TypeError, ValueError):
        return None
    return h if h > 0 else None


def _parse_apex_timing_normalized(shot: dict) -> float | None:
    traj = shot.get("trajectory")
    if not isinstance(traj, dict):
        return None
    apex = traj.get("apex_pixel")
    if not isinstance(apex, dict):
        return None
    try:
        apex_frame = int(apex["frame_index"])
        up_frame = int(traj["up_frame"])
        down_frame = int(traj["down_frame"])
    except (KeyError, TypeError, ValueError):
        return None
    span = down_frame - up_frame
    if span <= 0:
        return None
    t = (apex_frame - up_frame) / span
    if t < 0.0 or t > 1.0:
        return None
    return t


def _arc_heights_by_result(
    shot_points: list[dict],
) -> tuple[list[float], list[float], list[float]]:
    """Return (made_heights, missed_heights, all_heights) from trajectory.arc_height_px."""
    made_h: list[float] = []
    missed_h: list[float] = []
    all_h: list[float] = []
    for s in shot_points:
        h = _parse_arc_height_px(s)
        if h is None:
            continue
        all_h.append(h)
        if s.get("result") == "made":
            made_h.append(h)
        elif s.get("result") == "missed":
            missed_h.append(h)
    return made_h, missed_h, all_h


def _arc_heights_in_order(shot_points: list[dict]) -> list[float]:
    return [h for s in shot_points if (h := _parse_arc_height_px(s)) is not None]


def _apex_timings_in_order(shot_points: list[dict]) -> list[float]:
    return [t for s in shot_points if (t := _parse_apex_timing_normalized(s)) is not None]


def _meaningful_delta(higher: float, lower: float) -> bool:
    if lower <= 0:
        return higher > 0
    return (higher - lower) / lower >= _MADE_MISS_ARC_DELTA_RATIO


def _trajectory_feedback(
    shot_points: list[dict],
) -> tuple[list[str], list[str], dict[str, Any]]:
    """
    Trajectory-only insights, recommendations, and metrics.
    No output when required fields are missing or below thresholds.
    """
    insights: list[str] = []
    recommendations: list[str] = []
    extra: dict[str, Any] = {}

    made_h, missed_h, all_h = _arc_heights_by_result(shot_points)
    ordered_arc = _arc_heights_in_order(shot_points)
    apex_timings = _apex_timings_in_order(shot_points)

    if len(all_h) >= _MIN_ARC_SHOTS_FOR_INSIGHTS:
        extra["trajectory_shots_with_arc_height"] = len(all_h)
        avg_all = sum(all_h) / len(all_h)
        extra["trajectory_mean_arc_height_px"] = round(avg_all, 1)
        spread_px = max(all_h) - min(all_h)
        extra["trajectory_arc_height_spread_px"] = round(spread_px, 1)
        if avg_all > 0 and spread_px / avg_all >= _ARC_INCONSISTENT_SPREAD_RATIO:
            insights.append(
                "Arc height varied noticeably between attempts — aim for a more consistent release arc."
            )
            recommendations.append(
                "Repeat form shots aiming for the same target arc on each release."
            )

    # 1. Arc fatigue trend (ordered shots, first vs second half)
    if len(ordered_arc) >= _MIN_ARC_SHOTS_FOR_FATIGUE:
        k = len(ordered_arc) // 2
        first_half = ordered_arc[:k]
        second_half = ordered_arc[k:]
        if first_half and second_half:
            m_first = sum(first_half) / len(first_half)
            m_second = sum(second_half) / len(second_half)
            delta = m_second - m_first
            extra["first_half_mean_arc_height_px"] = round(m_first, 1)
            extra["second_half_mean_arc_height_px"] = round(m_second, 1)
            extra["arc_height_delta_px"] = round(delta, 1)
            threshold = m_first * _ARC_HALF_DELTA_RATIO
            if delta <= -threshold:
                insights.append(
                    "Arc height declined in the second half of the session — lift may have dropped as the session went on."
                )
                recommendations.append(
                    "Focus on maintaining lift through the full session; add a short reset when you feel arc flattening."
                )
            elif delta >= threshold:
                insights.append(
                    "Arc height improved in the second half of the session — you found more lift as you went on."
                )

    # 2. Made vs missed arc comparison
    if (
        len(made_h) >= _MIN_ARC_PER_RESULT_GROUP
        and len(missed_h) >= _MIN_ARC_PER_RESULT_GROUP
    ):
        made_avg = sum(made_h) / len(made_h)
        missed_avg = sum(missed_h) / len(missed_h)
        extra["trajectory_mean_arc_height_made_px"] = round(made_avg, 1)
        extra["trajectory_mean_arc_height_missed_px"] = round(missed_avg, 1)
        if _meaningful_delta(made_avg, missed_avg):
            insights.append(
                f"Made shots tended to have a higher arc than misses "
                f"({made_avg:.0f}px vs {missed_avg:.0f}px above the rim reference)."
            )
        elif _meaningful_delta(missed_avg, made_avg):
            insights.append(
                f"Missed shots averaged a higher arc than makes in this session "
                f"({missed_avg:.0f}px vs {made_avg:.0f}px) — a higher arc did not clearly correlate with makes here."
            )

    # 3. Apex timing consistency
    if len(apex_timings) >= _MIN_APEX_TIMING_SHOTS:
        t_mean = sum(apex_timings) / len(apex_timings)
        t_spread = max(apex_timings) - min(apex_timings)
        extra["apex_timing_mean"] = round(t_mean, 3)
        extra["apex_timing_spread"] = round(t_spread, 3)
        extra["trajectory_shots_with_apex_timing"] = len(apex_timings)
        if t_spread >= _APEX_TIMING_INCONSISTENT_SPREAD:
            insights.append(
                "Shot timing was inconsistent — the apex arrived at different points in the up-to-down window across attempts."
            )
            recommendations.append(
                "Slow the motion slightly and keep a repeatable release rhythm from shot to shot."
            )
        elif t_spread <= _APEX_TIMING_CONSISTENT_SPREAD:
            insights.append(
                "Trajectory timing was consistent — the apex landed at a similar point in each shot window."
            )

    return insights, recommendations, extra


def _split_accuracy(outcomes: list[str], take_first: bool) -> float | None:
    n = len(outcomes)
    if n < 6:
        return None
    k = n // 2
    chunk = outcomes[:k] if take_first else outcomes[k:]
    if not chunk:
        return None
    m = sum(1 for o in chunk if o == "made")
    return round(m / len(chunk) * 100, 2)


def generate_feedback(result: dict) -> dict:
    """
    Build a feedback block from a completed AnalyzeResult-shaped dict.
    Reads only: result['summary'] (total_shots, made, missed, accuracy_pct)
    and result['shot_points'].
    """
    summary = result.get("summary") or {}
    total = int(summary.get("total_shots", 0) or 0)
    made = int(summary.get("made", 0) or 0)
    missed = int(summary.get("missed", 0) or 0)
    accuracy = float(summary.get("accuracy_pct", 0.0) or 0.0)
    shot_points: list[dict] = list(result.get("shot_points") or [])

    outcomes = _shot_outcomes(shot_points)
    ending = _ending_streak(outcomes)
    longest_make = _longest_streak(outcomes, "made")
    longest_miss = _longest_streak(outcomes, "missed")
    early_acc = _split_accuracy(outcomes, take_first=True)
    late_acc = _split_accuracy(outcomes, take_first=False)

    metrics: dict[str, Any] = {
        "sample_shots": total,
        "reported_made": made,
        "reported_missed": missed,
        "reported_accuracy_pct": round(accuracy, 2),
        "outcomes_from_shot_points": len(outcomes),
        "longest_make_streak": longest_make,
        "longest_miss_streak": longest_miss,
    }
    if ending:
        metrics["ending_streak_type"] = ending[0]
        metrics["ending_streak_length"] = ending[1]
    if early_acc is not None and late_acc is not None:
        metrics["first_half_accuracy_pct"] = early_acc
        metrics["second_half_accuracy_pct"] = late_acc
        metrics["second_half_delta_pct"] = round(late_acc - early_acc, 2)

    insights: list[str] = []
    recommendations: list[str] = []

    if total == 0:
        fb_summary = {
            "headline": "No shots detected",
            "body": "There were no classified shot attempts in this video.",
        }
        insights.append("Without detected shots, session-level accuracy cannot be evaluated.")
        recommendations.append("Upload a clearer clip with visible ball and hoop, or a longer shooting segment.")
        return {
            "summary": fb_summary,
            "insights": insights,
            "recommendations": recommendations,
            "metrics": metrics,
        }

    if len(outcomes) != total:
        insights.append(
            "Some shot_points entries were missing a made/missed label; metrics use labeled shots only."
        )

    if total < 5:
        insights.append("Sample size is small — treat percentages as directional, not definitive.")
        recommendations.append("Record a longer session (5+ attempts) for steadier feedback.")

    if accuracy >= 70:
        insights.append(f"Strong session accuracy at {accuracy:.0f}% ({made}/{total} makes).")
        recommendations.append("Maintain rhythm; add variability (speed, range) to stress-test consistency.")
    elif accuracy >= 45:
        insights.append(f"Mid-range accuracy at {accuracy:.0f}% — room to push into the next tier.")
        recommendations.append("Focus on repeatable footwork and release timing between attempts.")
    else:
        insights.append(f"Accuracy at {accuracy:.0f}% suggests fundamentals or shot selection need attention.")
        recommendations.append("Prioritize form reps and high-percentage looks before volume.")

    if missed > made:
        insights.append(f"More misses than makes ({missed} vs {made}).")
        recommendations.append("Shorten the session slightly and reset after 2–3 consecutive misses.")

    if ending:
        kind, ln = ending
        if kind == "made" and ln >= 3:
            insights.append(f"Finished hot: {ln} makes in a row to close.")
        elif kind == "missed" and ln >= 3:
            insights.append(f"Cold finish: {ln} consecutive misses — fatigue or rush may be factors.")
            recommendations.append("Insert a 30–60s breather before the last few attempts next time.")

    if longest_make >= 4:
        insights.append(f"Longest make streak was {longest_make} — good momentum windows.")
    if longest_miss >= 4:
        insights.append(f"Longest miss streak was {longest_miss} — consider a reset cue after long cold spells.")

    if early_acc is not None and late_acc is not None:
        delta = late_acc - early_acc
        if delta >= 10:
            insights.append("Accuracy improved in the second half of the ordered shots — positive adjustment.")
        elif delta <= -10:
            insights.append("Accuracy dropped in the second half — watch for fatigue or pacing.")
            recommendations.append("Track energy: start slightly slower or add hydration between clusters.")

    traj_insights, traj_recs, traj_metrics = _trajectory_feedback(shot_points)
    insights.extend(traj_insights)
    recommendations.extend(traj_recs)
    metrics.update(traj_metrics)

    # De-duplicate while preserving order
    seen: set[str] = set()
    insights = [x for x in insights if not (x in seen or seen.add(x))]
    seen.clear()
    recommendations = [x for x in recommendations if not (x in seen or seen.add(x))]

    fb_summary = {
        "headline": f"{made}/{total} makes ({accuracy:.0f}%)",
        "body": (
            f"Session summary: {made} made, {missed} missed over {total} detected attempts."
        ),
    }

    return {
        "summary": fb_summary,
        "insights": insights,
        "recommendations": recommendations,
        "metrics": metrics,
    }
