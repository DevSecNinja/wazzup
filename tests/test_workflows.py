from __future__ import annotations

import unittest
from pathlib import Path


class WorkflowTests(unittest.TestCase):
    def test_news_workflow_runs_every_two_hours_at_minute_seven(self) -> None:
        workflow = Path(".github/workflows/news-hourly.yml").read_text(encoding="utf-8")
        self.assertIn('cron: "7 */2 * * *"', workflow)
        self.assertNotIn('cron: "d"', workflow)


if __name__ == "__main__":
    unittest.main()
