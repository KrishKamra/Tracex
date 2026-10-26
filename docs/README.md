# Tracex documentation

| Document | What's inside |
|---|---|
| [Architecture](architecture.md) | System context, indexing and query pipelines, data model, AST chunking, call-graph resolution, ranking math, frontend state, design decisions |
| [Benchmarks](benchmarks.md) | Dataset card, metric definitions, ablations, bootstrap CIs, randomization tests with Holm correction, cross-validated weights, error analysis, latency, threats to validity |
| [API spec](api-spec.md) | Every endpoint with real payloads, query prefixes, error codes, telemetry headers, configuration |
| [Design system](design-system.md) | Tokens, typography, layout, components, motion, syntax mapping, logo usage, accessibility |

Per-package READMEs go deeper on implementation:
[inference](../backend/app/README.md) · [retrieval](../backend/app/retrieval/README.md) ·
[evaluation](../backend/app/evaluation/README.md) · [API](../backend/app/api/README.md) ·
[frontend](../frontend/README.md).

## Assets

```text
docs/
├── assets/
│   ├── tracex-mark.svg          logo (theme-adaptive)
│   ├── tracex-favicon.svg       favicon (also frontend/src/app/icon.svg)
│   ├── tracex-typing.svg        README hero animation
│   ├── social-preview.png       1280×640 GitHub social card
│   ├── palette.svg              design tokens sheet
│   ├── figures/                 benchmark figures, light + dark SVG
│   └── screenshots/             captured from the running app
└── scripts/
    ├── make_figures.py          figures ← backend/eval/reports/*.json
    ├── build_typing_svg.py      tracex-typing.svg
    └── build_palette_svg.py     palette.svg
```

Regenerate the generated assets:

```bash
cd backend
uv run --group docs python ../docs/scripts/make_figures.py
uv run python ../docs/scripts/build_typing_svg.py
uv run python ../docs/scripts/build_palette_svg.py
```
