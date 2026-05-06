# Wazzup

Wazzup is planned as a GitHub-native personal tech-news briefing app. It collects RSS and podcast sources on a schedule, ranks items against user interests, and publishes concise AI-assisted morning, hourly, and evening briefings.

## Planning documents

- [Product requirements](docs/requirements.md)
- [Architecture](docs/architecture.md)
- [Testing strategy](docs/testing.md)
- [GitHub Actions design](docs/github-actions.md)
- [ADR 0001: GitHub-native static architecture](docs/adr/0001-github-native-static-architecture.md)
- [ADR 0002: AI execution strategy](docs/adr/0002-ai-execution-strategy.md)

## Configuration

- [config/sources.yml](config/sources.yml) maintains the RSS source registry, starting with Microsoft Security Blog, Microsoft Security Blog Threat Intelligence, and NOS Nieuws.

## Proposed MVP

1. Fetch RSS feeds hourly from GitHub Actions.
2. Normalize articles into stable JSON records.
3. Rank articles using configurable interests and source weights.
4. Generate AI-assisted summaries through an AI provider abstraction, with Copilot CLI as the preferred first GitHub-native runner if licensing and token setup are acceptable.
5. Publish static JSON plus a minimal PWA to GitHub Pages.
6. Run unit, integration, contract, and build checks in GitHub Actions.

## Repository status

This repository currently contains requirements and architecture only. Implementation should start after the open product and privacy decisions in [Product requirements](docs/requirements.md#open-decisions) are resolved.