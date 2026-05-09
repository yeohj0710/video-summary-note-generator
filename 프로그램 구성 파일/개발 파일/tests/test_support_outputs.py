from pathlib import Path

from clipnote_ai.pipeline import Scene, VideoNotePipeline


def test_support_output_files_use_korean_names(tmp_path: Path):
    pipeline = VideoNotePipeline.__new__(VideoNotePipeline)
    pipeline.progress = lambda *_args: None
    scenes = [
        Scene(
            index=1,
            seconds=0,
            timecode="00:00:00",
            heading="첫 장면",
            summary="",
            quote="",
            why="",
            script="첫 문장입니다. 두 번째 문장입니다.",
            image_path=None,
        )
    ]
    analysis = {"title": "테스트 노트"}

    markdown_path = pipeline._render_markdown(tmp_path, "테스트 노트", "local.mp4", 10, [], scenes, analysis)
    html_path = pipeline._render_html(tmp_path, "테스트 노트", "local.mp4", 10, [], scenes, analysis)

    assert markdown_path.name == "요약 노트.md"
    assert html_path.name == "요약 노트.html"
