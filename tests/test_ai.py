from __future__ import annotations

import os
import unittest
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import Mock, patch

from wazzup.ai import (
    CopilotCliCurationProvider,
    CopilotCliSummaryProvider,
    CopilotCliTransparencyReportProvider,
    COPILOT_CLI_MAX_ATTEMPTS,
    CurationRequest,
    DEFAULT_COPILOT_AGENT,
    DEFAULT_COPILOT_CURATOR_AGENT,
    DEFAULT_COPILOT_MODEL,
    DEFAULT_COPILOT_TRANSPARENCY_AGENT,
    FakeCurationProvider,
    FakeSummaryProvider,
    FakeTransparencyReportProvider,
    MAX_SUMMARY_DESCRIPTION_LENGTH,
    MAX_SUMMARY_HEADLINE_LENGTH,
    MAX_SUMMARY_TITLE_LENGTH,
    SummaryRequest,
    TransparencyReportRequest,
    build_curation_payload,
    build_prompt_payload,
    build_transparency_payload,
    curation_provider_from_env,
    provider_from_env,
    response_from_payload,
    transparency_provider_from_env,
    transparency_response_from_payload,
)
from wazzup.config import load_app_config, load_sources
from wazzup.feeds import parse_feed
from wazzup.models import SourceStatus
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

    def test_fake_provider_cites_related_source_items(self) -> None:
        source = load_sources("config/sources.yml")[0]
        item = parse_feed(source, Path("tests/fixtures/microsoft-security-blog.xml").read_bytes())[0]
        related = replace(item, id="item-related", source_id="related-source", source_name="Related Source")
        scored = score_items(
            [replace(item, related_items=(related,))],
            [source],
            load_app_config("config/interests.yml"),
            datetime(2026, 5, 6, tzinfo=UTC),
        )

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

        self.assertEqual([item.id, "item-related"], response.sections[0]["bullets"][0]["citations"])

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

    def test_prompt_contract_caps_title_and_description_lengths(self) -> None:
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
        contract = payload["outputContract"]["sections"][0]["bullets"][0]
        style_guide = "\n".join(payload["styleGuide"])
        agent = Path(".github/agents/wazzup-writer.agent.md").read_text(encoding="utf-8")
        self.assertIn(f"max {MAX_SUMMARY_HEADLINE_LENGTH} characters", payload["outputContract"]["headline"])
        self.assertIn(f"max {MAX_SUMMARY_TITLE_LENGTH} characters", contract["title"])
        self.assertIn(f"max {MAX_SUMMARY_DESCRIPTION_LENGTH} characters", contract["description"])
        self.assertIn("one concise complete sentence", style_guide)
        self.assertIn("under 96 characters", agent)
        self.assertIn("under 220 characters", agent)

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

    def test_prompt_style_guide_requires_related_items_to_be_correlated(self) -> None:
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
        style_guide = "\n".join(payload["styleGuide"])
        self.assertIn("relatedItems", style_guide)
        self.assertIn("one correlated story", style_guide)

    def test_prompt_allows_synthesized_bullets_for_related_items(self) -> None:
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
        style_guide = "\n".join(payload["styleGuide"])
        self.assertIn("Merge closely related input items into one synthesized bullet", style_guide)
        self.assertIn("same story", style_guide)
        self.assertIn("cite every source item ID", style_guide)

    def test_prompt_style_guide_requires_english_translation(self) -> None:
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
        style_guide = "\n".join(payload["styleGuide"])
        self.assertIn("Always translate source material into English", style_guide)
        self.assertIn("must be written in English", style_guide)

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

    def test_response_from_payload_truncates_overlong_bullet_fields(self) -> None:
        response = response_from_payload(
            {
                "headline": "H" * 120,
                "sections": [
                    {
                        "title": "Top updates",
                        "bullets": [
                            {
                                "title": "T" * 140,
                                "description": "D" * 260,
                                "text": "T" * 140 + ": " + "D" * 260,
                                "citations": ["item-1"],
                            }
                        ],
                    }
                ],
            },
            provider={"type": "copilot-cli", "validated": True},
        )

        bullet = response.sections[0]["bullets"][0]
        self.assertLessEqual(len(response.headline), MAX_SUMMARY_HEADLINE_LENGTH)
        self.assertLessEqual(len(bullet["title"]), MAX_SUMMARY_TITLE_LENGTH)
        self.assertLessEqual(len(bullet["description"]), MAX_SUMMARY_DESCRIPTION_LENGTH)

    @patch("wazzup.ai.subprocess.run")
    @patch("wazzup.ai.shutil.which", return_value="/usr/bin/copilot")
    def test_copilot_cli_uses_default_model_and_writer_agent(self, _which, run_mock) -> None:  # type: ignore[no-untyped-def]
        previous_model = os.environ.get("COPILOT_MODEL")
        previous_agent = os.environ.get("COPILOT_AGENT")
        previous_token = os.environ.get("COPILOT_GITHUB_TOKEN")
        os.environ.pop("COPILOT_MODEL", None)
        os.environ.pop("COPILOT_AGENT", None)
        os.environ["COPILOT_GITHUB_TOKEN"] = "test-token"

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
            prompt = command[command.index("-p") + 1]
            self.assertIn("Merge input items into one bullet", prompt)
            self.assertNotIn("Create one bullet for each input item", prompt)
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
            if previous_token is None:
                os.environ.pop("COPILOT_GITHUB_TOKEN", None)
            else:
                os.environ["COPILOT_GITHUB_TOKEN"] = previous_token

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

    @patch("wazzup.ai.subprocess.run")
    @patch("wazzup.ai.shutil.which", return_value="/usr/bin/copilot")
    def test_copilot_summary_retries_then_fails_on_runtime_failure(self, _which, run_mock) -> None:  # type: ignore[no-untyped-def]
        previous_token = os.environ.get("COPILOT_GITHUB_TOKEN")
        os.environ["COPILOT_GITHUB_TOKEN"] = "test-token"
        source = load_sources("config/sources.yml")[0]
        item = parse_feed(source, Path("tests/fixtures/microsoft-security-blog.xml").read_bytes())[0]
        scored = score_items([item], [source], load_app_config("config/interests.yml"), datetime(2026, 5, 6, tzinfo=UTC))
        run_mock.return_value = Mock(returncode=1, stdout="failed", stderr="upstream error")
        try:
            with self.assertRaisesRegex(RuntimeError, f"after {COPILOT_CLI_MAX_ATTEMPTS} attempts"):
                CopilotCliSummaryProvider().generate_structured_summary(
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

        self.assertEqual(COPILOT_CLI_MAX_ATTEMPTS, run_mock.call_count)


class AiCurationProviderTests(unittest.TestCase):
    def test_curation_provider_defaults_to_fake(self) -> None:
        previous_provider = os.environ.get("AI_PROVIDER")
        os.environ.pop("AI_PROVIDER", None)
        try:
            provider = curation_provider_from_env(load_app_config("config/interests.yml"))
            self.assertEqual("fake", provider.name)
        finally:
            if previous_provider is not None:
                os.environ["AI_PROVIDER"] = previous_provider

    def test_fake_curation_provider_returns_top_max_items(self) -> None:
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

        response = FakeCurationProvider().curate_items(
            CurationRequest(
                kind="hourly",
                window_start="2026-05-06T20:00:00Z",
                window_end="2026-05-06T21:00:00Z",
                generated_at="2026-05-06T21:00:00Z",
                timezone="Europe/Amsterdam",
                items=scored,
                max_items=5,
            )
        )

        self.assertEqual(5, len(response.selected_ids))
        self.assertEqual([s.item.id for s in scored[:5]], response.selected_ids)
        self.assertEqual("fake", response.provider["type"])

    def test_fake_curation_provider_returns_all_when_fewer_than_max(self) -> None:
        source = load_sources("config/sources.yml")[0]
        item = parse_feed(source, Path("tests/fixtures/microsoft-security-blog.xml").read_bytes())[0]
        scored = score_items([item], [source], load_app_config("config/interests.yml"), datetime(2026, 5, 6, tzinfo=UTC))

        response = FakeCurationProvider().curate_items(
            CurationRequest(
                kind="hourly",
                window_start="2026-05-06T20:00:00Z",
                window_end="2026-05-06T21:00:00Z",
                generated_at="2026-05-06T21:00:00Z",
                timezone="Europe/Amsterdam",
                items=scored,
                max_items=12,
            )
        )

        self.assertEqual(len(scored), len(response.selected_ids))

    def test_curation_payload_includes_max_items_and_guide(self) -> None:
        source = load_sources("config/sources.yml")[0]
        item = parse_feed(source, Path("tests/fixtures/microsoft-security-blog.xml").read_bytes())[0]
        scored = score_items([item], [source], load_app_config("config/interests.yml"), datetime(2026, 5, 6, tzinfo=UTC))

        payload = build_curation_payload(
            CurationRequest(
                kind="hourly",
                window_start="2026-05-06T20:00:00Z",
                window_end="2026-05-06T21:00:00Z",
                generated_at="2026-05-06T21:00:00Z",
                timezone="Europe/Amsterdam",
                items=scored,
                max_items=8,
            )
        )

        self.assertEqual(8, payload["maxItems"])
        self.assertIn("selectedIds", payload["outputContract"])
        guide = "\n".join(payload["curationGuide"])
        self.assertIn("8 items", guide)
        self.assertIn("diversity", guide)
        self.assertIn("fresh", guide.lower())

    def test_curation_payload_includes_scored_items(self) -> None:
        source = load_sources("config/sources.yml")[0]
        item = parse_feed(source, Path("tests/fixtures/microsoft-security-blog.xml").read_bytes())[0]
        scored = score_items([item], [source], load_app_config("config/interests.yml"), datetime(2026, 5, 6, tzinfo=UTC))

        payload = build_curation_payload(
            CurationRequest(
                kind="hourly",
                window_start="2026-05-06T20:00:00Z",
                window_end="2026-05-06T21:00:00Z",
                generated_at="2026-05-06T21:00:00Z",
                timezone="Europe/Amsterdam",
                items=scored,
                max_items=12,
            )
        )

        self.assertEqual(len(scored), len(payload["items"]))
        self.assertEqual(scored[0].item.id, payload["items"][0]["id"])

    @patch("wazzup.ai.subprocess.run")
    @patch("wazzup.ai.shutil.which", return_value="/usr/bin/copilot")
    def test_copilot_cli_curation_uses_curator_agent(self, _which, run_mock) -> None:  # type: ignore[no-untyped-def]
        previous_agent = os.environ.get("COPILOT_CURATOR_AGENT")
        previous_token = os.environ.get("COPILOT_GITHUB_TOKEN")
        os.environ.pop("COPILOT_CURATOR_AGENT", None)
        os.environ["COPILOT_GITHUB_TOKEN"] = "test-token"

        source = load_sources("config/sources.yml")[0]
        item = parse_feed(source, Path("tests/fixtures/microsoft-security-blog.xml").read_bytes())[0]
        scored = score_items([item], [source], load_app_config("config/interests.yml"), datetime(2026, 5, 6, tzinfo=UTC))

        def fake_run(command, capture_output, cwd, env, text):  # type: ignore[no-untyped-def]
            del capture_output, text
            selected_id = scored[0].item.id
            Path(env["WAZZUP_COPILOT_OUTPUT_PATH"]).write_text(
                f'{{"selectedIds":["{selected_id}"]}}',
                encoding="utf-8",
            )
            self.assertEqual(Path.cwd(), Path(cwd))
            self.assertIn("--agent", command)
            self.assertEqual(DEFAULT_COPILOT_CURATOR_AGENT, command[command.index("--agent") + 1])
            self.assertIn("--model", command)
            self.assertEqual(DEFAULT_COPILOT_MODEL, command[command.index("--model") + 1])
            prompt = command[command.index("-p") + 1]
            self.assertIn("curating items", prompt)
            return Mock(returncode=0, stdout="", stderr="")

        run_mock.side_effect = fake_run
        try:
            response = CopilotCliCurationProvider().curate_items(
                CurationRequest(
                    kind="hourly",
                    window_start="2026-05-06T20:00:00Z",
                    window_end="2026-05-06T21:00:00Z",
                    generated_at="2026-05-06T21:00:00Z",
                    timezone="Europe/Amsterdam",
                    items=scored,
                    max_items=12,
                )
            )
        finally:
            if previous_agent is None:
                os.environ.pop("COPILOT_CURATOR_AGENT", None)
            else:
                os.environ["COPILOT_CURATOR_AGENT"] = previous_agent
            if previous_token is None:
                os.environ.pop("COPILOT_GITHUB_TOKEN", None)
            else:
                os.environ["COPILOT_GITHUB_TOKEN"] = previous_token

        self.assertEqual(DEFAULT_COPILOT_CURATOR_AGENT, response.provider["agent"])
        self.assertEqual([scored[0].item.id], response.selected_ids)

    @patch("wazzup.ai.subprocess.run")
    @patch("wazzup.ai.shutil.which", return_value="/usr/bin/copilot")
    def test_copilot_cli_curation_falls_back_on_invalid_response(self, _which, run_mock) -> None:  # type: ignore[no-untyped-def]
        previous_token = os.environ.get("COPILOT_GITHUB_TOKEN")
        os.environ["COPILOT_GITHUB_TOKEN"] = "test-token"
        source = load_sources("config/sources.yml")[0]
        item = parse_feed(source, Path("tests/fixtures/microsoft-security-blog.xml").read_bytes())[0]
        scored = score_items([item], [source], load_app_config("config/interests.yml"), datetime(2026, 5, 6, tzinfo=UTC))

        def fake_run(_command, capture_output, cwd, env, text):  # type: ignore[no-untyped-def]
            del capture_output, text
            Path(env["WAZZUP_COPILOT_OUTPUT_PATH"]).write_text('{"selectedIds": "not-a-list"}', encoding="utf-8")
            self.assertEqual(Path.cwd(), Path(cwd))
            return Mock(returncode=0, stdout="", stderr="")

        run_mock.side_effect = fake_run
        try:
            response = CopilotCliCurationProvider().curate_items(
                CurationRequest(
                    kind="hourly",
                    window_start="2026-05-06T20:00:00Z",
                    window_end="2026-05-06T21:00:00Z",
                    generated_at="2026-05-06T21:00:00Z",
                    timezone="Europe/Amsterdam",
                    items=scored,
                    max_items=12,
                )
            )
        finally:
            if previous_token is None:
                os.environ.pop("COPILOT_GITHUB_TOKEN", None)
            else:
                os.environ["COPILOT_GITHUB_TOKEN"] = previous_token

        self.assertEqual("copilot-cli-fallback", response.provider["type"])
        self.assertIn("fallbackReason", response.provider)
        self.assertTrue(response.selected_ids)

    @patch("wazzup.ai.subprocess.run")
    @patch("wazzup.ai.shutil.which", return_value="/usr/bin/copilot")
    def test_copilot_cli_curation_retries_then_fails_on_runtime_failure(self, _which, run_mock) -> None:  # type: ignore[no-untyped-def]
        previous_token = os.environ.get("COPILOT_GITHUB_TOKEN")
        os.environ["COPILOT_GITHUB_TOKEN"] = "test-token"
        source = load_sources("config/sources.yml")[0]
        item = parse_feed(source, Path("tests/fixtures/microsoft-security-blog.xml").read_bytes())[0]
        scored = score_items([item], [source], load_app_config("config/interests.yml"), datetime(2026, 5, 6, tzinfo=UTC))
        run_mock.return_value = Mock(returncode=1, stdout="failed", stderr="upstream error")
        try:
            with self.assertRaisesRegex(RuntimeError, f"after {COPILOT_CLI_MAX_ATTEMPTS} attempts"):
                CopilotCliCurationProvider().curate_items(
                    CurationRequest(
                        kind="hourly",
                        window_start="2026-05-06T20:00:00Z",
                        window_end="2026-05-06T21:00:00Z",
                        generated_at="2026-05-06T21:00:00Z",
                        timezone="Europe/Amsterdam",
                        items=scored,
                        max_items=12,
                    )
                )
        finally:
            if previous_token is None:
                os.environ.pop("COPILOT_GITHUB_TOKEN", None)
            else:
                os.environ["COPILOT_GITHUB_TOKEN"] = previous_token

        self.assertEqual(COPILOT_CLI_MAX_ATTEMPTS, run_mock.call_count)


class AiTransparencyReportProviderTests(unittest.TestCase):
    def test_transparency_provider_defaults_to_fake(self) -> None:
        previous_provider = os.environ.get("AI_PROVIDER")
        os.environ.pop("AI_PROVIDER", None)
        try:
            provider = transparency_provider_from_env(load_app_config("config/interests.yml"))
            self.assertEqual("fake", provider.name)
        finally:
            if previous_provider is not None:
                os.environ["AI_PROVIDER"] = previous_provider

    def test_fake_transparency_report_summarizes_run(self) -> None:
        source = load_sources("config/sources.yml")[0]
        item = parse_feed(source, Path("tests/fixtures/microsoft-security-blog.xml").read_bytes())[0]
        scored = score_items([item], [source], load_app_config("config/interests.yml"), datetime(2026, 5, 6, tzinfo=UTC))
        request = TransparencyReportRequest(
            kind="hourly",
            window_start="2026-05-06T20:00:00Z",
            window_end="2026-05-06T21:00:00Z",
            generated_at="2026-05-06T21:00:00Z",
            timezone="Europe/Amsterdam",
            summary_language="en",
            max_items=12,
            statuses=[SourceStatus(source.id, True, "2026-05-06T21:00:00Z", 1, "fixture")],
            ranked_items=scored,
            selected_items=scored,
            curation_provider={"type": "fake", "model": "deterministic-passthrough"},
            summary_provider={"type": "fake", "model": "deterministic-template"},
        )

        response = FakeTransparencyReportProvider().generate_transparency_report(request)

        self.assertEqual("transparency-v1", response.provider["promptVersion"])
        self.assertIn("Generated a hourly briefing", response.summary)
        self.assertIn("Source health", [section["title"] for section in response.sections])
        self.assertIn("Scoring and selection", [section["title"] for section in response.sections])
        self.assertIn("Tuning suggestions", [section["title"] for section in response.sections])

    def test_transparency_payload_includes_source_health_and_providers(self) -> None:
        payload = build_transparency_payload(
            TransparencyReportRequest(
                kind="hourly",
                window_start="2026-05-06T20:00:00Z",
                window_end="2026-05-06T21:00:00Z",
                generated_at="2026-05-06T21:00:00Z",
                timezone="Europe/Amsterdam",
                summary_language="en",
                max_items=12,
                statuses=[SourceStatus("source-a", False, "2026-05-06T21:00:00Z", 0, "failed")],
                ranked_items=[],
                selected_items=[],
                curation_provider={"type": "fake"},
                summary_provider={"type": "copilot-cli", "agent": "wazzup-writer"},
            )
        )

        self.assertEqual(1, payload["sourceHealth"]["failedSourceCount"])
        self.assertEqual("source-a", payload["sourceHealth"]["failedSources"][0]["sourceId"])
        self.assertEqual("wazzup-writer", payload["providers"]["summary"]["agent"])
        self.assertIn("scoringModel", payload)
        self.assertEqual(0, payload["selection"]["missedItemCount"])
        self.assertIn("sections", payload["outputContract"])

    def test_transparency_payload_includes_missed_items_and_tuning_recommendations(self) -> None:
        source = load_sources("config/sources.yml")[0]
        item = parse_feed(source, Path("tests/fixtures/microsoft-security-blog.xml").read_bytes())[0]
        selected = replace(item, id="selected", title="Security AI selected", canonical_url="https://example.com/selected")
        missed = replace(item, id="missed", title="General market update", canonical_url="https://example.com/missed", summary="A market update.")
        scored = score_items([selected, missed], [source], load_app_config("config/interests.yml"), datetime(2026, 5, 6, tzinfo=UTC))
        selected_scored = [item for item in scored if item.item.id == "selected"]

        payload = build_transparency_payload(
            TransparencyReportRequest(
                kind="hourly",
                window_start="2026-05-06T20:00:00Z",
                window_end="2026-05-06T21:00:00Z",
                generated_at="2026-05-06T21:00:00Z",
                timezone="Europe/Amsterdam",
                summary_language="en",
                max_items=1,
                statuses=[],
                ranked_items=scored,
                selected_items=selected_scored,
                curation_provider={"type": "fake"},
                summary_provider={"type": "fake"},
            )
        )

        self.assertEqual(1, payload["selection"]["selectedItemCount"])
        self.assertEqual(len(scored) - 1, payload["selection"]["missedItemCount"])
        self.assertTrue(payload["selection"]["missedItems"])
        self.assertIn("recommendation", payload["selection"]["missedItems"][0])

    def test_transparency_response_from_payload_validates_shape(self) -> None:
        response = transparency_response_from_payload(
            {
                "title": "Transparency report",
                "summary": "A concise summary.",
                "sections": [{"title": "Inputs", "bullets": ["Used one source."]}],
            },
            provider={"type": "fake", "validated": True},
        )

        self.assertEqual("Transparency report", response.title)
        self.assertEqual(["Used one source."], response.sections[0]["bullets"])

    @patch("wazzup.ai.subprocess.run")
    @patch("wazzup.ai.shutil.which", return_value="/usr/bin/copilot")
    def test_copilot_cli_transparency_uses_reporter_agent(self, _which, run_mock) -> None:  # type: ignore[no-untyped-def]
        previous_agent = os.environ.get("COPILOT_TRANSPARENCY_AGENT")
        previous_token = os.environ.get("COPILOT_GITHUB_TOKEN")
        os.environ.pop("COPILOT_TRANSPARENCY_AGENT", None)
        os.environ["COPILOT_GITHUB_TOKEN"] = "test-token"

        def fake_run(command, capture_output, cwd, env, text):  # type: ignore[no-untyped-def]
            del capture_output, text
            Path(env["WAZZUP_COPILOT_OUTPUT_PATH"]).write_text(
                '{"title":"Transparency report","summary":"A concise summary.","sections":[{"title":"Inputs","bullets":["Used one source."]}]}',
                encoding="utf-8",
            )
            self.assertEqual(Path.cwd(), Path(cwd))
            self.assertIn("--agent", command)
            self.assertEqual(DEFAULT_COPILOT_TRANSPARENCY_AGENT, command[command.index("--agent") + 1])
            self.assertIn("--model", command)
            self.assertEqual(DEFAULT_COPILOT_MODEL, command[command.index("--model") + 1])
            prompt = command[command.index("-p") + 1]
            self.assertIn("transparency report", prompt)
            return Mock(returncode=0, stdout="", stderr="")

        run_mock.side_effect = fake_run
        try:
            response = CopilotCliTransparencyReportProvider().generate_transparency_report(
                TransparencyReportRequest(
                    kind="hourly",
                    window_start="2026-05-06T20:00:00Z",
                    window_end="2026-05-06T21:00:00Z",
                    generated_at="2026-05-06T21:00:00Z",
                    timezone="Europe/Amsterdam",
                    summary_language="en",
                    max_items=12,
                    statuses=[],
                    ranked_items=[],
                    selected_items=[],
                    curation_provider={"type": "fake"},
                    summary_provider={"type": "fake"},
                )
            )
        finally:
            if previous_agent is None:
                os.environ.pop("COPILOT_TRANSPARENCY_AGENT", None)
            else:
                os.environ["COPILOT_TRANSPARENCY_AGENT"] = previous_agent
            if previous_token is None:
                os.environ.pop("COPILOT_GITHUB_TOKEN", None)
            else:
                os.environ["COPILOT_GITHUB_TOKEN"] = previous_token

        self.assertEqual(DEFAULT_COPILOT_TRANSPARENCY_AGENT, response.provider["agent"])
        self.assertEqual("Transparency report", response.title)

    @patch("wazzup.ai.subprocess.run")
    @patch("wazzup.ai.shutil.which", return_value="/usr/bin/copilot")
    def test_copilot_cli_transparency_falls_back_on_runtime_failure(self, _which, run_mock) -> None:  # type: ignore[no-untyped-def]
        previous_token = os.environ.get("COPILOT_GITHUB_TOKEN")
        os.environ["COPILOT_GITHUB_TOKEN"] = "test-token"
        run_mock.return_value = Mock(returncode=1, stdout="failed", stderr="upstream error")
        try:
            response = CopilotCliTransparencyReportProvider().generate_transparency_report(
                TransparencyReportRequest(
                    kind="hourly",
                    window_start="2026-05-06T20:00:00Z",
                    window_end="2026-05-06T21:00:00Z",
                    generated_at="2026-05-06T21:00:00Z",
                    timezone="Europe/Amsterdam",
                    summary_language="en",
                    max_items=12,
                    statuses=[],
                    ranked_items=[],
                    selected_items=[],
                    curation_provider={"type": "fake"},
                    summary_provider={"type": "fake"},
                )
            )
        finally:
            if previous_token is None:
                os.environ.pop("COPILOT_GITHUB_TOKEN", None)
            else:
                os.environ["COPILOT_GITHUB_TOKEN"] = previous_token

        self.assertEqual("copilot-cli-fallback", response.provider["type"])
        self.assertEqual("copilot-cli", response.provider["fallbackFrom"])
        self.assertIn("exit code 1", response.provider["fallbackReason"])


if __name__ == "__main__":
    unittest.main()
