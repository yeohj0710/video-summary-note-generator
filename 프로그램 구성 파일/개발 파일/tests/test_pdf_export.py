from pathlib import Path

from PIL import Image, ImageDraw

from clipnote_ai.pipeline import Scene, TranscriptChunk, VideoNotePipeline


def test_render_pdf_contains_key_scene_and_script(tmp_path: Path):
    frame_dir = tmp_path / "frames"
    frame_dir.mkdir()
    image_path = frame_dir / "scene.jpg"
    image = Image.new("RGB", (1280, 720), "#1677ff")
    draw = ImageDraw.Draw(image)
    draw.rectangle((80, 80, 1200, 640), outline="white", width=8)
    image.save(image_path)

    pipeline = VideoNotePipeline.__new__(VideoNotePipeline)
    pipeline.progress = lambda *_args: None

    scenes = [
        Scene(
            index=1,
            seconds=12,
            timecode="00:00:12",
            heading="핵심 장면",
            summary="이 장면은 영상의 핵심 내용을 설명합니다.",
            quote="대표 발화입니다.",
            why="주제가 전환되는 지점입니다.",
            script="안녕하세요. 이것은 이미지 아래에 들어갈 장면 대본입니다.",
            image_path=image_path,
        )
    ]
    chunks = [
        TranscriptChunk(
            index=0,
            start=0,
            end=30,
            path=tmp_path / "audio.mp3",
            clean_text="안녕하세요. 이것은 PDF 생성 테스트입니다.",
        )
    ]
    analysis = {
        "title": "PDF 테스트",
        "one_line_summary": "PDF가 정상 생성되는지 확인합니다.",
        "summary_bullets": ["주요 화면 포함", "스크립트 포함"],
    }

    pdf_path = pipeline._render_pdf(tmp_path, "PDF 테스트", "local-test.mp4", 30, chunks, scenes, analysis)

    assert pdf_path.exists()
    assert pdf_path.stat().st_size > 1000


def test_render_docx_contains_editable_note(tmp_path: Path):
    frame_dir = tmp_path / "frames"
    frame_dir.mkdir()
    image_path = frame_dir / "scene.jpg"
    image = Image.new("RGB", (720, 1280), "#2563eb")
    image.save(image_path)

    pipeline = VideoNotePipeline.__new__(VideoNotePipeline)
    pipeline.progress = lambda *_args: None

    scenes = [
        Scene(
            index=1,
            seconds=12,
            timecode="00:00:12",
            heading="첫 장면",
            summary="",
            quote="",
            why="",
            script="첫 번째 문장입니다. 두 번째 문장입니다.",
            image_path=image_path,
        )
    ]
    analysis = {"title": "DOCX 테스트"}

    docx_path = pipeline._render_docx(tmp_path, "DOCX 테스트", "https://example.com/video", scenes, analysis)

    assert docx_path.exists()
    assert docx_path.name == "노션 붙여넣기용 요약 노트.docx"
    assert docx_path.stat().st_size > 1000


def test_transcript_paragraphs_split_long_blocks():
    pipeline = VideoNotePipeline.__new__(VideoNotePipeline)
    text = "첫 번째 문장입니다. 두 번째 문장입니다. 세 번째 문장입니다. 네 번째 문장입니다."

    paragraphs = pipeline._transcript_paragraphs(text)

    assert paragraphs == ["첫 번째 문장입니다. 두 번째 문장입니다.", "세 번째 문장입니다. 네 번째 문장입니다."]

