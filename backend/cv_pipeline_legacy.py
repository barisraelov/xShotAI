"""Legacy double-pass pipeline — rollback via XSHOT_LEGACY_PIPELINE=1."""

from __future__ import annotations

from typing import Optional

from court_mapper import CourtMapper


def run(
    video_path: str,
    court_mapper: Optional[CourtMapper] = None,
) -> tuple[list[dict], dict]:
    from cv_pipeline import _run_pipeline_inner_legacy
    return _run_pipeline_inner_legacy(video_path, court_mapper)
