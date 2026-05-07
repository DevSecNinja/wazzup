from __future__ import annotations

import os
import unittest
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from wazzup.ai import CopilotCliSummaryProvider, FakeSummaryProvider, SummaryRequest, provider_from_env
from wazzup.config import load_app_config, load_sources
from wazzup.feeds import parse_feed
from wazzup.scoring import score_items


class AiProviderTests(unittest.TestCase):
    def test_provider_defaults_to_fake(self) -> None:
        previous_provider = os.environ.get("AI_PROVIDER")
        os.environ.pop("AI_PROVIDER", None)
        try:
            provider = provider_from_env(load_app_config("config/interests.yml"))
            self.assertEqual("fake", provider.name)
        finally:
            if previous_provider is not None:
                os.environ["AI_PROVIDER"] = previous_provider

    def test_fake_provider_summarizes_without_scoring_jargon(self) -> None:
        source = load_sources("config/sources.yml")[0]
        item = parse_feed(source, Path("tests/fixtures/microsoft-security-blog.xml").read_bytes())[0]
        item = replace(item, summary="Microsoft Defender adds AI-assisted triage for security operations teams.")
        scored = score_items([item], [source], load_app_config("config/interests.yml"), datetime(2026, 5, 6, tzinfo=UTC))
        response = FakeSummaryProvider().generate_structured_summary(
            SummaryRequest(
                kind="hourly",
                window_start="2026-05-06T20:00:00Z",
                window_end="2026-05-06T21:00:00Z",
                generated_at="2026-05-06T21:00:00Z",
                timezone="Europe/Amsterdam",
                summary_language="en",
                items=scored,
            )
        )
        bullet = response.sections[0]["bullets"][0]["text"]
        description = response.sections[0]["bullets"][0]["description"]
        self.assertIn("Why it matters", bullet)
        self.assertIn("Why it matters", description)
        self.assertIn("title", response.sections[0]["bullets"][0])
        self.assertIn("security", bullet)
        self.assertNotIn("source weight", bullet.lower())

    @patch("wazzup.ai.shutil.which", return_value="/usr/bin/copilot")
    def test_copilot_requires_token_in_github_actions(self, _which) -> None:  # type: ignore[no-untyped-def]
        previous_actions = os.environ.get("GITHUB_ACTIONS")
        previous_token = os.environ.get("COPILOT_GITHUB_TOKEN")
        os.environ["GITHUB_ACTIONS"] = "true"
        os.environ.pop("COPILOT_GITHUB_TOKEN", None)
        try:
            request = SummaryRequest(
                kind="hourly",
                window_start="2026-05-06T20:00:00Z",
                window_end="2026-05-06T21:00:00Z",
                generated_at="2026-05-06T21:00:00Z",
                timezone="Europe/Amsterdam",
                summary_language="en",
                items=[],
            )
            with self.assertRaisesRegex(RuntimeError, "COPILOT_GITHUB_TOKEN"):
                CopilotCliSummaryProvider().generate_structured_summary(request)
        finally:
            if previous_actions is None:
                os.environ.pop("GITHUB_ACTIONS", None)
            else:
                os.environ["GITHUB_ACTIONS"] = previous_actions
            if previous_token is None:
                os.environ.pop("COPILOT_GITHUB_TOKEN", None)
            else:
                os.environ["COPILOT_GITHUB_TOKEN"] = previous_token


if __name__ == "__main__":
    unittest.main()
