# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- `docs/`: architecture, API spec, design system, and a benchmark report with nine
  light/dark figures generated from the committed evaluation JSON.
- Brand assets: a theme-adaptive logo, the favicon, a self-hosted typing animation and a social card.
- Project files: Apache-2.0 license, Code of Conduct, contributing guide, security
  policy, citation metadata, issue/PR templates, CODEOWNERS, Dependabot and CI workflows.
- `backend/scripts/capture_frontend_fixtures.py`, which regenerates frontend test fixtures from the real API.

### Changed
- The header logo and favicon now use the new Tracex mark.

## [0.4.0] - 2026-10-26: Workspace UI

### Added
- Next.js 15 workspace rebuilt from the golden UI reference: prefix-aware command bar,
  explainable RRF popover, grammar-accurate code inspector with trace mode and line
  permalinks, React Flow topology graph with `+N` expansion, telemetry, keyboard model.
- 55 Vitest tests over payloads captured from the API.

### Fixed
- Popovers could not open (React and the outside-click handler share `document`).
- Graph double-click never fired (unmeasured node objects briefly hidden by React Flow;
  d3-zoom dblclick swallowed the event).

## [0.3.0] - 2026-10-26: REST API

### Added
- FastAPI service: `/search`, `/symbol/{id}`, `/graph/{id}`, `/index`, `/health` with
  strict Pydantic v2 schemas and `Server-Timing` telemetry.
- `@symbol` / `#route` / `/path` query prefixes; exact per-call-site resolution.

## [0.2.0] - 2026-10-26: Hybrid retrieval and evaluation

### Added
- BM25 (sub-token), exact dense search, NetworkX call graph with type-aware name
  resolution, weighted RRF, cross-encoder reranking.
- Evaluation suite: MRR/NDCG/Recall/P/MAP/Hit, bootstrap CIs, paired randomization
  tests with Holm correction, cross-validated fusion weights; a 37-query gold set.

## [0.1.0] - 2026-10-26: Inference layer

### Added
- Tree-sitter AST chunking for Python, TypeScript and TSX; code-aware sub-tokenizer;
  structured serialization; dense embedder with device detection and fallback.

[Unreleased]: https://github.com/KrishKamra/Tracex/compare/v0.4.0...HEAD
[0.4.0]: https://github.com/KrishKamra/Tracex/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/KrishKamra/Tracex/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/KrishKamra/Tracex/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/KrishKamra/Tracex/releases/tag/v0.1.0
