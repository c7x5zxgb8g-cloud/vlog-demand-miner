# Vendored Upstream

This directory contains the functional `cheat-on-content` source used internally by NextTake.

- Repository: `https://github.com/XBuilderLAB/cheat-on-content.git`
- Commit: `9c42fe0c932fe81a12f07428492bdf7ae8488f41`
- Vendored on: `2026-07-17`
- License: MIT, preserved in `LICENSE`
- Local policy: reuse upstream behavior through routing and thin adapters; do not create parallel implementations of existing workflows.

## Packaging Transformations

NextTake applies interface-only packaging changes while preserving the workflow logic:

- the upstream root `SKILL.md` is packaged as `ENGINE.md`;
- nested `skills/*/SKILL.md` files are packaged as `skills/*/WORKFLOW.md` so Codex discovers only NextTake as a public Skill;
- workflow directories use neutral action names such as `initialize`, `ideate`, `predict` and `retro`;
- creator runtime files use the `.nexttake-*` namespace and environment variables use the `NEXTTAKE_*` namespace;
- creator-facing templates translate upstream command names into NextTake natural-language actions;
- the vendor directory is named `content-engine` so runtime paths and diagnostics do not leak the implementation brand.
- upstream promotional READMEs, badges, Star History assets and their generator are omitted because they are not part of the runtime or maintenance contract.

These transformations do not replace the upstream scoring, prediction, publication, retro, persona or recommendation protocols. `MANIFEST.sha256` records the transformed package actually shipped by NextTake.

## Clean Copy Policy

The vendored tree excludes upstream promotional material, Git metadata and generated or private runtime state, including:

- `.git/`
- promotional READMEs, badges and Star History automation
- `__pycache__/` and `*.pyc`
- virtual environments
- browser profiles, auth state, cookies, tokens and debug output
- creator-project content such as private predictions, videos and local state

`MANIFEST.sha256` records the content hashes for the clean vendored tree. It excludes the manifest file itself.

## Local Integration

NextTake keeps this source tree self-contained and points the VDM Douyin Browser Provider at its `douyin-session` adapter by default. Public overrides are `NEXTTAKE_CONTENT_ENGINE_ROOT` and `NEXTTAKE_DOUYIN_ADAPTER_DIR`; upstream-branded compatibility aliases are intentionally not exposed.

NextTake-owned code lives outside this directory. Any future compatibility patch inside the vendored tree must be documented here before the manifest is regenerated.

### Compatibility patches

- `adapters/perf-data/douyin-session/crawler.py` accepts an existing Playwright page and an optional post-navigation checkpoint callback for public comment collection. This lets the NextTake Browser Provider inspect login, verification and risk-control pages before scrolling and reuse the same navigation for public post metadata and comments. The default upstream call signature and behavior remain unchanged.
