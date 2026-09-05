"""LIVE-10 / LIVE-11 queue: maxsize 6, drop oldest waiting, keep frame_id."""

from __future__ import annotations

import unittest

from live_queue import DropOldestQueue, QueuedFrame


def _item(fid: int) -> QueuedFrame:
    return QueuedFrame(frame_id=fid, header={"frame_id": fid}, jpeg=b"", received_at=0.0)


class DropOldestQueueTests(unittest.TestCase):
    def test_maxsize_six_and_drop_oldest_keeps_new_ids(self) -> None:
        q = DropOldestQueue(maxsize=6)
        dropped = []
        for i in range(9):
            d = q.put(_item(i))
            if d is not None:
                dropped.append(d.frame_id)
        self.assertEqual(len(q), 6)
        self.assertEqual(q.peek_ids(), [3, 4, 5, 6, 7, 8])
        self.assertEqual(dropped, [0, 1, 2])
        self.assertEqual(dropped[0], 0)
        popped = q.pop()
        self.assertEqual(popped.frame_id, 3)

    def test_pop_empty(self) -> None:
        q = DropOldestQueue(maxsize=6)
        self.assertIsNone(q.pop())


if __name__ == "__main__":
    unittest.main()
