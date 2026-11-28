import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import MagicMock, call

from scripts.mor25_ledger_diagnostic import DIGEST, OPTIONS, diagnose


class LedgerDiagnosticTest(unittest.TestCase):
    def setUp(self):
        self.driver = MagicMock()
        self.conn = self.driver.connect.return_value
        self.conn.execute.return_value.fetchone.side_effect = [
            (True, True, True, True), (DIGEST, 7, {"openalex": 7})
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
        self.conn.execute.return_value.fetchone.side_effect = [(True,) * 4, ("other", 7, {"openalex": 7})]
        self.assertIn("stage=verify_authorization", self.run_check()[1])
