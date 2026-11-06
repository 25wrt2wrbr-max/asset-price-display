import datetime as dt
import unittest

import outcome_availability_audit as audit


class OutcomeAvailabilityTests(unittest.TestCase):
    def test_status_distinguishes_observed_pending_grace_and_missing(self):
        signal = dt.date(2024, 1, 1)
        target = dt.date(2024, 4, 1)
        self.assertEqual(audit.outcome_status(signal, target, None, None, dt.date(2024, 3, 31)), "not_due")
        self.assertEqual(audit.outcome_status(signal, target, None, None, dt.date(2024, 4, 10)), "within_exit_grace")
        self.assertEqual(audit.outcome_status(signal, target, None, None, dt.date(2024, 4, 11)), "matured_missing")
        self.assertEqual(audit.outcome_status(signal, target, dt.date(2024, 4, 2), 10., dt.date(2024, 4, 2)), "observed")
        self.assertEqual(audit.outcome_status(signal, target, dt.date(2024, 4, 2), 0., dt.date(2024, 4, 2)), "invalid_exit_price")
        self.assertEqual(audit.outcome_status(signal, target, dt.date(2024, 4, 12), 10., dt.date(2024, 4, 12)), "matured_missing")

    def test_future_exit_is_never_treated_as_observed(self):
        self.assertEqual(audit.outcome_status(dt.date(2024, 1, 1), dt.date(2024, 4, 1),
                                              dt.date(2024, 4, 2), 10., dt.date(2024, 3, 31)), "not_due")


if __name__ == "__main__":
    unittest.main()
