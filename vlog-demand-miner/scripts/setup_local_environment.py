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
MODEL_URL = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-base.bin"
MODEL_SHA256 = "60ed5bc3dd14eea856493d334349b405782ddcaf0028d4b5df4088345fba2efe"
MODEL_BYTES = 147_951_465
CHUNK_BYTES = 8 * 1024 * 1024


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


def ensure_bilibili(state_dir: Path) -> dict[str, str]:
    ensure_formula("python@3.12")
    python = Path(run("brew", "--prefix", "python@3.12", capture=True)) / "bin" / "python3.12"
    if not python.is_file():
        raise SetupError("python312_unavailable_after_install")
    source = state_dir / "upstreams" / "bilibili-cli"
    if not source.exists():
        source.parent.mkdir(parents=True, exist_ok=True)
        run("git", "clone", BILIBILI_REPOSITORY, str(source))
    run("git", "-C", str(source), "fetch", "origin", BILIBILI_COMMIT)
    run("git", "-C", str(source), "checkout", "--detach", BILIBILI_COMMIT)
    environment = state_dir / "envs" / "bilibili"
    binary = environment / "bin" / "bili"
    if not binary.is_file():
        run(str(python), "-m", "venv", str(environment))
        run(str(environment / "bin" / "python"), "-m", "pip", "install", "--upgrade", "pip")
        run(str(environment / "bin" / "python"), "-m", "pip", "install", str(source))
    run(str(binary), "--version")
    return {"bilibili_cli": str(binary), "login": "run_bili_login_interactively"}


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


def main() -> int:
    parser = argparse.ArgumentParser(description="Install VDM's local ASR and Bilibili CLI runtime without handling provider credentials.")
    parser.add_argument("--state-dir", default=os.getenv("VDM_STATE_DIR", "~/.local/share/vlog-demand-miner"))
    parser.add_argument("--project", help="Research project directory; creates or reuses its Keychain commenter HMAC reference")
    parser.add_argument("--sidecar-url", default="http://127.0.0.1:18080")
    parser.add_argument("--skip-bilibili", action="store_true")
    args = parser.parse_args()
    if platform.system() != "Darwin":
        print(json.dumps({"status": "unsupported", "error": "macos_runtime_required"}, ensure_ascii=False))
        return 2
    state_dir = Path(args.state_dir).expanduser().resolve()
    try:
        ensure_prerequisites()
        result: dict[str, object] = {"status": "ok", "state_dir": str(state_dir), "asr": ensure_asr(state_dir / "models"), "douyin_sidecar": sidecar_status(args.sidecar_url)}
        if not args.skip_bilibili:
            result["bilibili"] = ensure_bilibili(state_dir)
        if args.project:
            project = Path(args.project).expanduser().resolve()
            project.mkdir(parents=True, exist_ok=True)
            result["commenter_hmac_credential_ref"] = ensure_commenter_secret(project)
        if result["douyin_sidecar"] != "ready":
            result["next_action"] = "start_the_organization_approved_douyin_sidecar_then_complete_manual_login"
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except SetupError as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
