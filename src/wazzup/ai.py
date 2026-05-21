from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from .models import AppConfig, BriefingKind, ScoredItem, SourceStatus


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


@dataclass(frozen=True)
class TransparencyReportRequest:
    kind: BriefingKind
    window_start: str
    window_end: str
    generated_at: str
    timezone: str
    summary_language: str
    max_items: int
    statuses: list[SourceStatus]
    ranked_items: list[ScoredItem]
    selected_items: list[ScoredItem]
    curation_provider: dict[str, Any]
    summary_provider: dict[str, Any]


@dataclass(frozen=True)
class TransparencyReportResponse:
    title: str
    summary: str
    sections: list[dict[str, Any]]
    provider: dict[str, Any]


class AiTransparencyReportProvider(Protocol):
    name: str

    def generate_transparency_report(self, request: TransparencyReportRequest) -> TransparencyReportResponse:
        """Generate a structured transparency report for the pipeline run."""


DEFAULT_COPILOT_MODEL = "claude-sonnet-4.6"
DEFAULT_COPILOT_AGENT = "wazzup-writer"
DEFAULT_COPILOT_CURATOR_AGENT = "wazzup-curator"
DEFAULT_COPILOT_TRANSPARENCY_AGENT = "wazzup-transparency-reporter"
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


class FakeTransparencyReportProvider:
    name = "fake"

    def generate_transparency_report(self, request: TransparencyReportRequest) -> TransparencyReportResponse:
        failed_statuses = [status for status in request.statuses if not status.ok]
        selected_ids = [scored.item.id for scored in request.selected_items]
        selected_id_set = set(selected_ids)
        missed_items = [(index + 1, scored) for index, scored in enumerate(request.ranked_items) if scored.item.id not in selected_id_set]
        source_count = len(request.statuses)
        article_count = sum(status.item_count for status in request.statuses)
        selected_count = len(request.selected_items)
        summary = (
            f"Generated a {request.kind} briefing from {source_count} enabled sources. "
            f"Fetched {article_count} raw feed items, selected {selected_count} item"
            f"{'s' if selected_count != 1 else ''}, and recorded {len(failed_statuses)} source failure"
            f"{'s' if len(failed_statuses) != 1 else ''}."
        )
        return TransparencyReportResponse(
            title=f"Transparency report for {request.kind} briefing",
            summary=summary,
            sections=[
                {
                    "title": "Run inputs",
                    "bullets": [
                        f"Window: {request.window_start} to {request.window_end} ({request.timezone}).",
                        f"Configured maximum AI items: {request.max_items}.",
                        f"Enabled sources checked: {source_count}.",
                    ],
                },
                {
                    "title": "Source health",
                    "bullets": [
                        f"Successful sources: {source_count - len(failed_statuses)}.",
                        f"Failed sources: {len(failed_statuses)}.",
                        f"Raw feed items fetched before filtering and deduplication: {article_count}.",
                    ],
                },
                {
                    "title": "Scoring and selection",
                    "bullets": [
                        f"Ranked candidate items in the content window: {len(request.ranked_items)}.",
                        f"Selected item IDs: {', '.join(selected_ids) if selected_ids else 'none'}.",
                        "Scores combine source weight, matched interest keywords, freshness, and configured demotions.",
                    ],
                },
                {
                    "title": "Missed items",
                    "bullets": transparency_missed_item_bullets(missed_items, selected_count),
                },
                {
                    "title": "Tuning suggestions",
                    "bullets": transparency_tuning_bullets([scored for _, scored in missed_items]),
                },
                {
                    "title": "AI providers",
                    "bullets": [
                        f"Curator provider: {_provider_label(request.curation_provider)}.",
                        f"Writer provider: {_provider_label(request.summary_provider)}.",
                    ],
                },
            ],
            provider={
                "type": self.name,
                "model": "deterministic-template",
                "agent": None,
                "promptVersion": "transparency-v1",
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
            try:
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
            except (RuntimeError, json.JSONDecodeError) as exc:
                fallback = FakeCurationProvider().curate_items(request)
                return CurationResponse(
                    selected_ids=fallback.selected_ids,
                    provider={
                        **fallback.provider,
                        "type": "copilot-cli-fallback",
                        "fallbackFrom": self.name,
                        "fallbackReason": str(exc),
                        "validated": True,
                    },
                )
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
            try:
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
                return response_from_payload(payload, provider=provider)
            except (RuntimeError, ValueError, json.JSONDecodeError) as exc:
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


class CopilotCliTransparencyReportProvider:
    name = "copilot-cli"

    def __init__(
        self,
        copilot_command: str = "copilot",
        model: str | None = None,
        agent: str | None = None,
    ) -> None:
        self.copilot_command = copilot_command
        self.model = model if model is not None else os.environ.get("COPILOT_MODEL", DEFAULT_COPILOT_MODEL)
        self.agent = agent if agent is not None else os.environ.get("COPILOT_TRANSPARENCY_AGENT", DEFAULT_COPILOT_TRANSPARENCY_AGENT)

    def generate_transparency_report(self, request: TransparencyReportRequest) -> TransparencyReportResponse:
        if not shutil.which(self.copilot_command):
            raise RuntimeError("Copilot CLI is not installed; install @github/copilot or use AI_PROVIDER=fake")
        if os.environ.get("GITHUB_ACTIONS") == "true" and not os.environ.get("COPILOT_GITHUB_TOKEN"):
            raise RuntimeError(
                "AI_PROVIDER=copilot-cli requires COPILOT_GITHUB_TOKEN in GitHub Actions. "
                "Configure COPILOT_REQUESTS_PAT or COPILOT_GITHUB_TOKEN as a repository secret, "
                "or use AI_PROVIDER=fake."
            )
        report_payload = build_transparency_payload(request)
        temp_root = Path(".state")
        temp_root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="wazzup-transparency-", dir=temp_root) as tmp_dir:
            tmp_path = Path(tmp_dir)
            input_path = tmp_path / "transparency-input.json"
            output_path = tmp_path / "transparency-output.json"
            input_path.write_text(json.dumps(report_payload, indent=2), encoding="utf-8")
            run_env = os.environ.copy()
            run_env["WAZZUP_COPILOT_INPUT_PATH"] = str(input_path)
            run_env["WAZZUP_COPILOT_OUTPUT_PATH"] = str(output_path)
            prompt = (
                "You are writing the Wazzup transparency report. "
                f"Read {input_path}, explain how the news was scored, what made the cut, what missed the cut, "
                "why missed items did not appear, and what tuning changes could surface similar news later, "
                f"and write strict JSON to {output_path}. "
                "The JSON object must contain title, summary, and sections. "
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
            try:
                result = subprocess.run(command, capture_output=True, cwd=Path.cwd(), env=run_env, text=True)
                if result.returncode != 0:
                    details = []
                    if result.stdout.strip():
                        details.append(f"stdout: {result.stdout.strip()}")
                    if result.stderr.strip():
                        details.append(f"stderr: {result.stderr.strip()}")
                    detail_text = "\n" + "\n".join(details) if details else ""
                    raise RuntimeError(
                        f"Copilot CLI transparency report failed with exit code {result.returncode}. "
                        "Verify COPILOT_GITHUB_TOKEN has Copilot Requests permission, "
                        "or use AI_PROVIDER=fake."
                        f"{detail_text}"
                    )
                if not output_path.exists():
                    raise RuntimeError("Copilot CLI did not write transparency-output.json")
                payload = json.loads(output_path.read_text(encoding="utf-8"))
                provider = {
                    "type": self.name,
                    "model": payload.get("model", self.model or "copilot-cli"),
                    "agent": self.agent or None,
                    "promptVersion": "transparency-v1",
                    "validated": True,
                }
                return transparency_response_from_payload(payload, provider=provider)
            except (RuntimeError, ValueError, json.JSONDecodeError) as exc:
                fallback = FakeTransparencyReportProvider().generate_transparency_report(request)
                return TransparencyReportResponse(
                    title=fallback.title,
                    summary=fallback.summary,
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


def build_transparency_payload(request: TransparencyReportRequest) -> dict[str, Any]:
    failed_sources = [status.to_dict() for status in request.statuses if not status.ok]
    selected_ids = {scored.item.id for scored in request.selected_items}
    ranked_items = [transparency_item_payload(scored, rank=index + 1, selected=scored.item.id in selected_ids) for index, scored in enumerate(request.ranked_items)]
    selected_items = [item for item in ranked_items if item["selected"]]
    missed_items = [item for item in ranked_items if not item["selected"]]
    return {
        "schemaVersion": 1,
        "task": "Generate a concise transparency report explaining scoring, selected news, missed news, and tuning options for one Wazzup pipeline run.",
        "kind": request.kind,
        "windowStart": request.window_start,
        "windowEnd": request.window_end,
        "generatedAt": request.generated_at,
        "timezone": request.timezone,
        "summaryLanguage": request.summary_language,
        "maxItems": request.max_items,
        "sourceHealth": {
            "sourceCount": len(request.statuses),
            "successfulSourceCount": len([status for status in request.statuses if status.ok]),
            "failedSourceCount": len(failed_sources),
            "rawItemCount": sum(status.item_count for status in request.statuses),
            "failedSources": failed_sources,
        },
        "selection": {
            "rankedCandidateCount": len(request.ranked_items),
            "selectedItemCount": len(request.selected_items),
            "selectedItemIds": [scored.item.id for scored in request.selected_items],
            "selectedItems": selected_items,
            "missedItems": missed_items[:20],
            "missedItemCount": len(missed_items),
        },
        "scoringModel": {
            "base": "Every item starts at 10 times its source weight.",
            "interests": "Each matching positive interest keyword adds up to three keyword matches times 4 times the interest weight.",
            "demotions": "Negative interest weights subtract from the score when their keywords match.",
            "freshness": "Freshness adds a recency bonus and a freshness bucket reason.",
            "prioritySources": "Microsoft Security Threat Intelligence receives an additional priority-source bonus.",
        },
        "providers": {
            "curation": request.curation_provider,
            "summary": request.summary_provider,
        },
        "outputContract": {
            "title": "string",
            "summary": "string",
            "sections": [{"title": "string", "bullets": ["string"]}],
        },
        "styleGuide": [
            "Write in English for a technical reader who wants to understand why the briefing looked the way it did.",
            "Stay factual and source-grounded in the run metadata; do not invent external context.",
            "Explain how the news was scored, which selected items won, and which non-selected items missed the cut.",
            "For missed items, explain whether they were below the max-items cutoff, lacked matching interest keywords, had a lower source weight, were older, or were removed by curation.",
            "Highlight practical tuning options such as adding interest keywords, raising an interest weight, raising a source weight, increasing max items, or lowering an unwanted interest weight.",
            "Explain source failures and AI fallback providers plainly when present because they can hide otherwise relevant news.",
            "Do not disclose secrets, tokens, environment internals, or private runner details.",
            "Do not repeat every scoring reason unless it materially explains selection or exclusion.",
        ],
    }


def transparency_item_payload(scored: ScoredItem, rank: int, selected: bool) -> dict[str, Any]:
    return {
        "rank": rank,
        "selected": selected,
        "id": scored.item.id,
        "title": scored.item.title,
        "sourceId": scored.item.source_id,
        "sourceName": scored.item.source_name,
        "sourceTag": scored.item.source_tag,
        "publishedAt": scored.item.published_at,
        "score": round(scored.score, 3),
        "scoreReasons": scored.score_reasons,
        "matchedInterests": scored.matched_interests,
        "freshnessBucket": scored.freshness_bucket,
        "recommendation": transparency_item_recommendation(scored, selected),
    }


def transparency_item_recommendation(scored: ScoredItem, selected: bool) -> str:
    if selected:
        return "This item made the briefing; similar future items can be boosted by keeping its matched interests and source weight high."
    lowered_reasons = " ".join(scored.score_reasons).lower()
    if not scored.matched_interests:
        return "Add keywords from this story to an existing interest, create a new interest, or raise this source weight if similar stories should appear."
    if "demotes" in lowered_reasons:
        return "Review negative-interest keywords or weights if this type of story should not be demoted."
    if "source weight" in lowered_reasons:
        return "Raise this source weight or the matched interest weight if this source should compete more strongly."
    if scored.freshness_bucket in {"recent", "older"}:
        return "Increase max items or rely on broader briefing windows if older but relevant stories should still appear."
    return "Raise the matched interest weight, add more specific keywords, or increase max items if similar stories should make the cut."


def transparency_missed_item_bullets(missed_items: list[tuple[int, ScoredItem]], selected_count: int) -> list[str]:
    del selected_count
    if not missed_items:
        return ["No ranked candidate items missed the cut."]
    bullets = []
    for rank, scored in missed_items[:5]:
        bullets.append(
            f"Rank {rank}: {scored.item.title} from {scored.item.source_tag} scored {scored.score:.1f}; "
            f"reasons: {', '.join(scored.score_reasons[:3])}. {transparency_item_recommendation(scored, selected=False)}"
        )
    if len(missed_items) > 5:
        bullets.append(f"{len(missed_items) - 5} additional ranked candidates were omitted from this compact report.")
    return bullets


def transparency_tuning_bullets(missed_items: list[ScoredItem]) -> list[str]:
    if not missed_items:
        return ["No tuning needed for missed ranked candidates in this run."]
    no_interest_count = len([scored for scored in missed_items if not scored.matched_interests])
    older_count = len([scored for scored in missed_items if scored.freshness_bucket in {"recent", "older"}])
    bullets = [
        "Raise an interest weight when the right stories match but still rank below the cutoff.",
        "Add more specific keywords when relevant stories show no matched interests.",
        "Raise a source weight when a trusted publication should compete more strongly across topics.",
    ]
    if no_interest_count:
        bullets.append(f"{no_interest_count} missed item(s) had no positive interest match; keyword tuning would help most there.")
    if older_count:
        bullets.append(f"{older_count} missed item(s) were recent or older; increasing max items may surface more background stories.")
    return bullets


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


def transparency_response_from_payload(payload: dict[str, Any], provider: dict[str, Any]) -> TransparencyReportResponse:
    title = payload.get("title")
    summary = payload.get("summary")
    sections = payload.get("sections")
    if not isinstance(title, str) or not title.strip():
        raise ValueError("transparency report missing title")
    if not isinstance(summary, str) or not summary.strip():
        raise ValueError("transparency report missing summary")
    if not isinstance(sections, list) or not sections:
        raise ValueError("transparency report missing sections")
    normalized_sections: list[dict[str, Any]] = []
    for section in sections:
        if not isinstance(section, dict) or not isinstance(section.get("title"), str):
            raise ValueError("transparency report section missing title")
        bullets = section.get("bullets")
        if not isinstance(bullets, list):
            raise ValueError("transparency report section missing bullets")
        normalized_sections.append(
            {
                "title": section["title"].strip(),
                "bullets": [str(bullet).strip() for bullet in bullets if str(bullet).strip()],
            }
        )
    return TransparencyReportResponse(title=title.strip(), summary=summary.strip(), sections=normalized_sections, provider=provider)


def _provider_label(provider: dict[str, Any]) -> str:
    provider_type = str(provider.get("type", "unknown"))
    model = provider.get("model")
    agent = provider.get("agent")
    details = [provider_type]
    if isinstance(model, str) and model:
        details.append(model)
    if isinstance(agent, str) and agent:
        details.append(agent)
    return " / ".join(details)


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


def transparency_provider_from_env(app_config: AppConfig) -> AiTransparencyReportProvider:
    del app_config
    provider = os.environ.get("AI_PROVIDER", "fake").strip().lower()
    if provider == "fake":
        return FakeTransparencyReportProvider()
    if provider == "copilot-cli":
        return CopilotCliTransparencyReportProvider()
    raise ValueError(f"Unsupported AI_PROVIDER: {provider}")
