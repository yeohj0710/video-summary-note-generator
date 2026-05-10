from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


INVALID_FILENAME_CHARS = r'<>:"/\|?*'


def resource_path(*parts: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    return base.joinpath(*parts)


def sanitize_filename(value: str, fallback: str = "media") -> str:
    cleaned = "".join("_" if ch in INVALID_FILENAME_CHARS else ch for ch in value)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    cleaned = _truncate_filename(cleaned, 90)
    return cleaned or fallback


def _truncate_filename(value: str, max_length: int) -> str:
    if len(value) <= max_length:
        return value.strip(" .")

    truncated = value[:max_length].rstrip(" .-_")
    best_boundary = max(
        truncated.rfind(mark)
        for mark in (
            " - ",
            " | ",
            " / ",
            ") ",
            "] ",
            "} ",
            ". ",
            ", ",
        )
    )
    if best_boundary >= max_length * 0.55:
        truncated = truncated[: best_boundary + 1].rstrip(" .-_")

    truncated = _drop_unclosed_tail(truncated, "(", ")")
    truncated = _drop_unclosed_tail(truncated, "[", "]")
    truncated = _drop_unclosed_tail(truncated, "{", "}")
    return truncated.strip(" .-_") or value[:max_length].strip(" .-_")


def _drop_unclosed_tail(value: str, opener: str, closer: str) -> str:
    if value.count(opener) <= value.count(closer):
        return value
    cut = value.rfind(opener)
    if cut <= 0:
        return value
    return value[:cut].rstrip(" .-_")


def format_timecode(seconds: float | int) -> str:
    total = max(0, int(round(float(seconds))))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def parse_timecode(value: str) -> int | None:
    parts = value.strip().split(":")
    if len(parts) not in (2, 3):
        return None
    try:
        numbers = [int(float(part)) for part in parts]
    except ValueError:
        return None
    if len(numbers) == 2:
        minutes, seconds = numbers
        return minutes * 60 + seconds
    hours, minutes, seconds = numbers
    return hours * 3600 + minutes * 60 + seconds


def extract_json_object(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?", "", stripped, flags=re.IGNORECASE).strip()
        stripped = re.sub(r"```$", "", stripped).strip()
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        pass

    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("JSON 객체를 찾지 못했습니다.")
    return json.loads(stripped[start : end + 1])


def find_ffmpeg() -> Path:
    env_path = os.getenv("FFMPEG_BINARY")
    if env_path and Path(env_path).exists():
        return Path(env_path)

    try:
        import imageio_ffmpeg

        bundled = Path(imageio_ffmpeg.get_ffmpeg_exe())
        if bundled.exists():
            return bundled
    except Exception:
        pass

    found = shutil.which("ffmpeg")
    if found:
        return Path(found)
    raise RuntimeError("FFmpeg을 찾을 수 없습니다. ffmpeg 설치 또는 재빌드가 필요합니다.")


def run_process(args: list[str | os.PathLike[str]], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        [str(arg) for arg in args],
        cwd=str(cwd) if cwd else None,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
    )
    return completed


def get_media_duration(media_path: Path, ffmpeg_path: Path | None = None) -> float:
    ffmpeg = ffmpeg_path or find_ffmpeg()
    completed = run_process([ffmpeg, "-i", media_path])
    output = f"{completed.stdout}\n{completed.stderr}"
    match = re.search(r"Duration:\s*(\d{2}):(\d{2}):(\d{2}(?:\.\d+)?)", output)
    if not match:
        raise RuntimeError("영상 길이를 읽지 못했습니다.")
    hours, minutes, seconds = match.groups()
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def suggest_scene_count(duration_seconds: float, min_count: int = 4, max_count: int = 24) -> int:
    duration = max(1.0, float(duration_seconds))
    if duration <= 90:
        target = round(duration / 11)
    elif duration <= 600:
        target = round(duration / 55) + 4
    elif duration <= 1800:
        target = round(duration / 150) + 6
    else:
        target = round(duration / 300) + 10
    return max(min_count, min(max_count, int(target)))


def clamp_seconds(seconds: float | int, duration: float) -> int:
    upper = max(0, int(duration) - 1)
    return max(0, min(upper, int(round(float(seconds)))))

