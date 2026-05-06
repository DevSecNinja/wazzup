from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .models import AppConfig, BriefingKind, ScoredItem


@dataclass(frozen=True)
class SummaryRequest:
    kind: BriefingKind
    window_start: str
    window_end: str
    generated_at: str
    timezone: str
    summary_language: str
    items: list[ScoredItem]


@dataclass(frozen=True)
class SummaryResponse:
    headline: str
    sections: list[dict[str, Any]]
    provider: dict[str, Any]


class AiSummaryProvider(Protocol):
    name: str

    def generate_structured_summary(self, request: SummaryRequest) -> SummaryResponse:
        """Generate a structured summary for selected items."""


class FakeSummaryProvider:
    name = "fake"

    def generate_structured_summary(self, request: SummaryRequest) -> SummaryResponse:
        items = request.items[:8]
        if not items:
            headline = "No notable updates found"
            bullets: list[dict[str, Any]] = [
                {
                    "text": "No notable updates were found in the selected window.",
                    "citations": [],
                }
            ]
        else:
            headline = f"{len(items)} notable update{'s' if len(items) != 1 else ''} for {request.kind} briefing"
            bullets = [
                {
                    "text": _fake_bullet(scored),
                    "citations": [scored.item.id],
                }
                for scored in items[:6]
            ]
        return SummaryResponse(
            headline=headline,
            sections=[
                {
                    "title": "Top updates",
                    "bullets": bullets,
                }
            ],
            provider={
                "type": self.name,
                "model": "deterministic-template",
                "promptVersion": "summary-v1",
                "validated": True,
            },
        )


class CopilotCliSummaryProvider:
    name = "copilot-cli"

    def __init__(self, copilot_command: str = "copilot") -> None:
        self.copilot_command = copilot_command

    def generate_structured_summary(self, request: SummaryRequest) -> SummaryResponse:
        if not shutil.which(self.copilot_command):
            raise RuntimeError("Copilot CLI is not installed; install @github/copilot or use AI_PROVIDER=fake")
        prompt_payload = build_prompt_payload(request)
        with tempfile.TemporaryDirectory(prefix="wazzup-copilot-") as tmp_dir:
            tmp_path = Path(tmp_dir)
            input_path = tmp_path / "prompt.json"
            output_path = tmp_path / "summary.json"
            input_path.write_text(json.dumps(prompt_payload, indent=2), encoding="utf-8")
            prompt = (
                "You are generating the Wazzup news briefing. "
                f"Read {input_path}, summarize in English, and write strict JSON to {output_path}. "
                "The JSON object must contain headline and sections. "
                "Every bullet must include citations containing source item IDs from the input. "
                "Do not include Markdown fences or commentary."
            )
            command = [
                self.copilot_command,
                "-p",
                prompt,
                "--allow-tool=shell(cat:*)",
                "--allow-tool=write",
                "--no-ask-user",
            ]
            subprocess.run(command, check=True, cwd=tmp_dir, env=os.environ.copy())
            if not output_path.exists():
                raise RuntimeError("Copilot CLI did not write summary.json")
            payload = json.loads(output_path.read_text(encoding="utf-8"))
        return response_from_payload(
            payload,
            provider={
                "type": self.name,
                "model": payload.get("model", "copilot-cli"),
                "promptVersion": "summary-v1",
                "validated": True,
            },
        )


def _fake_bullet(scored: ScoredItem) -> str:
    reason = scored.score_reasons[0] if scored.score_reasons else "ranked as notable"
    return f"{scored.item.title} — {reason}."


def build_prompt_payload(request: SummaryRequest) -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "task": "Generate a concise English news briefing with citations.",
        "kind": request.kind,
        "windowStart": request.window_start,
        "windowEnd": request.window_end,
        "generatedAt": request.generated_at,
        "timezone": request.timezone,
        "summaryLanguage": request.summary_language,
        "items": [scored.to_dict() for scored in request.items],
        "outputContract": {
            "headline": "string",
            "sections": [
                {
                    "title": "string",
                    "bullets": [
                        {
                            "text": "string",
                            "citations": ["ContentItem.id"],
                        }
                    ],
                }
            ],
        },
    }


def response_from_payload(payload: dict[str, Any], provider: dict[str, Any]) -> SummaryResponse:
    headline = payload.get("headline")
    sections = payload.get("sections")
    if not isinstance(headline, str) or not headline.strip():
        raise ValueError("AI response missing headline")
    if not isinstance(sections, list) or not sections:
        raise ValueError("AI response missing sections")
    for section in sections:
        if not isinstance(section, dict) or not isinstance(section.get("title"), str):
            raise ValueError("AI response section missing title")
        bullets = section.get("bullets")
        if not isinstance(bullets, list):
            raise ValueError("AI response section missing bullets")
        for bullet in bullets:
            if not isinstance(bullet, dict) or not isinstance(bullet.get("text"), str):
                raise ValueError("AI response bullet missing text")
            citations = bullet.get("citations")
            if not isinstance(citations, list) or not all(isinstance(citation, str) for citation in citations):
                raise ValueError("AI response bullet missing citations")
    return SummaryResponse(headline=headline.strip(), sections=sections, provider=provider)


def provider_from_env(app_config: AppConfig) -> AiSummaryProvider:
    del app_config
    provider = os.environ.get("AI_PROVIDER", "fake").strip().lower()
    if provider == "fake":
        return FakeSummaryProvider()
    if provider == "copilot-cli":
        return CopilotCliSummaryProvider()
    raise ValueError(f"Unsupported AI_PROVIDER: {provider}")
