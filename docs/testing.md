# Testing strategy

## Principles

- Prefer deterministic tests over live network or live AI provider calls.
- Test core pipeline logic as pure functions wherever possible.
- Keep provider integrations behind interfaces with contract tests.
- Validate every generated YAML artifact and JSON mirror against versioned schemas.
- Treat prompts as versioned production assets with regression tests.
- Run fast checks on every pull request and slower scheduled checks separately.

## Test pyramid

| Layer | Purpose | Examples | CI trigger |
| --- | --- | --- | --- |
| Unit | Validate pure logic. | Date windows, scoring, dedupe, feed normalization, provider selection. | Pull request and manual CI. |
| Contract | Validate generated data shape and provider interfaces. | `ContentItem`, `Briefing`, `latest.json`, release-state layout. | Pull request and manual CI. |
| Integration | Validate components together with fixtures. | Parse saved RSS samples, run pipeline with fake AI provider, publish data to temp dir. | Pull request and manual CI. |
| Frontend | Validate rendering and accessibility basics. | Load fixture `latest.json`, render briefing, keyboard navigation, service worker registration. | Planned. |
| End-to-end | Validate deployed/static behavior. | Build app, restore release state, validate Pages artifact. | News hourly and Pages workflows. |
| Live smoke | Validate external services safely. | Fetch a small allowlisted feed, optional AI provider canary with tiny prompt. | Scheduled or manual only. |

## Implemented test suite

The current MVP uses Python `unittest` and lightweight scripts instead of pytest or a JavaScript test runner.

Implemented tests:

- [../tests/test_config.py](../tests/test_config.py): source and interest configuration loading.
- [../tests/test_feeds.py](../tests/test_feeds.py): RSS parsing, URL canonicalization, and deduplication priority.
- [../tests/test_scoring.py](../tests/test_scoring.py): deterministic scoring behavior.
- [../tests/test_pipeline.py](../tests/test_pipeline.py): end-to-end fixture pipeline generation with the fake AI provider and generated-data validation.
- [../tests/test_publisher.py](../tests/test_publisher.py): retention by path date, YAML/JSON mirror generation, and manifest updates.
- [../tests/test_ai.py](../tests/test_ai.py): provider defaulting and Copilot token guard behavior.
- [../tests/test_build_info.py](../tests/test_build_info.py): generated build metadata used by the footer and service worker versioning.
- [../tests/test_pwa_assets.py](../tests/test_pwa_assets.py): install icons, 24-hour time formatting hooks, build-versioned service worker registration, footer metadata hooks, simplified header, yesterday-summary hooks, capped headlines, structured item-card hooks, and service worker cache versioning.

Implemented validation commands:

```text
task format:check              # UTF-8, trailing newline, trailing whitespace
task lint                      # Python syntax parse via ast
task test                      # unittest discovery
task build                     # compile Python modules
task pipeline:generate:fixtures
task validate:data
task pages:build               # restore retained state and validate Pages data
```

## Required MVP tests

### Source tests

- Parse RSS 2.0 feed fixture.
- Parse Atom feed fixture. Parser support exists; an explicit Atom fixture test should still be added.
- Parse JSON Feed fixture. Deferred.
- Parse podcast RSS fixture with and without transcript metadata. Deferred.
- Handle malformed feeds without crashing the whole pipeline.
- Preserve original source URL and canonical URL separately.

### Deduplication tests

- Same GUID and URL deduplicates.
- Different tracking parameters deduplicate to canonical URL.
- Syndicated titles from multiple sources group into one duplicate group.
- Distinct articles with similar titles stay separate when timestamps and URLs differ.

### Scoring tests

- Matching configured interests increases score.
- Source weight affects ranking.
- Recency decays older items.
- Duplicate coverage can increase importance without duplicating summary bullets.
- Blocked topics or excluded sources are removed.

### Briefing-window tests

- Morning briefing at 07:00 local time covers previous day and overnight updates since 20:00.
- Evening briefing at 20:00 local time covers the day since 07:00.
- Daylight-saving transitions in the configured IANA time zone do not duplicate or skip windows.
- Hourly windows are based on actual timestamps, not workflow start time alone.

### AI provider tests

- Fake provider returns deterministic structured summaries.
- Provider output is rejected when required citations are missing.
- Provider output is rejected when JSON schema validation fails.
- Token and item budgets stop oversized requests.
- Cached article summaries are reused when `contentHash` and prompt version match.
- Copilot CLI provider fails with actionable diagnostics when a GitHub Actions token is missing or the CLI exits non-zero.

### Publisher tests

- Generated data files match the expected static layout.
- `latest.json` points to existing briefing files.
- Retention deletes or archives old data according to policy.
- No secrets are written to static output.

### Frontend tests

- The app can render latest, morning, evening, and source-health views from fixtures.
- Missing data shows an actionable empty state.
- Links open the original source article.
- Keyboard navigation works for briefing sections.
- Basic accessibility checks pass.

Frontend tests are not implemented yet because the MVP deliberately has no Node package/build/test setup. Add browser-level tests once the UI grows beyond the latest-briefing/source-health view.

## Prompt regression tests

Prompt behavior should be tested without relying on exact AI-generated prose. Recommended assertions:

- Output is valid structured JSON.
- Required sections are present.
- Citations reference known source IDs.
- The summary does not include uncited claims.
- The output length stays under configured limits.
- Important high-scoring items from fixtures are included.

## Test data

Use committed fixtures for repeatability:

```text
tests/fixtures/
  microsoft-security-blog.xml
  microsoft-security-threat-intelligence.xml
  nos-news.xml
```

Fixtures should be small and either hand-written or derived from permissively licensed/public examples without copying substantial article text.

## GitHub Actions test gates

The CI workflow should block merges unless these checks pass:

1. Formatting check.
2. Lint check.
3. Unit and integration tests.
4. Python compile/build check.
5. Fixture generation using fake AI provider.
6. Static output validation.

The separate reusable Lint workflow runs organization-standard checks on pull requests and manual dispatch.

Optional checks:

- Type check.
- Frontend/browser tests.
- Accessibility check.
- Dependency review.
- CodeQL.
- Live feed smoke test on schedule/manual trigger.

## Known coverage gaps after MVP launch feedback

- No real browser rendering tests yet for yesterday-summary rendering, notification permission flows, or offline behavior.
- No accessibility automation yet for the updated logo, footer, and cards.
- No visual regression tests for the PWA layout.
- No live Copilot CLI canary with a real token secret yet.
- No tests for a daily/monthly archive release because that archive strategy is deferred.

## Coverage targets

- Core pipeline logic: 85%+ line coverage.
- Contract/schema validators: 100% of required schemas covered.
- Frontend rendering logic: 70%+ line coverage.
- Critical date-window logic: explicit branch coverage for daylight-saving scenarios.

Coverage should guide quality but should not replace meaningful assertions.

## Local developer workflow

Implementation should provide commands equivalent to:

```text
task format:check
task lint
task test
task build
task pipeline:generate:fixtures
task validate:data
task pages:build
```

Use `mise install` first to install the pinned runtime/toolchain, then `task install` to install Python dependencies.
