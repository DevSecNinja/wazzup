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


DEFAULT_COPILOT_MODEL = "claude-sonnet-4.6"
DEFAULT_COPILOT_AGENT = "wazzup-writer"


class FakeSummaryProvider:
    name = "fake"

    def generate_structured_summary(self, request: SummaryRequest) -> SummaryResponse:
        items = request.items
        if not items:
            headline = "No notable updates found"
            bullets: list[dict[str, Any]] = [
                {
                    "title": "No notable updates",
                    "description": "No notable updates were found in the selected window.",
                    "text": "No notable updates were found in the selected window.",
                    "citations": [],
                }
            ]
        else:
            headline = f"{len(items)} notable update{'s' if len(items) != 1 else ''} for {request.kind} briefing"
            bullets = [
                {
                    "title": scored.item.title,
                    "description": _fake_description(scored, request.kind),
                    "text": _fake_bullet(scored, request.kind),
                    "citations": source_item_ids(scored),
                }
                for scored in items
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

    def __init__(
        self,
        copilot_command: str = "copilot",
        model: str | None = None,
        agent: str | None = None,
    ) -> None:
        self.copilot_command = copilot_command
        self.model = model if model is not None else os.environ.get("COPILOT_MODEL", DEFAULT_COPILOT_MODEL)
        self.agent = agent if agent is not None else os.environ.get("COPILOT_AGENT", DEFAULT_COPILOT_AGENT)

    def generate_structured_summary(self, request: SummaryRequest) -> SummaryResponse:
        if not shutil.which(self.copilot_command):
            raise RuntimeError("Copilot CLI is not installed; install @github/copilot or use AI_PROVIDER=fake")
        if os.environ.get("GITHUB_ACTIONS") == "true" and not os.environ.get("COPILOT_GITHUB_TOKEN"):
            raise RuntimeError(
                "AI_PROVIDER=copilot-cli requires COPILOT_GITHUB_TOKEN in GitHub Actions. "
                "Configure COPILOT_REQUESTS_PAT or COPILOT_GITHUB_TOKEN as a repository secret, "
                "or use AI_PROVIDER=fake."
            )
        prompt_payload = build_prompt_payload(request)
        temp_root = Path(".state")
        temp_root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="wazzup-copilot-", dir=temp_root) as tmp_dir:
            tmp_path = Path(tmp_dir)
            input_path = tmp_path / "prompt.json"
            output_path = tmp_path / "summary.json"
            input_path.write_text(json.dumps(prompt_payload, indent=2), encoding="utf-8")
            run_env = os.environ.copy()
            run_env["WAZZUP_COPILOT_INPUT_PATH"] = str(input_path)
            run_env["WAZZUP_COPILOT_OUTPUT_PATH"] = str(output_path)
            prompt = (
                "You are generating the Wazzup news briefing. "
                f"Read {input_path}, summarize in English, and write strict JSON to {output_path}. "
                "The JSON object must contain headline and sections. "
                "Every bullet must include citations containing source item IDs from the input. "
                "Merge input items into one bullet when they describe the same story, campaign, incident, vendor, "
                "product, or affected organization; cite every source item ID that supports the merged bullet. "
                "Otherwise preserve the input order so newly published hourly articles stay at the top. "
                "Do not include Markdown fences or commentary."
            )
            command = [
                self.copilot_command,
                "-p",
                prompt,
            ]
            if self.model:
                command.extend(["--model", self.model])
            if self.agent:
                command.extend(["--agent", self.agent])
            command.extend(
                [
                    "--allow-tool=shell(cat:*)",
                    "--allow-tool=write",
                    "--no-ask-user",
                ]
            )
            result = subprocess.run(command, capture_output=True, cwd=Path.cwd(), env=run_env, text=True)
            if result.returncode != 0:
                details = []
                if result.stdout.strip():
                    details.append(f"stdout: {result.stdout.strip()}")
                if result.stderr.strip():
                    details.append(f"stderr: {result.stderr.strip()}")
                detail_text = "\n" + "\n".join(details) if details else ""
                raise RuntimeError(
                    f"Copilot CLI failed with exit code {result.returncode}. "
                    "Verify COPILOT_GITHUB_TOKEN has Copilot Requests permission, "
                    "or use AI_PROVIDER=fake."
                    f"{detail_text}"
                )
            if not output_path.exists():
                raise RuntimeError("Copilot CLI did not write summary.json")
            payload = json.loads(output_path.read_text(encoding="utf-8"))
        provider = {
            "type": self.name,
            "model": payload.get("model", self.model or "copilot-cli"),
            "agent": self.agent or None,
            "promptVersion": "summary-v1",
            "validated": True,
        }
        try:
            return response_from_payload(payload, provider=provider)
        except ValueError as exc:
            fallback = FakeSummaryProvider().generate_structured_summary(request)
            return SummaryResponse(
                headline=fallback.headline,
                sections=fallback.sections,
                provider={
                    **fallback.provider,
                    "type": "copilot-cli-fallback",
                    "fallbackFrom": self.name,
                    "fallbackReason": str(exc),
                    "validated": True,
                },
            )


def _fake_bullet(scored: ScoredItem, kind: BriefingKind = "hourly") -> str:
    return f"{scored.item.title}: {_fake_description(scored, kind)}"


def source_item_ids(scored: ScoredItem) -> list[str]:
    return [scored.item.id, *(item.id for item in scored.item.related_items)]


def _fake_description(scored: ScoredItem, kind: BriefingKind = "hourly") -> str:
    summary = scored.item.summary.strip()
    if summary:
        text = summary.rstrip(".")
        if len(text) > 220:
            text = text[:219].rstrip() + "…"
    else:
        text = "This update is worth scanning based on your configured interests."
    if scored.matched_interests:
        interests = ", ".join(scored.matched_interests[:3]).replace("-", " ")
        if kind == "hourly":
            return f"{text}. Relevant to your {interests} interests."
        return f"{text}. It matches your {interests} interests."
    return f"{text}."


def build_prompt_payload(request: SummaryRequest) -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "task": "Generate a concise English news briefing with citations, tailored to the configured user interests.",
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
                            "title": "short item title",
                            "description": "1-2 sentence source-grounded description",
                            "text": "string",
                            "citations": ["ContentItem.id"],
                        }
                    ],
                }
            ],
        },
        "styleGuide": [
            "Write for a single technical reader, not as marketing copy.",
            "Always translate source material into English; all headlines, section titles, bullet titles, descriptions, and text fields must be written in English.",
            "Make the top-level headline a topic-only news headline under 80 characters; do not prefix it with the briefing kind, date, or labels like 'Morning Briefing', 'Evening Briefing', 'Daily Briefing', or 'Yesterday'.",
            "Describe relevance directly without labels like 'Why it matters'.",
            "For each bullet, provide title and description separately. Avoid repeating the same title in the description.",
            "Never mention scoring internals such as source weight, score, recency bonus, or duplicate group IDs.",
            "Keep bullets concise and source-grounded.",
            "Preserve the input item order so newly published hourly articles stay at the top, except when merging related items into one synthesized bullet.",
            "Merge closely related input items into one synthesized bullet when they describe the same story, campaign, incident, vendor, product, or affected organization; cite every source item ID that supports the merged bullet.",
            "When an input item includes relatedItems, treat the item and relatedItems as one correlated story and cite every source item ID that supports the bullet.",
        ],
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
            if not isinstance(bullet, dict):
                raise ValueError("AI response bullet missing text")
            if not isinstance(bullet.get("text"), str):
                title = bullet.get("title")
                description = bullet.get("description")
                if isinstance(title, str) and isinstance(description, str) and description.strip():
                    bullet["text"] = f"{title.strip()}: {description.strip()}" if title.strip() else description.strip()
                elif isinstance(description, str) and description.strip():
                    bullet["text"] = description.strip()
                else:
                    raise ValueError("AI response bullet missing text")
            if not isinstance(bullet.get("description"), str):
                bullet["description"] = bullet["text"]
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
