from __future__ import annotations

import unittest
from pathlib import Path

import yaml


class WorkflowTests(unittest.TestCase):
    def test_news_workflow_uses_freshness_gated_cadence(self) -> None:
        workflow = Path(".github/workflows/news.yml").read_text(encoding="utf-8")
        self.assertIn("name: News\n", workflow)
        # Several ticks per hour so dropped scheduled runs are made up quickly.
        self.assertIn('cron: "7,27,47 5-20 * * *"', workflow)
        self.assertIn("default: auto", workflow)
        self.assertIn("- auto", workflow)
        self.assertIn("Check scheduled cadence", workflow)
        self.assertIn("hour < 7 || hour >= 22", workflow)
        # Wall-clock hour parity skipped real work whenever ticks were dropped
        # or jittered; freshness of the persisted state decides instead.
        self.assertNotIn("hour % 2 == 1", workflow)
        self.assertIn("releases/tags/${STATE_RELEASE}", workflow)
        self.assertIn("STATE_ASSET: wazzup-state.zip", workflow)
        self.assertIn('CADENCE_INTERVAL_MINUTES: "100"', workflow)
        self.assertIn("FAILURE_BACKOFF_MINUTES:", workflow)
        self.assertIn("runs?status=failure", workflow)
        self.assertFalse(Path(".github/workflows/news-watchdog.yml").exists())

    def test_copilot_agents_do_not_override_runtime_model_policy(self) -> None:
        for agent in ("wazzup-curator", "wazzup-transparency-reporter", "wazzup-writer"):
            with self.subTest(agent=agent):
                definition = Path(f".github/agents/{agent}.agent.md").read_text(encoding="utf-8")
                frontmatter = yaml.safe_load(definition.split("---", 2)[1])
                self.assertNotIn("model", frontmatter)

    def test_news_workflow_uses_python_policy_and_summarizes_failures(self) -> None:
        workflow = Path(".github/workflows/news.yml").read_text(encoding="utf-8")
        self.assertNotIn("COPILOT_MODEL:", workflow)
        self.assertNotIn("COPILOT_WRITER_MODEL:", workflow)
        self.assertNotIn("claude-", workflow)
        steps = yaml.safe_load(workflow)["jobs"]["generate"]["steps"]
        summary = next(step for step in steps if step["name"] == "Write workflow summary")
        generation = next(step for step in steps if step["name"] == "Generate and persist retained news state")
        pages = next(step for step in steps if step["name"] == "Deploy refreshed state to Pages")
        self.assertEqual("${{ always() && steps.cadence.outputs.should_run == 'true' }}", summary["if"])
        self.assertEqual("${{ steps.generation.outcome }}", summary["env"]["GENERATION_OUTCOME"])
        self.assertEqual("${{ steps.pages.outcome }}", summary["env"]["PAGES_OUTCOME"])
        self.assertEqual("generation", generation["id"])
        self.assertEqual("pages", pages["id"])
        self.assertIn("task news:generate", generation["run"])
        self.assertIn("Copilot model selections and policy errors", summary["run"])
        self.assertIn("Falling back to AI_PROVIDER=fake for this run", workflow)

    def test_news_workflow_dispatches_pages_deploy_for_every_trigger(self) -> None:
        workflow = Path(".github/workflows/news.yml").read_text(encoding="utf-8")
        self.assertIn("actions: write", workflow)
        self.assertIn("Deploy refreshed state to Pages", workflow)
        self.assertIn("gh workflow run pages.yml", workflow)
        self.assertIn("- Pages deployment dispatch: ${PAGES_OUTCOME}", workflow)

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
