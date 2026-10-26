# Contributing to Tracex

Thanks for helping. Tracex is a research-grade code-search system, so **every change to
retrieval quality has to show its numbers**. This guide covers setup, the quality gates,
and the few conventions that keep the evaluation honest.

## Setup

| Tool | Version |
|---|---|
| Python | 3.12, managed by [uv](https://docs.astral.sh/uv/) |
| Node.js | 22 LTS |
| pnpm | 11 (`corepack enable` picks up `packageManager` from `package.json`) |

```bash
git clone https://github.com/KrishKamra/Tracex.git && cd Tracex

# backend
cd backend && uv sync && uv run pytest && cd ..

# frontend
cd frontend && pnpm install && pnpm test && cd ..
```

Run the stack locally:

```bash
cd backend && TRACEX_REPO=eval/corpora/billing_service uv run uvicorn app.api.main:app --port 8000
cd frontend && pnpm dev          # http://localhost:3000
```

The first run downloads the embedding model (about 300 MB) from the Hugging Face Hub. The test
suites never download models: they use deterministic fakes.

## Quality gates

CI runs exactly these. Run them before opening a PR.

```bash
# backend
cd backend
uv run ruff check .
uv run ruff format --check .
uv run pytest                                   # 142 tests, no network

# frontend
cd frontend
pnpm typecheck && pnpm lint && pnpm test && pnpm build
```

Optional slow check against a real model: `TRACEX_RUN_SLOW=1 uv run pytest -m slow`.

## Conventions

### Commits

[Conventional Commits](https://www.conventionalcommits.org/) scoped to the area:
`feat(retrieval): …`, `fix(api): …`, `docs: …`, `test(frontend): …`. Credit pair
work with `Co-authored-by:` trailers. Signed commits are preferred: the maintainers' commits
show as *Verified*.

### Changing the API contract

The backend schemas and the frontend types are kept in lockstep:

1. Edit `backend/app/api/schemas.py`. The models are strict and reject unknown fields.
2. Mirror the change in `frontend/src/lib/types.ts`.
3. Regenerate the frontend fixtures from the real API so tests exercise true payloads:
   `cd backend && uv run python scripts/capture_frontend_fixtures.py`.
4. Update [`docs/api-spec.md`](docs/api-spec.md).

### Changing retrieval or ranking

> [!IMPORTANT]
> A change that can move rankings needs before/after numbers from the benchmark in the PR.

```bash
cd backend
uv run python -m app.evaluation.benchmark --output eval/reports/billing_service.md \
    --json eval/reports/billing_service.json
uv run --group docs python ../docs/scripts/make_figures.py
```

* Report the **cross-validated** numbers. Never tune weights or thresholds on the gold
  queries and report the same queries.
* Commit the regenerated report and figures together with the code.
* A claim of improvement must survive the paired randomization test with Holm
  correction (see [`docs/benchmarks.md`](docs/benchmarks.md)).

### Adding gold queries

Gold queries are the most valuable contribution: the confidence intervals shrink with every one.
Use the *Retrieval quality* issue template, or edit
[`backend/eval/datasets/billing_service.json`](backend/eval/datasets/billing_service.json) directly:

* Give each query a category (`lexical`, `semantic` or `structural`) and a unique id.
* Grade **2** for the symbol a developer is looking for, and **1** for a direct collaborator
  (caller, callee or owning class).
* Write semantic queries without the target's identifiers.
* `uv run pytest` validates every `symbol_id` against the parsed corpus.

### Adding a language

Implement a `_Extractor` subclass in `backend/app/parser/ast_engine.py`. It needs:

* `is_target`: which nodes are definitions;
* naming, spans, docstrings and call sites;
* scope details.

Register the grammar and file extensions. The traversal, call graph and ranking are
language-agnostic. Add fixtures with exact line assertions, as `tests/test_ast_engine.py` does.

### Frontend

* Keep the design tokens in sync with [`docs/design-system.md`](docs/design-system.md).
  Never hard-code a hex colour in a component.
* Every interactive element needs a keyboard path and an accessible name.
* UI changes need a screenshot (light and dark) in the PR.

## Pull requests

* One logical change per PR, with a description of *why*.
* Green CI, an updated changelog entry under **Unreleased**, and updated docs.
* For retrieval changes, include the before/after table and the significance results.

## Code of Conduct

Participation is governed by the [Contributor Covenant](CODE_OF_CONDUCT.md).
