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
class CurationRequest:
    kind: BriefingKind
    window_start: str
    window_end: str
    generated_at: str
    timezone: str
    items: list[ScoredItem]
    max_items: int


@dataclass(frozen=True)
class CurationResponse:
    selected_ids: list[str]
    provider: dict[str, Any]


class AiCurationProvider(Protocol):
    name: str

    def curate_items(self, request: CurationRequest) -> CurationResponse:
        """Select and order items for the briefing."""


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
DEFAULT_COPILOT_CURATOR_AGENT = "wazzup-curator"
MAX_SUMMARY_HEADLINE_LENGTH = 80
MAX_SUMMARY_TITLE_LENGTH = 96
MAX_SUMMARY_DESCRIPTION_LENGTH = 220


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


class FakeCurationProvider:
    name = "fake"

    def curate_items(self, request: CurationRequest) -> CurationResponse:
        selected = request.items[: request.max_items]
        return CurationResponse(
            selected_ids=[scored.item.id for scored in selected],
            provider={
                "type": self.name,
                "model": "deterministic-passthrough",
                "promptVersion": "curation-v1",
                "validated": True,
            },
        )


class CopilotCliCurationProvider:
    name = "copilot-cli"

    def __init__(
        self,
        copilot_command: str = "copilot",
        model: str | None = None,
        agent: str | None = None,
    ) -> None:
        self.copilot_command = copilot_command
        self.model = model if model is not None else os.environ.get("COPILOT_MODEL", DEFAULT_COPILOT_MODEL)
        self.agent = agent if agent is not None else os.environ.get("COPILOT_CURATOR_AGENT", DEFAULT_COPILOT_CURATOR_AGENT)

    def curate_items(self, request: CurationRequest) -> CurationResponse:
        if not shutil.which(self.copilot_command):
            raise RuntimeError("Copilot CLI is not installed; install @github/copilot or use AI_PROVIDER=fake")
        if os.environ.get("GITHUB_ACTIONS") == "true" and not os.environ.get("COPILOT_GITHUB_TOKEN"):
            raise RuntimeError(
                "AI_PROVIDER=copilot-cli requires COPILOT_GITHUB_TOKEN in GitHub Actions. "
                "Configure COPILOT_REQUESTS_PAT or COPILOT_GITHUB_TOKEN as a repository secret, "
                "or use AI_PROVIDER=fake."
            )
        curation_payload = build_curation_payload(request)
        temp_root = Path(".state")
        temp_root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="wazzup-curator-", dir=temp_root) as tmp_dir:
            tmp_path = Path(tmp_dir)
            input_path = tmp_path / "curation-input.json"
            output_path = tmp_path / "curation-output.json"
            input_path.write_text(json.dumps(curation_payload, indent=2), encoding="utf-8")
            run_env = os.environ.copy()
            run_env["WAZZUP_COPILOT_INPUT_PATH"] = str(input_path)
            run_env["WAZZUP_COPILOT_OUTPUT_PATH"] = str(output_path)
            # This prompt mirrors the wazzup-curator agent file guidance.
            # Both must be kept in sync when the curation contract changes.
            prompt = (
                "You are curating items for the Wazzup news briefing. "
                f"Read {input_path}, select at most {request.max_items} of the most relevant and diverse items, "
                f"and write strict JSON to {output_path}. "
                "The JSON object must contain selectedIds: an ordered list of ContentItem.id values. "
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
                    f"Copilot CLI curation failed with exit code {result.returncode}. "
                    "Verify COPILOT_GITHUB_TOKEN has Copilot Requests permission, "
                    "or use AI_PROVIDER=fake."
                    f"{detail_text}"
                )
            if not output_path.exists():
                raise RuntimeError("Copilot CLI did not write curation-output.json")
            payload = json.loads(output_path.read_text(encoding="utf-8"))
        selected_ids = payload.get("selectedIds")
        if not isinstance(selected_ids, list) or not all(isinstance(item_id, str) for item_id in selected_ids):
            fallback = FakeCurationProvider()
            fallback_response = fallback.curate_items(request)
            return CurationResponse(
                selected_ids=fallback_response.selected_ids,
                provider={
                    **fallback_response.provider,
                    "type": "copilot-cli-fallback",
                    "fallbackFrom": self.name,
                    "fallbackReason": "Curator returned invalid selectedIds",
                    "validated": True,
                },
            )
        provider = {
            "type": self.name,
            "model": payload.get("model", self.model or "copilot-cli"),
            "agent": self.agent or None,
            "promptVersion": "curation-v1",
            "validated": True,
        }
        return CurationResponse(selected_ids=selected_ids, provider=provider)


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


def _truncate_summary_text(value: Any, max_length: int) -> str:
    text = str(value or "").strip()
    if len(text) <= max_length:
        return text
    clipped = text[: max_length + 1]
    sentence_end = max(clipped.rfind(". "), clipped.rfind("! "), clipped.rfind("? "))
    if sentence_end >= max_length // 2:
        return clipped[: sentence_end + 1].strip()
    return f"{text[: max_length - 1].rstrip()}…"


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


def build_curation_payload(request: CurationRequest) -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "task": "Select and order the most relevant news items for inclusion in the briefing.",
        "kind": request.kind,
        "windowStart": request.window_start,
        "windowEnd": request.window_end,
        "generatedAt": request.generated_at,
        "timezone": request.timezone,
        "maxItems": request.max_items,
        "items": [scored.to_dict() for scored in request.items],
        "outputContract": {
            "selectedIds": ["ContentItem.id (ordered list of selected item IDs)"],
        },
        "curationGuide": [
            f"Select at most {request.max_items} items.",
            "Prefer items that are fresh and directly relevant to the configured interests.",
            "Prefer diversity: avoid selecting multiple items about the exact same story unless they add distinct perspectives.",
            "Use the item score and matched interests as primary signals, but apply editorial judgment for newsworthiness.",
            "When items have relatedItems, select the parent item ID only.",
            "Never mention scoring internals such as source weight, score, recency bonus, or duplicate group IDs.",
        ],
    }


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
            "headline": f"string, max {MAX_SUMMARY_HEADLINE_LENGTH} characters",
            "sections": [
                {
                    "title": "string",
                    "bullets": [
                        {
                            "title": f"short item title, max {MAX_SUMMARY_TITLE_LENGTH} characters",
                            "description": f"one complete source-grounded sentence, max {MAX_SUMMARY_DESCRIPTION_LENGTH} characters",
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
            f"For each bullet, provide title and description separately. Keep titles under {MAX_SUMMARY_TITLE_LENGTH} characters and descriptions under {MAX_SUMMARY_DESCRIPTION_LENGTH} characters.",
            "Write each description as one concise complete sentence; avoid trailing clauses that need frontend truncation.",
            "Avoid repeating the same title in the description.",
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
    normalized_sections: list[dict[str, Any]] = []
    for section in sections:
        if not isinstance(section, dict) or not isinstance(section.get("title"), str):
            raise ValueError("AI response section missing title")
        bullets = section.get("bullets")
        if not isinstance(bullets, list):
            raise ValueError("AI response section missing bullets")
        normalized_bullets: list[dict[str, Any]] = []
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
            normalized_bullets.append(
                {
                    **bullet,
                    "title": _truncate_summary_text(bullet.get("title", ""), MAX_SUMMARY_TITLE_LENGTH),
                    "description": _truncate_summary_text(bullet.get("description", ""), MAX_SUMMARY_DESCRIPTION_LENGTH),
                    "text": _truncate_summary_text(bullet.get("text", ""), MAX_SUMMARY_TITLE_LENGTH + MAX_SUMMARY_DESCRIPTION_LENGTH + 2),
                }
            )
        normalized_sections.append({**section, "bullets": normalized_bullets})
    return SummaryResponse(
        headline=_truncate_summary_text(headline, MAX_SUMMARY_HEADLINE_LENGTH),
        sections=normalized_sections,
        provider=provider,
    )


def provider_from_env(app_config: AppConfig) -> AiSummaryProvider:
    del app_config
    provider = os.environ.get("AI_PROVIDER", "fake").strip().lower()
    if provider == "fake":
        return FakeSummaryProvider()
    if provider == "copilot-cli":
        return CopilotCliSummaryProvider()
    raise ValueError(f"Unsupported AI_PROVIDER: {provider}")


def curation_provider_from_env(app_config: AppConfig) -> AiCurationProvider:
    del app_config
    provider = os.environ.get("AI_PROVIDER", "fake").strip().lower()
    if provider == "fake":
        return FakeCurationProvider()
    if provider == "copilot-cli":
        return CopilotCliCurationProvider()
    raise ValueError(f"Unsupported AI_PROVIDER: {provider}")
