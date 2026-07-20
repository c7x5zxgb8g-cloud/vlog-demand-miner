# Vendored Upstream

This directory contains the complete `cheat-on-content` source used internally by NextTake.

- Repository: `https://github.com/XBuilderLAB/cheat-on-content.git`
- Commit: `9c42fe0c932fe81a12f07428492bdf7ae8488f41`
- Vendored on: `2026-07-17`
- License: MIT, preserved in `LICENSE`
- Local policy: reuse upstream behavior through routing and thin adapters; do not create parallel implementations of existing workflows.

## Packaging Transformations

NextTake applies interface-only packaging changes while preserving the workflow logic:

- the upstream root `SKILL.md` is packaged as `ENGINE.md`;
- nested `skills/*/SKILL.md` files are packaged as `skills/*/WORKFLOW.md` so Codex discovers only NextTake as a public Skill;
- creator-facing templates translate upstream command names into NextTake natural-language actions;
- the vendor directory is named `content-engine` so runtime paths and diagnostics do not leak the implementation brand.

These transformations do not replace the upstream scoring, prediction, publication, retro, persona or recommendation protocols. `MANIFEST.sha256` records the transformed package actually shipped by NextTake.

## Clean Copy Policy

The vendored tree excludes upstream Git metadata and generated or private runtime state, including:

- `.git/`
- `__pycache__/` and `*.pyc`
- virtual environments
- browser profiles, auth state, cookies, tokens and debug output
- creator-project content such as private predictions, videos and local state

`MANIFEST.sha256` records the content hashes for the clean vendored tree. It excludes the manifest file itself.

## Local Integration

NextTake keeps this source tree self-contained and points the VDM Douyin Browser Provider at its `douyin-session` adapter by default. Public overrides are `NEXTTAKE_CONTENT_ENGINE_ROOT` and `NEXTTAKE_DOUYIN_ADAPTER_DIR`; legacy environment names remain read-only compatibility aliases and are not documented in the public interface.

NextTake-owned code lives outside this directory. Any future compatibility patch inside the vendored tree must be documented here before the manifest is regenerated.
