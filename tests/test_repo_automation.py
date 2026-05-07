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
        for workflow in ["config-sync.yml", "label-sync.yml", "labeler.yml"]:
            path = Path(".github/workflows") / workflow
            self.assertTrue(path.exists(), workflow)
            content = path.read_text(encoding="utf-8")
            self.assertIn("DevSecNinja/.github/.github/workflows/", content)
            self.assertIn("# renovate: datasource=github-tags depName=DevSecNinja/.github", content)

    def test_labeler_configs_cover_key_project_areas(self) -> None:
        labels = yaml.safe_load(Path(".github/labels.yaml").read_text(encoding="utf-8"))
        label_names = {label["name"] for label in labels}
        self.assertTrue({"area/backend", "area/frontend", "area/data", "area/github", "area/renovate"}.issubset(label_names))

        pr_labeler = yaml.safe_load(Path(".github/pr-labeler.yaml").read_text(encoding="utf-8"))
        self.assertIn("area/frontend", pr_labeler)
        self.assertIn("area/backend", pr_labeler)
        self.assertIn("area/renovate", pr_labeler)


if __name__ == "__main__":
    unittest.main()
