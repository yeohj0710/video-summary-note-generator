from pathlib import Path
from types import SimpleNamespace

from clipnote_ai import pipeline as pipeline_module
from clipnote_ai.pipeline import (
    TEXT_MODEL_PRICING_USD_PER_1M,
    ApiCostTracker,
    TranscriptChunk,
    USD_TO_KRW,
    VideoNotePipeline,
)
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


def test_summary_target_uses_length_when_sentence_count_is_low():
    pipeline = VideoNotePipeline.__new__(VideoNotePipeline)
    pipeline.settings = AppSettings(auto_summary_sentences=True)
    transcript = " ".join(["Say, you're running up the road, push the pedal, I won't crash"] * 45)

    assert pipeline._summary_target_sentence_count(transcript) >= 7


def test_summary_instruction_stays_general():
    pipeline = VideoNotePipeline.__new__(VideoNotePipeline)
    instruction = pipeline._summary_mode_instruction(
        "CapCut을 불러와 주세요. Overlay 버튼을 누르세요.",
        "인스타그램 릴스 또는 짧은 세로 영상",
    )

    assert "요약 방식" in instruction
    assert "목표 길이" in instruction
    assert "튜토리얼" not in instruction
    assert "가사" not in instruction


def test_long_repeated_transcript_is_not_forced_into_special_case_prompt():
    pipeline = VideoNotePipeline.__new__(VideoNotePipeline)
    transcript = " ".join(["Say, you're running up the road, push the pedal, I won't crash"] * 45)

    instruction = pipeline._summary_mode_instruction(transcript, "유튜브 영상")

    assert "짧은 영상 요약 방식" not in instruction
    assert "1-2문장" not in instruction
    assert "중간 길이 요약 방식" not in instruction


def test_summary_target_can_be_set_manually():
    pipeline = VideoNotePipeline.__new__(VideoNotePipeline)
    pipeline.settings = AppSettings(auto_summary_sentences=False, summary_sentence_count=17)

    assert pipeline._summary_target_sentence_count("Sentence one. Sentence two.") == 17


def test_short_media_uses_single_large_audio_chunk():
    assert VideoNotePipeline._audio_chunk_seconds(146) == 600


def test_long_media_uses_fewer_five_minute_chunks():
    assert VideoNotePipeline._audio_chunk_seconds(7200) == 300


def test_audio_extraction_uses_lossless_wav_chunks(tmp_path: Path, monkeypatch):
    pipeline = VideoNotePipeline.__new__(VideoNotePipeline)
    pipeline.ffmpeg = "ffmpeg"
    pipeline.progress = lambda *_args, **_kwargs: None
    source = tmp_path / "source.mp4"
    source.write_bytes(b"fake")
    support_dir = tmp_path / "support"
    captured: list[str] = []

    def fake_run_process(args: list[object]):
        captured.extend(str(arg) for arg in args)
        chunk_dir = support_dir / "audio_chunks"
        chunk_dir.mkdir(parents=True, exist_ok=True)
        (chunk_dir / "chunk_000.wav").write_bytes(b"fake-wav")
        return SimpleNamespace(returncode=0, stderr="")

    monkeypatch.setattr(pipeline_module, "run_process", fake_run_process)
    monkeypatch.setattr(pipeline_module, "get_media_duration", lambda *_args: 12.0)

    chunks = pipeline._extract_audio_chunks(source, support_dir, 12.0)

    assert chunks[0].path.suffix == ".wav"
    assert "pcm_s16le" in captured
    assert "-b:a" not in captured


def test_transcribe_uses_deterministic_no_guess_request(tmp_path: Path):
    pipeline = VideoNotePipeline.__new__(VideoNotePipeline)
    pipeline.settings = AppSettings(transcription_model="gpt-4o-mini-transcribe")
    audio = tmp_path / "chunk.wav"
    audio.write_bytes(b"fake")
    calls: list[dict[str, object]] = []

    class FakeTranscriptions:
        def create(self, **kwargs):
            calls.append(kwargs)
            return "들리는 말만 전사합니다."

    pipeline.client = SimpleNamespace(audio=SimpleNamespace(transcriptions=FakeTranscriptions()))

    text = pipeline._transcribe_file(audio, "")

    assert text == "들리는 말만 전사합니다."
    assert calls[0]["temperature"] == 0
    assert "language" not in calls[0]
    assert "추측" in str(calls[0]["prompt"])


def test_clean_prompt_prefers_korean_for_common_terms(tmp_path: Path):
    pipeline = VideoNotePipeline.__new__(VideoNotePipeline)
    pipeline.progress = lambda *_args, **_kwargs: None
    captured: dict[str, str] = {}

    def fake_text_response(system: str, user: str) -> str:
        captured["system"] = system
        captured["user"] = user
        return "도베르만이라고 하면 되게 사납고 맹견에 들어갈 것 같아요."

    pipeline._text_response = fake_text_response
    chunks = [
        TranscriptChunk(
            index=0,
            start=0,
            end=10,
            path=tmp_path / "audio.mp3",
            raw_text="Doberman이라고 하면 되게 사납고 맹견에 들어갈 것 같아요.",
        )
    ]

    pipeline._clean_chunks(chunks)

    assert "Doberman" in captured["system"]
    assert "도베르만" in captured["system"]
    assert "일반 명사" in captured["system"]
    assert chunks[0].clean_text.startswith("도베르만")


def test_clean_chunks_keeps_raw_text_when_model_truncates(tmp_path: Path):
    pipeline = VideoNotePipeline.__new__(VideoNotePipeline)
    pipeline.progress = lambda *_args, **_kwargs: None
    raw = " ".join(f"문장 {index}입니다." for index in range(1, 41))
    calls: list[str] = []

    def fake_text_response(system: str, user: str) -> str:
        calls.append(user)
        return "문장 1입니다. 문장 2입니다."

    pipeline._text_response = fake_text_response
    chunks = [
        TranscriptChunk(
            index=0,
            start=0,
            end=90,
            path=tmp_path / "audio.mp3",
            raw_text=raw,
        )
    ]

    pipeline._clean_chunks(chunks)

    assert len(calls) == 2
    assert chunks[0].clean_text == raw


def test_clean_chunks_accepts_complete_clean_text(tmp_path: Path):
    pipeline = VideoNotePipeline.__new__(VideoNotePipeline)
    pipeline.progress = lambda *_args, **_kwargs: None
    raw = " ".join(f"문장 {index}입니다." for index in range(1, 21))
    cleaned = " ".join(f"문장 {index}입니다!" for index in range(1, 21))
    pipeline._text_response = lambda **_kwargs: cleaned
    chunks = [
        TranscriptChunk(
            index=0,
            start=0,
            end=90,
            path=tmp_path / "audio.mp3",
            raw_text=raw,
        )
    ]

    pipeline._clean_chunks(chunks)

    assert chunks[0].clean_text == cleaned


def test_clean_chunks_rejects_text_that_expands_too_much(tmp_path: Path):
    pipeline = VideoNotePipeline.__new__(VideoNotePipeline)
    pipeline.progress = lambda *_args, **_kwargs: None
    raw = " ".join(f"원문 문장 {index}입니다." for index in range(1, 41))
    bloated = raw + " " + ("원문에 없는 반복입니다. " * 80)
    calls: list[str] = []

    def fake_text_response(system: str, user: str) -> str:
        calls.append(user)
        return bloated

    pipeline._text_response = fake_text_response
    chunks = [
        TranscriptChunk(
            index=0,
            start=0,
            end=90,
            path=tmp_path / "audio.wav",
            raw_text=raw,
        )
    ]

    pipeline._clean_chunks(chunks)

    assert len(calls) == 2
    assert chunks[0].clean_text == raw


def test_clean_chunks_rejects_short_text_that_expands_too_much(tmp_path: Path):
    pipeline = VideoNotePipeline.__new__(VideoNotePipeline)
    pipeline.progress = lambda *_args, **_kwargs: None
    raw = "캡컷에서 Overlay 버튼을 누르고 다른 영상을 불러와 크기와 위치를 맞추세요."
    bloated = raw + "\n\n" + ("원문에 없는 긴 설명입니다. " * 35)
    pipeline._text_response = lambda **_kwargs: bloated
    chunks = [
        TranscriptChunk(
            index=0,
            start=0,
            end=20,
            path=tmp_path / "audio.wav",
            raw_text=raw,
        )
    ]

    pipeline._clean_chunks(chunks)

    assert chunks[0].clean_text == raw


def test_clean_chunks_can_skip_polish_to_save_cost(tmp_path: Path):
    pipeline = VideoNotePipeline.__new__(VideoNotePipeline)
    pipeline.settings = AppSettings(polish_transcript=False)
    pipeline.progress = lambda *_args, **_kwargs: None
    calls: list[str] = []
    pipeline._text_response = lambda **_kwargs: calls.append("called") or "should not be used"
    chunks = [
        TranscriptChunk(
            index=0,
            start=0,
            end=90,
            path=tmp_path / "audio.mp3",
            raw_text="raw transcript text",
        )
    ]

    pipeline._clean_chunks(chunks)

    assert calls == []
    assert chunks[0].clean_text == "raw transcript text"


class DummyUsage:
    input_tokens = 10_000
    output_tokens = 2_000
    input_tokens_details = {"cached_tokens": 1_000}


def test_text_pricing_covers_expanded_model_choices():
    expected_models = {
        "gpt-5.5",
        "gpt-5.4",
        "gpt-5.4-mini",
        "gpt-5.4-nano",
        "gpt-5",
        "gpt-5-mini",
        "gpt-5-nano",
        "gpt-4.1",
        "gpt-4.1-mini",
        "gpt-4.1-nano",
        "gpt-4o",
        "gpt-4o-mini",
        "o4-mini",
        "o3",
        "o3-mini",
        "o1",
        "o1-mini",
    }

    assert expected_models <= set(TEXT_MODEL_PRICING_USD_PER_1M)


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
