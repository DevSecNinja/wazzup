from __future__ import annotations

import unittest
from pathlib import Path


class WorkflowTests(unittest.TestCase):
    def test_news_workflow_uses_hourly_trigger_with_local_cadence_gate(self) -> None:
        workflow = Path(".github/workflows/news-hourly.yml").read_text(encoding="utf-8")
        self.assertIn('cron: "7 * * * *"', workflow)
        self.assertIn("default: auto", workflow)
        self.assertIn("- auto", workflow)
        self.assertIn("Check scheduled cadence", workflow)
        self.assertIn("hour >= 6 && hour < 22", workflow)
        self.assertIn("overnight two-hour cadence", workflow)
        self.assertNotIn('cron: "d"', workflow)


if __name__ == "__main__":
    unittest.main()
