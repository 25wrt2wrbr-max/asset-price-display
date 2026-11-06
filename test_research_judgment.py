import datetime as dt
import http.client
import json
import threading
import unittest
from unittest import mock
from zoneinfo import ZoneInfo
from http.server import ThreadingHTTPServer
from pathlib import Path

import research_judgment as judgment
import server


UTC = dt.timezone.utc


def points(start, count):
    return [{"t": int((start + dt.timedelta(days=i)).timestamp()), "c": 100 + i * .1}
            for i in range(count)]


class ResearchJudgmentTests(unittest.TestCase):
    def setUp(self):
        self.now = dt.datetime(2026, 10, 30, 16, tzinfo=UTC)
        self.points = points(dt.datetime(2026, 6, 1, 12, tzinfo=UTC), 152)

    def test_first_completed_monthly_close_not_latest(self):
        clean = judgment.completed_points(self.points, UTC, self.now)
        (window, day), error = judgment.latest_window(clean, self.now, UTC, months=3)
        self.assertIsNone(error)
        self.assertEqual(day.isoformat(), "2026-10-01")
        first = next(p for p in clean if dt.datetime.fromtimestamp(p["t"], UTC).date() == day)
        self.assertEqual(window[-1], first["c"])
        self.assertNotEqual(window[-1], clean[-1]["c"])

    def test_partial_and_stale_prices(self):
        clean = judgment.completed_points(self.points, UTC, self.now)
        self.assertTrue(all(dt.datetime.fromtimestamp(p["t"], UTC).date() < self.now.date() for p in clean))
        _, error = judgment.latest_window(clean[:-20], self.now, UTC, months=3)
        self.assertIn("seven", error)

    def test_asset_baseline_uses_completed_outcomes_and_stays_distinct(self):
        history = points(dt.datetime(2024, 1, 1, 12, tzinfo=UTC), 1033)
        base = judgment.historical_baseline(history, "A", "UTC", self.now)
        self.assertEqual(base["status"], "signaled")
        self.assertEqual(base["direction"], "bullish")
        self.assertEqual(base["historicalRate"], 1)
        self.assertEqual(base["method"], "asset_history_baseline")
        self.assertGreaterEqual(base["historicalCalls"], 6)
        self.assertEqual(base["unchanged"], 0)

    def test_asset_baseline_refuses_stale_or_short_history(self):
        self.assertEqual(judgment.historical_baseline(self.points[:-20], "A", "UTC", self.now)["status"], "unavailable")
        self.assertEqual(judgment.historical_baseline(self.points, "A", "UTC", self.now)["status"], "unavailable")
        self.assertEqual(judgment.historical_baseline(self.points, "A", None, self.now)["status"], "unavailable")

    def test_asset_baseline_ties_and_unchanged(self):
        history = points(dt.datetime(2024, 1, 1, 12, tzinfo=UTC), 1033)
        for p in history:
            p["c"] = 10
        base = judgment.historical_baseline(history, "A", "UTC", self.now)
        self.assertEqual(base["status"], "unavailable")
        self.assertIn("tied", base["reason"])

    def test_first_month_requires_prior_history(self):
        _, error = judgment.latest_window(self.points[-20:], self.now, UTC, months=3)
        self.assertIn("first monthly", error)

    def test_source_and_identity_guard(self):
        refs = {"universe": {"BTC-USD": "crypto", "AAPL": "us_equity"}, "pse_universe": {"PSE:TEL"}}
        self.assertIsNone(judgment.market_for("BTC-USD", {"source": "Binance", "type": "CRYPTOCURRENCY"}, refs))
        self.assertIsNone(judgment.market_for("BTC-USD", {"source": "Yahoo", "type": "CRYPTOCURRENCY"}, refs))
        self.assertIsNone(judgment.market_for("PSE:NEW", {"source": "TradingView"}, refs))
        self.assertEqual(judgment.market_for("PSE:TEL", {"source": "TradingView"}, refs), "PSE")

    def test_frozen_us_signal_and_missing_bear(self):
        refs = {"universe": {"AAPL": "us_equity"}, "timezones": {"AAPL": "UTC"},
                "extended": {"markets": {"us_equity": {"folds": [{"year": 2026, "bins": {str(i): {"direction": "bullish"} for i in range(7)}}]}}}}
        data = {"source": "Yahoo", "type": "EQUITY", "points": self.points}
        out = judgment.evaluate("AAPL", data, refs, self.now, lambda _: [])
        self.assertEqual(out["bullish"]["historicalRate"], .6077)
        self.assertEqual(out["bullish"]["signalDate"], "2026-10-01")
        self.assertEqual(out["bearish"]["status"], "unavailable")
        self.assertNotIn("historicalRate", out["bearish"])
        data["cached"] = True
        self.assertEqual(judgment.evaluate("AAPL", data, refs, self.now, lambda _: [])["bullish"]["status"], "unavailable")

    def test_currency_conflict_is_not_misreported(self):
        models = {d: {"validation": {"threshold": .5}} for d in ("bullish", "bearish")}
        refs = {"universe": {"EURUSD=X": "currency"}, "timezones": {"EURUSD=X": "UTC"},
                "models": {"markets": {"currency": {"folds": [{"year": 2026, "models": models}]}}}}
        with mock.patch.object(judgment.market_forecasts, "score", return_value=.8):
            out = judgment.evaluate("EURUSD=X", {"source": "Yahoo", "type": "CURRENCY", "points": self.points}, refs, self.now, lambda _: [])
        self.assertEqual(out["bullish"]["status"], "abstained")
        self.assertNotIn("historicalRate", out["bullish"])

    def test_pse_fetch_failure_is_not_a_negative(self):
        refs = {"pse_universe": {"PSE:TEL"}, "universe": {}}
        def failed(_):
            raise RuntimeError("offline")
        out = judgment.evaluate("PSE:TEL", {"source": "TradingView"}, refs, self.now, failed)
        self.assertEqual(out["bullish"]["status"], "unavailable")
        self.assertEqual(out["bearish"]["status"], "unavailable")

    def test_pse_bearish_replays_2026_frozen_rule(self):
        # Reproduce the original study's feature and decision for an actual
        # monthly observation, using its own historical PSE inputs.
        import bearish_forecast_research as prior
        import market_forecast_backtest as backtest
        import relative_forecast_research as relative
        raw = json.loads(Path("research/pse-history.json").read_text())
        sample_set, _ = backtest.observations({"bars": {"PSE:TEL": raw["bars"]["PSE:TEL"]}})
        current = next(s for s in sample_set if s["date"] == dt.date(2026, 7, 1))
        estimate = judgment.local.estimate(sample_set, current, "bearish")
        self.assertIsNotNone(estimate)
        prepared = relative.prepare_bars(raw["bars"], {k: "Asia/Manila" for k in raw["bars"]})
        rank = relative.relative_features(current, relative.peer_returns(prepared, current["date"]))[1]
        expected = prior.flags(current, estimate["score"], rank, None)["local_momentum"]
        tv = {k: [[r[0], 0, 0, 0, r[2]] for r in v] for k, v in raw["bars"].items()}
        now = dt.datetime(2026, 7, 20, 8, tzinfo=UTC)
        answer = judgment.pse_bearish(tv["PSE:TEL"], lambda: tv, "PSE:TEL", now, judgment.references())
        self.assertEqual(answer["status"], "signaled" if expected else "not_signaled")

    def test_pse_bearish_does_not_treat_missing_peers_as_negative(self):
        rows = [[p["t"], 0, 0, 0, p["c"]] for p in points(dt.datetime(2022, 1, 1, 12, tzinfo=UTC), 1760)]
        with mock.patch.object(judgment.local, "estimate", return_value={"score": .8}):
            out = judgment.pse_bearish(rows, lambda: {}, "PSE:TEL", self.now, judgment.references())
        self.assertEqual(out["status"], "unavailable")
        self.assertNotIn("historicalRate", out)

    def test_replay_first_month_window_matches_study(self):
        import pse_bull_fund_bear_research as study
        zone = ZoneInfo("Asia/Manila")
        history = points(dt.datetime(2026, 3, 1, 12, tzinfo=UTC), 245)
        samples, _ = study.pse_observations({"bars": {"PSE:TEL": [[p["t"], None, p["c"], None] for p in history]}})
        sample = next(s for s in samples if s["date"].month == 7)
        now = dt.datetime(2026, 7, 20, tzinfo=UTC)
        clean = judgment.completed_points(history, zone, now)
        snapshot, error = judgment.latest_window(clean, now, zone)
        self.assertIsNone(error)
        self.assertEqual(snapshot[1], sample["date"])
        self.assertEqual(judgment.market_forecasts.features(snapshot[0]), sample["features"])

    def test_server_route_registered(self):
        self.assertTrue(callable(server.Handler.api_research_judgment))

    def test_sparse_window_tries_longer_compatible_history(self):
        sparse = {d: judgment.unavailable(judgment.TOO_FEW_WINDOW_BARS)
                  for d in ("bullish", "bearish")}
        data = {"symbol": "AAPL", "source": "Yahoo", "type": "EQUITY"}
        bad = dict(data, source="Other")
        good = dict(data, points=self.points)
        expected = {"bullish": judgment.result("not_signaled"),
                    "bearish": judgment.unavailable("Missing peers")}
        with mock.patch.object(server, "chart_data", side_effect=[bad, good]) as fetch, \
                mock.patch.object(judgment, "evaluate", return_value=expected) as evaluate:
            result = server.retry_sparse_research("AAPL", data, sparse, {}, self.now, None, None)
        self.assertEqual(result, expected)
        self.assertEqual([call.args[1] for call in fetch.call_args_list], ["2y", "5y"])
        evaluate.assert_called_once_with("AAPL", good, {}, self.now, None, None)

    def test_sparse_window_keeps_original_when_retry_cannot_help(self):
        sparse = {d: judgment.unavailable(judgment.TOO_FEW_WINDOW_BARS)
                  for d in ("bullish", "bearish")}
        data = {"symbol": "AAPL", "source": "Yahoo", "type": "EQUITY"}
        with mock.patch.object(server, "chart_data", return_value=dict(data, cached=True)):
            self.assertIs(server.retry_sparse_research("AAPL", data, sparse, {}, self.now, None, None), sparse)
        with mock.patch.object(server, "chart_data", side_effect=RuntimeError("offline")):
            self.assertIs(server.retry_sparse_research("AAPL", data, sparse, {}, self.now, None, None), sparse)
        with mock.patch.object(server, "chart_data", return_value=data), \
                mock.patch.object(judgment, "evaluate", return_value=sparse):
            self.assertIs(server.retry_sparse_research("AAPL", data, sparse, {}, self.now, None, None), sparse)
        other = {d: judgment.unavailable("Missing peers") for d in ("bullish", "bearish")}
        with mock.patch.object(server, "chart_data") as fetch:
            self.assertIs(server.retry_sparse_research("AAPL", data, other, {}, self.now, None, None), other)
            fetch.assert_not_called()
        with mock.patch.object(server, "chart_data") as fetch:
            self.assertIs(server.retry_sparse_research("PSE:TEL", data, sparse, {}, self.now, None, None), sparse)
            fetch.assert_not_called()  # PSE already requests the provider's maximum.

    def test_endpoint_isolated_from_chart_on_failure(self):
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        worker = threading.Thread(target=httpd.serve_forever, daemon=True)
        worker.start()
        try:
            with mock.patch.object(server, "chart_data", side_effect=RuntimeError("offline")):
                conn = http.client.HTTPConnection("127.0.0.1", httpd.server_port, timeout=3)
                conn.request("GET", "/api/research-judgment?symbol=PSE%3ATEL")
                response = conn.getresponse()
                out = json.loads(response.read())
                self.assertEqual(response.status, 200)
                self.assertEqual(out["bullish"]["status"], "unavailable")
                self.assertEqual(out["bearish"]["status"], "unavailable")
                conn.close()
        finally:
            httpd.shutdown()
            httpd.server_close()
            worker.join()

    def test_chart_page_never_shows_the_research_judgment(self):
        # Removed by request: the line recited "could not be calculated" twice and
        # an in-sample baseline for every asset outside the studied universe, so
        # the chart no longer carries it. The endpoint still answers for anybody
        # asking directly; the page must not ask.
        html = Path("index.html").read_text(encoding="utf-8")
        for needle in ("researchJudgment", "research-judgment", "/api/research-judgment"):
            self.assertNotIn(needle, html)


if __name__ == "__main__":
    unittest.main()
