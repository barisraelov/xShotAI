"""
Single-pass pipeline runtime constants.

IDLE cadence 4,4,2 and related tunables from checkpoint adaptive-singlepass-v2.1-yolo-reuse.
"""

from enum import Enum


class PipelineMode(str, Enum):
    IDLE = "idle"
    SHOT = "shot"
    NEAR_HOOP = "near_hoop"
    COOLDOWN = "cooldown"


# IDLE main-loop YOLO cadence: +4, +4, +2, ... Resets on IDLE entry and cooldown→idle.
IDLE_CADENCE: tuple[int, ...] = (4, 4, 2)
IDLE_BALL_ACCEPT = 0.45

# After UP
SHOT_STRIDE = 2
SHOT_BALL_ACCEPT = 0.30

# Near hoop / trajectory dense phase
NEAR_HOOP_STRIDE = 1
TRAJECTORY_INFERENCE_CONF = 0.025  # entry_make_miss.INFERENCE_CONF_FLOOR

# After MAKE/MISS scored — fixed pause, then idle
POST_SHOT_COOLDOWN_FRAMES = 35

# Contact sampling during main loop (not during cooldown)
CONTACT_CHECK_EVERY = 24
CONTACT_UP_OFFSET = 24
RELEASE_FRAME_ALIGN = 6

# Hoop inference floor (matches production weak-hoop pass)
HOOP_INFERENCE_CONF = 0.20
