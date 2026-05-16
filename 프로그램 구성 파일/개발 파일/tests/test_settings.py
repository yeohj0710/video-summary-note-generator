import json
from pathlib import Path

from clipnote_ai import settings as settings_module
from clipnote_ai.settings import AppSettings, load_settings, save_settings


def test_saved_default_output_dir_follows_current_app_root(tmp_path: Path, monkeypatch):
    appdata = tmp_path / "appdata"
    old_root = tmp_path / "old-copy"
    new_root = tmp_path / "new-copy"
    new_root.mkdir()
    config_dir = appdata / settings_module.APP_NAME
    config_dir.mkdir(parents=True)
    (config_dir / "settings.json").write_text(
        json.dumps({"output_dir": str(old_root / "생성된 노트")}, ensure_ascii=False),
        encoding="utf-8",
    )

    monkeypatch.setenv("APPDATA", str(appdata))
    monkeypatch.chdir(new_root)

    loaded = load_settings()

    assert loaded.output_dir == str(new_root / "생성된 노트")


def test_save_settings_does_not_persist_default_output_dir(tmp_path: Path, monkeypatch):
    appdata = tmp_path / "appdata"
    root = tmp_path / "app-copy"
    root.mkdir()
    monkeypatch.setenv("APPDATA", str(appdata))
    monkeypatch.chdir(root)

    save_settings(AppSettings(output_dir=str(root / "생성된 노트")))

    payload = json.loads((appdata / settings_module.APP_NAME / "settings.json").read_text(encoding="utf-8"))
    assert payload["output_dir"] == ""


def test_save_settings_keeps_custom_output_dir(tmp_path: Path, monkeypatch):
    appdata = tmp_path / "appdata"
    root = tmp_path / "app-copy"
    custom = tmp_path / "my-results"
    root.mkdir()
    monkeypatch.setenv("APPDATA", str(appdata))
    monkeypatch.chdir(root)

    save_settings(AppSettings(output_dir=str(custom), output_dir_custom=True))

    payload = json.loads((appdata / settings_module.APP_NAME / "settings.json").read_text(encoding="utf-8"))
    assert payload["output_dir"] == str(custom)


def test_custom_output_dir_named_like_default_is_preserved(tmp_path: Path, monkeypatch):
    appdata = tmp_path / "appdata"
    root = tmp_path / "app-copy"
    custom = tmp_path / "archive" / "생성된 노트"
    root.mkdir()
    monkeypatch.setenv("APPDATA", str(appdata))
    monkeypatch.chdir(root)
    config_dir = appdata / settings_module.APP_NAME
    config_dir.mkdir(parents=True)
    (config_dir / "settings.json").write_text(
        json.dumps({"output_dir": str(custom), "output_dir_custom": True}, ensure_ascii=False),
        encoding="utf-8",
    )

    loaded = load_settings()

    assert loaded.output_dir == str(custom)


def test_transcript_polish_is_enabled_by_default():
    assert AppSettings().polish_transcript is True


def test_summary_creation_is_enabled_by_default():
    assert AppSettings().create_summary is True
