# Wazzup

Wazzup is a GitHub-native personal news briefing app. It collects configured RSS/Atom feeds on a schedule, ranks items against configured interests, generates concise English briefings, and publishes a minimal static PWA plus YAML/JSON data to GitHub Pages.

## Documentation

- [Product requirements](docs/requirements.md)
- [Architecture](docs/architecture.md)
- [Testing strategy](docs/testing.md)
- [GitHub Actions design](docs/github-actions.md)
- [ADR 0001: GitHub-native static architecture](docs/adr/0001-github-native-static-architecture.md)
- [ADR 0002: AI execution strategy](docs/adr/0002-ai-execution-strategy.md)
- [ADR 0003: Generated data state storage](docs/adr/0003-generated-data-state-storage.md)

## Configuration

- [config/sources.yml](config/sources.yml) maintains the RSS/Atom source registry with short source tags, broad category tags, source weights, and feed-specific interest hints.
- [config/interests.yml](config/interests.yml) configures English summaries, 35-day retention, `Europe/Amsterdam`, and weighted interests for security, AI/developer platforms, cloud, and Microsoft.

## Implemented app

1. Fetch configured RSS/Atom feeds from GitHub Actions using the local cadence gate: hourly from 06:00 through 21:59 Europe/Amsterdam and every two hours overnight.
2. Normalize articles into stable YAML records with JSON browser mirrors.
3. Deduplicate by canonical URL, raw feed reference/GUID, and normalized title plus publication day.
4. Rank articles using deterministic interest, source weight, and freshness scoring.
5. Generate a rolling English briefing for the current local day; hourly runs start fresh at local midnight and then keep incorporating the day’s retained feed items.
6. Render each briefing item as a title, short description, temperature indicator, source/category tags, timestamped citations, and source links in the PWA.
7. Generate English summaries through an AI provider abstraction:
   - `copilot-cli` for scheduled production-style runs when a Copilot token secret exists.
   - `fake` for deterministic CI, local development, and tokenless fallback.
8. Persist generated state outside Git history in a mutable `news-state` GitHub Release asset named `wazzup-state.zip`.
9. Publish the static PWA and generated data to GitHub Pages through the reusable `DevSecNinja/.github` Pages workflow.
10. Run lightweight formatting, syntax linting, unit/integration tests, compile checks, fixture generation, data validation, dependency update automation, repo-label sync, reusable organization lint workflows, and a manual shared auto-fix workflow in GitHub Actions.

## Repository status

This repository contains a working end-to-end personal briefing app: Python ingestion/scoring/publishing code, deterministic tests, RSS fixtures, Task/mise automation, release-backed generated state, reusable GitHub Pages deployment, and a vanilla HTML/CSS/JavaScript PWA.

Important current limitations and deviations from the original target architecture:

- The backend is Python under [src/wazzup](src/wazzup), not TypeScript.
- The frontend is vanilla JavaScript in [public/app.js](public/app.js), not TypeScript/Web Components yet.
- JSON Feed and podcast adapters are modeled but not implemented yet.
- Automatic morning/evening due-time selection is implemented in the pipeline and exposed through the scheduled workflow's `auto` mode; the workflow still runs on an hourly UTC cron with a local cadence gate.
- YAML is canonical generated state; JSON is generated only as a browser/PWA mirror.
- Copilot CLI is optional at runtime. If no `COPILOT_REQUESTS_PAT` or `COPILOT_GITHUB_TOKEN` secret exists, News hourly falls back to the deterministic fake provider so the pipeline and Pages deployment continue to work.
- The service worker cache is versioned from generated build metadata; the footer shows the short commit and links back to the repository.
- Notifications are opt-in. The installed PWA now uses service-worker background sync when the browser supports it, but there is still no server-side Web Push subscription store yet.
- Cost controls are partial: `WAZZUP_MAX_AI_ITEMS` caps prompt size, but token/monthly budget accounting is not enforced yet.
- Formal JSON Schema files are deferred; runtime validators and tests enforce the generated-data contract today.
- Renovate and repository automation are onboarded from `DevSecNinja/.github` through [renovate.json5](renovate.json5), labeler config, label sync, and config sync workflows.

## Local development

This repository uses [mise](https://mise.jdx.dev/) and [Task](https://taskfile.dev/) for local automation.

```text
mise install
task install
task hooks:install
task ci
AI_PROVIDER=fake task pipeline:generate
task validate:data
```

Open [public/index.html](public/index.html) through a local static server after generating data.

Common operational commands:

```text
task news:generate              # restore release state, generate, validate, persist
task pages:build                # restore retained state and validate Pages data
task pipeline:generate:fixtures # generate deterministic fixture output
```

`task hooks:install` enables the repo-specific [lefthook](.lefthook.toml) pre-commit checks and Conventional Commit message hook. The manual Auto-fix formatting workflow uses the shared `DevSecNinja/.github` reusable workflow to run dprint and yamlfmt with the local shared config files.

Configure either `COPILOT_REQUESTS_PAT` or `COPILOT_GITHUB_TOKEN` as a repository secret to enable Copilot CLI in News hourly runs; otherwise the workflow falls back to the fake provider with a warning.
