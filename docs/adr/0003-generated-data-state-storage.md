# ADR 0003: Generated data state storage

## Status

Accepted and implemented

## Context

The scheduled pipeline generates frequent data: 8 scheduled daytime snapshots plus morning and evening briefings means up to 10 generated outputs per day. Committing those outputs would create roughly 3,650 generated-data commits per year before retries, manual runs, or future recap artifacts.

The system still needs durable state between scheduled runs so the next workflow can publish a rolling 35-day Pages window instead of only the latest run.

## Decision

Do not commit generated article or briefing YAML/JSON to `main`.

Use a dedicated GitHub Release named `news-state` as the durable state store for the rolling Pages data window:

1. The scheduled workflow downloads `wazzup-state.zip` from the `news-state` release if it exists.
2. The workflow extracts the archive into `public/data`.
3. The pipeline fetches feeds, generates the new briefing, and writes updated YAML plus JSON browser mirrors.
4. The pipeline writes a transparency report for the run and enforces the 35-day retention window.
5. The workflow uploads the updated `wazzup-state.zip` release asset with `--clobber` and attaches the latest Markdown transparency report as `wazzup-transparency-report.md` when present.
6. The separate Pages workflow deploys `public` to GitHub Pages through the reusable `DevSecNinja/.github` Pages workflow.

Implemented refinement after the first Pages deployment failure:

- `task state:restore` uses `gh release download` when `GH_TOKEN` or `GITHUB_TOKEN` exists.
- If no token is available, `task state:restore` downloads the public release asset URL directly with `curl`.
- `task pages:build` sets `STATE_REQUIRED=true`; if state cannot be restored, Pages deployment fails explicitly instead of deploying missing `public/data/latest.json`.
- The reusable Pages workflow receives `build-command: ~/.local/bin/mise exec -- task pages:build` without trying to inject `GH_TOKEN` into a string input.
- The Pages reusable workflow later moved to `PYTHONPATH=src python3 scripts/pages_build.py` instead of `mise install`/`task pages:build`, because `github.token` is not reliably available inside reusable workflow string inputs and unauthenticated mise GitHub API calls can hit rate limits before deployment starts.

Do not create one GitHub Release per hour for operational state. That would create up to 8,760 releases per year before retries and manual runs. The mutable `news-state` release remains the hot state store. If human time travel becomes important beyond the 35-day Pages window, add immutable daily or monthly archive/recap releases with concise release bodies and attached snapshots.

The state archive currently contains YAML canonical files and JSON mirrors. YAML remains the operator-facing source of truth; JSON exists so the no-build PWA and simple consumers can fetch native browser data without a YAML parser.

## Consequences

### Positive

- Keeps `main` clean and human-readable.
- Avoids thousands of generated-data commits per year.
- Avoids a long-lived generated-data branch with unrelated history.
- Keeps the state store GitHub-native and easy to inspect/download.
- Lets GitHub Pages deploy from a build artifact instead of source-controlled generated files.

### Negative

- The scheduled workflow needs `contents: write` permission to create/update the release asset.
- Release asset updates are mutable state and need defensive validation before publishing.
- The `news-state` release is operational state, not a semantic product release.
- The Pages workflow depends on the state release being public or otherwise downloadable without a token. This matches the current public deployment assumption.

## Alternatives considered

### Commit generated data to `main`

- Pros: Simple checkout-based state restoration.
- Cons: At least 9,490 generated commits per year, noisy history, larger clones, and release-please/changelog noise risk.

### Commit generated data to a `news` branch

- Pros: Keeps `main` clean.
- Cons: Still creates thousands of commits per year, requires branch-specific workflows, and complicates recovery.

### Pages artifact only

- Pros: Simplest deployment path.
- Cons: Does not provide a durable state input for the next scheduled run.

### One release per hour

- Pros: Easy chronological browsing in GitHub Releases.
- Cons: Up to 8,760 releases per year, noisy release UI, weak app integration, and duplicated state-management complexity.

### One release per day or month

- Pros: Human-friendly archive cadence and good place for recap bodies.
- Cons: Still needs a separate rolling state store for the next scheduled run and is better treated as an archive feature, not the hot state path.

### External database or object storage

- Pros: Better query and state-management capabilities.
- Cons: Adds infrastructure the current architecture intentionally avoids.

## Follow-up decisions

- Add a monthly recap archive format once monthly recaps are implemented.
- Consider a daily recap release if GitHub Releases become the preferred long-term human archive.
- Decide whether `news-state` should be a prerelease forever or hidden behind a naming convention only.
- Add stronger integrity checks for the downloaded state archive before extraction.
- If Wazzup becomes private, revisit token propagation for reusable Pages workflows or move state restoration outside the reusable workflow boundary.
