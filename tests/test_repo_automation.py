from __future__ import annotations

import unittest
from pathlib import Path

import yaml


class RepoAutomationTests(unittest.TestCase):
    def test_renovate_extends_org_presets(self) -> None:
        renovate = Path("renovate.json5").read_text(encoding="utf-8")
        self.assertIn("github>DevSecNinja/.github//.renovate/base.json5", renovate)
        self.assertIn("github>DevSecNinja/.github//.renovate/customManagers.json5", renovate)
        self.assertIn("helpers:pinGitHubActionDigests", renovate)

    def test_repo_automation_workflows_are_onboarded(self) -> None:
        workflows = ["autofix.yml", "config-sync.yml", "label-sync.yml", "labeler.yml"]
        for workflow in workflows:
            path = Path(".github/workflows") / workflow
            self.assertTrue(path.exists(), workflow)
            content = path.read_text(encoding="utf-8")
            self.assertIn("DevSecNinja/.github/.github/workflows/", content)
            self.assertIn("# renovate: datasource=github-tags depName=DevSecNinja/.github", content)

    def test_lint_autofix_and_hooks_are_configured(self) -> None:
        lint_config_paths = ["dprint.json", ".yamlfmt.yaml", ".yamllint.yaml", ".lefthook.toml"]
        for path in lint_config_paths:
            self.assertTrue(Path(path).exists(), path)

        lint_workflow = Path(".github/workflows/lint.yml").read_text(encoding="utf-8")
        self.assertIn("lint-config-dir: .", lint_workflow)
        self.assertIn("lint-shellcheck: false", lint_workflow)

        autofix_workflow = Path(".github/workflows/autofix.yml").read_text(encoding="utf-8")
        self.assertIn("autofix-config-dir: .", autofix_workflow)
        self.assertIn("autofix-shfmt: false", autofix_workflow)

        mise = Path(".mise.toml").read_text(encoding="utf-8")
        self.assertIn("lefthook =", mise)
        self.assertIn("cocogitto =", mise)

    def test_labeler_configs_cover_key_project_areas(self) -> None:
        labels = yaml.safe_load(Path(".github/labels.yaml").read_text(encoding="utf-8"))
        label_names = {label["name"] for label in labels}
        self.assertTrue({"area/backend", "area/frontend", "area/data", "area/github", "area/renovate"}.issubset(label_names))

        pr_labeler = yaml.safe_load(Path(".github/pr-labeler.yaml").read_text(encoding="utf-8"))
        self.assertIn("area/frontend", pr_labeler)
        self.assertIn("area/backend", pr_labeler)
        self.assertIn("area/renovate", pr_labeler)

    def test_issue_labeler_uses_javascript_compatible_case_insensitive_regex(self) -> None:
        issue_labeler = Path(".github/issue-labeler.yaml").read_text(encoding="utf-8")
        self.assertNotIn("(?i)", issue_labeler)
        self.assertIn("/(feature request|enhancement|add support|would be (nice|great)|request)/i", issue_labeler)


if __name__ == "__main__":
    unittest.main()
