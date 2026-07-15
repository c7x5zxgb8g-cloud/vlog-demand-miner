#!/usr/bin/env python3
"""Create timestamped transcript segments with a local whisper.cpp CLI.

This adapter deliberately stays outside the provider layer: it receives a local
media file and writes only the JSON contract accepted by ``vdm.py
transcript-import``.  The intermediate WAV and SRT live in a caller supplied
temporary directory and are deleted after a successful conversion.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


SRT_BLOCK = re.compile(
    r"^\s*\d+\s*\r?\n"
    r"(?P<start>\d{2}:\d{2}:\d{2},\d{3})\s+-->\s+(?P<end>\d{2}:\d{2}:\d{2},\d{3})\s*\r?\n"
    r"(?P<text>.*?)(?=\r?\n\r?\n|\Z)",
    re.MULTILINE | re.DOTALL,
)


def timestamp_ms(value: str) -> int:
    hours, minutes, seconds_and_millis = value.split(":")
    seconds, millis = seconds_and_millis.split(",")
    return ((int(hours) * 60 + int(minutes)) * 60 + int(seconds)) * 1_000 + int(millis)


def parse_srt(text: str) -> list[dict[str, Any]]:
    segments: list[dict[str, Any]] = []
    for block in SRT_BLOCK.finditer(text):
        content = " ".join(line.strip() for line in block.group("text").splitlines() if line.strip())
        if not content:
            continue
        start_ms = timestamp_ms(block.group("start"))
        end_ms = timestamp_ms(block.group("end"))
        if end_ms < start_ms:
            raise ValueError("srt_end_precedes_start")
        segments.append({"start_ms": start_ms, "end_ms": end_ms, "text": content})
    if not segments:
        raise ValueError("srt_segments_required")
    return segments


def executable(name: str) -> str:
    resolved = shutil.which(name)
    if not resolved:
        raise RuntimeError(f"executable_not_found:{name}")
    return resolved


def transcribe(input_file: Path, output_file: Path, model_file: Path, language: str, threads: int, whisper_bin: str, ffmpeg_bin: str) -> int:
    if not input_file.is_file():
        raise RuntimeError("input_media_required")
    if not model_file.is_file():
        raise RuntimeError("model_file_required")
    output_file.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="vdm-asr-") as temporary:
        work = Path(temporary)
        audio = work / "audio.wav"
        basename = work / "transcript"
        subprocess.run(
            [ffmpeg_bin, "-nostdin", "-y", "-i", str(input_file), "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", str(audio)],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
        subprocess.run(
            # The Homebrew build can advertise Metal while a headless local
            # process cannot allocate a Metal buffer. CPU/BLAS is dependable
            # for a serial pilot and avoids a false successful CLI exit.
            [whisper_bin, "-ng", "-m", str(model_file), "-f", str(audio), "-l", language, "-t", str(threads), "-osrt", "-of", str(basename), "-np"],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
        segments = parse_srt((work / "transcript.srt").read_text(encoding="utf-8"))
    output_file.write_text(json.dumps({"segments": segments}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return len(segments)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run local whisper.cpp and emit VDM timestamped segments JSON.")
    parser.add_argument("--input", required=True, help="Local video or audio file")
    parser.add_argument("--output", required=True, help="Output JSON file with segments")
    parser.add_argument("--model", required=True, help="Local GGML/GGUF Whisper model")
    parser.add_argument("--language", default="zh", help="Spoken language code (default: zh)")
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--whisper-bin", default="whisper-cli")
    parser.add_argument("--ffmpeg-bin", default="ffmpeg")
    args = parser.parse_args()
    try:
        count = transcribe(
            Path(args.input).expanduser(),
            Path(args.output).expanduser(),
            Path(args.model).expanduser(),
            args.language,
            args.threads,
            executable(args.whisper_bin),
            executable(args.ffmpeg_bin),
        )
    except (OSError, RuntimeError, ValueError, subprocess.CalledProcessError) as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps({"status": "ok", "segments": count, "output": str(Path(args.output).expanduser())}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
