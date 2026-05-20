"""
xShot AI — FastAPI backend (Demo v1)

Endpoints:
  POST /analyze   (multipart: video file + optional fail flag)  → { job_id }
  GET  /jobs/{id}                                               → status | AnalyzeResult

Real CV path: video is saved to a temp file, processed by cv_pipeline.process_video()
in a thread pool (asyncio.to_thread), and the result is stored in the in-memory job
store once complete.

Test / dev helpers:
  fail=1 form field  → stub failure path (exercises the full failed AnalyzeResult UX)
  ?demo=session / ?demo=heatmap query params  → handled entirely in the frontend
    (DEMO_STUB in App.jsx); these never reach the backend.
"""

import asyncio
import json
import logging
import os
import tempfile
import time
import uuid
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import BackgroundTasks, FastAPI, File, Form, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

import cv_pipeline
from court_mapper import CourtMapper
from feedback import generate_feedback

logger = logging.getLogger(__name__)

# ── In-memory job store ────────────────────────────────────────────────────────
# { job_id: { "status": str, "result": dict | None, "created_at": float } }
_jobs: dict[str, dict] = {}


# ── Result builder ─────────────────────────────────────────────────────────────

def _build_real_result(
    job_id: str,
    shot_points: list[dict],
    homography_list: Optional[list] = None,
) -> dict:
    """
    Derive the full AnalyzeResult from real shot_points produced by cv_pipeline.
    When calibration was provided, origin.court, zone, and zone_aggregates are
    populated; otherwise they remain null / empty (graceful degradation).
    """
    total    = len(shot_points)
    made     = sum(1 for s in shot_points if s["result"] == "made")
    missed   = total - made
    accuracy = round(made / total * 100, 2) if total > 0 else 0.0

    # Aggregate zone stats from individual shot zone data (if present).
    zone_map: dict = {}
    for s in shot_points:
        z = s.get("zone")
        if not z:
            continue
        pid = z["polygon_id"]
        if pid not in zone_map:
            zone_map[pid] = {
                "polygon_id":  pid,
                "range_class": z["range_class"],
                "label":       z["label"],
                "attempts":    0,
                "made":        0,
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
            "total_shots":  total,
            "made":         made,
            "missed":       missed,
            "accuracy_pct": accuracy,
        },
        "shot_points":     shot_points,
        "zone_aggregates": zone_aggregates,
        "mapping": {
            "court_norm_version": "1.0",
            "polygon_version":    "1.0",
            "y_flip_applied":     False,
            "homography_matrix":  homography_list,
        },
    }
    out["feedback"] = generate_feedback(out)
    return out


# ── Background tasks ───────────────────────────────────────────────────────────

async def _simulate_failure(job_id: str) -> None:
    """Stub failure path — triggered by fail=1 form field. Exercises the full
    completed vs failed AnalyzeResult contract from the UI side."""
    await asyncio.sleep(3)
    if job_id in _jobs:
        _jobs[job_id]["status"] = "failed"
        _jobs[job_id]["result"] = {
            "job_id": job_id,
            "status": "failed",
            "error":  "Stub failure — triggered by fail=1 flag (test mode only).",
        }


async def _process_video_task(
    job_id: str,
    video_bytes: bytes,
    court_mapper: Optional[CourtMapper] = None,
) -> None:
    """
    Write video bytes to a temp file, run the CV pipeline in a thread pool
    (to keep the event loop free), then store the result in the job store.
    """
    tmp_path: Optional[str] = None
    try:
        # Persist the upload; suffix helps OpenCV pick the right decoder.
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            f.write(video_bytes)
            tmp_path = f.name

        logger.info("Job %s: starting CV pipeline on %s (%d bytes)",
                    job_id, tmp_path, len(video_bytes))

        shot_points = await asyncio.to_thread(
            cv_pipeline.process_video, tmp_path, court_mapper
        )

        homography_list = court_mapper.homography_matrix if court_mapper else None
        _jobs[job_id]["status"] = "completed"
        _jobs[job_id]["result"] = _build_real_result(job_id, shot_points, homography_list)
        logger.info("Job %s: completed — %d shots detected", job_id, len(shot_points))

    except Exception as exc:
        logger.exception("Job %s: CV pipeline error", job_id)
        _jobs[job_id]["status"] = "failed"
        _jobs[job_id]["result"] = {
            "job_id": job_id,
            "status": "failed",
            "error":  str(exc),
        }
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


# ── App ────────────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


app = FastAPI(title="xShot AI — Demo v1", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",    # React dev server (npm run dev)
        "http://127.0.0.1:5173",
        "http://localhost:8080",    # Prototype served via xShot-prototype/serve.py
        "http://127.0.0.1:8080",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/analyze")
async def analyze(
    background_tasks: BackgroundTasks,
    video: UploadFile = File(...),
    calibration_points: Optional[str] = Form(None),  # JSON: [[u,v], ...] × 6
    fail: Optional[str] = Form(None),                # "1" or "true" → stub failure
):
    job_id = f"job_{uuid.uuid4().hex[:10]}"
    _jobs[job_id] = {"status": "processing", "result": None, "created_at": time.time()}

    if fail and fail.lower() in ("1", "true", "yes"):
        background_tasks.add_task(_simulate_failure, job_id)
    else:
        video_bytes = await video.read()

        court_mapper: Optional[CourtMapper] = None
        if calibration_points:
            logger.info("Job %s: received calibration_points = %s", job_id, calibration_points)
            try:
                pts = json.loads(calibration_points)
                court_mapper = CourtMapper(pts)
                logger.info("Job %s: CourtMapper ready", job_id)
            except Exception as exc:
                logger.warning("Job %s: could not build CourtMapper — %s", job_id, exc)
        else:
            logger.info("Job %s: no calibration_points received — court mapping disabled", job_id)

        background_tasks.add_task(_process_video_task, job_id, video_bytes, court_mapper)

    return {"job_id": job_id}


@app.get("/jobs/{job_id}")
async def get_job(job_id: str):
    job = _jobs.get(job_id)
    if job is None:
        return JSONResponse(status_code=404, content={"detail": "Job not found"})
    if job["status"] == "processing":
        return {"job_id": job_id, "status": "processing"}
    return job["result"]
