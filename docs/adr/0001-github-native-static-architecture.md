# ADR 0001: GitHub-native static architecture

## Status

Accepted and implemented for the MVP

## Context

The product should collect technology news hourly, generate AI-assisted briefings, and present them to the user without requiring a maintained server or database. The user prefers GitHub-based automation and a minimal frontend. The system should still be designed so a future API, agent integration, or MCP server can reuse the same functionality.

The MVP may publish generated data publicly through GitHub Pages. The implementation should keep 35 days of detailed static data, generate English briefings, start with a PWA-only delivery surface, and use Copilot CLI as the default AI runner.

## Decision

Use GitHub Actions as the scheduled backend and GitHub Pages as the static frontend/data host for the MVP.

The backend pipeline will:

1. Fetch configured feeds hourly.
2. Normalize, deduplicate, and score items.
3. Generate due briefings through an AI provider abstraction.
4. Validate all generated data against versioned contracts.
5. Publish static YAML/JSON and frontend assets to GitHub Pages.
6. Optionally send delivery webhooks after successful publication.

The frontend will be a small static PWA that consumes generated JSON mirrors of the canonical YAML contracts.

Generated data state is stored outside Git history in a dedicated GitHub Release asset, then restored by the Pages workflow and published to GitHub Pages as a build artifact.

Implemented details:

- Backend runtime: Python package under [../../src/wazzup](../../src/wazzup).
- Frontend runtime: static vanilla HTML/CSS/JavaScript under [../../public](../../public).
- Automation boundary: [../../Taskfile.yml](../../Taskfile.yml) and [../../.mise.toml](../../.mise.toml).
- State asset: GitHub Release `news-state`, asset `wazzup-state.zip`.
- Deployment: [../../.github/workflows/news-hourly.yml](../../.github/workflows/news-hourly.yml) mutates release-backed state; [../../.github/workflows/pages.yml](../../.github/workflows/pages.yml) deploys through the reusable `DevSecNinja/.github` Pages workflow.

## Consequences

### Positive

- No always-on backend to maintain.
- Low operational cost.
- Simple deployment and scheduling through GitHub Actions.
- Generated data can be inspected and archived without committing it to `main`.
- Static YAML contracts and JSON mirrors can later become an API surface.

### Negative

- GitHub Actions schedules are best-effort and can be delayed.
- GitHub Pages data may be public depending on repository and account settings.
- Static hosting does not provide true server-side user state.
- Web Push requires additional backend state if implemented later.
- Large generated history can bloat artifacts without retention.
- Public Pages output means generated interests and summarized source choices are visible unless deployment changes later.
- Release asset restore must support both token-authenticated scheduled runs and tokenless public downloads inside reusable Pages deployment.

## Alternatives considered

### Always-on API with database

Run a backend service with a database, scheduler, API, and push notification support.

- Pros: Full control, private data, real push notifications, richer API.
- Cons: More infrastructure, maintenance, cost, and operational complexity.

### Serverless functions plus managed database

Use Azure Functions, Cloudflare Workers, or similar with managed storage.

- Pros: Lower ops than a full server and better API support than static hosting.
- Cons: Still requires cloud resources, secrets, storage provisioning, and deployment complexity.

### GitHub Releases only

Publish each briefing as a GitHub Release asset.

- Pros: Good archive semantics and no custom hosting.
- Cons: Poor app/frontend experience and awkward latest-data consumption.

This differs from the accepted release-backed state decision: releases store the rolling state input, while GitHub Pages remains the user-facing app and data host.

## Follow-up decisions

- Select the implementation runtime and package manager. Resolved: Python, mise, and Task.
- Validate Copilot CLI behavior in scheduled Actions runs. Partially resolved: Copilot CLI is implemented, and missing token secrets now fall back to `fake`.
- Select the first delivery target beyond the PWA.
- Define JSON schemas before writing pipeline logic. Deferred; runtime validators and tests currently protect the contract.
- Replace manual service worker cache versioning with generated build metadata.
