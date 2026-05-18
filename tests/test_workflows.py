from __future__ import annotations

import unittest
from pathlib import Path


class WorkflowTests(unittest.TestCase):
    def test_news_workflow_uses_active_two_hour_local_cadence_gate(self) -> None:
        workflow = Path(".github/workflows/news-hourly.yml").read_text(encoding="utf-8")
        self.assertIn('cron: "7 * * * *"', workflow)
        self.assertIn("default: auto", workflow)
        self.assertIn("- auto", workflow)
        self.assertIn("Check scheduled cadence", workflow)
        self.assertIn("COPILOT_MODEL: claude-sonnet-4.6", workflow)
        self.assertIn("- Copilot model: ${COPILOT_MODEL}", workflow)
        self.assertIn("hour >= 6 && hour < 22 && hour % 2 == 1", workflow)
        self.assertIn("active two-hour local cadence", workflow)
        self.assertIn("outside active two-hour local cadence", workflow)
        self.assertNotIn("overnight two-hour cadence", workflow)
        self.assertNotIn('cron: "d"', workflow)

    def test_news_watchdog_dispatches_delayed_two_hour_runs(self) -> None:
        workflow = Path(".github/workflows/news-hourly-watchdog.yml").read_text(encoding="utf-8")
        self.assertIn('cron: "37 * * * *"', workflow)
        self.assertIn("actions: write", workflow)
        self.assertIn("TARGET_WORKFLOW: news-hourly.yml", workflow)
        self.assertIn("hour >= 6 && hour < 22 && hour % 2 == 1", workflow)
        self.assertIn("current_hour_start=", workflow)
        self.assertIn("| jq --arg cutoff", workflow)
        self.assertIn("Existing News hourly runs this scheduled UTC hour", workflow)
        self.assertIn("gh workflow run \"${TARGET_WORKFLOW}\"", workflow)
        self.assertIn("--repo \"${GITHUB_REPOSITORY}\"", workflow)
        self.assertIn("forceBriefing=auto", workflow)
        self.assertIn("aiProvider=copilot-cli", workflow)

    def test_pages_workflow_runs_after_main_updates(self) -> None:
        workflow = Path(".github/workflows/pages.yml").read_text(encoding="utf-8")
        self.assertIn("push:", workflow)
        self.assertIn("branches:", workflow)
        self.assertIn("- main", workflow)
        self.assertIn("workflow_run:", workflow)
        self.assertIn("workflow_dispatch:", workflow)
        self.assertIn("python3 -m pip install --break-system-packages -r requirements.txt", workflow)
        self.assertIn("PYTHONPATH=src python3 -m unittest discover -s tests", workflow)
        self.assertIn("build-command: PYTHONPATH=src python3 scripts/pages_build.py", workflow)
        self.assertNotIn('export GITHUB_TOKEN="${{ github.token }}"', workflow)
        self.assertNotIn("mise install", workflow)

    def test_data_validation_accepts_legacy_latest_without_transparency_report(self) -> None:
        validator = Path("src/wazzup/validate_data.py").read_text(encoding="utf-8")
        self.assertIn("def validate_optional_transparency_report", validator)
        self.assertIn("if not present_keys:", validator)


if __name__ == "__main__":
    unittest.main()
