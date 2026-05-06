from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from wazzup.ai import CopilotCliSummaryProvider, SummaryRequest, provider_from_env
from wazzup.config import load_app_config


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
