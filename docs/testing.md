# Testing strategy

## Principles

- Prefer deterministic tests over live network or live AI provider calls.
- Test core pipeline logic as pure functions wherever possible.
- Keep provider integrations behind interfaces with contract tests.
- Validate every generated JSON artifact against versioned schemas.
- Treat prompts as versioned production assets with regression tests.
- Run fast checks on every pull request and slower scheduled checks separately.

## Test pyramid

| Layer | Purpose | Examples | CI trigger |
| --- | --- | --- | --- |
| Unit | Validate pure logic. | Date windows, scoring, dedupe, feed normalization, cost limits. | Every PR and push. |
| Contract | Validate schemas and provider interfaces. | `ContentItem`, `Briefing`, `latest.json`, delivery payloads. | Every PR and push. |
| Integration | Validate components together with fixtures. | Parse real saved RSS samples, run pipeline with fake AI provider, publish data to temp dir. | Every PR and push. |
| Frontend | Validate rendering and accessibility basics. | Load fixture `latest.json`, render briefing, keyboard navigation, service worker registration. | Every PR and push. |
| End-to-end | Validate deployed/static behavior. | Build app, serve static output, browse latest briefing. | Main branch and release. |
| Live smoke | Validate external services safely. | Fetch a small allowlisted feed, optional AI provider canary with tiny prompt. | Scheduled or manual only. |

## Required MVP tests

### Source tests

- Parse RSS 2.0 feed fixture.
- Parse Atom feed fixture.
- Parse JSON Feed fixture.
- Parse podcast RSS fixture with and without transcript metadata.
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
  feeds/rss-basic.xml
  feeds/atom-basic.xml
  feeds/json-feed-basic.json
  feeds/podcast-with-transcript.xml
  feeds/malformed.xml
  ai/summary-response-valid.json
  ai/summary-response-invalid-missing-citation.json
  expected/briefing-morning.json
```

Fixtures should be small and either hand-written or derived from permissively licensed/public examples without copying substantial article text.

## GitHub Actions test gates

The CI workflow should block merges unless these checks pass:

1. Formatting check.
2. Lint check.
3. Type check.
4. Unit tests.
5. Contract/schema tests.
6. Integration tests using fixtures and fake AI provider.
7. Frontend build.
8. Static output validation.

Optional checks:

- Accessibility check.
- Dependency review.
- CodeQL.
- Live feed smoke test on schedule/manual trigger.

## Coverage targets

- Core pipeline logic: 85%+ line coverage.
- Contract/schema validators: 100% of required schemas covered.
- Frontend rendering logic: 70%+ line coverage.
- Critical date-window logic: explicit branch coverage for daylight-saving scenarios.

Coverage should guide quality but should not replace meaningful assertions.

## Local developer workflow

Implementation should provide commands equivalent to:

```text
format
lint
typecheck
test
test:integration
build
validate:data
```

The exact package manager and command names should be finalized when the implementation stack is selected.