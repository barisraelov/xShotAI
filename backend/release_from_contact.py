"""Release frame from up_frame + last contact (no per-shot ReleaseEstimator video pass)."""

from __future__ import annotations

from typing import Optional

from contact_sampler import ContactSampler
from runtime_config import CONTACT_UP_OFFSET, RELEASE_FRAME_ALIGN


def floor_to_multiple_of_6(n: int) -> int:
    return (n // RELEASE_FRAME_ALIGN) * RELEASE_FRAME_ALIGN


def compute_release_pixel(
    up_frame: int,
    contact_sampler: ContactSampler,
) -> Optional[dict]:
    last = contact_sampler.last_contact_frame
    if last is None:
        return None
    release_estimate = (up_frame - CONTACT_UP_OFFSET + last) // 2
    release_frame = floor_to_multiple_of_6(release_estimate)
    ball = contact_sampler.ball_at_frame(release_frame)
    if ball is None:
        ball = contact_sampler.ball_at_frame(last)
    if ball is None:
        return {"frame_index": int(release_frame), "u": 0, "v": 0}
    return {
        "u": int(ball[0]),
        "v": int(ball[1]),
        "frame_index": int(release_frame),
    }
