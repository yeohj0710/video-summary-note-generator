from __future__ import annotations

import html
import json
import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

from openai import OpenAI

from clipnote_ai.settings import AppSettings
from clipnote_ai.utils import (
    clamp_seconds,
    extract_json_object,
    find_ffmpeg,
    format_timecode,
    get_media_duration,
    parse_timecode,
    run_process,
    sanitize_filename,
    suggest_scene_count,
)


ProgressCallback = Callable[[str, float, str], None]


@dataclass
class TranscriptChunk:
    index: int
    start: float
    end: float
    path: Path
    raw_text: str = ""
    clean_text: str = ""


@dataclass
class Scene:
    index: int
    seconds: int
    timecode: str
    heading: str
    summary: str
    quote: str
    why: str
    image_path: Path | None = None


@dataclass
class PipelineResult:
    output_dir: Path
    markdown_path: Path
    html_path: Path
    pdf_path: Path
    transcript_path: Path
    title: str
    scene_count: int


class VideoNotePipeline:
    def __init__(self, settings: AppSettings, progress: ProgressCallback | None = None):
        self.settings = settings
        self.progress = progress or (lambda _message, _percent, _detail: None)
        self.ffmpeg = find_ffmpeg()
        self.client = OpenAI(api_key=settings.api_key)

    @staticmethod
    def is_url(source: str) -> bool:
        parsed = urlparse(source.strip())
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)

    def run(self, source: str) -> PipelineResult:
        source = source.strip()
        if not source:
            raise ValueError("URL 또는 동영상 파일을 입력해 주세요.")
        if not self.settings.api_key.strip():
            raise ValueError("OpenAI API 키를 입력해 주세요.")

        output_root = Path(self.settings.output_dir).expanduser().resolve()
        output_root.mkdir(parents=True, exist_ok=True)

        started = time.strftime("%Y%m%d_%H%M%S")
        job_dir = output_root / f"{started}_processing"
        job_dir.mkdir(parents=True, exist_ok=False)

        self.progress("준비 중", 0.02, "작업 폴더를 만들고 있습니다.")

        if self.is_url(source):
            video_path, source_title = self._download_video(source, job_dir)
            source_label = source
        else:
            video_path = Path(source).expanduser().resolve()
            if not video_path.exists():
                raise FileNotFoundError(f"동영상 파일을 찾을 수 없습니다: {video_path}")
            source_title = video_path.stem
            source_label = str(video_path)

        safe_title = sanitize_filename(source_title)
        final_dir = output_root / f"{started}_{safe_title}"
        suffix = 1
        while final_dir.exists() and final_dir != job_dir:
            suffix += 1
            final_dir = output_root / f"{started}_{safe_title}_{suffix}"
        if final_dir != job_dir:
            old_job_dir = job_dir
            try:
                relative_video_path = video_path.relative_to(old_job_dir)
            except ValueError:
                relative_video_path = None
            job_dir.rename(final_dir)
            job_dir = final_dir
            if relative_video_path is not None:
                video_path = job_dir / relative_video_path

        duration = get_media_duration(video_path, self.ffmpeg)
        self.progress("영상 분석 중", 0.12, f"영상 길이: {format_timecode(duration)}")

        chunks = self._extract_audio_chunks(video_path, job_dir, duration)
        self._transcribe_chunks(chunks)
        self._clean_chunks(chunks)

        transcript_path = self._write_transcript(job_dir, chunks)
        analysis = self._analyze_scenes(source_title, source_label, duration, chunks)
        scenes = self._normalize_scenes(analysis, duration, chunks)
        self._extract_scene_images(video_path, job_dir, scenes)

        markdown_path = self._render_markdown(job_dir, source_title, source_label, duration, chunks, scenes, analysis)
        html_path = self._render_html(job_dir, source_title, source_label, duration, scenes, analysis)
        pdf_path = self._render_pdf(job_dir, source_title, source_label, duration, chunks, scenes, analysis)
        self._write_metadata(job_dir, source_title, source_label, duration, scenes, analysis)

        self.progress("완료", 1.0, f"결과 생성 완료: {pdf_path.name}")
        return PipelineResult(
            output_dir=job_dir,
            markdown_path=markdown_path,
            html_path=html_path,
            pdf_path=pdf_path,
            transcript_path=transcript_path,
            title=str(analysis.get("title") or source_title),
            scene_count=len(scenes),
        )

    def _download_video(self, url: str, job_dir: Path) -> tuple[Path, str]:
        self.progress("영상 다운로드 중", 0.05, "YouTube/Reels 공개 링크를 가져오고 있습니다.")
        import yt_dlp

        downloads_dir = job_dir / "source"
        downloads_dir.mkdir(parents=True, exist_ok=True)
        outtmpl = str(downloads_dir / "%(title).90s.%(ext)s")
        ffmpeg_dir = str(self.ffmpeg.parent)
        ydl_opts: dict[str, object] = {
            "format": "bv*+ba/b",
            "outtmpl": outtmpl,
            "merge_output_format": "mp4",
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "restrictfilenames": True,
            "ffmpeg_location": ffmpeg_dir,
        }
        if self.settings.use_browser_cookies:
            ydl_opts["cookiesfrombrowser"] = (self.settings.cookie_browser,)

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            if info is None:
                raise RuntimeError("영상 정보를 가져오지 못했습니다.")
            title = str(info.get("title") or "downloaded_video")
            downloaded = Path(ydl.prepare_filename(info))
            merged = downloaded.with_suffix(".mp4")
            if merged.exists():
                downloaded = merged
            if not downloaded.exists():
                candidates = sorted(downloads_dir.glob("*"), key=lambda path: path.stat().st_mtime, reverse=True)
                if not candidates:
                    raise RuntimeError("다운로드된 영상 파일을 찾지 못했습니다.")
                downloaded = candidates[0]
        return downloaded.resolve(), title

    def _extract_audio_chunks(self, video_path: Path, job_dir: Path, duration: float) -> list[TranscriptChunk]:
        self.progress("음성 추출 중", 0.18, "오디오를 전사용 작은 조각으로 나누고 있습니다.")
        chunk_dir = job_dir / "audio_chunks"
        chunk_dir.mkdir(parents=True, exist_ok=True)
        chunk_seconds = 480
        output_pattern = chunk_dir / "chunk_%03d.mp3"
        completed = run_process(
            [
                self.ffmpeg,
                "-y",
                "-i",
                video_path,
                "-map",
                "0:a:0",
                "-vn",
                "-ac",
                "1",
                "-ar",
                "16000",
                "-b:a",
                "48k",
                "-f",
                "segment",
                "-segment_time",
                str(chunk_seconds),
                "-reset_timestamps",
                "1",
                output_pattern,
            ]
        )
        if completed.returncode != 0:
            raise RuntimeError(f"오디오 추출에 실패했습니다.\n{completed.stderr[-1200:]}")

        chunk_paths = sorted(chunk_dir.glob("chunk_*.mp3"))
        if not chunk_paths:
            raise RuntimeError("추출된 오디오 조각이 없습니다. 영상에 음성 트랙이 있는지 확인해 주세요.")

        chunks: list[TranscriptChunk] = []
        for index, path in enumerate(chunk_paths):
            start = index * chunk_seconds
            end = min(duration, start + chunk_seconds)
            chunks.append(TranscriptChunk(index=index, start=start, end=end, path=path))
        return chunks

    def _transcribe_chunks(self, chunks: list[TranscriptChunk]) -> None:
        previous_tail = ""
        total = len(chunks)
        for chunk in chunks:
            base_percent = 0.24 + (chunk.index / max(1, total)) * 0.26
            self.progress(
                "전사 중",
                base_percent,
                f"{chunk.index + 1}/{total} 조각 전사: {format_timecode(chunk.start)}-{format_timecode(chunk.end)}",
            )
            chunk.raw_text = self._transcribe_file(chunk.path, previous_tail).strip()
            previous_tail = chunk.raw_text[-600:]

    def _transcribe_file(self, path: Path, previous_tail: str) -> str:
        prompt = (
            "한국어 영상 음성입니다. 자연스러운 한국어 띄어쓰기와 문장부호를 최대한 살려 주세요."
        )
        if previous_tail:
            prompt += f"\n직전 내용 일부: {previous_tail}"

        attempts = [
            {"language": "ko", "prompt": prompt},
            {"prompt": prompt},
            {},
        ]
        last_error: Exception | None = None
        for extra in attempts:
            try:
                with path.open("rb") as audio_file:
                    result = self.client.audio.transcriptions.create(
                        model=self.settings.transcription_model,
                        file=audio_file,
                        response_format="text",
                        **extra,
                    )
                if isinstance(result, str):
                    return result
                return str(getattr(result, "text", result))
            except Exception as exc:
                last_error = exc
        raise RuntimeError(f"OpenAI 전사 호출에 실패했습니다: {last_error}") from last_error

    def _clean_chunks(self, chunks: list[TranscriptChunk]) -> None:
        total = len(chunks)
        for chunk in chunks:
            base_percent = 0.50 + (chunk.index / max(1, total)) * 0.18
            self.progress(
                "문장 다듬는 중",
                base_percent,
                f"{chunk.index + 1}/{total} 조각의 맞춤법과 띄어쓰기를 정리하고 있습니다.",
            )
            if not chunk.raw_text.strip():
                chunk.clean_text = ""
                continue
            chunk.clean_text = self._text_response(
                system=(
                    "너는 한국어 영상 전사문 교정자다. 의미를 바꾸거나 내용을 추가하지 말고, "
                    "맞춤법, 띄어쓰기, 문장부호, 어색한 ASR 오류만 자연스럽게 고친다. "
                    "결과 텍스트만 반환한다."
                ),
                user=(
                    f"구간: {format_timecode(chunk.start)}-{format_timecode(chunk.end)}\n\n"
                    f"{chunk.raw_text}"
                ),
            ).strip()

    def _text_response(self, system: str, user: str) -> str:
        try:
            response = self.client.responses.create(
                model=self.settings.text_model,
                input=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            )
            output_text = getattr(response, "output_text", None)
            if output_text:
                return str(output_text)
            pieces: list[str] = []
            for item in getattr(response, "output", []) or []:
                for content in getattr(item, "content", []) or []:
                    text = getattr(content, "text", None)
                    if text:
                        pieces.append(str(text))
            if pieces:
                return "\n".join(pieces)
        except Exception:
            pass

        completion = self.client.chat.completions.create(
            model=self.settings.text_model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return completion.choices[0].message.content or ""

    def _write_transcript(self, job_dir: Path, chunks: list[TranscriptChunk]) -> Path:
        transcript_path = job_dir / "transcript.txt"
        lines: list[str] = []
        for chunk in chunks:
            lines.append(f"[{format_timecode(chunk.start)} - {format_timecode(chunk.end)}]")
            lines.append(chunk.clean_text or chunk.raw_text)
            lines.append("")
        transcript_path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
        return transcript_path

    def _transcript_for_prompt(self, chunks: list[TranscriptChunk], max_chars: int = 170_000) -> str:
        per_chunk_limit = max(900, max_chars // max(1, len(chunks)))
        blocks: list[str] = []
        for chunk in chunks:
            text = (chunk.clean_text or chunk.raw_text).strip()
            if len(text) > per_chunk_limit:
                text = text[:per_chunk_limit].rstrip() + "\n...[긴 구간이라 일부 생략됨]"
            blocks.append(f"[{format_timecode(chunk.start)} - {format_timecode(chunk.end)}]\n{text}")
        return "\n\n".join(blocks)

    def _analyze_scenes(
        self,
        source_title: str,
        source_label: str,
        duration: float,
        chunks: list[TranscriptChunk],
    ) -> dict[str, object]:
        auto_count = suggest_scene_count(
            duration,
            int(self.settings.min_scene_count),
            int(self.settings.max_scene_count),
        )
        scene_instruction = (
            f"자동 추천 장면 수는 {auto_count}개다. 내용 밀도에 따라 "
            f"{self.settings.min_scene_count}-{self.settings.max_scene_count}개 사이에서 정하라."
            if self.settings.auto_scene_count
            else f"반드시 {self.settings.fixed_scene_count}개 장면을 고르라."
        )
        transcript = self._transcript_for_prompt(chunks)
        self.progress("주요 장면 고르는 중", 0.72, "AI가 타임라인에서 중요한 순간을 고르고 있습니다.")
        json_text = self._text_response(
            system=(
                "너는 한국어 영상 편집자이자 노트 작성자다. 전사문을 읽고 문맥상 중요한 장면을 고른다. "
                "반드시 JSON만 반환한다. 설명 문장이나 마크다운 코드는 쓰지 않는다."
            ),
            user=(
                f"원본 제목: {source_title}\n"
                f"원본: {source_label}\n"
                f"영상 길이: {format_timecode(duration)} ({int(duration)}초)\n"
                f"{scene_instruction}\n\n"
                "장면 선택 기준:\n"
                "- 핵심 주장, 전환점, 예시, 결론, 감정적으로 강한 순간을 우선한다.\n"
                "- 릴스처럼 짧으면 장면 간격을 촘촘히, 강의처럼 길면 챕터처럼 넓게 배치한다.\n"
                "- 같은 말을 반복하는 장면은 하나만 고른다.\n"
                "- seconds는 0 이상 영상 길이 미만의 정수여야 한다.\n\n"
                "JSON 형식:\n"
                "{\n"
                '  "title": "노트 제목",\n'
                '  "one_line_summary": "한 줄 요약",\n'
                '  "summary_bullets": ["핵심 요약 1", "핵심 요약 2"],\n'
                '  "scenes": [\n'
                '    {"seconds": 12, "timecode": "00:00:12", "heading": "장면 제목", '
                '"summary": "장면 설명", "quote": "대표 발화 또는 빈 문자열", "why": "이 장면을 고른 이유"}\n'
                "  ]\n"
                "}\n\n"
                f"전사문:\n{transcript}"
            ),
        )
        return extract_json_object(json_text)

    def _normalize_scenes(
        self,
        analysis: dict[str, object],
        duration: float,
        chunks: list[TranscriptChunk],
    ) -> list[Scene]:
        raw_scenes = analysis.get("scenes")
        scenes: list[Scene] = []
        if isinstance(raw_scenes, list):
            for item in raw_scenes:
                if not isinstance(item, dict):
                    continue
                seconds = item.get("seconds")
                if seconds is None and isinstance(item.get("timecode"), str):
                    seconds = parse_timecode(str(item["timecode"]))
                if seconds is None:
                    continue
                safe_seconds = clamp_seconds(float(seconds), duration)
                scenes.append(
                    Scene(
                        index=len(scenes) + 1,
                        seconds=safe_seconds,
                        timecode=format_timecode(safe_seconds),
                        heading=str(item.get("heading") or f"주요 장면 {len(scenes) + 1}"),
                        summary=str(item.get("summary") or ""),
                        quote=str(item.get("quote") or ""),
                        why=str(item.get("why") or ""),
                    )
                )

        if not scenes:
            count = (
                int(self.settings.fixed_scene_count)
                if not self.settings.auto_scene_count
                else suggest_scene_count(duration, self.settings.min_scene_count, self.settings.max_scene_count)
            )
            step = duration / (count + 1)
            for index in range(count):
                seconds = clamp_seconds((index + 1) * step, duration)
                scenes.append(
                    Scene(
                        index=index + 1,
                        seconds=seconds,
                        timecode=format_timecode(seconds),
                        heading=f"주요 장면 {index + 1}",
                        summary="전사문 기반 자동 분석에 실패해 균등 간격으로 추출한 장면입니다.",
                        quote="",
                        why="대체 추출",
                    )
                )

        scenes = sorted(scenes, key=lambda scene: scene.seconds)
        for index, scene in enumerate(scenes, start=1):
            scene.index = index
            scene.timecode = format_timecode(scene.seconds)
        return scenes

    def _extract_scene_images(self, video_path: Path, job_dir: Path, scenes: list[Scene]) -> None:
        frames_dir = job_dir / "frames"
        frames_dir.mkdir(parents=True, exist_ok=True)
        total = len(scenes)
        for scene in scenes:
            self.progress(
                "이미지 추출 중",
                0.78 + (scene.index / max(1, total)) * 0.12,
                f"{scene.index}/{total} 장면 이미지 저장: {scene.timecode}",
            )
            output = frames_dir / f"scene_{scene.index:02d}_{scene.timecode.replace(':', '-')}.jpg"
            completed = run_process(
                [
                    self.ffmpeg,
                    "-y",
                    "-ss",
                    f"{scene.seconds:.3f}",
                    "-i",
                    video_path,
                    "-frames:v",
                    "1",
                    "-q:v",
                    "2",
                    output,
                ]
            )
            if completed.returncode != 0 or not output.exists():
                raise RuntimeError(f"장면 이미지 추출에 실패했습니다.\n{completed.stderr[-1200:]}")
            scene.image_path = output

    def _render_markdown(
        self,
        job_dir: Path,
        source_title: str,
        source_label: str,
        duration: float,
        chunks: list[TranscriptChunk],
        scenes: list[Scene],
        analysis: dict[str, object],
    ) -> Path:
        markdown_path = job_dir / "summary.md"
        title = str(analysis.get("title") or source_title)
        bullets = analysis.get("summary_bullets") if isinstance(analysis.get("summary_bullets"), list) else []
        lines = [
            f"# {title}",
            "",
            f"- 원본: {source_label}",
            f"- 영상 길이: {format_timecode(duration)}",
            f"- 주요 장면: {len(scenes)}개",
            "- developed by yeohj0710",
            "",
            "## 한 줄 요약",
            "",
            str(analysis.get("one_line_summary") or "").strip() or "요약이 비어 있습니다.",
            "",
        ]
        if bullets:
            lines.extend(["## 핵심 요약", ""])
            for bullet in bullets:
                lines.append(f"- {str(bullet).strip()}")
            lines.append("")

        lines.extend(["## 주요 장면", ""])
        for scene in scenes:
            rel_image = scene.image_path.relative_to(job_dir).as_posix() if scene.image_path else ""
            lines.extend(
                [
                    f"### {scene.index:02d}. {scene.timecode} · {scene.heading}",
                    "",
                    f"![{scene.heading}]({rel_image})" if rel_image else "",
                    "",
                    scene.summary,
                    "",
                ]
            )
            if scene.quote:
                lines.extend([f"> {scene.quote}", ""])
            if scene.why:
                lines.extend([f"선정 이유: {scene.why}", ""])

        lines.extend(["## 정리된 전사문", ""])
        for chunk in chunks:
            lines.append(f"### {format_timecode(chunk.start)} - {format_timecode(chunk.end)}")
            lines.append("")
            lines.append(chunk.clean_text or chunk.raw_text)
            lines.append("")

        markdown_path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
        return markdown_path

    def _render_html(
        self,
        job_dir: Path,
        source_title: str,
        source_label: str,
        duration: float,
        scenes: list[Scene],
        analysis: dict[str, object],
    ) -> Path:
        html_path = job_dir / "summary.html"
        title = str(analysis.get("title") or source_title)
        bullets = analysis.get("summary_bullets") if isinstance(analysis.get("summary_bullets"), list) else []
        scene_cards = []
        for scene in scenes:
            rel_image = scene.image_path.relative_to(job_dir).as_posix() if scene.image_path else ""
            quote = f"<blockquote>{html.escape(scene.quote)}</blockquote>" if scene.quote else ""
            why = f"<p class='why'>선정 이유: {html.escape(scene.why)}</p>" if scene.why else ""
            scene_cards.append(
                f"""
                <section class="scene">
                  <div class="time">{html.escape(scene.timecode)}</div>
                  <h2>{scene.index:02d}. {html.escape(scene.heading)}</h2>
                  <img src="{html.escape(rel_image)}" alt="{html.escape(scene.heading)}">
                  <p>{html.escape(scene.summary)}</p>
                  {quote}
                  {why}
                </section>
                """
            )
        bullet_items = "".join(f"<li>{html.escape(str(item))}</li>" for item in bullets)
        document = f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
  <style>
    :root {{
      color-scheme: light;
      --ink: #17202a;
      --muted: #5f6b7a;
      --line: #dbe2ea;
      --paper: #fbfcfe;
      --accent: #1677ff;
    }}
    body {{
      margin: 0;
      font-family: "Segoe UI", "Malgun Gothic", sans-serif;
      background: var(--paper);
      color: var(--ink);
      line-height: 1.65;
    }}
    main {{
      width: min(960px, calc(100vw - 40px));
      margin: 40px auto 72px;
    }}
    header {{
      border-bottom: 1px solid var(--line);
      padding-bottom: 24px;
      margin-bottom: 28px;
    }}
    h1 {{
      margin: 0 0 12px;
      font-size: clamp(28px, 5vw, 44px);
      letter-spacing: 0;
      line-height: 1.15;
    }}
    .meta, .why {{
      color: var(--muted);
      font-size: 14px;
    }}
    .summary {{
      font-size: 19px;
      margin-top: 18px;
    }}
    .credit {{
      display: inline-flex;
      margin-top: 10px;
      padding: 3px 9px;
      border-radius: 6px;
      background: #eaf2ff;
      color: #2563eb;
      font-size: 13px;
      font-weight: 700;
    }}
    ul {{
      padding-left: 22px;
    }}
    .scene {{
      padding: 30px 0;
      border-top: 1px solid var(--line);
    }}
    .time {{
      color: var(--accent);
      font-weight: 700;
      font-size: 14px;
    }}
    h2 {{
      margin: 6px 0 16px;
      font-size: 24px;
      letter-spacing: 0;
    }}
    img {{
      width: 100%;
      max-height: 680px;
      object-fit: contain;
      background: #111827;
      border-radius: 8px;
      border: 1px solid var(--line);
    }}
    blockquote {{
      margin: 16px 0;
      padding-left: 14px;
      border-left: 4px solid var(--accent);
      color: #263445;
    }}
    footer {{
      border-top: 1px solid var(--line);
      color: var(--muted);
      font-size: 13px;
      padding-top: 18px;
      margin-top: 28px;
    }}
  </style>
</head>
<body>
  <main>
    <header>
      <h1>{html.escape(title)}</h1>
      <div class="meta">원본: {html.escape(source_label)} · 길이: {html.escape(format_timecode(duration))} · 주요 장면 {len(scenes)}개</div>
      <div class="credit">developed by yeohj0710</div>
      <p class="summary">{html.escape(str(analysis.get("one_line_summary") or ""))}</p>
      <ul>{bullet_items}</ul>
    </header>
    {''.join(scene_cards)}
    <footer>ClipNote AI · developed by yeohj0710</footer>
  </main>
</body>
</html>
"""
        html_path.write_text(document, encoding="utf-8")
        return html_path

    def _register_pdf_fonts(self) -> tuple[str, str]:
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont

        windows = Path(os.getenv("WINDIR", r"C:\Windows")) / "Fonts"
        regular_candidates = [
            windows / "malgun.ttf",
            windows / "NanumGothic.ttf",
            Path(r"C:\Windows\Fonts\malgun.ttf"),
        ]
        bold_candidates = [
            windows / "malgunbd.ttf",
            windows / "NanumGothicBold.ttf",
            Path(r"C:\Windows\Fonts\malgunbd.ttf"),
        ]

        regular_path = next((path for path in regular_candidates if path.exists()), None)
        bold_path = next((path for path in bold_candidates if path.exists()), regular_path)
        if not regular_path:
            return "Helvetica", "Helvetica-Bold"

        if "ClipNoteKorean" not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont("ClipNoteKorean", str(regular_path)))
        if bold_path and "ClipNoteKorean-Bold" not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont("ClipNoteKorean-Bold", str(bold_path)))
        return "ClipNoteKorean", "ClipNoteKorean-Bold" if bold_path else "ClipNoteKorean"

    def _pdf_image(self, image_path: Path, max_width: float, max_height: float):
        from PIL import Image as PILImage
        from reportlab.platypus import Image

        with PILImage.open(image_path) as image:
            width, height = image.size
        if width <= 0 or height <= 0:
            return None
        scale = min(max_width / width, max_height / height, 1.0)
        return Image(str(image_path), width=width * scale, height=height * scale)

    def _pdf_paragraph_text(self, value: object) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        return html.escape(text).replace("\n", "<br/>")

    def _render_pdf(
        self,
        job_dir: Path,
        source_title: str,
        source_label: str,
        duration: float,
        chunks: list[TranscriptChunk],
        scenes: list[Scene],
        analysis: dict[str, object],
    ) -> Path:
        self.progress("PDF 생성 중", 0.94, "주요 화면과 스크립트를 PDF로 정리하고 있습니다.")

        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.lib.units import mm
        from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

        pdf_path = job_dir / "summary.pdf"
        regular_font, bold_font = self._register_pdf_fonts()
        title = str(analysis.get("title") or source_title)
        bullets = analysis.get("summary_bullets") if isinstance(analysis.get("summary_bullets"), list) else []

        doc = SimpleDocTemplate(
            str(pdf_path),
            pagesize=A4,
            rightMargin=18 * mm,
            leftMargin=18 * mm,
            topMargin=17 * mm,
            bottomMargin=17 * mm,
            title=title,
            author="ClipNote AI",
            subject="developed by yeohj0710",
        )
        width, _height = A4
        content_width = width - doc.leftMargin - doc.rightMargin

        styles = {
            "title": ParagraphStyle(
                "ClipNoteTitle",
                fontName=bold_font,
                fontSize=22,
                leading=30,
                textColor=colors.HexColor("#142033"),
                spaceAfter=10,
            ),
            "h2": ParagraphStyle(
                "ClipNoteH2",
                fontName=bold_font,
                fontSize=15,
                leading=21,
                textColor=colors.HexColor("#142033"),
                spaceBefore=14,
                spaceAfter=8,
            ),
            "h3": ParagraphStyle(
                "ClipNoteH3",
                fontName=bold_font,
                fontSize=12,
                leading=18,
                textColor=colors.HexColor("#1677ff"),
                spaceBefore=8,
                spaceAfter=5,
            ),
            "body": ParagraphStyle(
                "ClipNoteBody",
                fontName=regular_font,
                fontSize=10.2,
                leading=16,
                textColor=colors.HexColor("#17202a"),
                spaceAfter=7,
            ),
            "muted": ParagraphStyle(
                "ClipNoteMuted",
                fontName=regular_font,
                fontSize=9,
                leading=14,
                textColor=colors.HexColor("#5f6b7a"),
                spaceAfter=6,
            ),
            "credit": ParagraphStyle(
                "ClipNoteCredit",
                fontName=bold_font,
                fontSize=8.8,
                leading=13,
                textColor=colors.HexColor("#2563eb"),
                backColor=colors.HexColor("#eaf2ff"),
                borderPadding=5,
                spaceAfter=6,
            ),
            "quote": ParagraphStyle(
                "ClipNoteQuote",
                fontName=regular_font,
                fontSize=9.5,
                leading=15,
                leftIndent=8,
                borderColor=colors.HexColor("#1677ff"),
                borderWidth=0,
                borderPadding=6,
                backColor=colors.HexColor("#eef6ff"),
                textColor=colors.HexColor("#263445"),
                spaceAfter=7,
            ),
        }

        story = [
            Paragraph(self._pdf_paragraph_text(title), styles["title"]),
            Paragraph(
                self._pdf_paragraph_text(
                    f"원본: {source_label}\n영상 길이: {format_timecode(duration)}\n주요 장면: {len(scenes)}개"
                ),
                styles["muted"],
            ),
            Paragraph("developed by yeohj0710", styles["credit"]),
            Spacer(1, 5 * mm),
            Paragraph("한 줄 요약", styles["h2"]),
            Paragraph(self._pdf_paragraph_text(analysis.get("one_line_summary") or "요약이 비어 있습니다."), styles["body"]),
        ]

        if bullets:
            story.append(Paragraph("핵심 요약", styles["h2"]))
            for bullet in bullets:
                story.append(Paragraph(f"• {self._pdf_paragraph_text(bullet)}", styles["body"]))

        story.append(Paragraph("주요 화면과 스크립트", styles["h2"]))
        for scene in scenes:
            story.append(Paragraph(f"{scene.index:02d}. {scene.timecode} · {self._pdf_paragraph_text(scene.heading)}", styles["h3"]))
            if scene.image_path and scene.image_path.exists():
                image = self._pdf_image(scene.image_path, content_width, 92 * mm)
                if image:
                    story.append(image)
                    story.append(Spacer(1, 3 * mm))
            if scene.summary:
                story.append(Paragraph(self._pdf_paragraph_text(scene.summary), styles["body"]))
            if scene.quote:
                story.append(Paragraph(self._pdf_paragraph_text(f"대표 발화: {scene.quote}"), styles["quote"]))
            if scene.why:
                story.append(Paragraph(self._pdf_paragraph_text(f"선정 이유: {scene.why}"), styles["muted"]))

        story.append(PageBreak())
        story.append(Paragraph("전체 스크립트", styles["h2"]))
        for chunk in chunks:
            chunk_title = f"{format_timecode(chunk.start)} - {format_timecode(chunk.end)}"
            text = (chunk.clean_text or chunk.raw_text).strip()
            story.append(Paragraph(self._pdf_paragraph_text(chunk_title), styles["h3"]))
            if text:
                story.append(Paragraph(self._pdf_paragraph_text(text), styles["body"]))

        def draw_footer(canvas, document):
            canvas.saveState()
            canvas.setFont(regular_font, 8)
            canvas.setFillColor(colors.HexColor("#7a8797"))
            canvas.drawRightString(width - doc.rightMargin, 9 * mm, f"ClipNote AI · developed by yeohj0710 · {document.page}")
            canvas.restoreState()

        doc.build(story, onFirstPage=draw_footer, onLaterPages=draw_footer)
        return pdf_path

    def _write_metadata(
        self,
        job_dir: Path,
        source_title: str,
        source_label: str,
        duration: float,
        scenes: list[Scene],
        analysis: dict[str, object],
    ) -> None:
        payload = {
            "source_title": source_title,
            "source": source_label,
            "duration_seconds": duration,
            "transcription_model": self.settings.transcription_model,
            "text_model": self.settings.text_model,
            "analysis": analysis,
            "scenes": [
                {
                    "index": scene.index,
                    "seconds": scene.seconds,
                    "timecode": scene.timecode,
                    "heading": scene.heading,
                    "summary": scene.summary,
                    "quote": scene.quote,
                    "why": scene.why,
                    "image": str(scene.image_path.relative_to(job_dir)) if scene.image_path else "",
                }
                for scene in scenes
            ],
        }
        (job_dir / "metadata.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
