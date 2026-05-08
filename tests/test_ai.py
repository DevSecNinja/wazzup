from __future__ import annotations

import os
import unittest
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import Mock, patch

from wazzup.ai import (
    CopilotCliSummaryProvider,
    DEFAULT_COPILOT_AGENT,
    DEFAULT_COPILOT_MODEL,
    FakeSummaryProvider,
    SummaryRequest,
    build_prompt_payload,
    provider_from_env,
    response_from_payload,
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

    def test_fake_provider_includes_every_selected_item(self) -> None:
        source = load_sources("config/sources.yml")[0]
        item = parse_feed(source, Path("tests/fixtures/microsoft-security-blog.xml").read_bytes())[0]
        items = [
            replace(
                item,
                id=f"item-{index}",
                title=f"Article {index}",
                canonical_url=f"https://example.com/{index}",
            )
            for index in range(10)
        ]
        scored = score_items(items, [source], load_app_config("config/interests.yml"), datetime(2026, 5, 6, tzinfo=UTC))

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

        bullets = response.sections[0]["bullets"]
        self.assertEqual(len(scored), len(bullets))
        self.assertEqual([scored_item.item.id for scored_item in scored], [bullet["citations"][0] for bullet in bullets])

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

    def test_prompt_style_guide_requires_topic_only_headline(self) -> None:
        payload = build_prompt_payload(
            SummaryRequest(
                kind="evening",
                window_start="2026-05-06T05:00:00Z",
                window_end="2026-05-06T18:00:00Z",
                generated_at="2026-05-06T18:00:00Z",
                timezone="Europe/Amsterdam",
                summary_language="en",
                items=[],
            )
        )
        style_guide = "\n".join(payload["styleGuide"])
        self.assertIn("topic-only news headline", style_guide)
        self.assertIn("under 80 characters", style_guide)
        self.assertIn("Evening Briefing", style_guide)
        self.assertIn("date", style_guide)

    def test_response_from_payload_accepts_description_without_text(self) -> None:
        response = response_from_payload(
            {
                "headline": "Important updates",
                "sections": [
                    {
                        "title": "Top updates",
                        "bullets": [
                            {
                                "title": "Microsoft ships a security update",
                                "description": "The release improves defender triage workflows.",
                                "citations": ["item-1"],
                            }
                        ],
                    }
                ],
            },
            provider={"type": "copilot-cli", "validated": True},
        )

        bullet = response.sections[0]["bullets"][0]
        self.assertEqual(
            "Microsoft ships a security update: The release improves defender triage workflows.", bullet["text"]
        )
        self.assertEqual("The release improves defender triage workflows.", bullet["description"])

    @patch("wazzup.ai.subprocess.run")
    @patch("wazzup.ai.shutil.which", return_value="/usr/bin/copilot")
    def test_copilot_cli_uses_default_model_and_writer_agent(self, _which, run_mock) -> None:  # type: ignore[no-untyped-def]
        previous_model = os.environ.get("COPILOT_MODEL")
        previous_agent = os.environ.get("COPILOT_AGENT")
        os.environ.pop("COPILOT_MODEL", None)
        os.environ.pop("COPILOT_AGENT", None)

        def fake_run(command, capture_output, cwd, env, text):  # type: ignore[no-untyped-def]
            del capture_output, text
            Path(env["WAZZUP_COPILOT_OUTPUT_PATH"]).write_text(
                '{"headline":"No updates","sections":[{"title":"Top updates","bullets":[]}]}',
                encoding="utf-8",
            )
            self.assertEqual(Path.cwd(), Path(cwd))
            self.assertIn("--model", command)
            self.assertEqual(DEFAULT_COPILOT_MODEL, command[command.index("--model") + 1])
            self.assertIn("--agent", command)
            self.assertEqual(DEFAULT_COPILOT_AGENT, command[command.index("--agent") + 1])
            return Mock(returncode=0, stdout="", stderr="")

        run_mock.side_effect = fake_run
        try:
            response = CopilotCliSummaryProvider().generate_structured_summary(
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
        finally:
            if previous_model is None:
                os.environ.pop("COPILOT_MODEL", None)
            else:
                os.environ["COPILOT_MODEL"] = previous_model
            if previous_agent is None:
                os.environ.pop("COPILOT_AGENT", None)
            else:
                os.environ["COPILOT_AGENT"] = previous_agent

        self.assertEqual(DEFAULT_COPILOT_MODEL, response.provider["model"])
        self.assertEqual(DEFAULT_COPILOT_AGENT, response.provider["agent"])

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
            del capture_output, text
            Path(env["WAZZUP_COPILOT_OUTPUT_PATH"]).write_text('{"headline":"Invalid"}', encoding="utf-8")
            self.assertEqual(Path.cwd(), Path(cwd))
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
