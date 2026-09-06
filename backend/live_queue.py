"""Bounded RAM frame queue: drop oldest waiting frame when full (LIVE-10 / LIVE-11)."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Any, Optional

from live_constants import QUEUE_MAXSIZE


@dataclass
class QueuedFrame:
    frame_id: int
    header: dict[str, Any]
    jpeg: bytes
    received_at: float
    generation: int = 0
    extra: dict[str, Any] = field(default_factory=dict)


class DropOldestQueue:
    """FIFO of waiting frames. The in-process frame is never stored here."""

    def __init__(self, maxsize: int = QUEUE_MAXSIZE) -> None:
        self.maxsize = maxsize
        self._items: deque[QueuedFrame] = deque()
        self.dropped_count = 0

    def __len__(self) -> int:
        return len(self._items)

    def put(self, item: QueuedFrame) -> Optional[QueuedFrame]:
        """Append `item`. If at capacity, evict the oldest waiting frame first."""
        dropped: Optional[QueuedFrame] = None
        if len(self._items) >= self.maxsize:
            dropped = self._items.popleft()
            self.dropped_count += 1
        self._items.append(item)
        return dropped

    def pop(self) -> Optional[QueuedFrame]:
        if not self._items:
            return None
        return self._items.popleft()

    def clear(self) -> list[QueuedFrame]:
        dumped = list(self._items)
        self._items.clear()
        return dumped

    def peek_ids(self) -> list[int]:
        return [item.frame_id for item in self._items]
