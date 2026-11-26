"""At most MAX_BROWSERS Moli runs at once; a run past its wait fails as an outage."""

import sys
import threading
import time
import unittest
from unittest import mock

import moli_client


class FakePopen:
    live = 0
    peak = 0
    lock = threading.Lock()

    def __init__(self, *a, **k):
        self.pid = 0
        self.returncode = 0

    def communicate(self, timeout=None):
        with FakePopen.lock:
            FakePopen.live += 1
            FakePopen.peak = max(FakePopen.peak, FakePopen.live)
        time.sleep(0.05)
        with FakePopen.lock:
            FakePopen.live -= 1
        return '{"status": 200, "body": "{}"}', ""


class MoliCapTests(unittest.TestCase):
    def setUp(self):
        FakePopen.live = FakePopen.peak = 0

    def test_never_more_than_the_cap_at_once(self):
        slots = threading.BoundedSemaphore(2)
        with mock.patch.object(moli_client, "MOLI", sys.executable), \
             mock.patch.object(moli_client, "_browser_slots", slots), \
             mock.patch.object(moli_client.subprocess, "Popen", FakePopen):
            threads = [threading.Thread(target=moli_client._moli_run, args=("p", "s"))
                       for _ in range(8)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
        self.assertEqual(FakePopen.peak, 2)
        # Every slot was handed back.
        for _ in range(2):
            self.assertTrue(slots.acquire(timeout=0))

    def test_a_run_that_cannot_get_a_slot_is_an_outage(self):
        slots = threading.BoundedSemaphore(1)
        slots.acquire()
        with mock.patch.object(moli_client, "MOLI", sys.executable), \
             mock.patch.object(moli_client, "_browser_slots", slots), \
             mock.patch.object(moli_client.subprocess, "Popen", FakePopen):
            with self.assertRaises(moli_client.UpstreamError) as cm:
                moli_client._moli_run("p", "s", wall_timeout=0.05)
        self.assertIn("busy", str(cm.exception))
        self.assertEqual(FakePopen.peak, 0)

    def test_slot_is_returned_when_the_run_fails(self):
        slots = threading.BoundedSemaphore(1)

        class Broken(FakePopen):
            def communicate(self, timeout=None):
                self.returncode = 1
                return "", "boom"

        with mock.patch.object(moli_client, "MOLI", sys.executable), \
             mock.patch.object(moli_client, "_browser_slots", slots), \
             mock.patch.object(moli_client.subprocess, "Popen", Broken):
            with self.assertRaises(moli_client.UpstreamError):
                moli_client._moli_run("p", "s")
        self.assertTrue(slots.acquire(timeout=0))


if __name__ == "__main__":
    unittest.main()


class BusyIsNotBrokenTests(unittest.TestCase):
    def test_a_full_queue_does_not_mark_the_browser_broken(self):
        slots = threading.BoundedSemaphore(1)
        slots.acquire()
        before = dict(moli_client.health)
        with mock.patch.object(moli_client, "MOLI", sys.executable), \
             mock.patch.object(moli_client, "_browser_slots", slots), \
             mock.patch.object(moli_client.sourcestats, "record") as record:
            with self.assertRaises(moli_client.MoliBusy):
                moli_client.moli_run("p", "s", wall_timeout=0.05)
        self.assertEqual(moli_client.health, before)
        record.assert_not_called()


class PortRangeTests(unittest.TestCase):
    def test_out_of_range_port_is_refused_without_a_traceback(self):
        import http_handler
        with mock.patch.object(sys, "argv", ["server.py", "70000"]), \
             mock.patch("sys.stderr"):
            self.assertEqual(http_handler.main(), 2)
