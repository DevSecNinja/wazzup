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
        self.assertIn("COPILOT_MODEL: claude-sonnet-4.6", workflow)
        self.assertIn("- Copilot model: ${COPILOT_MODEL}", workflow)
        self.assertIn("hour >= 6 && hour < 22", workflow)
        self.assertIn("overnight two-hour cadence", workflow)
        self.assertNotIn('cron: "d"', workflow)

    def test_news_watchdog_dispatches_delayed_hourly_runs(self) -> None:
        workflow = Path(".github/workflows/news-hourly-watchdog.yml").read_text(encoding="utf-8")
        self.assertIn('cron: "37 * * * *"', workflow)
        self.assertIn("actions: write", workflow)
        self.assertIn("TARGET_WORKFLOW: news-hourly.yml", workflow)
        self.assertIn("current_hour_start=", workflow)
        self.assertIn("| jq --arg cutoff", workflow)
        self.assertIn("Existing News hourly runs this UTC hour", workflow)
        self.assertIn("gh workflow run \"${TARGET_WORKFLOW}\"", workflow)
        self.assertIn("forceBriefing=auto", workflow)
        self.assertIn("aiProvider=copilot-cli", workflow)

    def test_pages_workflow_runs_after_main_updates(self) -> None:
        workflow = Path(".github/workflows/pages.yml").read_text(encoding="utf-8")
        self.assertIn("push:", workflow)
        self.assertIn("branches:", workflow)
        self.assertIn("- main", workflow)
        self.assertIn("workflow_run:", workflow)
        self.assertIn("workflow_dispatch:", workflow)
        self.assertIn('export GITHUB_TOKEN="${{ github.token }}"', workflow)
        self.assertIn("build-command: ~/.local/bin/mise exec -- task pages:build", workflow)


if __name__ == "__main__":
    unittest.main()
