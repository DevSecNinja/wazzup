from __future__ import annotations

import os
import unittest
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import Mock, patch

from wazzup.ai import (
    CopilotCliSummaryProvider,
    FakeSummaryProvider,
    SummaryRequest,
    build_prompt_payload,
    provider_from_env,
)
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

    def test_fake_provider_standardizes_hourly_descriptions(self) -> None:
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
        self.assertNotIn("Why it matters", bullet)
        self.assertNotIn("Why it matters", description)
        self.assertIn("Relevant to your", description)
        self.assertIn("title", response.sections[0]["bullets"][0])
        self.assertIn("security", bullet)
        self.assertNotIn("source weight", bullet.lower())

    def test_prompt_style_guide_discourages_why_it_matters_label(self) -> None:
        payload = build_prompt_payload(
            SummaryRequest(
                kind="hourly",
                window_start="2026-05-06T20:00:00Z",
                window_end="2026-05-06T21:00:00Z",
                generated_at="2026-05-06T21:00:00Z",
                timezone="Europe/Amsterdam",
                summary_language="en",
                items=[],
            )
        )
        style_guide = payload["styleGuide"]
        self.assertIn("Describe relevance directly without labels like 'Why it matters'.", style_guide)

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

    @patch("wazzup.ai.subprocess.run")
    @patch("wazzup.ai.shutil.which", return_value="/usr/bin/copilot")
    def test_copilot_invalid_payload_falls_back_to_deterministic_summary(self, _which, run_mock) -> None:  # type: ignore[no-untyped-def]
        previous_token = os.environ.get("COPILOT_GITHUB_TOKEN")
        os.environ["COPILOT_GITHUB_TOKEN"] = "test-token"
        source = load_sources("config/sources.yml")[0]
        item = parse_feed(source, Path("tests/fixtures/microsoft-security-blog.xml").read_bytes())[0]
        scored = score_items([item], [source], load_app_config("config/interests.yml"), datetime(2026, 5, 6, tzinfo=UTC))

        def fake_run(_command, capture_output, cwd, env, text):  # type: ignore[no-untyped-def]
            del capture_output, env, text
            Path(cwd, "summary.json").write_text('{"headline":"Invalid"}', encoding="utf-8")
            return Mock(returncode=0, stdout="", stderr="")

        run_mock.side_effect = fake_run
        try:
            response = CopilotCliSummaryProvider().generate_structured_summary(
                SummaryRequest(
                    kind="hourly",
                    window_start="2026-05-06T00:00:00Z",
                    window_end="2026-05-06T21:00:00Z",
                    generated_at="2026-05-06T21:00:00Z",
                    timezone="Europe/Amsterdam",
                    summary_language="en",
                    items=scored,
                )
            )
        finally:
            if previous_token is None:
                os.environ.pop("COPILOT_GITHUB_TOKEN", None)
            else:
                os.environ["COPILOT_GITHUB_TOKEN"] = previous_token

        self.assertEqual("copilot-cli-fallback", response.provider["type"])
        self.assertIn("fallbackReason", response.provider)
        self.assertTrue(response.sections[0]["bullets"])


if __name__ == "__main__":
    unittest.main()
