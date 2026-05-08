# Copilot instructions for Wazzup

Trust the information in this document. Only fall back to repository search if a
command, path, or fact below is missing or proven wrong by an actual error.

## What this repo is

Wazzup is a small **GitHub-native personal news briefing pipeline** plus a
vanilla static **PWA**. A scheduled GitHub Actions workflow fetches RSS/Atom
feeds, ranks items against configured interests, generates English briefings
through an AI provider abstraction, persists rolling state in a GitHub Release
asset, and publishes `public/` to GitHub Pages.

- Backend: **Python** under [src/wazzup](src/wazzup). Single runtime
  dependency: `PyYAML` (see [requirements.txt](requirements.txt)).
- Frontend: vanilla **HTML/CSS/JavaScript** under [public/](public).
- Tests: stdlib **unittest** under [tests/](tests) with RSS fixtures in
  [tests/fixtures/](tests/fixtures).
- Automation: **mise** + **Task** ([Taskfile.yml](Taskfile.yml)). A thin
  [Makefile](Makefile) just shells out to `task`.
- Repo size: small (~10 Python modules, ~10 unit-test modules, a few
  workflows). No `node_modules`, no compiled artifacts, no `requirements-dev.txt`.

## Environment and tooling

The canonical toolchain (Python, Task, dprint, yamlfmt, yamllint, actionlint,
gitleaks, lefthook, zizmor, cocogitto) and its pinned versions live in
[.mise.toml](.mise.toml). Always treat that file as the source of truth; do
not hard-code tool versions in code or docs.

Devcontainer / cloud-agent realities (validated):

- The devcontainer uses the `mise` installed in the shared base image. If an
  existing container reports an older `mise` than [.mise.toml](.mise.toml)
  requires, update/rebuild the base image before relying on `mise install`,
  `mise exec`, or lefthook hooks.
- `mise install` installs the pinned Python, Task, Node.js, Copilot CLI, and
  validation tools. The devcontainer `postCreateCommand` runs
  `mise exec -- task install` so Python dependencies are installed under the
  mise-managed Python.
- `pip install` against the system Python may fail with
  `error: externally-managed-environment` (PEP 668). Use
  `pip install --break-system-packages -r requirements.txt` **or** a venv.
  The `task install` target runs plain `python -m pip install -r
  requirements.txt`, which fails on the system Python for the same reason —
  prefer `mise exec -- task install` or the explicit pip command above when
  not running under mise.
- The unit tests need `PYTHONPATH=src` (the Taskfile sets this globally via
  `env:`; if you invoke `python -m unittest` directly, export it yourself).

## Always-do bootstrap (works in this devcontainer)

```bash
pip install --break-system-packages -r requirements.txt
export PYTHONPATH=src
```

Equivalent on a clean machine or rebuilt devcontainer that has the pinned mise
toolchain installed:

```bash
mise install
mise exec -- task install
```

## Build, test, validate

The CI workflow ([.github/workflows/ci.yml](.github/workflows/ci.yml)) runs,
in order:

1. `task install`           – installs `PyYAML`.
2. `task ci`                – runs `format:check`, `lint`, `test`, `build`.
3. `task pipeline:generate:fixtures` – deterministic briefing from
   `tests/fixtures` with `AI_PROVIDER=fake`.
4. `task validate:data`     – schema/shape checks of `public/data`.

Always reproduce that exact order locally before pushing. The individual
pieces (validated to work in this devcontainer) are:

| Step              | Task target                       | Direct command                                                                                                  |
| ----------------- | --------------------------------- | --------------------------------------------------------------------------------------------------------------- |
| Format check      | `task format:check`               | `python3 scripts/check_format.py`                                                                               |
| Python lint (AST) | `task lint`                       | `python3 scripts/lint.py`                                                                                       |
| Unit tests        | `task test`                       | `PYTHONPATH=src python3 -m unittest discover -s tests`                                                          |
| Compile check     | `task build`                      | `python3 -m compileall -q src scripts`                                                                          |
| Build metadata    | `task build:metadata`             | `PYTHONPATH=src python3 -m wazzup.build_info`                                                                   |
| Fixture pipeline  | `task pipeline:generate:fixtures` | `PYTHONPATH=src AI_PROVIDER=fake python3 -m wazzup.pipeline --fixture-dir tests/fixtures --force-briefing auto` |
| Validate data     | `task validate:data`              | `PYTHONPATH=src python3 -m wazzup.validate_data public/data`                                                    |

Notes / gotchas observed:

- `validate:data` requires `public/data` to already exist – run the pipeline
  (or `task pipeline:generate:fixtures`) first. The fixture run intentionally
  reports `"ok": false` for some sources whose fixtures simulate failures;
  the script itself still exits 0.
- `task news:generate`, `task pages:build`, `task state:restore`, and
  `task state:persist` need `gh` auth + `GITHUB_REPOSITORY` and a real
  `news-state` Release. **Do not run them in PR validation.**

## Project layout

Repo root:

```
.devcontainer/  .github/  config/  docs/  public/  scripts/  src/  tests/
.mise.toml  .lefthook.toml  .yamlfmt.yaml  .yamllint.yaml  dprint.json
Taskfile.yml  Makefile  pyproject.toml  requirements.txt  renovate.json5
README.md  LICENSE  .gitignore
```

Python package [src/wazzup/](src/wazzup):

- [`pipeline.py`](src/wazzup/pipeline.py) – `main()` entrypoint
  (`python -m wazzup.pipeline`); orchestrates fetch → dedupe → score →
  briefing → publish. Console script: `wazzup`.
- [`feeds.py`](src/wazzup/feeds.py) – RSS/Atom fetch and normalization
  (uses fixtures via `--fixture-dir`).
- [`scoring.py`](src/wazzup/scoring.py) – deterministic interest/source/
  freshness scoring.
- [`ai.py`](src/wazzup/ai.py) – AI provider abstraction. Selected by env
  `AI_PROVIDER` (`copilot-cli` or `fake`). `fake` is the default in tests
  and CI.
- [`publisher.py`](src/wazzup/publisher.py) – writes YAML state and JSON
  mirrors under `public/data/`.
- [`validate_data.py`](src/wazzup/validate_data.py) – `wazzup-validate-data`
  console script.
- [`build_info.py`](src/wazzup/build_info.py) – writes static build metadata
  (`public/data/build-info.json`) for the PWA footer and SW cache version.
- [`config.py`](src/wazzup/config.py), [`models.py`](src/wazzup/models.py) –
  YAML config loading and dataclasses.

Configuration consumed at runtime:

- [config/sources.yml](config/sources.yml) – RSS/Atom source registry.
- [config/interests.yml](config/interests.yml) – interests, weights, locale,
  timezone (`Europe/Amsterdam`), retention (35 days).

PWA static assets in [public/](public): `index.html`, `app.js`, `styles.css`,
`sw.js`, `manifest.webmanifest`, `icons/`. Generated data lives under
`public/data/` and is not committed (see `.gitignore`).

GitHub Actions workflows ([.github/workflows/](.github/workflows)):

- `ci.yml` – PR validation (the one you must keep green).
- `lint.yml` – reusable lint pipeline (Markdown / YAML / workflows).
- `news-hourly.yml` – scheduled briefing generation; cadence-gated.
- `pages.yml` – GitHub Pages deploy via reusable workflow.
- `autofix.yml`, `labeler.yml`, `label-sync.yml`, `config-sync.yml` –
  repo automation.

Docs worth reading before non-trivial changes:
[docs/architecture.md](docs/architecture.md),
[docs/requirements.md](docs/requirements.md),
[docs/testing.md](docs/testing.md),
[docs/github-actions.md](docs/github-actions.md), and the three ADRs in
[docs/adr/](docs/adr).

## Pre-PR validation checklist

Before opening a PR, run **exactly** what CI runs:

```bash
pip install --break-system-packages -r requirements.txt   # or: task install
export PYTHONPATH=src
task ci                                  # format:check, lint, test, build
task pipeline:generate:fixtures          # AI_PROVIDER=fake, deterministic
task validate:data
```

If `task` is unavailable, the equivalent direct commands in the table above
produce the same result.

## Conventions

- Conventional Commits are enforced by the commit-msg hook (`cocogitto`).
- Python: prefer `from __future__ import annotations`, stdlib only beyond
  `PyYAML`. Do not add new runtime dependencies without updating both
  [requirements.txt](requirements.txt) and [pyproject.toml](pyproject.toml).
- Keep generated artifacts out of git: `public/data/`, `.state/`, and
  `__pycache__/` are gitignored.
- Tool versions are managed by mise + Renovate annotations
  (`# renovate: datasource=...`) — when bumping a tool, keep the comment
  intact.
