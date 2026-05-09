from pathlib import Path

from clipnote_ai.pipeline import Scene, TranscriptChunk, VideoNotePipeline


def test_attach_full_transcript_to_scenes_keeps_every_sentence(tmp_path: Path):
    pipeline = VideoNotePipeline.__new__(VideoNotePipeline)
    scenes = [
        Scene(index=1, seconds=10, timecode="00:00:10", heading="Intro", summary="", quote="", why="", script="short"),
        Scene(index=2, seconds=40, timecode="00:00:40", heading="Next", summary="", quote="", why="", script="short"),
    ]
    chunks = [
        TranscriptChunk(
            index=0,
            start=0,
            end=60,
            path=tmp_path / "audio.mp3",
            clean_text="First sentence. Second sentence. Third sentence. Fourth sentence.",
        )
    ]

    pipeline._attach_full_transcript_to_scenes(scenes, chunks)
    combined = f"{scenes[0].script} {scenes[1].script}"

    assert "First sentence." in combined
    assert "Second sentence." in combined
    assert "Third sentence." in combined
    assert "Fourth sentence." in combined
