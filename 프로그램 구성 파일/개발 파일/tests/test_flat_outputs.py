from pathlib import Path

from clipnote_ai import pipeline as pipeline_module
from clipnote_ai.pipeline import TranscriptChunk, VideoNotePipeline
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
    assert any(name.endswith("source 요약.txt") for name in files)
    assert "\n\n" in result.transcript_path.read_text(encoding="utf-8")
    assert "핵심 디테일" in result.summary_path.read_text(encoding="utf-8")
