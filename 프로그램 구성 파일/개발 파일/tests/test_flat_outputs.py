from pathlib import Path

from clipnote_ai import pipeline as pipeline_module
from clipnote_ai.pipeline import AUDIO_EXTENSIONS, TranscriptChunk, VIDEO_EXTENSIONS, VideoNotePipeline
from clipnote_ai.settings import AppSettings


def test_run_writes_video_and_txt_pair_in_output_root(tmp_path: Path, monkeypatch):
    source = tmp_path / "source.mp4"
    source.write_bytes(b"fake-video")
    output_dir = tmp_path / "생성된 노트"

    app = VideoNotePipeline.__new__(VideoNotePipeline)
    app.settings = AppSettings(api_key="sk-test", output_dir=str(output_dir))
    app.ffmpeg = "ffmpeg"
    app.progress = lambda *_args: None

    monkeypatch.setattr(pipeline_module, "get_media_duration", lambda *_args: 12.0)
    monkeypatch.setattr(
        app,
        "_extract_audio_chunks",
        lambda *_args: [
            TranscriptChunk(
                index=0,
                start=0,
                end=12,
                path=tmp_path / "audio.mp3",
                clean_text="첫 문장입니다. 둘째 문장입니다.",
            )
        ],
    )
    monkeypatch.setattr(app, "_transcribe_chunks", lambda _chunks: None)
    monkeypatch.setattr(app, "_clean_chunks", lambda _chunks: None)
    monkeypatch.setattr(app, "_text_response", lambda **_kwargs: "테스트 노트\n\n핵심 디테일을 살린 요약입니다.")

    result = app.run(str(source))
    files = sorted(path.name for path in output_dir.iterdir())

    assert result.output_dir == output_dir
    assert len(files) == 3
    assert any(name.endswith("source.mp4") for name in files)
    assert any(name.endswith("source.txt") for name in files)
    assert result.summary_path.stem.endswith("_\uc694\uc57d")
    assert "\n\n" in result.transcript_path.read_text(encoding="utf-8")
    assert "핵심 디테일" in result.summary_path.read_text(encoding="utf-8")


def test_run_accepts_audio_file_and_keeps_audio_extension(tmp_path: Path, monkeypatch):
    source = tmp_path / "meeting.mp3"
    source.write_bytes(b"fake-audio")
    output_dir = tmp_path / "notes"

    app = VideoNotePipeline.__new__(VideoNotePipeline)
    app.settings = AppSettings(api_key="sk-test", output_dir=str(output_dir))
    app.ffmpeg = "ffmpeg"
    app.progress = lambda *_args: None

    monkeypatch.setattr(pipeline_module, "get_media_duration", lambda *_args: 42.0)
    monkeypatch.setattr(
        app,
        "_extract_audio_chunks",
        lambda *_args: [
            TranscriptChunk(
                index=0,
                start=0,
                end=42,
                path=tmp_path / "chunk.mp3",
                clean_text="회의 녹음입니다. 다음 할 일을 정리합니다.",
            )
        ],
    )
    monkeypatch.setattr(app, "_transcribe_chunks", lambda _chunks: None)
    monkeypatch.setattr(app, "_clean_chunks", lambda _chunks: None)
    monkeypatch.setattr(app, "_text_response", lambda **_kwargs: "회의에서 다음 할 일을 정리했다.")

    result = app.run(str(source))
    files = sorted(path.name for path in output_dir.iterdir())

    assert result.video_path.suffix == ".mp3"
    assert any(name.endswith("meeting.mp3") for name in files)
    assert any(name.endswith("meeting.txt") for name in files)
    assert any(name.endswith("meeting_요약.txt") for name in files)
    assert app._source_kind(str(source)) == "내 컴퓨터 오디오 파일"


def test_unique_output_base_uses_parentheses_for_duplicates(tmp_path: Path):
    pipeline = VideoNotePipeline.__new__(VideoNotePipeline)
    (tmp_path / "2605101200 source.mp4").write_bytes(b"old")

    base = pipeline._unique_output_base(tmp_path, "2605101200 source", ".mp4")

    assert base.name == "2605101200 source (2)"


def test_output_paths_do_not_treat_title_dots_as_extensions(tmp_path: Path):
    base = tmp_path / "2605102002 LOV3 (Feat. Bryan Chase, Okasian)"

    video_path = VideoNotePipeline._output_path(base, ".mp4")
    transcript_path = VideoNotePipeline._output_path(base, ".txt")
    summary_path = VideoNotePipeline._summary_output_path(base)

    assert video_path.name == "2605102002 LOV3 (Feat. Bryan Chase, Okasian).mp4"
    assert transcript_path.name == "2605102002 LOV3 (Feat. Bryan Chase, Okasian).txt"
    assert summary_path.name == "2605102002 LOV3 (Feat. Bryan Chase, Okasian)_요약.txt"
    assert len({video_path, transcript_path, summary_path}) == 3


def test_media_extensions_cover_common_phone_formats():
    assert {".mov", ".mp4", ".3gp", ".m4v"} <= VIDEO_EXTENSIONS
    assert {".mp3", ".m4a", ".amr", ".caf", ".aiff"} <= AUDIO_EXTENSIONS
