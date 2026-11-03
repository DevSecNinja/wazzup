from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass
from functools import cache
from http.client import HTTPException
from pathlib import Path
from typing import Any, Literal
from urllib.request import urlopen

MODEL_POLICY_URL = "https://raw.githubusercontent.com/DevSecNinja/.github/refs/heads/main/copilot-models.json"
POLICY_TIMEOUT_SECONDS = 10
MAX_POLICY_BYTES = 64 * 1024
MAX_POLICY_REVISION = 2**53 - 1
ModelRole = Literal["default", "writer"]


class ModelPolicyError(RuntimeError):
    """A missing or invalid explicit model policy must block Copilot execution."""


@dataclass(frozen=True)
class ModelPolicy:
    revision: int
    default: str
    writer: str


@dataclass(frozen=True)
class ModelSelection:
    role: ModelRole
    model: str
    source: str
    revision: int

    def metadata(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "modelRole": self.role,
            "modelSource": self.source,
            "modelPolicyUrl": MODEL_POLICY_URL,
            "modelPolicyRevision": self.revision,
        }

    def failure_hint(self) -> str:
        return (
            f"Selected role={self.role}, model={self.model}, source={self.source}, policy revision={self.revision}. "
            "Verify this model is available to the CLI's authenticated account; "
            f"review the override or update {MODEL_POLICY_URL}. No alternate model will be tried. "
        )


def report_model_policy(message: str) -> None:
    print(message, file=sys.stderr, flush=True)
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with Path(summary_path).open("a", encoding="utf-8") as summary:
            summary.write(f"- {message}\n")


def validate_model_id(value: Any, source: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,127}", value) or value == "auto":
        raise ModelPolicyError(
            f"{source} must be an explicit model ID (1-128 lowercase letters, digits, dots, underscores or hyphens; "
            "starting with a letter or digit). Blank values, whitespace and auto are not allowed."
        )
    return value


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ModelPolicyError("Policy JSON contains a duplicate key.")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise ModelPolicyError("Policy JSON contains a non-standard numeric constant.")


def parse_model_policy(data: bytes) -> ModelPolicy:
    if len(data) > MAX_POLICY_BYTES:
        raise ModelPolicyError(f"Policy exceeds {MAX_POLICY_BYTES} bytes.")
    try:
        payload = json.loads(data.decode("utf-8"), object_pairs_hook=_unique_object, parse_constant=_reject_json_constant)
    except (ValueError, RecursionError) as exc:
        raise ModelPolicyError("Policy must be valid UTF-8 JSON.") from exc
    if not isinstance(payload, dict):
        raise ModelPolicyError("Policy must be a JSON object.")
    if set(payload) != {"schemaVersion", "revision", "models"}:
        raise ModelPolicyError("Policy must contain exactly schemaVersion, revision and models.")
    if type(payload.get("schemaVersion")) is not int or payload["schemaVersion"] != 1:
        raise ModelPolicyError("Policy schemaVersion must be integer 1.")
    if type(payload.get("revision")) is not int or not 1 <= payload["revision"] <= MAX_POLICY_REVISION:
        raise ModelPolicyError("Policy revision must be a positive safe integer.")
    models = payload.get("models")
    if not isinstance(models, dict) or set(models) != {"default", "writer"}:
        raise ModelPolicyError("Policy models must contain exactly default and writer roles.")
    return ModelPolicy(
        revision=payload["revision"],
        default=validate_model_id(models.get("default"), "Policy models.default"),
        writer=validate_model_id(models.get("writer"), "Policy models.writer"),
    )


@cache
def load_model_policy() -> ModelPolicy:
    # One immutable snapshot per process; never reuse an on-disk or stale fallback.
    try:
        with urlopen(MODEL_POLICY_URL, timeout=POLICY_TIMEOUT_SECONDS) as response:
            return parse_model_policy(response.read(MAX_POLICY_BYTES + 1))
    except (OSError, HTTPException, ModelPolicyError) as exc:
        message = (
            f"Copilot model policy failed: {MODEL_POLICY_URL}: {exc}. "
            "Publish or repair the reviewed shared policy and check network access. No model/provider fallback was used."
        )
        report_model_policy(message)
        raise ModelPolicyError(message) from exc


def resolve_model(role: ModelRole, model: str | None = None) -> ModelSelection:
    policy = load_model_policy()
    source = f"policy.models.{role}"
    value = policy.writer if role == "writer" else policy.default
    if model is not None:
        source, value = "constructor", model
    elif role == "writer" and "COPILOT_WRITER_MODEL" in os.environ:
        source, value = "COPILOT_WRITER_MODEL", os.environ["COPILOT_WRITER_MODEL"]
    elif "COPILOT_MODEL" in os.environ:
        source, value = "COPILOT_MODEL", os.environ["COPILOT_MODEL"]
    try:
        selected = ModelSelection(role, validate_model_id(value, source), source, policy.revision)
    except ModelPolicyError as exc:
        report_model_policy(
            f"Copilot model selection failed: role={role}, source={source}, policy revision={policy.revision}, "
            f"policy={MODEL_POLICY_URL}. {exc} No model/provider fallback was used."
        )
        raise
    report_model_policy(
        f"Copilot model selection: role={selected.role}, model={selected.model}, source={selected.source}, "
        f"policy revision={selected.revision}, policy={MODEL_POLICY_URL}."
    )
    return selected
