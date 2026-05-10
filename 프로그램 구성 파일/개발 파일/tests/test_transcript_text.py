from pathlib import Path

from clipnote_ai.pipeline import ApiCostTracker, TranscriptChunk, USD_TO_KRW, VideoNotePipeline
from clipnote_ai.settings import AppSettings


def test_sentence_splitter_keeps_version_numbers_together():
    pipeline = VideoNotePipeline.__new__(VideoNotePipeline)

    paragraphs = pipeline._note_paragraphs("Version 5.1 started here. Version 5.2 followed.")

    assert paragraphs == ["Version 5.1 started here.", "Version 5.2 followed."]


def test_sentence_splitter_repairs_spaced_version_numbers():
    pipeline = VideoNotePipeline.__new__(VideoNotePipeline)

    paragraphs = pipeline._note_paragraphs("Version 5. 1 started here. Version 5. 2 followed.")

    assert paragraphs == ["Version 5.1 started here.", "Version 5.2 followed."]


def test_summary_text_removes_title_and_adds_reading_space():
    pipeline = VideoNotePipeline.__new__(VideoNotePipeline)

    text = pipeline._normalize_summary_text(
        "Sample Video\n\nGPT 5.1 started here. GPT 5.2 followed with more details.",
        "Sample Video",
    )

    assert not text.startswith("Sample Video")
    assert "GPT 5.1 started here.\n\nGPT 5.2 followed with more details." in text


def test_summary_target_defaults_to_one_fifth_of_script_sentences():
    pipeline = VideoNotePipeline.__new__(VideoNotePipeline)
    pipeline.settings = AppSettings(auto_summary_sentences=True)
    transcript = " ".join(f"Sentence {index}." for index in range(1, 51))

    assert pipeline._summary_target_sentence_count(transcript) == 10


def test_summary_target_for_short_script_is_compact():
    pipeline = VideoNotePipeline.__new__(VideoNotePipeline)
    pipeline.settings = AppSettings(auto_summary_sentences=True)
    transcript = "CapCut을 불러와 주세요. Overlay 버튼을 누르세요. 다른 영상을 불러와 크기를 맞추세요."

    assert pipeline._summary_target_sentence_count(transcript) == 1


def test_short_reels_summary_instruction_asks_for_rewritten_core():
    pipeline = VideoNotePipeline.__new__(VideoNotePipeline)
    instruction = pipeline._summary_mode_instruction(
        "CapCut을 불러와 주세요. Overlay 버튼을 누르세요.",
        "인스타그램 릴스 또는 짧은 세로 영상",
    )

    assert "원문을 문장별로 다시 쓰지 말고" in instruction
    assert "1-2문장" in instruction


def test_summary_target_can_be_set_manually():
    pipeline = VideoNotePipeline.__new__(VideoNotePipeline)
    pipeline.settings = AppSettings(auto_summary_sentences=False, summary_sentence_count=17)

    assert pipeline._summary_target_sentence_count("Sentence one. Sentence two.") == 17


class DummyUsage:
    input_tokens = 10_000
    output_tokens = 2_000
    input_tokens_details = {"cached_tokens": 1_000}


def test_cost_tracker_estimates_text_and_transcription_costs():
    tracker = ApiCostTracker()

    tracker.add_text_usage("gpt-5-nano", DummyUsage())
    tracker.add_transcription_minutes("gpt-4o-mini-transcribe", 10)
    report = tracker.report()

    expected_usd = ((9_000 * 0.05) + (1_000 * 0.005) + (2_000 * 0.40)) / 1_000_000 + 0.03
    assert abs(report.total_cost_usd - expected_usd) < 0.000001
    assert round(report.total_cost_krw) == round(expected_usd * USD_TO_KRW)
    assert "예상 API 비용" in report.format_for_log()


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

    transcript_path = pipeline._write_transcript(tmp_path / "2605091859 영상제목.txt", chunks)
    text = transcript_path.read_text(encoding="utf-8")

    assert "[00:00:00 - 00:05:51]" not in text
    assert "구간:" not in text
    assert "요즘 뜨거운 주제입니다." in text


def test_write_transcript_adds_blank_lines_between_sentences(tmp_path: Path):
    pipeline = VideoNotePipeline.__new__(VideoNotePipeline)
    chunks = [
        TranscriptChunk(
            index=0,
            start=0,
            end=10,
            path=tmp_path / "audio.mp3",
            clean_text="첫 번째 문장입니다. 두 번째 문장입니다. 세 번째 문장입니다.",
        )
    ]

    transcript_path = pipeline._write_transcript(tmp_path / "2605091859 영상제목.txt", chunks)
    text = transcript_path.read_text(encoding="utf-8")

    assert "첫 번째 문장입니다.\n\n두 번째 문장입니다." in text
