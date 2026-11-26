"""Safety nets for background work: the memo's single-flight always closes,
and the row warmer outlives an unexpected error."""
import threading
import unittest
from unittest import mock

import server  # noqa: F401  (loads first)
import memo
import warm


class FlightAlwaysClosesTest(unittest.TestCase):
    def setUp(self):
        server._cache.pop("t:flight", None)
        server._flights.pop("t:flight", None)

    def test_raising_usable_check_releases_the_key(self):
        def bad_usable(_value):
            raise RuntimeError("usable broke")

        with mock.patch.object(server.diskcache, "store"):
            with self.assertRaises(RuntimeError):
                memo.cached("t:flight", lambda: {"x": 1}, 60, usable=bad_usable)
        self.assertNotIn("t:flight", server._flights)
        # The next caller produces again instead of waiting forever.
        done = []
        t = threading.Thread(target=lambda: done.append(
            memo.cached("t:flight", lambda: {"x": 2}, 60)))
        with mock.patch.object(server.diskcache, "store"):
            t.start()
            t.join(5)
        self.assertEqual(done, [{"x": 2}])

    def test_raising_fallback_releases_the_key(self):
        def producer():
            raise server.UpstreamError("down")

        with mock.patch.object(server, "is_transient", return_value=True), \
                mock.patch.object(server, "_stamp_copy",
                                  side_effect=OSError("disk unreadable")):
            with self.assertRaises(OSError):
                memo.cached("t:flight", producer, 60)
        self.assertNotIn("t:flight", server._flights)


class WarmerRestartsTest(unittest.TestCase):
    def test_error_is_noted_and_loop_continues(self):
        calls = []

        def fake_pass():
            calls.append(1)
            if len(calls) == 1:
                raise ValueError("odd upstream json")
            raise KeyboardInterrupt  # stop the test loop on the second pass

        with mock.patch.object(warm, "_warm_rows_forever", side_effect=fake_pass), \
                mock.patch.object(warm.faults, "note") as note, \
                mock.patch.object(warm.time, "sleep"):
            with self.assertRaises(KeyboardInterrupt):
                warm.warm_rows_loop()
        self.assertEqual(len(calls), 2)
        note.assert_called_once()


if __name__ == "__main__":
    unittest.main()
