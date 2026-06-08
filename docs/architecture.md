# Architecture

## Implemented architecture summary

Wazzup currently uses a GitHub-native static architecture:

- GitHub Actions runs the backend pipeline every two hours during the local active window.
- The Python pipeline fetches sources, normalizes content, deduplicates and ranks items, calls an AI summary provider, and writes versioned JSON outputs.
- GitHub Pages hosts both the minimal PWA and the generated JSON data.
- A dedicated GitHub Release asset stores the rolling generated-data state between scheduled runs.
- Optional delivery adapters are not implemented yet; services such as Home Assistant, ntfy, email, Teams, or Slack remain future work.
- The core domain contracts remain independent from GitHub Actions and GitHub Pages so they can later power a REST API, agent tool, or MCP server.
- Commits must follow Conventional Commits so release-please can be added without history cleanup.

Implementation deviations from the original target are intentional for the current lightweight architecture:

- Backend runtime is Python 3.11+ under [../src/wazzup](../src/wazzup).
- Frontend is vanilla HTML/CSS/JavaScript under [../public](../public); there is no frontend build step yet.
- JSON is the canonical generated state format consumed directly by the PWA.
- Pages state restoration supports tokenless public release-asset downloads because reusable workflow string inputs cannot reliably inject `GH_TOKEN` for nested shell commands.
- The News workflow requests Copilot CLI by default, keeps curator and transparency on Claude Sonnet 4.6 (`claude-sonnet-4.6`), pins the briefing writer to Claude Opus 4.8 (`claude-opus-4.8`) unless `COPILOT_WRITER_MODEL` overrides it, and falls back to the deterministic fake provider if Copilot token secrets are missing.

## Context diagram

```mermaid
flowchart LR
    User[User] --> PWA[PWA on GitHub Pages]
    PWA --> StaticData[Static JSON data]
    Actions[GitHub Actions scheduler] --> Pipeline[News pipeline]
    Pipeline --> Feeds[RSS / Atom now; JSON Feed / Podcast RSS later]
    Pipeline --> AI[AI summary provider]
    Pipeline --> StaticData
    Pipeline --> Delivery[Optional delivery adapters]
    Delivery --> HA[Home Assistant]
    Delivery --> Notify[ntfy / email / chat]
```

## Runtime components

| Component            | Responsibility                                                                                     | Current implementation                                                                                        |
| -------------------- | -------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------- |
| Source configuration | Defines feeds, short source tags, categories, weights, headers, and interest hints.                | [../config/sources.yml](../config/sources.yml) and [../config/interests.yml](../config/interests.yml).        |
| Fetcher              | Retrieves RSS and Atom XML feeds.                                                                  | `urllib.request` based Python fetcher in [../src/wazzup/feeds.py](../src/wazzup/feeds.py).                    |
| Normalizer           | Converts source entries into `ContentItem` records.                                                | Pure functions with fixtures.                                                                                 |
| Deduplicator         | Groups duplicate or near-duplicate articles.                                                       | Canonical URL + raw ref/GUID + normalized title/day transitive groups.                                        |
| Ranker               | Scores items against interests, source quality, recency, and coverage.                             | Deterministic scoring plus optional AI reranking later.                                                       |
| Curator              | Selects and orders the most relevant items from the ranked list for the briefing.                  | AI curation provider abstraction; `wazzup-curator` agent for Copilot CLI, deterministic passthrough for fake. |
| Summarizer           | Generates article and briefing summaries from the curated item selection.                          | AI summary provider abstraction with prompt versioning; `wazzup-writer` agent for Copilot CLI.                |
| Transparency reporter | Explains run inputs, source health, selection, and AI providers for auditability.                  | AI report provider abstraction; `wazzup-transparency-reporter` agent for Copilot CLI, deterministic fake report for tests. |
| Publisher            | Writes canonical static JSON, source health, transparency reports, `latest`, and `manifest` files. | [../src/wazzup/publisher.py](../src/wazzup/publisher.py).                                                     |
| State store          | Persists generated data across scheduled runs without commits.                                     | `news-state` GitHub Release asset `wazzup-state.zip`.                                                         |
| Delivery adapters    | Pushes selected briefings to external channels.                                                    | Not implemented yet.                                                                                          |
| Frontend             | Displays latest briefing and source health.                                                        | Static vanilla PWA in [../public](../public).                                                                 |

## Pipeline flow

```mermaid
sequenceDiagram
    participant Cron as GitHub Actions cron
    participant CLI as Pipeline CLI
    participant Feeds as Feeds
    participant Curator as AI curator (wazzup-curator)
    participant Writer as AI writer (wazzup-writer)
    participant Reporter as AI transparency reporter
    participant Pages as GitHub Pages data
    participant User as User channels

    Cron->>CLI: run every two local active hours
    CLI->>Pages: restore previous release-backed data window
    CLI->>Feeds: fetch configured sources
    Feeds-->>CLI: feed entries
    CLI->>CLI: normalize, dedupe, score
    CLI->>Curator: select most relevant items
    Curator-->>CLI: ordered selected item IDs
    CLI->>Writer: summarize curated articles
    Writer-->>CLI: structured summary data
    CLI->>Reporter: write transparency report
    Reporter-->>CLI: structured report data
    CLI->>CLI: validate contracts and item caps
    CLI->>Pages: persist JSON state to release asset
    Pages->>Pages: reusable Pages workflow restores state and deploys public artifact
    CLI->>User: optional delivery webhook
```

## Repository structure

```text
config/
  sources.yml
  interests.yml
docs/
src/
  wazzup/
    ai.py               # provider interface, fake provider, Copilot CLI provider
    build_info.py       # generated build metadata for footer/SW cache version
    config.py           # YAML config loading/validation
    feeds.py            # RSS/Atom fetch, parse, canonicalization, dedupe
    models.py           # dataclass domain contracts
    pipeline.py         # CLI orchestration
    publisher.py        # JSON canonical output
    scoring.py          # deterministic ranking
    validate_data.py    # generated-data validation
public/
  index.html
  styles.css
  app.js
  sw.js
  manifest.webmanifest
tests/
  fixtures/
.github/workflows/
  ci.yml
  lint.yml
  news.yml
  pages.yml
```

Future work can split the Python modules into deeper packages if complexity grows, but the current flat package keeps the app easy to inspect.

## Domain contracts

### `ContentItem`

Represents one normalized source item.

Required fields:

- `schemaVersion`
- `id`
- `sourceId`
- `sourceName`
- `sourceTag`
- `sourceType`
- `title`
- `url`
- `canonicalUrl`
- `publishedAt`
- `discoveredAt`
- `authors`
- `tags`
- `language`
- `summary`
- `contentHash`
- `rawRef`

### `ScoredItem`

Extends `ContentItem` with ranking metadata.

Required fields:

- `score`
- `scoreReasons`
- `matchedInterests`
- `duplicateGroupId`
- `freshnessBucket`

### `Briefing`

Represents a generated user-facing summary.

Required fields:

- `schemaVersion`
- `id`
- `kind`: `hourly`, `morning`, `evening`, or `manual`
- `windowStart`
- `windowEnd`
- `generatedAt`
- `timezone`
- `headline`
- `sections`: each bullet keeps a backward-compatible `text` field and may include structured `title` and `description` fields for the PWA card layout.
- `sourceItemIds`: includes selected item IDs plus any correlated `relatedItems` source IDs so a story can be tracked across sources.
- `citations`: includes article source, source tag, category tags, published timestamp, and temperature metadata. Multiple citations may point to correlated sources for one briefing bullet.
- `model`
- `promptVersion`
- `costEstimate`

### `DeliveryTarget`

Represents an optional outgoing notification channel.

Required fields:

- `id`
- `kind`: `home-assistant-webhook`, `ntfy`, `email`, `slack`, `teams`, or `custom-webhook`
- `enabled`
- `briefingKinds`
- `secretRef`

## Static data layout

```text
public/data/
  latest.json                 # canonical
  manifest.json               # canonical
  sources/status.json         # canonical
  transparency/latest.md      # latest human-readable report copied to the GitHub Release asset
  transparency/YYYY/MM/DD/hourly-HH.json
  transparency/YYYY/MM/DD/hourly-HH.md
  articles/YYYY/MM/DD.json    # full ranked candidate set for the day
  briefings/YYYY/MM/DD/hourly-HH.json
  briefings/YYYY/MM/DD/morning.json
  briefings/YYYY/MM/DD/evening.json
  archives/YYYY-MM.json
public/build-info.json        # generated deployment metadata for footer/SW version
```

The scheduled workflow must not commit generated article or briefing JSON to `main`. It restores the previous `public/data` window from a dedicated `news-state` GitHub Release asset, generates new data, enforces the configured retention window (currently 3 days), and uploads the updated release asset. The separate Pages workflow then uses the reusable Pages deployment from `DevSecNinja/.github` to restore that same release asset and deploy the static files to GitHub Pages.

JSON is the canonical persisted state format. The PWA consumes it directly without a YAML parser dependency, and the no-build static app, Home Assistant-style consumers, and validation tooling all read the same files.

The daily `articles/YYYY/MM/DD.json` file stores the full ranked candidate set for the day, not just the curated briefing items. This lets a later scheduled run reprioritize against the whole day rather than only the small selected subset.

Release-state restore behavior:

- In the `News` workflow, [../Taskfile.yml](../Taskfile.yml) uses `GH_TOKEN` and `gh release download` to restore prior state, then `gh release upload --clobber` or `gh release create` to persist updated state.
- In `Pages`, the reusable workflow cannot receive a working token through a string input, so `task pages:build` restores `wazzup-state.zip` through the public release download URL when no `GH_TOKEN`/`GITHUB_TOKEN` is available.
- `pages:build` sets `STATE_REQUIRED=true`; if retained state cannot be restored, deployment fails explicitly instead of uploading an empty app data directory.
- The current state release is intentionally one mutable operational release, not one release per hour. Hourly releases would create thousands of releases per year and duplicate the generated-data churn problem in a different GitHub surface. A better future archive is one immutable daily or monthly recap release whose body contains a human-readable digest and links to archived assets.

Rejected alternatives:

- Committing generated data to `main`: too much history churn for hourly outputs.
- Committing generated data to a `news` branch: avoids polluting `main`, but still creates thousands of commits per year and adds branch-management complexity.
- Pages artifact only: simple, but does not provide a durable state input for the next scheduled run.

## Deduplication strategy

Deduplication is a first-class pipeline step because duplicate RSS entries were a primary frustration with previous feed tooling.

The current pipeline deduplicates before scoring using transitive duplicate groups:

1. Canonical URL key after removing common tracking parameters and fragments.
2. Feed GUID/raw reference key when available.
3. Normalized title plus publication day key for syndicated or mirrored stories with different URLs.

When multiple items land in the same group, the winner is selected by source priority, summary richness, and publication timestamp. The Microsoft Threat Intelligence topic feed currently has elevated source priority over the broader Microsoft Security Blog feed. Future improvements can add semantic title similarity, source-specific canonicalization rules, and duplicate-group metadata in the published output.

### `latest.json`

Small pointer file consumed by the frontend and Home Assistant.

Example fields:

- `latestHourlyBriefingUrl`
- `latestMorningBriefingUrl`
- `latestEveningBriefingUrl`
- `generatedAt`
- `health`

## Scheduling model

GitHub Actions cron runs in UTC and can be delayed. The workflow should use an hourly UTC cron with a local cadence gate, run every two hours during the configured active window, and let the pipeline decide whether a morning or evening briefing is due in the configured IANA time zone.

Recommended defaults:

- `timezone`: `Europe/Amsterdam`
- `morningBriefingLocalTime`: `07:00`
- `eveningBriefingLocalTime`: `20:00`
- `hourlyBriefing`: enabled for notable changes only

This avoids daylight-saving issues in workflow YAML.

Implementation note: [../.github/workflows/news.yml](../.github/workflows/news.yml) defaults `forceBriefing` to `auto`, and [../src/wazzup/pipeline.py](../src/wazzup/pipeline.py) selects due morning/evening briefings in local time when not explicitly forced.

## Implementation sequence

Build the first implementation as an end-to-end thin slice instead of isolated layers:

1. Validate [config/sources.yml](../config/sources.yml) and fetch the three initial RSS feeds.
2. Normalize feed entries into versioned `ContentItem` records.
3. Score and select a small set of articles using deterministic rules.
4. Generate an English briefing through the Copilot CLI provider when configured, with a fake provider for tests and tokenless fallback.
5. Write static JSON to the Pages data layout.
6. Render the latest briefing in a minimal PWA.
7. Add CI gates and a scheduled workflow skeleton.

This sequence keeps the system demonstrable from the beginning and limits architectural drift.

## AI integration

The pipeline uses two sequential AI steps with separate provider interfaces and agents:

### Curation

```text
AiCurationProvider.curate_items(request) -> CurationResponse
```

The curator selects and orders the most relevant items from the scored list. It returns only item IDs, not any written text. This separation keeps the curation concern (what to cover) distinct from the writing concern (how to describe it).

### Summarization

```text
AiSummaryProvider.generate_structured_summary(request) -> SummaryResponse
```

The writer receives the curated item selection and generates the full briefing — headline, sections, and bullets with citations.

### Provider implementations

| Provider                              | Curation                                         | Summarization                               | Notes                                                                                                                                                                            |
| ------------------------------------- | ------------------------------------------------ | ------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Copilot CLI                           | `wazzup-curator` agent (`curation-v1` prompt)    | `wazzup-writer` agent (`summary-v1` prompt) | Implemented with `copilot -p`, `COPILOT_GITHUB_TOKEN`, `--no-ask-user`, and narrow `--allow-tool` permissions. Requires `COPILOT_REQUESTS_PAT` or `COPILOT_GITHUB_TOKEN` secret. |
| Fake provider                         | Deterministic passthrough (top N by score order) | Deterministic template-based bullets        | Implemented and used by CI.                                                                                                                                                      |
| Azure OpenAI / OpenAI / GitHub Models | Planned.                                         | Planned.                                    | Direct API-based invocation with clearer model and token accounting.                                                                                                             |
| Ollama / Foundry                      | Planned.                                         | Planned.                                    | Local/self-contained or platform-specific experiments.                                                                                                                           |

The pipeline prepares provider-neutral requests, then adapters translate them into provider-specific invocations. For Copilot CLI, each adapter writes a prompt bundle to a temporary file, runs the CLI in programmatic mode, requests structured JSON output, and validates the output before proceeding.

Implementation requirements and current status:

- Validate provider output with JSON Schema or a runtime type validator. Runtime validation is implemented in [../src/wazzup/ai.py](../src/wazzup/ai.py); formal schema files are deferred.
- Keep prompt templates versioned (`curation-v1`, `summary-v1`).
- Include citations in the summary request and require cited output.
- Cache article-level summaries by `contentHash` and `promptVersion`. Deferred.
- Enforce max input items, max tokens, and monthly cost budget. Max input items are enforced through `WAZZUP_MAX_AI_ITEMS`; token/monthly cost accounting is deferred.
- Provide a fake deterministic provider for tests. Implemented for both curation and summarization.
- Restrict Copilot CLI tool permissions to the minimum needed, and avoid giving it write access outside a temporary output directory.
- Track provider metadata in every briefing, including provider type, model if known, prompt version, token or request estimate, and validation result.

## Frontend architecture

Use a small static PWA:

- `index.html` with semantic sections.
- CSS custom properties for theming.
- Vanilla JavaScript for data loading and rendering.
- Service Worker for static asset and recently fetched data caching.
- No runtime framework in the current PWA unless complexity proves it adds clear design or functionality value. If introduced, keep dependencies low, stable, and well-known.

Implemented frontend behavior:

- The homepage renders a single rolling briefing for the current local day. Hourly runs start the item set fresh at local midnight, then include all retained feed items published between local midnight and the current run.
- Each briefing item is displayed as a title plus short description with citations, instead of forcing the reader through one long paragraph.
- Each item also receives visible temperature metadata (`hot`, `warm`, or `cool`) derived from the existing relevance score. The PWA uses this for an icon, border, and title color so important items are scannable while scrolling.
- The hero headline is capped in the PWA and the duplicate briefing headline is replaced with a stable “Today’s rolling briefing” heading.
- The sidebar shows source health and the latest retained summary from yesterday, rendered inline rather than linking to generated JSON.
- It consumes the canonical JSON data directly, avoiding a browser-side YAML parser dependency.
- It supports opt-in local notifications when the browser supports background sync. Unsupported browsers, including iOS browsers without Background Sync or Periodic Background Sync, show notifications as unavailable instead of promising delayed catch-up notifications on app open. True background push notifications still require stored subscriptions and are deferred.
- The service worker cache is versioned by the app commit from `build-info.json`, uses `updateViaCache: 'none'`, and supports offline reading for assets/data that have already been fetched.

A dedicated daily briefing kind is not implemented yet. The current site behavior is a rolling current-day briefing plus an inline yesterday card that renders the latest retained roll-up from yesterday.

## Notification architecture

### Current behavior

- PWA displays latest data when opened.
- No external delivery channel is required yet.

### Later

- Web Push service with subscription persistence.
- User preferences per delivery channel.
- Mobile push through ntfy or a dedicated push provider.

## Release and commit conventions

All commits must follow Conventional Commits, for example:

- `docs: add product requirements and architecture`
- `feat: ingest RSS sources`
- `fix: handle malformed feed dates`
- `test: add briefing window coverage`

This is a hard project convention because release-please will be introduced later. Pull requests should be squash-merged with a Conventional Commit title, or individual commits should already comply.

## Home Assistant integration

Initial integration options:

1. REST sensor polling `public/data/latest.json`.
2. Webhook delivery from GitHub Actions after briefing generation.
3. MQTT discovery for richer state and automation.

Example automations:

- Speak the morning briefing through a TTS service.
- Show the top 3 headlines on a dashboard card.
- Trigger a notification only when high-priority topics are detected.

## Podcast integration

Podcast support should reuse the source adapter pattern:

- Parse podcast RSS episodes.
- Detect transcript links from Podcasting 2.0 tags, show notes, or known provider metadata.
- Normalize episodes as `ContentItem` with `sourceType: podcast`.
- Score episodes separately from articles to avoid over-ranking long-form content.
- Generate a `shouldListen` recommendation with reasons and estimated listening time.

Audio transcription should be opt-in due to cost, latency, and copyright considerations.

## Future API and MCP readiness

To avoid rework, the current app treats static JSON contracts as canonical. A later API or MCP server can expose the same operations:

- `list_briefings(window, kind)`
- `get_briefing(id)`
- `list_items(window, sourceType, interests)`
- `explain_score(itemId)`
- `search_items(query)`
- `mark_saved(itemId)` if user state is later introduced

The future MCP server should depend on the domain contracts in [../src/wazzup](../src/wazzup), not scrape the frontend.

## Security and privacy

- Store AI provider keys and delivery secrets in GitHub Actions secrets.
- Do not log full prompts if they may contain private interests or paid content.
- Redact provider responses in debug logs unless explicitly enabled.
- Treat Pages output as public for the current deployment and avoid publishing secrets, private notes, or full article text.
- Respect source terms and avoid publishing full article text unless licensed.
- Prefer summaries and links over copied article content.

## Key risks and mitigations

| Risk                                    | Mitigation                                                                                                                                       |
| --------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------ |
| GitHub Pages exposes personal interests | Public output is accepted for the current deployment; keep source preferences and prompts minimal and support private/static alternatives later. |
| Repository bloat from generated data    | Store rolling state in a GitHub Release asset and deploy Pages artifacts without committing generated JSON.                                 |
| AI hallucinations                       | Require citations, validate structured output, keep source links visible.                                                                        |
| AI provider cost spikes                 | Cap item count today; add summary caching and token/monthly accounting before relying on strict budget guarantees.                               |
| Scheduled workflows delayed             | Treat schedules as best-effort and compute windows from timestamps.                                                                              |
| Feed parsing failures                   | Isolate source failures and publish source health.                                                                                               |
| Copyright issues                        | Store metadata and summaries only; avoid republishing full content.                                                                              |
