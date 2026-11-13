import json
import tempfile
import unittest
from pathlib import Path
from datetime import date

import generate


class GeneratorTests(unittest.TestCase):
    def test_chronological_evaluation_windows(self):
        self.assertEqual(generate.evaluation_period(date(2026, 6, 30)), "train")
        self.assertEqual(generate.evaluation_period(date(2026, 7, 1)), "validation")
        self.assertEqual(generate.evaluation_period(date(2026, 9, 30)), "validation")
        self.assertEqual(generate.evaluation_period(date(2026, 10, 1)), "test")

    def test_seeded_runs_match_and_have_expected_exceptions(self):
        counts = {"campaigns": 8, "contacts": 40, "touchpoints": 180, "opportunities": 25}
        with tempfile.TemporaryDirectory() as temp:
            first = Path(temp) / "first"
            second = Path(temp) / "second"
            manifest_a = generate.generate_dataset(first, counts, 20261022)
            manifest_b = generate.generate_dataset(second, counts, 20261022)
            self.assertEqual(manifest_a["checksums_sha256"], manifest_b["checksums_sha256"])
            self.assertEqual(manifest_a["row_counts"]["campaigns"], counts["campaigns"])
            self.assertEqual(manifest_a["row_counts"]["contacts"], counts["contacts"])
            self.assertEqual(manifest_a["row_counts"]["touchpoints"], counts["touchpoints"])
            self.assertEqual(manifest_a["row_counts"]["opportunities"], counts["opportunities"])
            self.assertEqual(manifest_a["row_counts"]["campaign_events"], counts["campaigns"])
            ground_truth = json.loads((first / "ground_truth.json").read_text(encoding="utf-8"))
            self.assertEqual(
                {row["issue_type"] for row in ground_truth},
                {"duplicate_revenue", "post_conversion_touch", "currency_mismatch", "omitted_campaign_cost", "anonymous_session_link"},
            )
            self.assertTrue(json.loads((first / "validation_summary.json").read_text(encoding="utf-8"))["passed"])

    def test_sql_seed_loads_with_foreign_keys_enabled(self):
        counts = {"campaigns": 8, "contacts": 40, "touchpoints": 180, "opportunities": 25}
        with tempfile.TemporaryDirectory() as temp:
            output = Path(temp) / "dataset"
            generate.generate_dataset(output, counts, 20261022)
            connection = __import__("sqlite3").connect(":memory:")
            connection.executescript((output / "seed.sql").read_text(encoding="utf-8"))
            self.assertEqual(connection.execute("PRAGMA foreign_key_check").fetchall(), [])
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM campaigns").fetchone()[0], 8)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM opportunities").fetchone()[0], 25)
            connection.close()


if __name__ == "__main__":
    unittest.main()
