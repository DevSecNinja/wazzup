# GitHub Actions design

## Workflow overview

| Workflow | Trigger | Responsibility |
| --- | --- | --- |
| CI | Pull request and push to `main` | Formatting, linting, type checks, tests, schema validation, frontend build. |
| News hourly | Hourly schedule and manual dispatch | Fetch feeds, update article store, generate due briefings, and persist release-backed state. |
| Pages deploy | After successful news generation or manual dispatch | Deploy PWA and static YAML/JSON data to GitHub Pages through the reusable `DevSecNinja/.github` Pages workflow. |
| Live smoke | Manual or daily schedule | Optional real feed and AI provider canary checks with strict budgets. |
| Archive cleanup | Monthly schedule | Keep release-backed rolling state compact and optionally publish monthly recap archives. |
| Release automation | Push to `main` | Future release-please workflow driven by Conventional Commits. |

## Recommended workflow boundaries

- CI must not require external network calls beyond dependency installation.
- CI must not call paid AI provider APIs.
- Scheduled workflows may call feeds and AI providers, but should enforce budgets.
- Publishing should happen only after contract validation succeeds.
- Delivery notifications should happen only after publishing succeeds.
- Commit messages and PR titles must follow Conventional Commits before release-please is enabled.

## AI runner options in Actions

The preferred MVP path is Copilot CLI because it is GitHub-native and can run directly inside a scheduled workflow. The pipeline should still expose a provider abstraction so the same request can be handled by Copilot CLI, an API provider, Ollama, or a fake test provider.

| Runner | When to use | Workflow implications |
| --- | --- | --- |
| Copilot CLI | Preferred first production runner. | Install `@github/copilot`, set `COPILOT_GITHUB_TOKEN` from a fine-grained PAT with Copilot Requests permission, run `copilot -p` with `--no-ask-user`, and restrict `--allow-tool`. |
| API provider | Fallback or production runner when strict structured output, model selection, or accounting is easier through an API. | Store provider keys in Actions secrets and call through the pipeline adapter. |
| Ollama | Optional local-model experiment or privacy-focused smoke run. | Install/start Ollama, pull/cache a small model, expect slower CPU inference on GitHub-hosted runners. |
| Fake provider | CI and deterministic tests. | No secrets or network calls. |

## CI workflow sketch

```yaml
name: CI

on:
  pull_request:
  push:
    branches: [main]

permissions:
  contents: read

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: jdx/mise-action@v4
        with:
          version: 2026.4.18
      - run: task install
      - run: task ci
      - run: task pipeline:generate:fixtures
      - run: task validate:data
```

If the implementation uses another runtime, keep the same gate structure and replace setup/install commands.

## Hourly news workflow sketch

```yaml
name: News hourly

on:
  schedule:
    - cron: "7 * * * *"
  workflow_dispatch:
    inputs:
      forceBriefing:
        description: Force briefing kind: none, hourly, morning, evening
        required: false
        default: none

permissions:
  contents: read

concurrency:
  group: news-hourly
  cancel-in-progress: false

jobs:
  generate:
    runs-on: ubuntu-latest
    timeout-minutes: 20
    permissions:
      contents: write
    env:
      WAZZUP_TIMEZONE: Europe/Amsterdam
      WAZZUP_MAX_AI_ITEMS: 30
      WAZZUP_MAX_AI_COST_USD: 1.00
    steps:
      - uses: actions/checkout@v4
      - uses: jdx/mise-action@v4
        with:
          version: 2026.4.18
      - run: task install
      - name: Generate retained news state
        run: task news:generate
        env:
          AI_PROVIDER: copilot-cli
          COPILOT_GITHUB_TOKEN: ${{ secrets.COPILOT_REQUESTS_PAT || secrets.COPILOT_GITHUB_TOKEN }}
```

## Copilot CLI workflow variant

The implementation hides provider-specific commands behind `task news:generate` and the Python AI provider adapter. Internally, a Copilot CLI adapter can follow this pattern:

```yaml
- uses: actions/setup-node@v4
  with:
    node-version: 22
    cache: npm

- run: npm ci

- name: Install Copilot CLI
  run: npm install -g @github/copilot

- name: Generate briefing with Copilot CLI provider
  env:
    AI_PROVIDER: copilot-cli
    COPILOT_GITHUB_TOKEN: ${{ secrets.COPILOT_REQUESTS_PAT || secrets.COPILOT_GITHUB_TOKEN }}
    FORCE_BRIEFING: ${{ inputs.forceBriefing || 'hourly' }}
  run: task news:generate
```

Provider adapter requirements:

- Run Copilot CLI in programmatic mode with `copilot -p`.
- Use `--no-ask-user` so the workflow never blocks for interaction.
- Use only narrow `--allow-tool` permissions, such as read-only shell access to generated prompt/input files and write access to a temporary output file.
- Require the CLI to write structured JSON, then validate that JSON before publication.
- Do not pass secrets, full debug logs, or unnecessary repository write permissions into the prompt context.

## Ollama workflow variant

Ollama can be evaluated behind the same provider interface:

```yaml
- name: Install Ollama
  run: curl -fsSL https://ollama.com/install.sh | sh

- name: Start Ollama
  run: ollama serve &

- name: Pull model
  run: ollama pull llama3.2:3b

- name: Generate briefing with local model
  env:
    AI_PROVIDER: ollama
    OLLAMA_MODEL: llama3.2:3b
  run: npm run pipeline:generate -- --force-briefing "${{ inputs.forceBriefing || 'none' }}"
```

This should not be the default MVP runner unless quality and runtime are acceptable. Prefer caching model layers and running it only on manual or scheduled canary workflows until validated.

## Reusable workflow integration

For shared workflows from a `.github` repository, keep project-specific schedules here and delegate common checks:

```yaml
jobs:
  shared-ci:
    uses: DevSecNinja/.github/.github/workflows/node-ci.yml@v1
    with:
      node-version: 22
      build-command: npm run build
      test-command: npm test
    secrets: inherit
```

Use pinned tags or SHA references for reusable workflows. Avoid using a moving branch for security-sensitive release workflows.

## Future release-please workflow

Release automation should be added after the first implementation stabilizes. It should rely on Conventional Commits rather than a custom changelog process.

Expected future behavior:

- Parse Conventional Commits on `main`.
- Open or update a release PR.
- Generate changelog entries.
- Tag releases after the release PR merges.
- Optionally publish immutable static-app artifacts or monthly recap archives.

## Secrets

Expected MVP secrets:

| Secret | Purpose |
| --- | --- |
| `COPILOT_REQUESTS_PAT` | Preferred repository secret containing a fine-grained PAT for Copilot CLI with Copilot Requests permission. |
| `COPILOT_GITHUB_TOKEN` | Alternative secret name accepted by the News hourly workflow. |
| `AZURE_OPENAI_ENDPOINT` | Azure OpenAI endpoint. |
| `AZURE_OPENAI_API_KEY` | Azure OpenAI API key. |
| `OPENAI_API_KEY` | Optional alternative provider. |
| `NOTIFY_WEBHOOK_URL` | Optional delivery webhook. |
| `HOME_ASSISTANT_WEBHOOK_URL` | Optional Home Assistant webhook. |

Rules:

- Never echo secrets.
- If Copilot CLI is requested without either Copilot token secret, the News hourly workflow logs a warning and uses the deterministic `fake` provider so release-backed state, validation, and Pages automation can still complete.
- Redact prompt/debug logs by default.
- Scope permissions per workflow.
- Use GitHub Environments for deployment approvals if outputs are public.

## Scheduling details

Use a single hourly cron and calculate briefing windows in application code using the configured IANA time zone. This handles daylight-saving transitions better than maintaining separate UTC cron expressions.

Recommended behavior:

- Every hourly run fetches feeds and updates article indexes.
- If local time is near 07:00 and no morning briefing exists for that date, generate morning briefing.
- If local time is near 20:00 and no evening briefing exists for that date, generate evening briefing.
- Generate hourly briefing only if there are enough high-scoring new items.
- Use idempotency keys based on briefing kind, date, and time window.

## Artifact and retention strategy

- Publish current static output to GitHub Pages.
- Keep 35 days of detailed article YAML plus JSON mirrors in Pages data.
- Persist the 35-day Pages data window as a `wazzup-state.zip` asset on the `news-state` GitHub Release.
- Keep compact monthly recap archives in separate GitHub Releases if history matters.
- Upload debug artifacts only for failed runs and redact sensitive data.
- Avoid committing generated hourly YAML/JSON to `main` to prevent repository bloat.
- Avoid a generated-data branch unless release assets prove insufficient; it still creates thousands of commits per year.

## Task automation boundary

Workflow shell logic should live in [Taskfile.yml](../Taskfile.yml) wherever practical. GitHub Actions should call tasks such as `task news:generate`, `task pages:build`, `task pipeline:generate:fixtures`, and `task validate:data` instead of duplicating pipeline commands inline.

## Standardized Pages deployment

The scheduled `News hourly` workflow is responsible for mutating release-backed state. It does not deploy Pages directly. After it succeeds, the `Pages` workflow calls the reusable Pages workflow from `DevSecNinja/.github` and restores the `news-state` release asset through `task pages:build` before deployment.

## Security hardening

- Use least-privilege `permissions` in every workflow.
- Pin third-party actions to major versions at minimum; pin to SHA for higher assurance.
- Add dependency review for pull requests.
- Add CodeQL after implementation language is selected.
- Validate all generated files before deployment.
- Treat feed content as untrusted input.
- Sanitize HTML from feed titles/descriptions before rendering.

## Failure handling

- A single feed failure should not fail the whole run unless failure rate exceeds a configured threshold.
- AI provider failures should publish source data and mark summary generation as degraded.
- Delivery failures should not roll back successful publication.
- Repeated failures should be visible in `sources/status.json` and workflow summaries.

## Workflow summary output

Each scheduled run should write a GitHub Actions step summary containing:

- Number of feeds configured, fetched, failed, and skipped.
- Number of new, duplicate, and selected items.
- Briefing kinds generated.
- Estimated AI provider cost and token/request usage.
- Published artifact paths.
- Delivery targets attempted and status.
