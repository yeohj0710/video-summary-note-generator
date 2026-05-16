from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path


APP_NAME = "MediaSummaryNoteGenerator"
DEFAULT_TEXT_MODEL = "gpt-5-nano"
DEFAULT_OUTPUT_FOLDER_NAME = "생성된 노트"
DEFAULT_DOWNLOAD_FOLDER_NAME = "다운로드한 영상"


@dataclass
class AppSettings:
    api_key: str = ""
    save_api_key: bool = False
    transcription_model: str = "gpt-4o-mini-transcribe"
    text_model: str = DEFAULT_TEXT_MODEL
    polish_transcript: bool = True
    create_summary: bool = True
    output_dir: str = ""
    output_dir_custom: bool = False
    auto_summary_sentences: bool = True
    summary_sentence_count: int = 30
    auto_scene_count: bool = True
    fixed_scene_count: int = 10
    min_scene_count: int = 4
    max_scene_count: int = 24
    use_browser_cookies: bool = False
    cookie_browser: str = "chrome"


def app_data_dir() -> Path:
    base = os.getenv("APPDATA")
    if base:
        return Path(base) / APP_NAME
    return Path.home() / f".{APP_NAME.lower()}"


def app_root_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path.cwd()


def default_output_dir() -> Path:
    return app_root_dir() / DEFAULT_OUTPUT_FOLDER_NAME


def default_download_dir() -> Path:
    return app_root_dir() / DEFAULT_DOWNLOAD_FOLDER_NAME


def settings_path() -> Path:
    return app_data_dir() / "settings.json"


def _is_default_output_like(path_text: str) -> bool:
    if not path_text.strip():
        return True
    try:
        path = Path(path_text).expanduser()
    except (OSError, ValueError):
        return False
    return path.name == DEFAULT_OUTPUT_FOLDER_NAME


def _is_current_default_output_dir(path_text: str) -> bool:
    if not path_text.strip():
        return True
    try:
        path = Path(path_text).expanduser().resolve()
        default_path = default_output_dir().expanduser().resolve()
    except (OSError, ValueError):
        return False
    return os.path.normcase(str(path)) == os.path.normcase(str(default_path))


def is_current_default_output_dir(path_text: str) -> bool:
    return _is_current_default_output_dir(path_text)


def load_settings() -> AppSettings:
    path = settings_path()
    data: dict[str, object] = {}
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}

    settings = AppSettings()
    for key, value in data.items():
        if hasattr(settings, key):
            setattr(settings, key, value)

    if not settings.output_dir:
        settings.output_dir = str(default_output_dir())
        settings.output_dir_custom = False
    elif not settings.output_dir_custom and _is_default_output_like(str(settings.output_dir)):
        settings.output_dir = str(default_output_dir())
    if settings.text_model == "gpt-4.1-mini":
        settings.text_model = DEFAULT_TEXT_MODEL
    if not settings.save_api_key:
        settings.api_key = ""
    return settings


def save_settings(settings: AppSettings) -> None:
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = asdict(settings)
    if not settings.save_api_key:
        payload["api_key"] = ""
    if _is_current_default_output_dir(str(settings.output_dir)):
        payload["output_dir"] = ""
        payload["output_dir_custom"] = False
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

