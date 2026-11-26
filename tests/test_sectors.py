"""The sector table: the eight PSE indexes through the chart's own path."""

import unittest

import sectors


class BuildTests(unittest.TestCase):
    def test_rows_are_the_chart_payloads_and_failures_are_listed(self):
        seen = []

        def chart_data(symbol, span, interval):
            seen.append((symbol, span, interval))
            if symbol == "PSE:M_O":
                raise RuntimeError("socket dropped")
            return {"trend": {"label": "neutral"}, "source": "TradingView",
                    "points": [{"t": 1, "c": 10.0, "x": 0}, {"t": 2, "c": 11.0}]}

        out = sectors.build(chart_data)
        self.assertEqual([s for s, _, _ in seen], [s for s, _ in sectors.INDEXES])
        self.assertTrue(all(span == "3mo" and iv == "1d" for _, span, iv in seen))
        self.assertEqual(len(out["rows"]), 7)
        self.assertEqual(out["errors"], {"PSE:M_O": "socket dropped"})
        self.assertEqual(out["rows"][0]["name"], "PSEi")
        self.assertEqual(out["rows"][0]["points"], [{"t": 1, "c": 10.0}, {"t": 2, "c": 11.0}])

    def test_all_failed_keeps_the_last_good_table(self):
        sectors._payload = {"rows": [{"symbol": "PSE:PSEI"}], "errors": {}, "pending": False}

        def down(*_a):
            raise RuntimeError("down")

        sectors._refresh(down)
        self.assertEqual(sectors._payload["rows"], [{"symbol": "PSE:PSEI"}])
        self.assertIn("down", sectors._payload["staleError"])


if __name__ == "__main__":
    unittest.main()
