# Security policy

## Supported versions

| Version | Supported |
|---|---|
| 0.4.x (`main`) | ✔ |
| < 0.4 | ✘ |

## Reporting a vulnerability

**Please do not open a public issue.** Report it privately:

1. **Preferred:** the repository's **Security → Report a vulnerability** form (GitHub
   private vulnerability reporting).
2. **Or:** a private message to a maintainer on GitHub
   ([@KrishKamra](https://github.com/KrishKamra), [@jashkankariya](https://github.com/jashkankariya)).

Please include the affected version or commit, reproduction steps, and the impact you observed.
We aim to acknowledge reports within **3 business days** and to agree a fix and disclosure
timeline with you. We're happy to credit reporters.

## Threat model

Tracex is a **local developer tool**. It indexes source code on the machine it runs on and
serves results to a browser on the same machine.

| Surface | Risk | Built-in mitigation | Your responsibility |
|---|---|---|---|
| **No authentication** | Anyone who can reach the API can search the indexed code and read whole files through `/symbol` | Uvicorn binds to `127.0.0.1` by default; CORS allows only `http://localhost:3000` | Don't expose port 8000 beyond localhost without an authenticating proxy |
| **`POST /api/v1/index`** | Reads any directory the server process can read | `TRACEX_WORKSPACE_ROOT` confines indexing to one tree; the body schema is strict | Set `TRACEX_WORKSPACE_ROOT` whenever the API is reachable by others |
| **Model downloads** | Supply chain through the Hugging Face Hub | `trust_remote_code` is enabled **only** for `jinaai/jina-embeddings-v2-base-code`; other models load as plain weights | Pin model revisions, or pre-download to an internal mirror, in sensitive environments |
| **Indexed content** | Secrets in source files become searchable | Nothing is persisted: the index lives in memory only | Don't index trees containing credentials, or rotate anything found |
| **Dependencies** | Vulnerable transitive packages | Lockfiles (`uv.lock`, `pnpm-lock.yaml`); Dependabot; pnpm build scripts denied by default | Keep dependencies current |
| **Frontend** | XSS through indexed source | Code is rendered as React text nodes, never as HTML; tooltips are text-only | n/a |

## Hardening checklist for shared deployments

- [ ] Put the API behind an authenticating reverse proxy (or keep it on loopback).
- [ ] Set `TRACEX_WORKSPACE_ROOT` and `TRACEX_CORS_ORIGINS` explicitly.
- [ ] Pin model revisions and run with outbound network disabled after the first download.
- [ ] Run the service as an unprivileged user with read-only access to the indexed tree.
