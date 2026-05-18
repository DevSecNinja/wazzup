# ADR 0002: AI execution strategy

## Status

Accepted and implemented for the current provider set

## Context

Wazzup needs scheduled AI-assisted summaries from GitHub Actions. Two relevant execution patterns are worth considering:

- GitHub's documented Copilot CLI automation pattern for Actions, using `@github/copilot`, `COPILOT_GITHUB_TOKEN`, `copilot -p`, `--no-ask-user`, and scoped tool permissions.
- Running local models with Ollama inside GitHub Actions for self-contained LLM workflows.

The product should lean toward the Copilot CLI path because it fits the GitHub-native design, but it should not couple the domain pipeline to one AI execution mechanism.

## Decision

Implement AI summarization behind an `AiSummaryProvider` interface.

Preferred provider order:

1. Copilot CLI provider for GitHub-native scheduled runs when a Copilot token secret exists.
2. Fake deterministic provider for CI, repeatable tests, local runs, and tokenless scheduled fallback.
3. API provider for Azure OpenAI, OpenAI, GitHub Models, or compatible endpoints when stricter provider control is needed.
4. Ollama, Foundry, or other provider adapters for later experiments, local-model canaries, and privacy-oriented runs.

The Copilot CLI provider should:

- Install GitHub Copilot CLI in the Actions runner.
- Authenticate with a fine-grained PAT stored as `COPILOT_REQUESTS_PAT` or `COPILOT_GITHUB_TOKEN` and exposed to the CLI as `COPILOT_GITHUB_TOKEN`.
- Run non-interactively with `copilot -p` and `--no-ask-user`.
- Use narrowly scoped `--allow-tool` values.
- Write structured JSON to a temporary output file.
- Validate schema, citations, and size limits before publication.

Implemented safety behavior:

- [../../.github/workflows/news-hourly.yml](../../.github/workflows/news-hourly.yml) selects an effective provider before installing Node or Copilot CLI.
- If `copilot-cli` is requested without either token secret, the workflow logs a warning and uses `AI_PROVIDER=fake`.
- [../../src/wazzup/ai.py](../../src/wazzup/ai.py) checks for `COPILOT_GITHUB_TOKEN` in GitHub Actions and raises an actionable error if the workflow guard is bypassed.
- The provider defaults to model `claude-sonnet-4.6` and the repo-local `wazzup-writer` custom agent, both overridable through environment variables.
- Copilot CLI stdout/stderr is captured and included in sanitized failure diagnostics when the CLI exits non-zero.

## Consequences

### Positive

- Keeps the current implementation strongly aligned with GitHub Actions and GitHub-native automation.
- Avoids introducing a separate hosted backend for summarization.
- Allows provider changes without rewriting feed, ranking, storage, or frontend code.
- Keeps tests deterministic through the fake provider.
- Lets the scheduled pipeline and Pages deployment keep working before Copilot token setup is complete.

### Negative

- Copilot CLI automation requires a licensed GitHub account and a PAT with Copilot Requests permission.
- CLI behavior can be less predictable than a direct structured-output API and must be validated defensively.
- Usage accounting may be less precise than direct API token accounting.
- Ollama on GitHub-hosted runners can be slow and model downloads can dominate runtime; Foundry or other provider paths will require separate evaluation.
- Fake-provider fallback keeps automation green but produces deterministic placeholder-style summaries instead of true AI summaries until Copilot token setup is complete.

## Alternatives considered

### Direct API-only strategy

Use Azure OpenAI, OpenAI, GitHub Models, or another provider API as the only production path.

- Pros: Clear model selection, token accounting, structured-output features, and retry semantics.
- Cons: Less GitHub-native and may require separate provider setup, billing, and policy review.

### Copilot CLI-only strategy

Use Copilot CLI directly throughout the pipeline.

- Pros: Simple GitHub-native automation.
- Cons: Harder to test, harder to swap providers, and more risk if CLI behavior or licensing requirements change.

### Ollama-only strategy

Run local models in Actions only.

- Pros: No external LLM API key and potentially better data locality.
- Cons: Slower on CPU runners, quality varies by model size, and caching/model management adds complexity.

## Follow-up decisions

- Confirm Copilot license and PAT setup work in scheduled automation with a real `COPILOT_REQUESTS_PAT` or `COPILOT_GITHUB_TOKEN` secret. Resolved for the current provider set.
- Define formal structured summary schema files. Runtime validation exists; schema files are deferred.
- Build a small canary workflow comparing Copilot CLI and fake provider output validation.
- Defer Ollama, Foundry, and other provider experiments until the Copilot CLI path is understood.
