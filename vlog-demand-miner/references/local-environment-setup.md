# Local Environment Setup

Use this reference only for “install environment”, “initialize local runtime”, “set up a new Mac”, or “configure Provider” requests.

## One Command

Require macOS with Homebrew and Git available. Require Docker Desktop only for the 抖音 Sidecar. The installer may install Homebrew formulas, but it intentionally does not install Homebrew or Docker Desktop themselves.

Run from the installed Skill directory. The command is idempotent and installs only non-credential dependencies:

```bash
python3 scripts/setup_local_environment.py --project /absolute/path/to/research-project
```

It installs Homebrew `ffmpeg`, `whisper-cpp`, Python 3.12, a pinned `bilibili-cli`, a checksum-verified Whisper base model, and a project-local commenter HMAC key in macOS Keychain. It returns the B站 CLI path and never prints the HMAC value.

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

### 抖音

The installer only checks `http://127.0.0.1:18080/openapi.json`. It intentionally does not build, start, configure, or inspect a Sidecar that may contain credentials. Use the organization-approved local Sidecar deployment and let the user complete its browser/login flow. Once the Sidecar is healthy, run:

```bash
python3 scripts/vdm.py --project /absolute/path/to/research-project doctor
```

Treat `blocked_auth`, `blocked_verification`, `risk_control`, and `schema_drift` as a stop condition. Do not retry within the platform; preserve the checkpoint and ask the user to refresh the login or use the approved Browser Provider.

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

The environment is ready when ASR tools, B站 CLI, Keychain credential reference, and the local Sidecar health check are ready. Platform login remains a user-controlled state, not an installation result.
