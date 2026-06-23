from __future__ import annotations

import unittest
from pathlib import Path


class WorkflowTests(unittest.TestCase):
    def test_news_workflow_uses_active_two_hour_local_cadence_gate(self) -> None:
        workflow = Path(".github/workflows/news.yml").read_text(encoding="utf-8")
        self.assertIn("name: News\n", workflow)
        self.assertIn('cron: "7 * * * *"', workflow)
        self.assertIn("default: auto", workflow)
        self.assertIn("- auto", workflow)
        self.assertIn("Check scheduled cadence", workflow)
        self.assertIn("COPILOT_MODEL: claude-sonnet-4.6", workflow)
        self.assertIn("COPILOT_WRITER_MODEL: claude-opus-4.8", workflow)
        self.assertIn("- Copilot model: ${COPILOT_MODEL}", workflow)
        self.assertIn("- Copilot writer model: ${COPILOT_WRITER_MODEL}", workflow)
        self.assertIn("hour >= 6 && hour < 22 && hour % 2 == 1", workflow)
        self.assertIn("active two-hour local cadence", workflow)
        self.assertIn("outside active two-hour local cadence", workflow)
        self.assertNotIn("overnight two-hour cadence", workflow)
        self.assertNotIn('cron: "d"', workflow)

    def test_news_workflow_dispatches_pages_deploy_for_every_trigger(self) -> None:
        workflow = Path(".github/workflows/news.yml").read_text(encoding="utf-8")
        self.assertIn("actions: write", workflow)
        self.assertIn("Deploy refreshed state to Pages", workflow)
        self.assertIn("gh workflow run pages.yml", workflow)
        self.assertIn("- Pages deployment: dispatched explicitly after persisting state", workflow)

    def test_news_watchdog_dispatches_when_effective_generation_is_stale(self) -> None:
        workflow = Path(".github/workflows/news-watchdog.yml").read_text(encoding="utf-8")
        self.assertIn('cron: "37 * * * *"', workflow)
        self.assertIn("actions: write", workflow)
        self.assertIn("TARGET_WORKFLOW: news.yml", workflow)
        # The watchdog runs every hour inside the active window. Gating on
        # odd-hour parity would disable it under GitHub schedule jitter, which
        # is exactly when catch-up dispatches are needed.
        self.assertIn("hour >= 7 && hour < 22", workflow)
        self.assertNotIn("hour % 2 == 1", workflow)
        # Two-hour cadence is enforced by elapsed time since the last effective
        # generation, not by the wall-clock hour of this run.
        self.assertIn("CADENCE_INTERVAL_MINUTES:", workflow)
        self.assertIn("GENERATE_STEP_NAME: Generate and persist retained news state", workflow)
        self.assertIn("last_effective_epoch", workflow)
        self.assertIn("threshold_epoch", workflow)
        # A cadence skip still produces a News run, so existence alone must not
        # suppress catch-up; the generate step result is inspected instead.
        self.assertIn("/jobs", workflow)
        self.assertNotIn("Existing News runs this scheduled UTC hour", workflow)
        self.assertIn("gh workflow run \"${TARGET_WORKFLOW}\"", workflow)
        self.assertIn("--repo \"${GITHUB_REPOSITORY}\"", workflow)
        self.assertIn("forceBriefing=auto", workflow)
        self.assertIn("aiProvider=copilot-cli", workflow)

    def test_pages_workflow_runs_after_main_updates(self) -> None:
        workflow = Path(".github/workflows/pages.yml").read_text(encoding="utf-8")
        self.assertIn("push:", workflow)
        self.assertIn("branches:", workflow)
        self.assertIn("- main", workflow)
        self.assertIn("workflow_dispatch:", workflow)
        self.assertNotIn("workflow_run:", workflow)
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
