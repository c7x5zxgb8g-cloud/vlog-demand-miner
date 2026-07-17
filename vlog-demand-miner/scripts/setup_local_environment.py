#!/usr/bin/env python3
"""Install or verify the local, non-credential VDM runtime on macOS."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import secrets
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from urllib.request import Request, urlopen


BILIBILI_REPOSITORY = "https://github.com/public-clis/bilibili-cli.git"
BILIBILI_COMMIT = "dbe28551930df43b633baa52e9639832aeada967"
CHEAT_REPOSITORY = "https://github.com/XBuilderLAB/cheat-on-content.git"
CHEAT_COMMIT = "9c42fe0c932fe81a12f07428492bdf7ae8488f41"
MODEL_URL = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.bin"
MODEL_SHA256 = "60ed5bc3dd14eea856493d334349b405782ddcaf0028d4b5df4088345fba2efe"
MODEL_BYTES = 147_951_465
CHUNK_BYTES = 8 * 1024 * 1024
PLAYWRIGHT_VERSION = "1.55.0"
SKILL_ROOT = Path(__file__).resolve().parents[1]
VENDORED_CHEAT_ROOT = Path(os.getenv("VDM_CHEAT_ROOT", str(SKILL_ROOT / "vendor" / "cheat-on-content"))).expanduser().resolve()
DEFAULT_CHEAT_DOUYIN_ADAPTER = VENDORED_CHEAT_ROOT / "adapters" / "perf-data" / "douyin-session"
KNOWN_CHEAT_DOUYIN_ADAPTERS = (
    DEFAULT_CHEAT_DOUYIN_ADAPTER,
    Path.home() / ".cc-switch" / "skills" / "cheat-on-content" / "adapters" / "perf-data" / "douyin-session",
    Path.home() / ".codex" / "skills" / "cheat-on-content" / "adapters" / "perf-data" / "douyin-session",
    Path.home() / ".agents" / "skills" / "cheat-on-content" / "adapters" / "perf-data" / "douyin-session",
)


class SetupError(RuntimeError):
    pass


def run(*command: str, capture: bool = False) -> str:
    try:
        completed = subprocess.run(command, check=True, text=True, stdout=subprocess.PIPE if capture else subprocess.DEVNULL, stderr=subprocess.PIPE)
    except FileNotFoundError as exc:
        raise SetupError(f"required_command_not_found:{command[0]}") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or "").strip().splitlines()[-1:] or ["command_failed"]
        raise SetupError(f"command_failed:{command[0]}:{detail[0][:200]}") from exc
    return completed.stdout.strip() if capture else ""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def ensure_formula(formula: str) -> None:
    if subprocess.run(["brew", "list", "--versions", formula], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode != 0:
        run("brew", "install", formula)


def ensure_prerequisites() -> None:
    for command in ("brew", "git"):
        if not shutil.which(command):
            raise SetupError(f"required_command_not_found:{command}")


def ensure_asr(model_dir: Path) -> dict[str, str]:
    for formula in ("ffmpeg", "whisper-cpp"):
        ensure_formula(formula)
    if not shutil.which("ffmpeg") or not shutil.which("whisper-cli"):
        raise SetupError("asr_binaries_unavailable_after_install")
    target = model_dir / "ggml-base.bin"
    if not target.is_file() or sha256(target) != MODEL_SHA256:
        download_model(target)
    return {"ffmpeg": shutil.which("ffmpeg") or "", "whisper_cli": shutil.which("whisper-cli") or "", "model": str(target)}


def download_model(target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="vdm-model-", dir=target.parent) as directory:
        partial = Path(directory) / target.name
        with partial.open("wb") as output:
            for start in range(0, MODEL_BYTES, CHUNK_BYTES):
                end = min(start + CHUNK_BYTES, MODEL_BYTES) - 1
                request = Request(MODEL_URL, headers={"Range": f"bytes={start}-{end}"})
                with urlopen(request, timeout=120) as response:
                    content_range = response.headers.get("Content-Range", "")
                    expected = f"bytes {start}-{end}/{MODEL_BYTES}"
                    block = response.read()
                if content_range != expected or len(block) != end - start + 1:
                    raise SetupError("asr_model_range_validation_failed")
                output.write(block)
        if sha256(partial) != MODEL_SHA256:
            raise SetupError("asr_model_checksum_failed")
        partial.replace(target)


def ensure_python312() -> Path:
    ensure_formula("python@3.12")
    python = Path(run("brew", "--prefix", "python@3.12", capture=True)) / "bin" / "python3.12"
    if not python.is_file():
        raise SetupError("python312_unavailable_after_install")
    return python


def is_douyin_adapter(path: Path) -> bool:
    return (path / "crawler.py").is_file() and (path / "requirements.txt").is_file()


def content_revision(adapter_dir: Path) -> str:
    digest = hashlib.sha256()
    for name in ("crawler.py", "paths.py", "requirements.txt"):
        path = adapter_dir / name
        if path.is_file():
            digest.update(name.encode())
            digest.update(path.read_bytes())
    return f"sha256:{digest.hexdigest()}"


def current_git_commit(source: Path) -> str | None:
    completed = subprocess.run(
        ["git", "-C", str(source), "rev-parse", "HEAD"],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    return completed.stdout.strip() if completed.returncode == 0 else None


def ensure_pinned_checkout(source: Path, repository: str, commit: str) -> None:
    if source.exists() and not (source / ".git").is_dir():
        raise SetupError(f"managed_upstream_path_is_not_git_checkout:{source}")
    if not source.exists():
        source.parent.mkdir(parents=True, exist_ok=True)
        run("git", "clone", repository, str(source))
    dirty = run("git", "-C", str(source), "status", "--porcelain", capture=True)
    if dirty:
        raise SetupError(f"managed_upstream_checkout_has_local_changes:{source}")
    if current_git_commit(source) == commit:
        return
    run("git", "-C", str(source), "fetch", "origin", commit)
    run("git", "-C", str(source), "checkout", "--detach", commit)


def resolve_cheat_douyin_adapter(state_dir: Path, configured: str | None = None) -> dict[str, str]:
    if configured:
        adapter = Path(configured).expanduser().resolve()
        if not is_douyin_adapter(adapter):
            raise SetupError(f"configured_cheat_douyin_adapter_invalid:{adapter}")
        return {"path": str(adapter), "source": "configured", "revision": content_revision(adapter)}
    for candidate in KNOWN_CHEAT_DOUYIN_ADAPTERS:
        adapter = candidate.expanduser().resolve()
        if is_douyin_adapter(adapter):
            return {"path": str(adapter), "source": "discovered", "revision": content_revision(adapter)}
    source = state_dir / "upstreams" / "cheat-on-content"
    ensure_pinned_checkout(source, CHEAT_REPOSITORY, CHEAT_COMMIT)
    adapter = source / "adapters" / "perf-data" / "douyin-session"
    if not is_douyin_adapter(adapter):
        raise SetupError("pinned_cheat_douyin_session_adapter_missing")
    return {"path": str(adapter), "source": "managed_pinned_checkout", "repository": CHEAT_REPOSITORY, "commit": CHEAT_COMMIT, "revision": content_revision(adapter)}


def browser_runtime_ready(executable: Path) -> bool:
    if not executable.is_file():
        return False
    probe = (
        "from pathlib import Path; from playwright.sync_api import sync_playwright; "
        "p=sync_playwright().start(); x=p.chromium.executable_path; p.stop(); print(x)"
    )
    try:
        browser = Path(run(str(executable), "-c", probe, capture=True))
    except SetupError:
        return False
    return browser.is_file()


def ensure_douyin_browser(state_dir: Path, upstream: dict[str, str]) -> dict[str, str]:
    adapter_dir = Path(upstream["path"])
    requirements = adapter_dir / "requirements.txt"
    if not is_douyin_adapter(adapter_dir):
        raise SetupError("cheat_douyin_session_adapter_required")
    python = ensure_python312()
    environment = state_dir / "envs" / "douyin-browser"
    executable = environment / "bin" / "python"
    marker = environment / ".vdm-browser-runtime.json"
    runtime_spec = {
        "playwright": PLAYWRIGHT_VERSION,
        "requirements_sha256": sha256(requirements),
        "upstream_revision": upstream["revision"],
    }
    if not executable.is_file():
        run(str(python), "-m", "venv", str(environment))
    installed_spec = None
    if marker.is_file():
        try:
            installed_spec = json.loads(marker.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    if installed_spec != runtime_spec or not browser_runtime_ready(executable):
        run(str(executable), "-m", "pip", "install", "--upgrade", "pip")
        run(str(executable), "-m", "pip", "install", f"playwright=={PLAYWRIGHT_VERSION}")
        run(str(executable), "-m", "pip", "install", "-r", str(requirements))
        run(str(executable), "-m", "playwright", "install", "chromium")
        marker.write_text(json.dumps(runtime_spec, sort_keys=True) + "\n", encoding="utf-8")
    if not browser_runtime_ready(executable):
        raise SetupError("douyin_browser_runtime_unavailable_after_install")
    return {
        "python": str(executable),
        "runtime": "playwright-chromium",
        "upstream_adapter": str(adapter_dir),
        "upstream_source": upstream["source"],
        "upstream_revision": upstream["revision"],
        "upstream_commit": upstream.get("commit", "unversioned_existing_install"),
        "login": "run_vdm_douyin_login_interactively",
    }


def ensure_bilibili(state_dir: Path) -> dict[str, str]:
    python = ensure_python312()
    source = state_dir / "upstreams" / "bilibili-cli"
    ensure_pinned_checkout(source, BILIBILI_REPOSITORY, BILIBILI_COMMIT)
    environment = state_dir / "envs" / "bilibili"
    binary = environment / "bin" / "bili"
    if not binary.is_file():
        run(str(python), "-m", "venv", str(environment))
        run(str(environment / "bin" / "python"), "-m", "pip", "install", "--upgrade", "pip")
        run(str(environment / "bin" / "python"), "-m", "pip", "install", str(source))
    run(str(binary), "--version")
    return {"bilibili_cli": str(binary), "repository": BILIBILI_REPOSITORY, "commit": BILIBILI_COMMIT, "login": "run_bili_login_interactively"}


def ensure_commenter_secret(project: Path) -> str:
    if platform.system() != "Darwin":
        raise SetupError("macos_keychain_required_for_project_commenter_secret")
    service = f"vlog-demand-miner/{project.name}/commenter-hmac"
    account = "VDM_COMMENT_HMAC_KEY"
    found = subprocess.run(["security", "find-generic-password", "-s", service, "-a", account], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if found.returncode != 0:
        run("security", "add-generic-password", "-U", "-s", service, "-a", account, "-w", secrets.token_urlsafe(48))
    return service


def sidecar_status(url: str) -> str:
    try:
        with urlopen(f"{url.rstrip('/')}/openapi.json", timeout=5) as response:
            return "ready" if response.status == 200 else "unavailable"
    except OSError:
        return "needs_approved_logged_in_sidecar"


def build_next_actions(
    *, state_dir: Path, project: Path | None, skill_root: Path,
    browser: dict[str, object] | None, bilibili: dict[str, object] | None,
) -> tuple[dict[str, str], list[dict[str, object]]]:
    environment: dict[str, str] = {}
    actions: list[dict[str, object]] = []
    project_path = str(project or state_dir / "example-project")
    if browser:
        environment.update({
            "VDM_DOUYIN_BROWSER_PYTHON": str(browser["python"]),
            "VDM_CHEAT_DOUYIN_ADAPTER_DIR": str(browser["upstream_adapter"]),
            "VDM_CHEAT_DOUYIN_ADAPTER_REVISION": str(browser["upstream_revision"]),
            "VDM_DOUYIN_BROWSER_PROFILE_DIR": str(state_dir / "browser-profiles" / "douyin"),
        })
        actions.append({
            "name": "douyin_browser_login",
            "interactive": True,
            "env": environment.copy(),
            "argv": [sys.executable, str(skill_root / "scripts" / "vdm.py"), "--project", project_path, "--douyin-provider", "browser", "douyin-login", "--wait-seconds", "300"],
        })
    if bilibili:
        environment["VDM_BILIBILI_CLI"] = str(bilibili["bilibili_cli"])
        actions.append({"name": "bilibili_login", "interactive": True, "argv": [str(bilibili["bilibili_cli"]), "login"]})
    actions.append({
        "name": "doctor",
        "interactive": False,
        "env": environment.copy(),
        "argv": [sys.executable, str(skill_root / "scripts" / "vdm.py"), "--project", project_path, "doctor"],
    })
    return environment, actions


def main() -> int:
    parser = argparse.ArgumentParser(description="Install VDM's local ASR, Browser Provider, and Bilibili CLI runtime without handling provider credentials.")
    parser.add_argument("--state-dir", default=os.getenv("VDM_STATE_DIR", "~/.local/share/vlog-demand-miner"))
    parser.add_argument("--project", help="Research project directory; creates or reuses its Keychain commenter HMAC reference")
    parser.add_argument("--sidecar-url", default="http://127.0.0.1:18080")
    parser.add_argument("--skip-asr", action="store_true", help="Repair/test providers without changing the default full installation")
    parser.add_argument("--skip-bilibili", action="store_true")
    parser.add_argument("--skip-douyin-browser", action="store_true")
    parser.add_argument("--cheat-douyin-adapter-dir", default=os.getenv("VDM_CHEAT_DOUYIN_ADAPTER_DIR"))
    args = parser.parse_args()
    if platform.system() != "Darwin":
        print(json.dumps({"status": "unsupported", "error": "macos_runtime_required"}, ensure_ascii=False))
        return 2
    state_dir = Path(args.state_dir).expanduser().resolve()
    try:
        ensure_prerequisites()
        result: dict[str, object] = {"status": "ok", "state_dir": str(state_dir), "douyin_sidecar": sidecar_status(args.sidecar_url)}
        if not args.skip_asr:
            result["asr"] = ensure_asr(state_dir / "models")
        if not args.skip_douyin_browser:
            upstream = resolve_cheat_douyin_adapter(state_dir, args.cheat_douyin_adapter_dir)
            result["douyin_browser"] = ensure_douyin_browser(state_dir, upstream)
        if not args.skip_bilibili:
            result["bilibili"] = ensure_bilibili(state_dir)
        project = Path(args.project).expanduser().resolve() if args.project else None
        if project:
            project.mkdir(parents=True, exist_ok=True)
            result["commenter_hmac_credential_ref"] = ensure_commenter_secret(project)
        skill_root = Path(__file__).resolve().parents[1]
        browser = result.get("douyin_browser") if isinstance(result.get("douyin_browser"), dict) else None
        bilibili = result.get("bilibili") if isinstance(result.get("bilibili"), dict) else None
        environment, actions = build_next_actions(state_dir=state_dir, project=project, skill_root=skill_root, browser=browser, bilibili=bilibili)
        result["environment"] = environment
        result["next_actions"] = actions
        if result["douyin_sidecar"] != "ready":
            result["next_action"] = "complete_douyin_browser_manual_login_or_start_the_organization_approved_sidecar" if browser else "start_the_organization_approved_sidecar"
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except SetupError as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
