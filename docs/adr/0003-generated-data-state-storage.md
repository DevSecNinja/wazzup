# ADR 0003: Generated data state storage

## Status

Accepted

## Context

The scheduled pipeline generates frequent data: 24 hourly snapshots plus morning and evening briefings means at least 26 generated outputs per day. Committing those outputs would create roughly 9,490 generated-data commits per year before retries, manual runs, or future recap artifacts.

The system still needs durable state between scheduled runs so the next workflow can publish a rolling 35-day Pages window instead of only the latest run.

## Decision

Do not commit generated article or briefing JSON to `main`.

Use a dedicated GitHub Release named `news-state` as the durable state store for the rolling Pages data window:

1. The scheduled workflow downloads `wazzup-state.zip` from the `news-state` release if it exists.
2. The workflow extracts the archive into `public/data`.
3. The pipeline fetches feeds, generates the new briefing, and writes updated JSON.
4. The pipeline enforces the 35-day retention window.
5. The workflow uploads the updated `wazzup-state.zip` release asset with `--clobber`.
6. The workflow deploys `public` to GitHub Pages.

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

### External database or object storage

- Pros: Better query and state-management capabilities.
- Cons: Adds infrastructure the MVP is explicitly avoiding.

## Follow-up decisions

- Add a monthly recap archive format once monthly recaps are implemented.
- Decide whether `news-state` should be a prerelease forever or hidden behind a naming convention only.
- Add stronger integrity checks for the downloaded state archive before extraction.
