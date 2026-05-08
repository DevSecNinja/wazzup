# GitHub Actions design

## Workflow overview

| Workflow            | Trigger                                                     | Responsibility                                                                                                                                   |
| ------------------- | ----------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------ |
| CI                  | Pull request and manual dispatch                            | Formatting, syntax linting, tests, compile checks, fixture generation, and generated-data validation.                                            |
| Lint                | Pull request and manual dispatch                            | Reusable organization lint workflow from `DevSecNinja/.github`.                                                                                  |
| Auto-fix formatting | Manual dispatch                                             | Reusable organization formatting workflow that commits dprint/yamlfmt fixes back to the branch.                                                  |
| News hourly         | Hourly schedule with local cadence gate and manual dispatch | Fetch feeds, generate a rolling briefing, validate data, persist release-backed state, and upload a short-lived `public` artifact for debugging. |
| Pages               | Successful `News hourly` workflow run, push to `main`, and manual dispatch | Deploy PWA and static YAML/JSON data to GitHub Pages through the reusable `DevSecNinja/.github` Pages workflow.                                  |
| Config Sync         | Weekly and manual dispatch                                  | Open PRs when shared repo config from `DevSecNinja/.github` drifts.                                                                              |
| Label Sync          | Daily, manual dispatch, and label config changes            | Sync repository labels from the org base labels plus repo-specific labels.                                                                       |
| Labeler             | Pull requests, issues, and manual dispatch                  | Apply area/type labels using shared labeler automation.                                                                                          |
| Live smoke          | Not implemented yet                                         | Optional real feed and AI provider canary checks with strict budgets.                                                                            |
| Archive cleanup     | Not implemented yet                                         | Keep release-backed rolling state compact and optionally publish monthly recap archives.                                                         |
| Release automation  | Not implemented yet                                         | Future release-please workflow driven by Conventional Commits.                                                                                   |

## Recommended workflow boundaries

- CI must not require external network calls beyond dependency installation.
- CI must not call paid AI provider APIs.
- Scheduled workflows may call feeds and AI providers. They enforce prompt-size item caps today; token/monthly budget enforcement remains deferred.
- Publishing should happen only after contract validation succeeds.
- Delivery notifications should happen only after publishing succeeds.
- Commit messages and PR titles must follow Conventional Commits before release-please is enabled.

## Repository automation from `DevSecNinja/.github`

Implemented repository automation:

- [../renovate.json5](../renovate.json5) imports the shared Renovate presets from `DevSecNinja/.github` for dependency grouping, labels, semantic commits, custom managers, and safe automerge rules.
- Reusable workflow refs and version inputs include `# renovate:` markers where the org custom managers can maintain them through PRs.
- [../.github/workflows/autofix.yml](../.github/workflows/autofix.yml) runs the shared auto-fix workflow on demand with the local [../dprint.json](../dprint.json), [../.yamlfmt.yaml](../.yamlfmt.yaml), and [../.yamllint.yaml](../.yamllint.yaml) configuration.
- [../.github/workflows/config-sync.yml](../.github/workflows/config-sync.yml) runs weekly and can open PRs for shared config drift.
- [../.github/workflows/label-sync.yml](../.github/workflows/label-sync.yml) syncs labels from [../.github/labels.yaml](../.github/labels.yaml) plus the org base labels.
- [../.github/workflows/labeler.yml](../.github/workflows/labeler.yml) applies issue/PR labels using [../.github/issue-labeler.yaml](../.github/issue-labeler.yaml) and [../.github/pr-labeler.yaml](../.github/pr-labeler.yaml).

The reusable Lint workflow is scoped to checks that are meaningful for this static Python/PWA repository. Shell script and IaC scanners are disabled because the project does not currently contain shell scripts or Terraform/Kubernetes-style IaC; gitleaks, actionlint, yamllint, yamlfmt, dprint, and zizmor remain enabled.

Release Please remains deferred until the app has an explicit first release/versioning policy.

## AI runner options in Actions

The preferred current path is Copilot CLI because it is GitHub-native and can run directly inside a scheduled workflow. The pipeline should still expose a provider abstraction so the same request can be handled by Copilot CLI, an API provider, Ollama, or a fake test provider.

| Runner        | When to use                                                                                                           | Workflow implications                                                                                                                                                               |
| ------------- | --------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Copilot CLI   | Preferred first production runner.                                                                                    | Install `@github/copilot`, set `COPILOT_GITHUB_TOKEN` from a fine-grained PAT with Copilot Requests permission, run `copilot -p` with `--model`, `--agent`, `--no-ask-user`, and restricted `--allow-tool`. |
| API provider  | Fallback or production runner when strict structured output, model selection, or accounting is easier through an API. | Store provider keys in Actions secrets and call through the pipeline adapter.                                                                                                       |
| Ollama        | Optional local-model experiment or privacy-focused smoke run.                                                         | Install/start Ollama, pull/cache a small model, expect slower CPU inference on GitHub-hosted runners.                                                                               |
| Fake provider | CI and deterministic tests.                                                                                           | No secrets or network calls.                                                                                                                                                        |

## Implemented CI workflow

```yaml
name: CI

on:
  pull_request:
  workflow_dispatch:

permissions:
  contents: read

jobs:
  test:
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/checkout@v6
        with:
          persist-credentials: false
      - uses: jdx/mise-action@v4
        with:
          version: 2026.4.19
      - run: task install
      - run: task ci
      - run: task pipeline:generate:fixtures
      - run: task validate:data
```

CI intentionally does not run on every push to `main` to avoid duplicate checks when PR validation already covered the change. Deployment/state workflows still run on their own operational triggers.

## Implemented hourly news workflow

Key excerpts from [../.github/workflows/news-hourly.yml](../.github/workflows/news-hourly.yml):

```yaml
name: News hourly

on:
  schedule:
    - cron: "7 * * * *"
  workflow_dispatch:
    inputs:
      forceBriefing:
        description: Force briefing kind
        required: false
        default: auto
        type: choice
        options: [auto, hourly, morning, evening]
      aiProvider:
        description: AI provider adapter
        required: false
        default: copilot-cli
        type: choice
        options: [copilot-cli, fake]

permissions:
  contents: read

concurrency:
  group: news-hourly-${{ github.ref }}
  cancel-in-progress: false

jobs:
  generate:
    runs-on: ubuntu-24.04
    timeout-minutes: 25
    permissions:
      contents: write
    env:
      WAZZUP_TIMEZONE: Europe/Amsterdam
      WAZZUP_MAX_AI_ITEMS: 30
      WAZZUP_MAX_AI_COST_USD: 1.00
      COPILOT_MODEL: claude-sonnet-4.6
    steps:
      - uses: actions/checkout@v6
      - uses: jdx/mise-action@v4
        with:
          version: 2026.4.18
      - name: Select AI provider
        id: ai
        env:
          COPILOT_TOKEN: ${{ secrets.COPILOT_REQUESTS_PAT || secrets.COPILOT_GITHUB_TOKEN }}
        run: |
          # Actual workflow validates requested provider, then falls back to fake
          # only when copilot-cli was requested without a Copilot token secret.
          provider="${REQUESTED_AI_PROVIDER}"
          if [[ "${provider}" == "copilot-cli" && -z "${COPILOT_TOKEN}" ]]; then
            provider="fake"
          fi
          echo "provider=${provider}" >>"${GITHUB_OUTPUT}"
      - name: Set up Node.js for Copilot CLI
        if: ${{ steps.ai.outputs.provider == 'copilot-cli' }}
        uses: actions/setup-node@v6
      - name: Install Copilot CLI
        if: ${{ steps.ai.outputs.provider == 'copilot-cli' }}
        run: npm install -g @github/copilot
      - run: task install
      - name: Generate retained news state
        run: task news:generate
        env:
          GH_TOKEN: ${{ github.token }}
          AI_PROVIDER: ${{ steps.ai.outputs.provider }}
          COPILOT_GITHUB_TOKEN: ${{ secrets.COPILOT_REQUESTS_PAT || secrets.COPILOT_GITHUB_TOKEN }}
          COPILOT_MODEL: ${{ env.COPILOT_MODEL }}
```

The workflow triggers hourly because GitHub cron is UTC-only and does not understand `Europe/Amsterdam` daylight-saving transitions. A first cadence step computes the local hour and continues every hour from 06:00 to 21:59, then only on even local hours from 22:00 to 05:59. Manual dispatch always runs.

### Manual catch-up for delayed or missed runs

When cron delivery is delayed, use the existing **News hourly** `workflow_dispatch` path:

1. Open **Actions → News hourly → Run workflow**.
2. Keep `forceBriefing=auto` for normal catch-up, or select `hourly`/`morning`/`evening` for an explicit run.
3. Keep `aiProvider=copilot-cli` unless you intentionally want deterministic fallback with `fake`.
4. Run once, then verify `public/data/latest.json` shows a fresh `runStatus.lastSuccessfulRunAt`.

### Lightweight stale-run alert path

The PWA now marks pipeline status as **Stale** when the last attempted run age exceeds the UI threshold. For an operational alert, add a small scheduled workflow that checks `public/data/latest.json` (`runStatus.lastAttemptedRunAt`) and opens an issue or sends a notification when stale for too long.

Operational learning: the first live News hourly run failed because Copilot CLI was requested but the token secret was empty. The workflow now selects an effective provider before installing Node/Copilot. If `copilot-cli` is requested without `COPILOT_REQUESTS_PAT` or `COPILOT_GITHUB_TOKEN`, it logs a warning and uses `AI_PROVIDER=fake` so the release state and Pages deployment path can still be validated end to end.

After enabling the Copilot PAT, one live run failed because Copilot CLI wrote JSON without the required `sections` array. The provider now treats invalid structured Copilot output as an AI-provider failure and falls back to the deterministic summary shape, recording `provider.type: copilot-cli-fallback` and the validation reason instead of failing the whole state/deploy pipeline.

The Copilot CLI provider pins the briefing writer to `COPILOT_MODEL`, defaulting to Claude Sonnet 4.6 via the CLI model ID `claude-sonnet-4.6`, and invokes the repo-local `wazzup-writer` custom agent. This avoids the CLI's higher-cost default model while keeping the model overridable for manual canaries.

## Copilot CLI workflow variant

The implementation hides provider-specific commands behind `task news:generate` and the Python AI provider adapter. Internally, a Copilot CLI adapter can follow this pattern:

```yaml
- uses: actions/setup-node@v6
  with:
    node-version: 24

- name: Install Copilot CLI
  run: npm install -g @github/copilot

- name: Generate briefing with Copilot CLI provider
  env:
    AI_PROVIDER: copilot-cli
    COPILOT_GITHUB_TOKEN: ${{ secrets.COPILOT_REQUESTS_PAT || secrets.COPILOT_GITHUB_TOKEN }}
    COPILOT_MODEL: claude-sonnet-4.6
    FORCE_BRIEFING: ${{ inputs.forceBriefing || 'auto' }}
  run: task news:generate
```

Provider adapter requirements:

- Run Copilot CLI in programmatic mode with `copilot -p`.
- Pass `--model` from `COPILOT_MODEL`; default to `claude-sonnet-4.6` rather than the CLI's `Auto` default.
- Pass `--agent wazzup-writer` so the briefing-writing style and JSON contract live in [../.github/agents/wazzup-writer.agent.md](../.github/agents/wazzup-writer.agent.md).
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
    FORCE_BRIEFING: ${{ inputs.forceBriefing || 'auto' }}
  run: task pipeline:generate
```

This should not be the default runner unless quality and runtime are acceptable. Prefer caching model layers and running it only on manual or scheduled canary workflows until validated.

## Reusable workflow integration

For shared workflows from a `.github` repository, keep project-specific schedules here and delegate common checks. Wazzup currently uses:

- `DevSecNinja/.github/.github/workflows/lint.yml@af5030dd0d6f61b80fe58f949c9b985d1931ddf2` for [../.github/workflows/lint.yml](../.github/workflows/lint.yml).
- `DevSecNinja/.github/.github/workflows/pages.yml@af5030dd0d6f61b80fe58f949c9b985d1931ddf2` for [../.github/workflows/pages.yml](../.github/workflows/pages.yml).

General pattern:

```yaml
jobs:
  shared-ci:
    uses: DevSecNinja/.github/.github/workflows/node-ci.yml@v1
    with:
      node-version: 22
      build-command: task build
      test-command: task test
    secrets: inherit
```

Use pinned tags or SHA references for reusable workflows. Avoid using a moving branch for security-sensitive release workflows. Wazzup pins the reusable workflows to the commit for `.github` release `v1.3.0`.

## Implemented Pages workflow

[../.github/workflows/pages.yml](../.github/workflows/pages.yml) runs after successful `News hourly` completion, on pushes to `main`, or by manual dispatch. This means content and PWA shell changes deploy when they merge, while scheduled news runs still deploy freshly generated data after state persistence succeeds. It delegates deployment to the reusable Pages workflow with these important inputs:

- `artifact-path: public`
- `install-command`: install mise, trust config, install tools, and run `task install`
- `test-command`: `~/.local/bin/mise exec -- task ci`
- `build-command`: `~/.local/bin/mise exec -- task pages:build`
- `cloudflare-preview: false`

Operational learning: do not inject `GH_TOKEN="${{ github.token }}"` into the reusable workflow `build-command` string. In practice, the token was evaluated to an empty value inside the called workflow and `gh release download` failed. The fixed design makes `task pages:build` restore `news-state` through the public release asset URL when no `GH_TOKEN` or `GITHUB_TOKEN` is available.

## Future release-please workflow

Release automation should be added after the first implementation stabilizes. It should rely on Conventional Commits rather than a custom changelog process.

Expected future behavior:

- Parse Conventional Commits on `main`.
- Open or update a release PR.
- Generate changelog entries.
- Tag releases after the release PR merges.
- Optionally publish immutable static-app artifacts or monthly recap archives.

## Secrets

Expected secrets:

| Secret                       | Purpose                                                                                                     |
| ---------------------------- | ----------------------------------------------------------------------------------------------------------- |
| `COPILOT_REQUESTS_PAT`       | Preferred repository secret containing a fine-grained PAT for Copilot CLI with Copilot Requests permission. |
| `COPILOT_GITHUB_TOKEN`       | Alternative secret name accepted by the News hourly workflow.                                               |
| `COPILOT_MODEL`              | Optional Copilot CLI model override; defaults to `claude-sonnet-4.6` for the briefing writer.               |
| `AZURE_OPENAI_ENDPOINT`      | Azure OpenAI endpoint.                                                                                      |
| `AZURE_OPENAI_API_KEY`       | Azure OpenAI API key.                                                                                       |
| `OPENAI_API_KEY`             | Optional alternative provider.                                                                              |
| `NOTIFY_WEBHOOK_URL`         | Optional delivery webhook.                                                                                  |
| `HOME_ASSISTANT_WEBHOOK_URL` | Optional Home Assistant webhook.                                                                            |

Rules:

- Never echo secrets.
- If Copilot CLI is requested without either Copilot token secret, the News hourly workflow logs a warning and uses the deterministic `fake` provider so release-backed state, validation, and Pages automation can still complete.
- Redact prompt/debug logs by default.
- Scope permissions per workflow.
- Use GitHub Environments for deployment approvals if outputs are public.

## Scheduling details

Use a single cron and calculate briefing windows in application code using the configured IANA time zone. This handles daylight-saving transitions better than maintaining separate UTC cron expressions. The implemented cadence is every two hours at minute 7 (`7 */2 * * *`), which is a better fit for the rolling daily briefing and avoids unnecessary AI calls when feeds are quiet.

Recommended behavior:

- Every scheduled run fetches feeds and updates article indexes.
- If local time is near 07:00 and no morning briefing exists for that date, generate morning briefing.
- If local time is near 20:00 and no evening briefing exists for that date, generate evening briefing.
- Generate a rolling current-day briefing from local midnight through the current run.
- Use idempotency keys based on briefing kind, date, and time window.

## Artifact and retention strategy

- Publish current static output to GitHub Pages.
- Keep 35 days of detailed article YAML plus JSON mirrors in Pages data.
- Persist the 35-day Pages data window as a `wazzup-state.zip` asset on the `news-state` GitHub Release.
- `task state:restore` uses `gh release download` when a token is available and falls back to `https://github.com/DevSecNinja/wazzup/releases/download/news-state/wazzup-state.zip` style download when it is not.
- `task pages:build` sets `STATE_REQUIRED=true`, so Pages deployment fails clearly if retained state is unavailable instead of deploying a PWA with missing `public/data/latest.json`.
- Keep compact monthly recap archives in separate GitHub Releases if history matters.
- Upload debug artifacts only for failed runs and redact sensitive data.
- Avoid committing generated hourly YAML/JSON to `main` to prevent repository bloat.
- Avoid a generated-data branch unless release assets prove insufficient; it still creates thousands of commits per year.

## Task automation boundary

Workflow shell logic should live in [Taskfile.yml](../Taskfile.yml) wherever practical. GitHub Actions should call tasks such as `task news:generate`, `task pages:build`, `task pipeline:generate:fixtures`, and `task validate:data` instead of duplicating pipeline commands inline.

`task build:metadata` writes `public/build-info.json` with the current commit, build id, repository URL, and timestamp. It is called by pipeline generation and Pages builds so the footer can link to the deployed commit and the service worker can register with a build-specific cache key.

## Standardized Pages deployment

The scheduled `News hourly` workflow is responsible for mutating release-backed state. It does not deploy Pages directly. After it succeeds, the `Pages` workflow calls the reusable Pages workflow from `DevSecNinja/.github` and restores the `news-state` release asset through `task pages:build` before deployment. The Pages restore path supports unauthenticated release-asset downloads so it works inside the reusable workflow without injecting `GH_TOKEN` into a string input.

Observed failure modes and fixes:

| Failure                                                  | Cause                                                                                              | Fix                                                                                                                   |
| -------------------------------------------------------- | -------------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------- |
| News hourly failed in Copilot CLI                        | `COPILOT_GITHUB_TOKEN` was empty while `AI_PROVIDER=copilot-cli`.                                  | Select effective provider first and fall back to `fake` when no Copilot token secret exists.                          |
| Pages deploy failed validating `public/data/latest.json` | Reusable workflow received empty `GH_TOKEN`, state restore skipped, and `public/data` was missing. | Restore public release asset without a token in Pages builds and make missing retained state fatal for `pages:build`. |

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
- AI provider token absence should not fail scheduled runs; the workflow falls back to the fake provider. Other AI provider failures currently fail the run with captured CLI diagnostics.
- Delivery failures should not roll back successful publication.
- Repeated failures should be visible in `sources/status.json` and workflow summaries.

## Workflow summary output

The implemented News hourly workflow writes a concise GitHub Actions step summary containing:

- Forced briefing kind.
- Requested AI provider.
- Effective AI provider after token fallback.
- State release name.
- Reminder that Pages deployment is handled by the Pages workflow after success.

Target future summary additions:

- Number of feeds configured, fetched, failed, and skipped.
- Number of new, duplicate, and selected items.
- Briefing kinds generated.
- Estimated AI provider cost and token/request usage.
- Published artifact paths.
- Delivery targets attempted and status.
