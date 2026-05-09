from __future__ import annotations

import os
import queue
import sys
import threading
import traceback
import webbrowser
from pathlib import Path
from tkinter import filedialog, font as tkfont, messagebox
import tkinter as tk

import customtkinter as ctk

from clipnote_ai.pipeline import PipelineResult, VideoNotePipeline
from clipnote_ai.settings import AppSettings, default_output_dir, load_settings, save_settings


class ClipNoteApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()
        ctk.set_appearance_mode("light")
        ctk.set_default_color_theme("blue")

        self.title("ClipNote AI")
        self.geometry("1160x820")
        self.minsize(1080, 740)

        self.settings = load_settings()
        self.worker_thread: threading.Thread | None = None
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.latest_result: PipelineResult | None = None

        self.source_type = tk.StringVar(value="url")
        self.url_var = tk.StringVar()
        self.file_var = tk.StringVar()
        self.api_key_var = tk.StringVar(value=self.settings.api_key)
        self.save_api_key_var = tk.BooleanVar(value=self.settings.save_api_key)
        self.transcription_model_var = tk.StringVar(value=self.settings.transcription_model)
        self.text_model_var = tk.StringVar(value=self.settings.text_model)
        self.output_dir_var = tk.StringVar(value=self.settings.output_dir or str(default_output_dir()))
        self.auto_scene_var = tk.BooleanVar(value=self.settings.auto_scene_count)
        self.fixed_scene_var = tk.StringVar(value=str(self.settings.fixed_scene_count))
        self.min_scene_var = tk.StringVar(value=str(self.settings.min_scene_count))
        self.max_scene_var = tk.StringVar(value=str(self.settings.max_scene_count))
        self.use_cookies_var = tk.BooleanVar(value=self.settings.use_browser_cookies)
        self.cookie_browser_var = tk.StringVar(value=self.settings.cookie_browser)

        self._configure_typography()
        self._build_ui()
        self.after(120, self._drain_events)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _configure_typography(self) -> None:
        available = set(tkfont.families(self))
        for candidate in ("Pretendard", "맑은 고딕", "Malgun Gothic", "Segoe UI"):
            if candidate in available:
                self.font_family = candidate
                break
        else:
            self.font_family = "Segoe UI"

        self.option_add("*Font", f"{{{self.font_family}}} 11")
        self.font_title = ctk.CTkFont(family=self.font_family, size=32, weight="bold")
        self.font_subtitle = ctk.CTkFont(family=self.font_family, size=15)
        self.font_card_title = ctk.CTkFont(family=self.font_family, size=19, weight="bold")
        self.font_section_title = ctk.CTkFont(family=self.font_family, size=18, weight="bold")
        self.font_body = ctk.CTkFont(family=self.font_family, size=14)
        self.font_label = ctk.CTkFont(family=self.font_family, size=13)
        self.font_button = ctk.CTkFont(family=self.font_family, size=14, weight="bold")
        self.font_input = ctk.CTkFont(family=self.font_family, size=14)
        self.font_log = ctk.CTkFont(family=self.font_family, size=13)

    def _build_ui(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        header = ctk.CTkFrame(self, fg_color="#f8fafc", corner_radius=0)
        header.grid(row=0, column=0, sticky="ew")
        header.grid_columnconfigure(0, weight=1)
        header.grid_columnconfigure(1, weight=0)

        title = ctk.CTkLabel(
            header,
            text="ClipNote AI",
            font=self.font_title,
            text_color="#111827",
        )
        title.grid(row=0, column=0, padx=32, pady=(24, 5), sticky="w")
        subtitle = ctk.CTkLabel(
            header,
            text="릴스, 유튜브, 로컬 동영상을 주요 장면 이미지와 한국어 노트로 변환합니다.",
            font=self.font_subtitle,
            text_color="#475569",
        )
        subtitle.grid(row=1, column=0, padx=32, pady=(0, 22), sticky="w")
        ctk.CTkButton(
            header,
            text="사용설명서 열기",
            width=172,
            height=40,
            corner_radius=8,
            font=self.font_button,
            fg_color="#334155",
            hover_color="#1f2937",
            command=self._open_user_guide,
        ).grid(row=0, column=1, rowspan=2, padx=(12, 32), pady=26, sticky="e")

        body = ctk.CTkFrame(self, fg_color="#edf1f6", corner_radius=0)
        body.grid(row=1, column=0, sticky="nsew")
        body.grid_columnconfigure(0, weight=3)
        body.grid_columnconfigure(1, weight=2)
        body.grid_rowconfigure(0, weight=1)

        left = ctk.CTkScrollableFrame(body, fg_color="#edf1f6")
        left.grid(row=0, column=0, sticky="nsew", padx=(24, 12), pady=24)
        left.grid_columnconfigure(0, weight=1)

        right = ctk.CTkFrame(body, fg_color="#ffffff", corner_radius=10)
        right.grid(row=0, column=1, sticky="nsew", padx=(12, 24), pady=24)
        right.grid_columnconfigure(0, weight=1)
        right.grid_rowconfigure(3, weight=1)

        self._source_card(left).grid(row=0, column=0, sticky="ew", pady=(0, 14))
        self._api_card(left).grid(row=1, column=0, sticky="ew", pady=(0, 14))
        self._output_card(left).grid(row=2, column=0, sticky="ew", pady=(0, 14))

        self._status_panel(right)

    def _card(self, parent: ctk.CTkBaseClass, title: str) -> ctk.CTkFrame:
        card = ctk.CTkFrame(parent, fg_color="#ffffff", corner_radius=10)
        card.grid_columnconfigure(0, weight=1)
        label = ctk.CTkLabel(card, text=title, font=self.font_card_title, text_color="#111827")
        label.grid(row=0, column=0, padx=22, pady=(20, 12), sticky="w")
        return card

    def _source_card(self, parent: ctk.CTkBaseClass) -> ctk.CTkFrame:
        card = self._card(parent, "1. 영상 선택")
        mode_row = ctk.CTkFrame(card, fg_color="transparent")
        mode_row.grid(row=1, column=0, padx=22, pady=(0, 14), sticky="ew")
        mode_row.grid_columnconfigure((0, 1), weight=1)

        ctk.CTkRadioButton(
            mode_row,
            text="URL로 가져오기",
            variable=self.source_type,
            value="url",
            font=self.font_body,
            radiobutton_width=24,
            radiobutton_height=24,
        ).grid(
            row=0, column=0, sticky="w"
        )
        ctk.CTkRadioButton(
            mode_row,
            text="내 컴퓨터 파일",
            variable=self.source_type,
            value="file",
            font=self.font_body,
            radiobutton_width=24,
            radiobutton_height=24,
        ).grid(
            row=0, column=1, sticky="w"
        )

        url_label = ctk.CTkLabel(card, text="릴스 또는 유튜브 링크", font=self.font_label, text_color="#334155")
        url_label.grid(row=2, column=0, padx=22, pady=(0, 7), sticky="w")
        url_entry = ctk.CTkEntry(
            card,
            textvariable=self.url_var,
            placeholder_text="https://www.youtube.com/watch?v=...",
            height=38,
            font=self.font_input,
            corner_radius=7,
        )
        url_entry.grid(row=3, column=0, padx=22, pady=(0, 14), sticky="ew")

        file_row = ctk.CTkFrame(card, fg_color="transparent")
        file_row.grid(row=4, column=0, padx=22, pady=(0, 14), sticky="ew")
        file_row.grid_columnconfigure(0, weight=1)
        ctk.CTkEntry(
            file_row,
            textvariable=self.file_var,
            placeholder_text="동영상 파일 경로",
            height=38,
            font=self.font_input,
            corner_radius=7,
        ).grid(
            row=0, column=0, sticky="ew", padx=(0, 10)
        )
        ctk.CTkButton(
            file_row,
            text="파일 선택",
            width=118,
            height=38,
            corner_radius=7,
            font=self.font_button,
            command=self._choose_video_file,
        ).grid(
            row=0, column=1, sticky="e"
        )

        cookie_row = ctk.CTkFrame(card, fg_color="#f6f8fb", corner_radius=8)
        cookie_row.grid(row=5, column=0, padx=22, pady=(0, 22), sticky="ew")
        cookie_row.grid_columnconfigure(1, weight=1)
        ctk.CTkCheckBox(
            cookie_row,
            text="브라우저 쿠키 사용",
            variable=self.use_cookies_var,
            font=self.font_body,
            checkbox_width=24,
            checkbox_height=24,
        ).grid(row=0, column=0, padx=16, pady=14, sticky="w")
        ctk.CTkComboBox(
            cookie_row,
            variable=self.cookie_browser_var,
            values=["chrome", "edge", "firefox", "brave", "opera"],
            width=150,
            height=36,
            font=self.font_input,
            dropdown_font=self.font_input,
            corner_radius=7,
        ).grid(row=0, column=1, padx=(0, 16), pady=14, sticky="e")
        return card

    def _api_card(self, parent: ctk.CTkBaseClass) -> ctk.CTkFrame:
        card = self._card(parent, "2. OpenAI 설정")
        ctk.CTkLabel(card, text="API 키", font=self.font_label, text_color="#334155").grid(
            row=1, column=0, padx=22, pady=(0, 7), sticky="w"
        )
        ctk.CTkEntry(
            card,
            textvariable=self.api_key_var,
            show="*",
            placeholder_text="sk-...",
            height=38,
            font=self.font_input,
            corner_radius=7,
        ).grid(
            row=2, column=0, padx=22, pady=(0, 12), sticky="ew"
        )
        ctk.CTkCheckBox(
            card,
            text="이 PC에 API 키 저장",
            variable=self.save_api_key_var,
            font=self.font_body,
            checkbox_width=24,
            checkbox_height=24,
        ).grid(row=3, column=0, padx=22, pady=(0, 18), sticky="w")

        model_grid = ctk.CTkFrame(card, fg_color="transparent")
        model_grid.grid(row=4, column=0, padx=22, pady=(0, 22), sticky="ew")
        model_grid.grid_columnconfigure((0, 1), weight=1)
        ctk.CTkLabel(model_grid, text="전사 모델", font=self.font_label, text_color="#334155").grid(
            row=0, column=0, sticky="w"
        )
        ctk.CTkLabel(model_grid, text="문장/요약 모델", font=self.font_label, text_color="#334155").grid(
            row=0, column=1, padx=(12, 0), sticky="w"
        )
        ctk.CTkComboBox(
            model_grid,
            variable=self.transcription_model_var,
            values=["gpt-4o-mini-transcribe", "gpt-4o-transcribe"],
            height=38,
            font=self.font_input,
            dropdown_font=self.font_input,
            corner_radius=7,
        ).grid(row=1, column=0, sticky="ew", pady=(7, 0), padx=(0, 12))
        ctk.CTkComboBox(
            model_grid,
            variable=self.text_model_var,
            values=["gpt-4.1-mini", "gpt-4o-mini", "gpt-5.4-mini", "gpt-5.4"],
            height=38,
            font=self.font_input,
            dropdown_font=self.font_input,
            corner_radius=7,
        ).grid(row=1, column=1, sticky="ew", pady=(7, 0), padx=(12, 0))
        return card

    def _output_card(self, parent: ctk.CTkBaseClass) -> ctk.CTkFrame:
        card = self._card(parent, "3. 출력 설정")
        output_row = ctk.CTkFrame(card, fg_color="transparent")
        output_row.grid(row=1, column=0, padx=22, pady=(0, 16), sticky="ew")
        output_row.grid_columnconfigure(0, weight=1)
        ctk.CTkEntry(
            output_row,
            textvariable=self.output_dir_var,
            height=38,
            font=self.font_input,
            corner_radius=7,
        ).grid(row=0, column=0, sticky="ew", padx=(0, 10))
        ctk.CTkButton(
            output_row,
            text="폴더 선택",
            width=118,
            height=38,
            corner_radius=7,
            font=self.font_button,
            command=self._choose_output_dir,
        ).grid(row=0, column=1)

        scene_box = ctk.CTkFrame(card, fg_color="#f6f8fb", corner_radius=8)
        scene_box.grid(row=2, column=0, padx=22, pady=(0, 20), sticky="ew")
        scene_box.grid_columnconfigure((0, 1, 2), weight=1)
        ctk.CTkCheckBox(
            scene_box,
            text="장면 수 자동 결정",
            variable=self.auto_scene_var,
            font=self.font_body,
            checkbox_width=24,
            checkbox_height=24,
        ).grid(row=0, column=0, padx=16, pady=(16, 10), sticky="w")

        ctk.CTkLabel(scene_box, text="직접 지정", font=self.font_label, text_color="#475569").grid(
            row=1, column=0, padx=16, pady=(0, 7), sticky="w"
        )
        ctk.CTkEntry(
            scene_box,
            textvariable=self.fixed_scene_var,
            width=96,
            height=36,
            font=self.font_input,
            corner_radius=7,
        ).grid(
            row=2, column=0, padx=16, pady=(0, 16), sticky="w"
        )
        ctk.CTkLabel(scene_box, text="자동 최소", font=self.font_label, text_color="#475569").grid(
            row=1, column=1, padx=16, pady=(0, 7), sticky="w"
        )
        ctk.CTkEntry(
            scene_box,
            textvariable=self.min_scene_var,
            width=96,
            height=36,
            font=self.font_input,
            corner_radius=7,
        ).grid(
            row=2, column=1, padx=16, pady=(0, 16), sticky="w"
        )
        ctk.CTkLabel(scene_box, text="자동 최대", font=self.font_label, text_color="#475569").grid(
            row=1, column=2, padx=16, pady=(0, 7), sticky="w"
        )
        ctk.CTkEntry(
            scene_box,
            textvariable=self.max_scene_var,
            width=96,
            height=36,
            font=self.font_input,
            corner_radius=7,
        ).grid(
            row=2, column=2, padx=16, pady=(0, 16), sticky="w"
        )

        action_row = ctk.CTkFrame(card, fg_color="transparent")
        action_row.grid(row=3, column=0, padx=22, pady=(0, 24), sticky="ew")
        action_row.grid_columnconfigure(0, weight=1)
        self.start_button = ctk.CTkButton(
            action_row,
            text="노트 만들기",
            height=46,
            corner_radius=8,
            font=ctk.CTkFont(family=self.font_family, size=16, weight="bold"),
            command=self._start_job,
        )
        self.start_button.grid(row=0, column=0, sticky="ew", padx=(0, 10))
        self.open_output_button = ctk.CTkButton(
            action_row,
            text="결과 폴더 열기",
            width=146,
            height=46,
            state="disabled",
            corner_radius=8,
            font=self.font_button,
            fg_color="#334155",
            hover_color="#1f2937",
            command=self._open_latest_output,
        )
        self.open_output_button.grid(row=0, column=1, sticky="e")
        return card

    def _status_panel(self, parent: ctk.CTkFrame) -> None:
        ctk.CTkLabel(parent, text="진행 상황", font=self.font_section_title, text_color="#111827").grid(
            row=0, column=0, padx=22, pady=(22, 10), sticky="w"
        )
        self.status_label = ctk.CTkLabel(parent, text="대기 중", text_color="#334155", font=self.font_body)
        self.status_label.grid(row=1, column=0, padx=22, pady=(0, 10), sticky="w")
        self.progress_bar = ctk.CTkProgressBar(parent, height=10, corner_radius=5)
        self.progress_bar.grid(row=2, column=0, padx=22, pady=(0, 18), sticky="ew")
        self.progress_bar.set(0)
        self.log_box = ctk.CTkTextbox(
            parent,
            wrap="word",
            fg_color="#101827",
            text_color="#f1f5f9",
            font=self.font_log,
            corner_radius=8,
            border_width=0,
        )
        self.log_box.grid(row=3, column=0, padx=22, pady=(0, 22), sticky="nsew")
        self.log_box.insert("end", "준비되었습니다.\n")
        self.log_box.configure(state="disabled")

    def _choose_video_file(self) -> None:
        path = filedialog.askopenfilename(
            title="동영상 파일 선택",
            filetypes=[
                ("동영상 파일", "*.mp4 *.mov *.mkv *.avi *.webm *.m4v"),
                ("모든 파일", "*.*"),
            ],
        )
        if path:
            self.file_var.set(path)
            self.source_type.set("file")

    def _choose_output_dir(self) -> None:
        path = filedialog.askdirectory(title="출력 폴더 선택")
        if path:
            self.output_dir_var.set(path)

    def _collect_settings(self) -> AppSettings:
        def as_int(value: str, fallback: int, low: int, high: int) -> int:
            try:
                parsed = int(value.strip())
            except ValueError:
                return fallback
            return max(low, min(high, parsed))

        min_scene = as_int(self.min_scene_var.get(), 4, 1, 60)
        max_scene = as_int(self.max_scene_var.get(), 24, min_scene, 80)
        fixed_scene = as_int(self.fixed_scene_var.get(), 10, 1, 80)
        settings = AppSettings(
            api_key=self.api_key_var.get().strip(),
            save_api_key=bool(self.save_api_key_var.get()),
            transcription_model=self.transcription_model_var.get().strip() or "gpt-4o-mini-transcribe",
            text_model=self.text_model_var.get().strip() or "gpt-4.1-mini",
            output_dir=self.output_dir_var.get().strip() or str(default_output_dir()),
            auto_scene_count=bool(self.auto_scene_var.get()),
            fixed_scene_count=fixed_scene,
            min_scene_count=min_scene,
            max_scene_count=max_scene,
            use_browser_cookies=bool(self.use_cookies_var.get()),
            cookie_browser=self.cookie_browser_var.get().strip() or "chrome",
        )
        save_settings(settings)
        self.settings = settings
        return settings

    def _start_job(self) -> None:
        if self.worker_thread and self.worker_thread.is_alive():
            return

        settings = self._collect_settings()
        source = self.url_var.get().strip() if self.source_type.get() == "url" else self.file_var.get().strip()
        if not source:
            messagebox.showwarning("입력 필요", "URL 또는 동영상 파일을 선택해 주세요.")
            return
        if not settings.api_key:
            messagebox.showwarning("API 키 필요", "OpenAI API 키를 입력해 주세요.")
            return

        self.latest_result = None
        self.open_output_button.configure(state="disabled")
        self.start_button.configure(state="disabled", text="처리 중...")
        self.progress_bar.set(0)
        self._set_status("시작합니다", 0.01)
        self._append_log("작업을 시작합니다.")

        self.worker_thread = threading.Thread(target=self._run_worker, args=(settings, source), daemon=True)
        self.worker_thread.start()

    def _run_worker(self, settings: AppSettings, source: str) -> None:
        try:
            pipeline = VideoNotePipeline(settings, progress=self._worker_progress)
            result = pipeline.run(source)
            self.events.put(("done", result))
        except Exception as exc:
            detail = traceback.format_exc()
            self.events.put(("error", f"{exc}\n\n{detail}"))

    def _worker_progress(self, message: str, percent: float, detail: str) -> None:
        self.events.put(("progress", (message, percent, detail)))

    def _drain_events(self) -> None:
        while True:
            try:
                kind, payload = self.events.get_nowait()
            except queue.Empty:
                break
            if kind == "progress":
                message, percent, detail = payload  # type: ignore[misc]
                self._set_status(str(message), float(percent))
                self._append_log(str(detail))
            elif kind == "done":
                self.latest_result = payload  # type: ignore[assignment]
                self._set_status("완료", 1.0)
                self._append_log(f"완료: {self.latest_result.output_dir}")
                self.start_button.configure(state="normal", text="노트 만들기")
                self.open_output_button.configure(state="normal")
                messagebox.showinfo("완료", f"노트가 만들어졌습니다.\n\n{self.latest_result.output_dir}")
            elif kind == "error":
                self._set_status("오류", 0)
                self._append_log(str(payload))
                self.start_button.configure(state="normal", text="노트 만들기")
                messagebox.showerror("처리 실패", str(payload).splitlines()[0])
        self.after(120, self._drain_events)

    def _set_status(self, text: str, percent: float) -> None:
        self.status_label.configure(text=text)
        self.progress_bar.set(max(0.0, min(1.0, percent)))

    def _append_log(self, text: str) -> None:
        self.log_box.configure(state="normal")
        self.log_box.insert("end", f"{text}\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _open_latest_output(self) -> None:
        if not self.latest_result:
            return
        path = self.latest_result.output_dir
        if os.name == "nt":
            os.startfile(path)  # type: ignore[attr-defined]
        else:
            messagebox.showinfo("결과 폴더", str(path))

    def _guide_path(self) -> Path:
        if getattr(sys, "frozen", False):
            return Path(sys.executable).resolve().parent / "사용설명서.html"
        return Path(__file__).resolve().parents[2] / "사용설명서.html"

    def _open_user_guide(self) -> None:
        path = self._guide_path()
        if not path.exists():
            messagebox.showwarning("사용설명서 없음", f"사용설명서 파일을 찾지 못했습니다.\n\n{path}")
            return
        if os.name == "nt":
            os.startfile(path)  # type: ignore[attr-defined]
        else:
            webbrowser.open(path.as_uri())

    def _on_close(self) -> None:
        self._collect_settings()
        self.destroy()


def main() -> None:
    app = ClipNoteApp()
    app.mainloop()
