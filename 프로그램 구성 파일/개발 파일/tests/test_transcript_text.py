from pathlib import Path

from clipnote_ai.pipeline import TranscriptChunk, VideoNotePipeline


def test_write_transcript_omits_internal_time_labels(tmp_path: Path):
    pipeline = VideoNotePipeline.__new__(VideoNotePipeline)
    chunks = [
        TranscriptChunk(
            index=0,
            start=0,
            end=351,
            path=tmp_path / "audio.mp3",
            clean_text="[00:00:00 - 00:05:51]\n구간: 00:00:00-00:05:51 요즘 뜨거운 주제입니다.",
        )
    ]

    transcript_path = pipeline._write_transcript(tmp_path, chunks)
    text = transcript_path.read_text(encoding="utf-8")

    assert "[00:00:00 - 00:05:51]" not in text
    assert "구간:" not in text
    assert "요즘 뜨거운 주제입니다." in text
