# Local Environment Setup

Use this reference only for “install environment”, “initialize local runtime”, “set up a new Mac”, or “configure Provider” requests.

## One Command

Require macOS with Homebrew and Git available. Docker Desktop is optional: the 抖音 Sidecar remains preferred, while the local Browser Provider is the Docker-free fallback. The installer may install Homebrew formulas, but it intentionally does not install Homebrew or Docker Desktop themselves.

Run from the installed Skill directory. The command is idempotent and installs only non-credential dependencies:

```bash
python3 scripts/setup_local_environment.py --project /absolute/path/to/research-project
```

It installs Homebrew `ffmpeg`, `whisper-cpp`, Python 3.12, a pinned `bilibili-cli`, a checksum-verified Whisper base model, a separate pinned Playwright runtime for the 抖音 Browser Provider, and a project-local commenter HMAC key in macOS Keychain. The Browser Provider directly bridges cheat-on-content's `douyin-session` adapter. The installer first uses the complete pinned source vendored at `vendor/cheat-on-content/`, then checks approved external installations, and only falls back to a managed checkout when neither is available. It returns the selected source, revision, executable paths, environment variables, and ordered `next_actions`; it never prints the HMAC value.

The upstream checkout and Browser virtual environment are idempotent. A matching pinned checkout is not fetched again, and a matching Browser runtime is not reinstalled. The script stops instead of overwriting a non-Git upstream directory or a managed checkout containing local edits.

Use `--skip-asr`, `--skip-bilibili`, or `--skip-douyin-browser` only for targeted repair and installer smoke tests. The normal first-install command omits all skip flags and installs the complete runtime.

Use the returned B站 CLI path for every VDM command:

```bash
python3 scripts/vdm.py --project /absolute/path/to/research-project \
  --bilibili-cli /absolute/path/from-setup/bili doctor
```

## Required Interactive Steps

Do not attempt to automate, copy, print, or persist cookies.

### B站

After installation, run the returned executable interactively:

```bash
/absolute/path/from-setup/bili login
```

Ask the user to complete QR-code login and confirm completion. Then run `doctor` or a single `sync --pages 1` health check.

### 抖音 Sidecar (preferred)

The installer only checks `http://127.0.0.1:18080/openapi.json`. It intentionally does not build, start, configure, or inspect a Sidecar that may contain credentials. Use the organization-approved local Sidecar deployment and let the user complete its browser/login flow. Once the Sidecar is healthy, run:

```bash
python3 scripts/vdm.py --project /absolute/path/to/research-project doctor
```

Treat `blocked_auth`, `blocked_verification`, `risk_control`, and `schema_drift` as a stop condition. Do not retry within the platform; preserve the checkpoint and use the approved Browser Provider or ask the user to refresh the Sidecar login.

### 抖音 Browser Provider (Docker-free fallback)

The installer returns a dedicated Python path. Use it to open an ordinary, persistent browser window and complete login manually:

    export VDM_DOUYIN_BROWSER_PYTHON=/absolute/path/from-setup/douyin-browser/bin/python
    python3 scripts/vdm.py --project /absolute/path/to/research-project --douyin-provider browser douyin-login --wait-seconds 300

After the window closes, verify the runtime and run a small serial sync:

    python3 scripts/vdm.py --project /absolute/path/to/research-project --douyin-provider browser doctor
    python3 scripts/vdm.py --project /absolute/path/to/research-project --douyin-provider browser sync --creator-id "<creator-id>" --pages 1

Browser Provider reuses the upstream persistent browser session and passive XHR capture for public-video comments. VDM never copies, exports, prints, or writes Cookie/browser-storage values to projects, artifacts, reports, model inputs, or logs; it does not download media, solve CAPTCHA, or claim complete/random comment coverage. This upstream public-page path does not expose a stable raw user ID, so Browser comments use an HMAC of the available display name and carry `commenter_identity_display_name_based`; missing names remain unidentified. Never treat comment IDs as independent users. When ASR is required, supply a locally obtained media file and use `transcript-import`.

Adapter discovery checks these locations in order:

```text
<skill-root>/vendor/cheat-on-content/adapters/perf-data/douyin-session
~/.cc-switch/skills/cheat-on-content/adapters/perf-data/douyin-session
~/.codex/skills/cheat-on-content/adapters/perf-data/douyin-session
~/.agents/skills/cheat-on-content/adapters/perf-data/douyin-session
<state-dir>/upstreams/cheat-on-content/adapters/perf-data/douyin-session
```

The last path is installed automatically at the pinned `CHEAT_COMMIT` only when the vendored and approved external copies are absent. Set `VDM_CHEAT_ROOT` to select another complete source root, or set `VDM_CHEAT_DOUYIN_ADAPTER_DIR` / pass `--cheat-douyin-adapter-dir` for an explicit adapter path. The upstream adapter's creator-center inventory and private metrics are never used for competitor accounts; VDM only reuses its browser-session and public-video comment acquisition path.

After setup, use the `environment` object exactly as returned, then execute the `next_actions` arrays in order. They include the absolute Browser Python, upstream adapter, persistent profile, B站 CLI, interactive login commands, project path, and final `doctor` command. Never convert or log a Keychain secret as part of this handoff.

## Initialize a New Research Project

Run the environment command first, then:

```bash
python3 scripts/vdm.py --project /absolute/path/to/research-project init --name "研究名称"
```

For comments, retrieve the existing Keychain entry only in the process that invokes VDM. Never echo it or put it in `.env`, reports, artifacts, model input, shell history, or chat:

```bash
VDM_COMMENT_HMAC_KEY="$(security find-generic-password \
  -s 'vlog-demand-miner/<project-folder>/commenter-hmac' \
  -a 'VDM_COMMENT_HMAC_KEY' -w)" \
python3 scripts/vdm.py --project /absolute/path/to/research-project \
  --commenter-hmac-key-env VDM_COMMENT_HMAC_KEY <command>
```

## Verification

Require these checks before a live study:

```bash
whisper-cli --version
ffmpeg -version
python3 scripts/vdm.py --project /absolute/path/to/research-project doctor
python3 scripts/vdm.py --project /tmp/vdm-demo demo
```

The environment is ready when ASR tools, B站 CLI, Keychain credential reference, and at least one 抖音 provider is ready: the local Sidecar or the Browser Provider runtime. Platform login remains a user-controlled state, not an installation result.
