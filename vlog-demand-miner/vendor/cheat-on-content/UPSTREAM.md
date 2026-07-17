# Vendored Upstream

This directory preserves the complete `cheat-on-content` source used by NextTake.

- Repository: `https://github.com/XBuilderLAB/cheat-on-content.git`
- Commit: `9c42fe0c932fe81a12f07428492bdf7ae8488f41`
- Vendored on: `2026-07-17`
- License: MIT, preserved in `LICENSE`
- Local policy: reuse upstream behavior through routing and thin adapters; do not create parallel implementations of existing `cheat-*` workflows.

## Clean Copy Policy

The vendored tree excludes upstream Git metadata and generated or private runtime state, including:

- `.git/`
- `__pycache__/` and `*.pyc`
- virtual environments
- browser profiles, auth state, cookies, tokens and debug output
- creator-project content such as private predictions, videos and local state

`MANIFEST.sha256` records the content hashes for the clean vendored tree. It excludes the manifest file itself.

## Local Integration

NextTake keeps this source tree self-contained and points the VDM Douyin Browser Provider at its `douyin-session` adapter by default. `VDM_CHEAT_ROOT` and `VDM_CHEAT_DOUYIN_ADAPTER_DIR` remain available as explicit overrides.

NextTake-owned code lives outside this directory. Any future compatibility patch inside the vendored tree must be documented here before the manifest is regenerated.
