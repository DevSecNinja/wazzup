# ADR 0002: AI execution strategy

## Status

Proposed

## Context

Wazzup needs scheduled AI-assisted summaries from GitHub Actions. Two relevant execution patterns are worth considering:

- GitHub's documented Copilot CLI automation pattern for Actions, using `@github/copilot`, `COPILOT_GITHUB_TOKEN`, `copilot -p`, `--no-ask-user`, and scoped tool permissions.
- Running local models with Ollama inside GitHub Actions for self-contained LLM workflows.

The product should lean toward the Copilot CLI path because it fits the GitHub-native design, but it should not couple the domain pipeline to one AI execution mechanism.

## Decision

Implement AI summarization behind an `AiSummaryProvider` interface.

Preferred provider order for the MVP:

1. Copilot CLI provider for GitHub-native scheduled runs.
2. API provider for Azure OpenAI, OpenAI, GitHub Models, or compatible endpoints when stricter provider control is needed.
3. Ollama, Foundry, or other provider adapters for later experiments, local-model canaries, and privacy-oriented runs.
4. Fake deterministic provider for CI and repeatable tests.

The Copilot CLI provider should:

- Install GitHub Copilot CLI in the Actions runner.
- Authenticate with a fine-grained PAT stored as `COPILOT_REQUESTS_PAT` and exposed as `COPILOT_GITHUB_TOKEN`.
- Run non-interactively with `copilot -p` and `--no-ask-user`.
- Use narrowly scoped `--allow-tool` values.
- Write structured JSON to a temporary output file.
- Validate schema, citations, and size limits before publication.

## Consequences

### Positive

- Keeps the MVP strongly aligned with GitHub Actions and GitHub-native automation.
- Avoids introducing a separate hosted backend for summarization.
- Allows provider changes without rewriting feed, ranking, storage, or frontend code.
- Keeps tests deterministic through the fake provider.

### Negative

- Copilot CLI automation requires a licensed GitHub account and a PAT with Copilot Requests permission.
- CLI behavior can be less predictable than a direct structured-output API and must be validated defensively.
- Usage accounting may be less precise than direct API token accounting.
- Ollama on GitHub-hosted runners can be slow and model downloads can dominate runtime; Foundry or other provider paths will require separate evaluation.

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

- Confirm Copilot license and PAT setup work in scheduled automation.
- Define the first structured summary schema and prompt bundle format.
- Build a small canary workflow comparing Copilot CLI and fake provider output validation.
- Defer Ollama, Foundry, and other provider experiments until the Copilot CLI path is understood.
