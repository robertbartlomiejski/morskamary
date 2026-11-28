import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import MagicMock, call

from scripts.mor25_ledger_diagnostic import DIGEST, OPTIONS, diagnose


class LedgerDiagnosticTest(unittest.TestCase):
    def setUp(self):
        self.driver = MagicMock()
        self.conn = self.driver.connect.return_value
        self.ceilings = dict.fromkeys(
            ("crossref", "google_drive", "microsoft_graph", "scival", "scopus", "wos"), 0
        )
        self.ceilings["openalex"] = 7
        self.set_authorization(("physical_attempt_ledger/2", DIGEST, 7, self.ceilings))

    def set_authorization(self, row):
        self.conn.execute.return_value.fetchone.side_effect = [
            (True, True, True, True), row
        ]

    def run_check(self):
        output = io.StringIO()
        with redirect_stdout(output):
            status = diagnose(self.driver, "private-test-value")
        self.assertNotIn("private-test-value", output.getvalue())
        return status, output.getvalue()

    def test_production_options(self):
        self.assertEqual(self.run_check(), (0, "pilot_read_ok\n"))
        self.driver.connect.assert_called_once_with("private-test-value", connect_timeout=5, options=OPTIONS)
        self.assertEqual(self.conn.execute.call_args_list[0], call("SET TRANSACTION READ ONLY"))

    def test_control_success_keeps_original_failure(self):
        self.driver.connect.side_effect = [ValueError("private-test-value"), self.conn]
        status, output = self.run_check()
        self.assertEqual(status, 1)
        self.assertIn("control_read_ok", output)
        self.assertEqual(self.driver.connect.call_args, call("private-test-value", connect_timeout=5))

    def test_parse_error_stops_before_connect(self):
        self.driver.conninfo.conninfo_to_dict.side_effect = ValueError("private-test-value")
        self.assertIn("stage=parse", self.run_check()[1])
        self.driver.connect.assert_not_called()

    def test_wrong_budget_fails(self):
        self.set_authorization(("physical_attempt_ledger/2", "other", 7, self.ceilings))
        self.assert_authorization_failure()

    def test_wrong_schema_fails_with_matching_budget(self):
        self.set_authorization(("physical_attempt_ledger/1", DIGEST, 7, self.ceilings))
        self.assert_authorization_failure()

    def test_provider_map_must_match_exactly(self):
        for ceilings in (
            {**self.ceilings, "extra_provider": 0},
            {**self.ceilings, "crossref": 1},
            {key: value for key, value in self.ceilings.items() if key != "wos"},
        ):
            with self.subTest(ceilings=ceilings):
                self.set_authorization(("physical_attempt_ledger/2", DIGEST, 7, ceilings))
                self.assert_authorization_failure()

    def test_control_rejects_mismatched_authorization(self):
        self.driver.connect.side_effect = [ValueError("private-test-value"), self.conn]
        self.set_authorization(("physical_attempt_ledger/2", DIGEST, 7, {**self.ceilings, "scopus": 1}))
        self.assert_authorization_failure()

    def assert_authorization_failure(self):
        status, output = self.run_check()
        self.assertEqual(status, 1)
        self.assertIn("stage=verify_authorization", output)
        self.assertNotIn("read_ok", output)
