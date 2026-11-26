"""Enriched digest text and offline morning packet."""

from __future__ import annotations

import unittest
from unittest import mock

import notify


class DigestPacketTests(unittest.TestCase):
    def test_pse_session_shape(self):
        # Weekend afternoon Manila → not trading.
        status = notify.pse_session_status(now=1732464000)  # 2024-11-24 Sunday UTC-ish
        self.assertIn(status["state"], ("weekend", "holiday", "closed", "pre-open", "open"))
        self.assertIn("localTime", status)
        self.assertIn("trading", status)
        self.assertIn("secondsToOpen", status)
        self.assertIn("secondsToClose", status)
        if status["state"] in ("weekend", "holiday", "closed", "pre-open"):
            self.assertTrue(
                status["secondsToOpen"] is None or status["secondsToOpen"] >= 0)
            self.assertIsNone(status["secondsToClose"])

    def test_digest_text_includes_pse_and_markets(self):
        digest = {
            "summary": "PSE open | hello",
            "pseSession": {"state": "open", "localTime": "10:00", "date": "2026-11-25"},
            "markets": [{"market": "US stocks", "state": "live"}],
            "freshTurns": [],
            "watchlist": [{"symbol": "BTC-USD", "phrase": "Bullish"}],
            "alarms": {"fired": [], "peso": [{"symbol": "PSE:ALI", "target": 30, "fired": False}]},
        }
        text = notify.digest_text(digest)
        self.assertIn("PSE session: open", text)
        self.assertIn("US stocks=live", text)
        self.assertIn("Peso alarms: PSE:ALI @ 30", text)
        self.assertIn("Watchlist: BTC-USD Bullish", text)

    def test_build_packet_from_warm_state(self):
        server = mock.Mock()
        server.recent_state.return_value = {
            "health": [{"market": "Crypto", "bullish": 1, "bearish": 0, "neutral": 2, "judged": 3}],
            "markets": [{"market": "Crypto", "state": "live"}],
            "rows": [{"chartSymbol": "BTC-USD", "ticker": "BTC", "market": "Crypto",
                      "price": 1, "currency": "USD", "trend": {"label": "bullish"}}],
            "leaning": [],
            "bearish": [],
        }
        server.saved_watchlist.return_value = []
        server.chart_key.return_value = "k"
        server.WARM_SPAN = "3mo"
        server.WARM_INTERVAL = "1d"
        net = mock.Mock(_watch_online=True)
        with mock.patch.object(notify, "load_alarms", return_value=[]), \
             mock.patch("notify.diskcache.load", return_value=None):
            packet = notify.build_packet(server, net)
        self.assertTrue(packet["fromDisk"])
        self.assertTrue(packet["ok"])
        self.assertIn("digest", packet)
        self.assertEqual(packet["recentSample"][0]["ticker"], "BTC")
        self.assertIn("PSE", packet["digest"]["summary"])


if __name__ == "__main__":
    unittest.main()
