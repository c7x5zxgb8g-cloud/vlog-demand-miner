# Local Environment Setup

Use this reference only for “install environment”, “initialize local runtime”, “set up a new Mac”, or “configure Provider” requests.

## One Command

Require macOS with Homebrew and Git available. Docker Desktop is optional: the 抖音 Sidecar remains preferred, while the local Browser Provider is the Docker-free fallback. The installer may install Homebrew formulas, but it intentionally does not install Homebrew or Docker Desktop themselves.

Run from the installed Skill directory. The command is idempotent and installs only non-credential dependencies:

```bash
python3 scripts/setup_local_environment.py --project /absolute/path/to/research-project
```

It installs Homebrew `ffmpeg`, `whisper-cpp`, Python 3.12, a pinned `bilibili-cli`, a checksum-verified Whisper base model, a separate pinned Playwright runtime for the 抖音 Browser Provider, and a project-local commenter HMAC key in macOS Keychain. The Browser Provider uses NextTake's bundled content adapter. The installer first uses the fixed source under `vendor/content-engine/` and falls back to a managed pinned checkout only when the bundled copy is unavailable. It returns the selected revision, executable paths, public environment variables and ordered `next_actions`; it never prints the HMAC value.

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

Ask the user to complete QR-code login and confirm completion. Then run `doctor` or a single `sync --pages 1` health check. NextTake rejects larger page counts. Run one creator account at a time; provider operations and separate CLI processes share the project-level serial request gate, with a random `6-12` second delay after the previous operation completes.

### 抖音 Sidecar (preferred)

The installer only checks `http://127.0.0.1:18080/openapi.json`. It intentionally does not build, start, configure, or inspect a Sidecar that may contain credentials. Use the organization-approved local Sidecar deployment and let the user complete its browser/login flow. A running container is not sufficient evidence: require the NextTake health check to return `status: ok`. Once the Sidecar is healthy, run:

```bash
python3 scripts/vdm.py --project /absolute/path/to/research-project doctor
```

For a known local deployment, explicitly select the Sidecar for the first one-page smoke sync:

```bash
python3 scripts/vdm.py --project /absolute/path/to/research-project \
  --sidecar-url http://127.0.0.1:18080 \
  --douyin-provider sidecar \
  sync --creator-id "<creator-id>" --platform douyin --pages 1
```

Treat `blocked_auth`, `blocked_verification`, `risk_control`, and `schema_drift` as a stop condition. Do not retry within the platform; preserve the checkpoint and use the approved Browser Provider or ask the user to refresh the Sidecar login.

The current Sidecar can resolve a user-provided Douyin profile/share URL and collect a known account, but it does not expose keyword account search. Use the Browser Provider for automatic track-based Douyin account discovery. Do not copy Sidecar cookies into the Browser profile.

### 抖音 Browser Provider (Docker-free fallback)

The installer returns a dedicated Python path. Use it to open an ordinary, persistent browser window and complete login manually:

    export VDM_DOUYIN_BROWSER_PYTHON=/absolute/path/from-setup/douyin-browser/bin/python
    python3 scripts/vdm.py --project /absolute/path/to/research-project --douyin-provider browser douyin-login --wait-seconds 300

After the window closes, verify the runtime and run a small serial sync:

    python3 scripts/vdm.py --project /absolute/path/to/research-project --douyin-provider browser doctor
    python3 scripts/vdm.py --project /absolute/path/to/research-project --douyin-provider browser sync --creator-id "<creator-id>" --pages 1

After successful manual login, automatic account discovery can use the public content search page:

    python3 scripts/vdm.py --project /absolute/path/to/research-project --douyin-provider browser creator-discover --track "首次租房" --platform douyin --limit 3

Browser Provider reuses the upstream persistent browser session and passive XHR capture for public-video comments. VDM never copies, exports, prints, or writes Cookie/browser-storage values to projects, artifacts, reports, model inputs, or logs; it does not download media, solve CAPTCHA, or claim complete/random comment coverage. This upstream public-page path does not expose a stable raw user ID, so Browser comments use an HMAC of the available display name and carry `commenter_identity_display_name_based`; missing names remain unidentified. Never treat comment IDs as independent users. When ASR is required, supply a locally obtained media file and use `transcript-import`.

Adapter discovery checks these locations in order:

```text
<skill-root>/vendor/content-engine/adapters/perf-data/douyin-session
<state-dir>/upstreams/content-engine/adapters/perf-data/douyin-session
```

The managed path is installed automatically at the pinned engine revision only when the bundled copy is absent. Set `NEXTTAKE_CONTENT_ENGINE_ROOT` to select another complete source root, or set `NEXTTAKE_DOUYIN_ADAPTER_DIR` / pass `--douyin-adapter-dir` for an explicit adapter path. The adapter's creator-center inventory and private metrics are never used for competitor accounts; NextTake only uses its browser-session and public-video comment acquisition path.

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

## Acquisition Rate Policy

Live `sync` and `acquire` commands submit Provider operations serially. The default random interval is `6-12` seconds between operation completions and the next operation start, persisted per research project so separate CLI processes cannot accidentally burst. Only platform name and completion time are stored; account identifiers, request parameters, Cookie and Token values are not written to the gate.

Use a more conservative bounded interval when needed:

```bash
python3 scripts/vdm.py --project /absolute/path/to/research-project \
  --request-delay-min-seconds 10 \
  --request-delay-max-seconds 18 \
  sync --creator-id "<creator-id>" --platform bilibili --pages 1
```

The bounds must be numeric and non-negative, with minimum no greater than maximum. Rate controls reduce accidental high frequency; they do not bypass risk control. Stop on authentication expiry, CAPTCHA, verification, `risk_control`, or schema drift.
