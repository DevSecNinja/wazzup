from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from dataclasses import FrozenInstanceError
from http.client import IncompleteRead
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from wazzup.ai import (
    CopilotCliCurationProvider,
    CopilotCliSummaryProvider,
    CopilotCliTransparencyReportProvider,
    curation_provider_from_env,
    provider_from_env,
    transparency_provider_from_env,
)
from wazzup.config import load_app_config
from wazzup.model_policy import (
    MAX_POLICY_BYTES,
    MAX_POLICY_REVISION,
    MODEL_POLICY_URL,
    POLICY_TIMEOUT_SECONDS,
    ModelPolicyError,
    load_model_policy,
    parse_model_policy,
    resolve_model,
)
from wazzup.pipeline import generate

POLICY_BYTES = Path("tests/fixtures/copilot-models.json").read_bytes()
PROVIDERS = (CopilotCliCurationProvider, CopilotCliSummaryProvider, CopilotCliTransparencyReportProvider)


class ModelPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.process_environment = os.environ.copy()
        environment = patch.dict(os.environ, {}, clear=True)
        environment.start()
        self.addCleanup(environment.stop)
        stderr = patch("sys.stderr", new_callable=io.StringIO)
        self.stderr = stderr.start()
        self.addCleanup(stderr.stop)
        fetch = patch("wazzup.model_policy.urlopen")
        self.fetch = fetch.start()
        self.addCleanup(fetch.stop)
        self.response = self.fetch.return_value.__enter__.return_value
        self.response.read.return_value = POLICY_BYTES
        load_model_policy.cache_clear()
        self.addCleanup(load_model_policy.cache_clear)

    def test_import_does_not_fetch_policy(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "from unittest.mock import patch\n"
                "with patch('urllib.request.urlopen', side_effect=AssertionError('network on import')) as fetch:\n"
                "    import wazzup.ai\n"
                "    fetch.assert_not_called()\n",
            ],
            env={**self.process_environment, "PYTHONPATH": "src"},
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stderr)

    def test_policy_is_one_immutable_snapshot_for_all_providers(self) -> None:
        policy = json.loads(POLICY_BYTES)
        policy["revision"] = 2
        policy["models"] = {"default": "later-general", "writer": "later-writer"}
        self.response.read.side_effect = [POLICY_BYTES, json.dumps(policy).encode()]
        providers = [provider() for provider in PROVIDERS]
        self.assertEqual(["claude-sonnet-5", "claude-opus-5.5", "claude-sonnet-5"], [p.model for p in providers])
        self.assertEqual([1, 1, 1], [p.model_selection.revision for p in providers])
        self.fetch.assert_called_once_with(MODEL_POLICY_URL, timeout=POLICY_TIMEOUT_SECONDS)
        self.response.read.assert_called_once_with(MAX_POLICY_BYTES + 1)
        with self.assertRaises(FrozenInstanceError):
            load_model_policy().revision = 2

    def test_model_override_precedence_and_sources(self) -> None:
        for provider_type in PROVIDERS:
            is_writer = provider_type is CopilotCliSummaryProvider
            cases = [
                ({}, None, "claude-opus-5.5" if is_writer else "claude-sonnet-5", "policy.models.writer" if is_writer else "policy.models.default"),
                ({"COPILOT_MODEL": "shared-override"}, None, "shared-override", "COPILOT_MODEL"),
                (
                    {"COPILOT_MODEL": "shared-override", "COPILOT_WRITER_MODEL": "writer-override"},
                    None,
                    "writer-override" if is_writer else "shared-override",
                    "COPILOT_WRITER_MODEL" if is_writer else "COPILOT_MODEL",
                ),
                ({"COPILOT_MODEL": "shared-override", "COPILOT_WRITER_MODEL": "writer-override"}, "constructor-model", "constructor-model", "constructor"),
                ({"COPILOT_MODEL": "", "COPILOT_WRITER_MODEL": "auto"}, "constructor-model", "constructor-model", "constructor"),
            ]
            for environment, override, expected_model, source in cases:
                with self.subTest(provider=provider_type.__name__, environment=environment, override=override):
                    with patch.dict(os.environ, environment, clear=True):
                        provider = provider_type(model=override)
                    self.assertEqual(expected_model, provider.model)
                    self.assertEqual(source, provider.model_selection.source)
                    self.assertEqual("writer" if is_writer else "default", provider.model_selection.role)

    def test_invalid_selected_overrides_block_before_cli(self) -> None:
        for invalid in ("", " ", "auto", "AUTO", " model", "model ", "model\n", "--model", "a;echo", "a/b", "m" * 129):
            for provider_type in PROVIDERS:
                environments = [{"COPILOT_MODEL": invalid}]
                if provider_type is CopilotCliSummaryProvider:
                    environments.append({"COPILOT_MODEL": "valid-general", "COPILOT_WRITER_MODEL": invalid})
                for environment in environments:
                    with self.subTest(provider=provider_type.__name__, environment=environment):
                        with patch.dict(os.environ, environment, clear=True), patch("wazzup.ai.subprocess.run") as run:
                            with self.assertRaises(ModelPolicyError):
                                provider_type()
                            run.assert_not_called()
                with self.subTest(provider=provider_type.__name__, constructor=invalid):
                    with patch("wazzup.ai.subprocess.run") as run, self.assertRaises(ModelPolicyError):
                        provider_type(model=invalid)
                    run.assert_not_called()

    def test_policy_schema_and_model_ids_are_strict(self) -> None:
        invalid_payloads: list[object] = [
            None, [], "", {}, {"schemaVersion": 1},
            {**json.loads(POLICY_BYTES), "unexpected": True},
            {**json.loads(POLICY_BYTES), "models": {**json.loads(POLICY_BYTES)["models"], "unexpected": "model"}},
        ]
        for field in ("schemaVersion", "revision", "models"):
            payload = json.loads(POLICY_BYTES)
            del payload[field]
            invalid_payloads.append(payload)
        for field, values in (
            ("schemaVersion", (None, True, 1.0, "1", 0, 2)),
            ("revision", (None, True, 1.0, "1", 0, -1, MAX_POLICY_REVISION + 1)),
            ("models", (None, [], "models")),
        ):
            for value in values:
                invalid_payloads.append({**json.loads(POLICY_BYTES), field: value})
        for role in ("default", "writer"):
            payload = json.loads(POLICY_BYTES)
            del payload["models"][role]
            invalid_payloads.append(payload)
            for value in (None, False, 5, {}, [], "", " ", "auto", "AUTO", "m\n", "a b", "a/b", "--model", "$(echo)", "m" * 129):
                payload = json.loads(POLICY_BYTES)
                payload["models"][role] = value
                invalid_payloads.append(payload)
        for payload in invalid_payloads:
            with self.subTest(payload=payload), self.assertRaises(ModelPolicyError):
                parse_model_policy(json.dumps(payload).encode())

    def test_malformed_and_oversized_policy_data_is_rejected(self) -> None:
        for data in (
            b"",
            b"<html>not found</html>",
            b'{"schemaVersion":1',
            b"\xff",
            POLICY_BYTES + b"{}",
            b'{"schemaVersion":1,"schemaVersion":1}',
            b'{"schemaVersion":NaN}',
            b'{"schemaVersion":Infinity}',
            b'{"revision":' + b"9" * 5000 + b"}",
            b"[" * 2000 + b"]" * 2000,
            b" " * (MAX_POLICY_BYTES + 1),
        ):
            with self.subTest(data=data[:80]), self.assertRaises(ModelPolicyError):
                parse_model_policy(data)

    def test_revision_and_model_id_boundaries(self) -> None:
        payload = json.loads(POLICY_BYTES)
        payload["revision"] = MAX_POLICY_REVISION
        payload["models"] = {"default": "a", "writer": "m" * 128}
        policy = parse_model_policy(json.dumps(payload).encode())
        self.assertEqual(MAX_POLICY_REVISION, policy.revision)
        self.assertEqual("a", policy.default)
        self.assertEqual("m" * 128, policy.writer)

    def test_missing_or_invalid_policy_cannot_be_bypassed_by_overrides(self) -> None:
        for provider_type in PROVIDERS:
            for body in (b"{}", b'{"schemaVersion":2}', b"not-json"):
                with self.subTest(provider=provider_type.__name__, body=body):
                    load_model_policy.cache_clear()
                    self.response.read.return_value = body
                    with patch.dict(os.environ, {"COPILOT_MODEL": "explicit-general", "COPILOT_WRITER_MODEL": "explicit-writer"}):
                        with patch("wazzup.ai.subprocess.run") as run, self.assertRaises(ModelPolicyError):
                            provider_type(model="constructor-model")
                        run.assert_not_called()

    def test_http_timeout_dns_and_interrupted_read_fail_without_retry(self) -> None:
        errors = (
            HTTPError(MODEL_POLICY_URL, 404, "Not Found", None, None),
            HTTPError(MODEL_POLICY_URL, 503, "Service Unavailable", None, None),
            URLError("DNS failure"),
            TimeoutError("timed out"),
            IncompleteRead(b"partial"),
        )
        for error in errors:
            with self.subTest(error=error):
                load_model_policy.cache_clear()
                self.fetch.reset_mock()
                self.fetch.side_effect = error
                with patch("wazzup.ai.subprocess.run") as run, self.assertRaisesRegex(ModelPolicyError, "No model/provider fallback"):
                    CopilotCliSummaryProvider()
                self.fetch.assert_called_once()
                run.assert_not_called()

    def test_new_process_snapshot_does_not_fall_back_to_old_policy(self) -> None:
        self.assertEqual(1, load_model_policy().revision)
        load_model_policy.cache_clear()
        self.fetch.side_effect = TimeoutError("timed out")
        with self.assertRaises(ModelPolicyError):
            load_model_policy()

    def test_fake_factories_do_not_resolve_policy_or_invoke_cli(self) -> None:
        self.fetch.side_effect = AssertionError("fake mode fetched policy")
        config = load_app_config("config/interests.yml")
        with patch.dict(os.environ, {"AI_PROVIDER": "fake", "COPILOT_MODEL": "auto", "COPILOT_WRITER_MODEL": ""}):
            with patch("wazzup.ai.subprocess.run") as run:
                for factory in (curation_provider_from_env, provider_from_env, transparency_provider_from_env):
                    self.assertEqual("fake", factory(config).name)
                run.assert_not_called()
        self.fetch.assert_not_called()

    def test_selection_is_logged_and_in_summary_before_generation_failure(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            summary_path = Path(directory) / "summary.md"
            with patch.dict(os.environ, {"AI_PROVIDER": "copilot-cli", "GITHUB_STEP_SUMMARY": str(summary_path)}):
                with patch("wazzup.pipeline.collect_items", side_effect=RuntimeError("feed failure")) as collect:
                    with self.assertRaisesRegex(RuntimeError, "feed failure"):
                        generate([])
                collect.assert_called_once()
            summary = summary_path.read_text(encoding="utf-8")
        for text in (
            "role=default, model=claude-sonnet-5, source=policy.models.default",
            "role=writer, model=claude-opus-5.5, source=policy.models.writer",
            "policy revision=1",
            MODEL_POLICY_URL,
        ):
            self.assertIn(text, summary)
            self.assertIn(text, self.stderr.getvalue())
        self.fetch.assert_called_once()

    def test_policy_failure_is_in_workflow_summary_before_any_feed_or_cli_call(self) -> None:
        self.fetch.side_effect = TimeoutError("timed out")
        with tempfile.TemporaryDirectory() as directory:
            summary_path = Path(directory) / "summary.md"
            with patch.dict(os.environ, {"AI_PROVIDER": "copilot-cli", "GITHUB_STEP_SUMMARY": str(summary_path)}):
                with patch("wazzup.pipeline.collect_items") as collect, patch("wazzup.ai.subprocess.run") as run:
                    with self.assertRaises(ModelPolicyError):
                        generate([])
                    collect.assert_not_called()
                    run.assert_not_called()
            self.assertIn("Copilot model policy failed", summary_path.read_text(encoding="utf-8"))

    def test_invalid_writer_override_blocks_before_curator_spends_inference(self) -> None:
        with patch.dict(os.environ, {"AI_PROVIDER": "copilot-cli", "COPILOT_WRITER_MODEL": ""}):
            with patch("wazzup.pipeline.collect_items") as collect, patch("wazzup.ai.subprocess.run") as run:
                with self.assertRaises(ModelPolicyError):
                    generate([])
                collect.assert_not_called()
                run.assert_not_called()

    def test_selection_metadata_is_policy_provenance(self) -> None:
        selection = resolve_model("writer", "explicit-writer")
        self.assertEqual(
            {
                "model": "explicit-writer",
                "modelRole": "writer",
                "modelSource": "constructor",
                "modelPolicyUrl": MODEL_POLICY_URL,
                "modelPolicyRevision": 1,
            },
            selection.metadata(),
        )

    def test_selection_does_not_pollute_stdout(self) -> None:
        with patch("sys.stdout", new_callable=io.StringIO) as stdout:
            resolve_model("writer")
        self.assertEqual("", stdout.getvalue())

    def test_unavailable_cli_model_keeps_all_selections_in_failure_summary(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            summary_path = Path(directory) / "summary.md"
            environment = {"AI_PROVIDER": "copilot-cli", "GITHUB_STEP_SUMMARY": str(summary_path)}
            with patch.dict(os.environ, environment):
                with patch("wazzup.pipeline.collect_items", return_value=([], [], [])):
                    with patch("wazzup.ai.shutil.which", return_value="copilot"), patch("wazzup.ai.subprocess.run") as run:
                        run.return_value.returncode = 1
                        run.return_value.stdout = ""
                        run.return_value.stderr = 'Model "claude-sonnet-5" from --model flag is not available.'
                        with self.assertRaisesRegex(RuntimeError, "is not available"):
                            generate(["--force-briefing", "hourly"])
                        run.assert_called_once()
            summary = summary_path.read_text(encoding="utf-8")
        self.assertIn("role=default, model=claude-sonnet-5", summary)
        self.assertIn("role=writer, model=claude-opus-5.5", summary)
        self.assertIn("policy revision=1", summary)


if __name__ == "__main__":
    unittest.main()
