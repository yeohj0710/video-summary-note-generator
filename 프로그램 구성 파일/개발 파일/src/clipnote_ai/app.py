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
from openai import OpenAI

from clipnote_ai.pipeline import (
    AUDIO_EXTENSIONS,
    PipelineResult,
    UserFacingError,
    VIDEO_EXTENSIONS,
    VideoNotePipeline,
)
from clipnote_ai.settings import (
    DEFAULT_TEXT_MODEL,
    AppSettings,
    default_output_dir,
    is_current_default_output_dir,
    load_settings,
    save_settings,
)
from clipnote_ai.utils import resource_path


SOURCE_URL_MODE = "링크로 가져오기"
SOURCE_FILE_MODE = "내 컴퓨터 파일"
PRODUCT_NAME = "영상·음성 요약 노트 생성기"
CUSTOM_TEXT_MODEL_OPTION = "직접 입력"
TRANSCRIPTION_MODEL_CHOICES = ["gpt-4o-mini-transcribe", "gpt-4o-transcribe"]
TEXT_MODEL_CHOICES = ["gpt-5-nano", "gpt-4.1-nano", "gpt-4o-mini", CUSTOM_TEXT_MODEL_OPTION]
VIDEO_FILE_PATTERN = " ".join(f"*{ext}" for ext in sorted(VIDEO_EXTENSIONS))
AUDIO_FILE_PATTERN = " ".join(f"*{ext}" for ext in sorted(AUDIO_EXTENSIONS))
MEDIA_FILE_PATTERN = f"{VIDEO_FILE_PATTERN} {AUDIO_FILE_PATTERN}"


class SmoothScrollableFrame(ctk.CTkScrollableFrame):
    scroll_pixels_per_notch = 34
    scroll_frame_delay_ms = 12
    scroll_ease = 0.16

    def __init__(self, *args: object, **kwargs: object) -> None:
        self.scrollbar_gap = int(kwargs.pop("scrollbar_gap", 14))
        self.scrollbar_outer_padding = int(kwargs.pop("scrollbar_outer_padding", 4))
        self._smooth_scroll_target_px: float | None = None
        self._smooth_scroll_after_id: str | None = None
        super().__init__(*args, **kwargs)
        self._add_scrollbar_breathing_room()
        if self._orientation == "vertical":
            self._scrollbar.configure(command=self._scrollbar_yview)

    def _add_scrollbar_breathing_room(self) -> None:
        if self._orientation != "vertical":
            return
        border_spacing = self._apply_widget_scaling(
            self._parent_frame.cget("corner_radius") + self._parent_frame.cget("border_width")
        )
        self._parent_canvas.grid_configure(
            padx=(border_spacing, self._apply_widget_scaling(self.scrollbar_gap)),
            pady=border_spacing,
        )
        self._scrollbar.grid_configure(
            padx=(0, self._apply_widget_scaling(self.scrollbar_outer_padding)),
            pady=(border_spacing, border_spacing),
        )

    def destroy(self) -> None:
        self._cancel_smooth_scroll()
        super().destroy()

    def _cancel_smooth_scroll(self) -> None:
        if self._smooth_scroll_after_id is not None:
            try:
                self.after_cancel(self._smooth_scroll_after_id)
            except tk.TclError:
                pass
            self._smooth_scroll_after_id = None
        self._smooth_scroll_target_px = None

    def _scrollbar_yview(self, *args: object) -> None:
        self._cancel_smooth_scroll()
        self._parent_canvas.yview(*args)

    def _mouse_wheel_all(self, event: tk.Event) -> str | None:
        if not self.check_if_master_is_canvas(event.widget):
            return None
        if self._shift_pressed:
            return super()._mouse_wheel_all(event)
        if self._parent_canvas.yview() == (0.0, 1.0):
            return "break"

        notches = self._wheel_notches(event)
        if notches == 0:
            return "break"

        self._smooth_scroll_by(-notches * self.scroll_pixels_per_notch)
        return "break"

    def _wheel_notches(self, event: tk.Event) -> float:
        delta = getattr(event, "delta", 0)
        if delta:
            if sys.platform.startswith("win"):
                notches = float(delta) / 120
                return max(-1.0, min(1.0, notches))
            return float(delta)
        number = getattr(event, "num", None)
        if number == 4:
            return 1.0
        if number == 5:
            return -1.0
        return 0.0

    def _scroll_metrics(self) -> tuple[float, float]:
        self._parent_canvas.update_idletasks()
        bbox = self._parent_canvas.bbox("all")
        if bbox is None:
            return 0.0, 0.0
        content_height = max(1, bbox[3] - bbox[1])
        viewport_height = max(1, self._parent_canvas.winfo_height())
        return float(max(0, content_height - viewport_height)), self._parent_canvas.yview()[0]

    def _smooth_scroll_by(self, pixels: float) -> None:
        scrollable_px, current_fraction = self._scroll_metrics()
        if scrollable_px <= 0:
            return

        current_px = current_fraction * scrollable_px
        base_px = self._smooth_scroll_target_px if self._smooth_scroll_target_px is not None else current_px
        self._smooth_scroll_target_px = max(0.0, min(scrollable_px, base_px + pixels))

        if self._smooth_scroll_after_id is None:
            self._animate_smooth_scroll()

    def _animate_smooth_scroll(self) -> None:
        if self._smooth_scroll_target_px is None:
            self._smooth_scroll_after_id = None
            return

        scrollable_px, current_fraction = self._scroll_metrics()
        if scrollable_px <= 0:
            self._smooth_scroll_target_px = None
            self._smooth_scroll_after_id = None
            return

        current_px = current_fraction * scrollable_px
        diff = self._smooth_scroll_target_px - current_px
        if abs(diff) < 1.0:
            self._parent_canvas.yview_moveto(self._smooth_scroll_target_px / scrollable_px)
            self._smooth_scroll_target_px = None
            self._smooth_scroll_after_id = None
            return

        step = diff * self.scroll_ease
        if abs(step) < 1.0:
            step = 1.0 if diff > 0 else -1.0
        next_px = max(0.0, min(scrollable_px, current_px + step))
        self._parent_canvas.yview_moveto(next_px / scrollable_px)
        self._smooth_scroll_after_id = self.after(self.scroll_frame_delay_ms, self._animate_smooth_scroll)


class ActivitySpinner(tk.Canvas):
    def __init__(
        self,
        master: tk.Misc,
        size: int = 18,
        color: str = "#2563eb",
        bg: str = "#ffffff",
    ) -> None:
        super().__init__(
            master,
            width=size,
            height=size,
            bg=bg,
            highlightthickness=0,
            bd=0,
        )
        self.size = size
        self.color = color
        self.angle = 90
        self.after_id: str | None = None
        self.running = False

    def start(self) -> None:
        if self.running:
            return
        self.running = True
        self._tick()

    def stop(self) -> None:
        self.running = False
        if self.after_id is not None:
            try:
                self.after_cancel(self.after_id)
            except tk.TclError:
                pass
            self.after_id = None
        self.delete("all")

    def _tick(self) -> None:
        self.delete("all")
        pad = 3
        self.create_arc(
            pad,
            pad,
            self.size - pad,
            self.size - pad,
            start=self.angle,
            extent=285,
            style="arc",
            outline=self.color,
            width=3,
        )
        self.angle = (self.angle - 18) % 360
        if self.running:
            self.after_id = self.after(33, self._tick)


class ClipNoteApp(ctk.CTk):
    primary_color = "#2563eb"
    primary_hover = "#1d4ed8"
    secondary_color = "#eef4ff"
    secondary_hover = "#dbeafe"
    secondary_text = "#1d4ed8"
    success_color = "#059669"
    success_hover = "#047857"
    warning_color = "#f59e0b"
    warning_hover = "#d97706"
    disabled_color = "#d8dee8"
    disabled_text = "#64748b"

    def __init__(self) -> None:
        super().__init__()
        ctk.set_appearance_mode("light")
        ctk.set_default_color_theme("blue")

        self.title(PRODUCT_NAME)
        self._set_window_icon()
        self.geometry("1160x820")
        self.minsize(1080, 740)

        self.settings = load_settings()
        self.worker_thread: threading.Thread | None = None
        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.latest_result: PipelineResult | None = None
        self.is_processing = False
        self.processing_locked_widgets: list[ctk.CTkBaseClass] = []

        self.source_type = tk.StringVar(value=SOURCE_URL_MODE)
        self.url_var = tk.StringVar()
        self.file_var = tk.StringVar()
        self.api_key_var = tk.StringVar(value=self.settings.api_key)
        self.api_key_locked = bool(self.settings.api_key.strip())
        self.save_api_key_var = tk.BooleanVar(value=self.settings.save_api_key)
        self.transcription_model_var = tk.StringVar(value=self.settings.transcription_model)
        saved_text_model = self.settings.text_model.strip() or DEFAULT_TEXT_MODEL
        if saved_text_model in TEXT_MODEL_CHOICES:
            self.text_model_var = tk.StringVar(value=saved_text_model)
            self.custom_text_model_var = tk.StringVar(value="")
        else:
            self.text_model_var = tk.StringVar(value=CUSTOM_TEXT_MODEL_OPTION)
            self.custom_text_model_var = tk.StringVar(value=saved_text_model)
        self.output_dir_var = tk.StringVar(value=self.settings.output_dir or str(default_output_dir()))
        self.auto_summary_var = tk.BooleanVar(value=self.settings.auto_summary_sentences)
        self.summary_sentence_var = tk.StringVar(value=str(self.settings.summary_sentence_count))
        self.auto_scene_var = tk.BooleanVar(value=self.settings.auto_scene_count)
        self.fixed_scene_var = tk.StringVar(value=str(self.settings.fixed_scene_count))
        self.min_scene_var = tk.StringVar(value=str(self.settings.min_scene_count))
        self.max_scene_var = tk.StringVar(value=str(self.settings.max_scene_count))
        self.use_cookies_var = tk.BooleanVar(value=self.settings.use_browser_cookies)
        self.cookie_browser_var = tk.StringVar(value=self.settings.cookie_browser)

        self._configure_typography()
        self._build_ui()
        self._ensure_user_folders()
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
        self.font_credit = ctk.CTkFont(family=self.font_family, size=12, weight="bold")
        self.font_card_title = ctk.CTkFont(family=self.font_family, size=19, weight="bold")
        self.font_section_title = ctk.CTkFont(family=self.font_family, size=18, weight="bold")
        self.font_body = ctk.CTkFont(family=self.font_family, size=14)
        self.font_label = ctk.CTkFont(family=self.font_family, size=13)
        self.font_button = ctk.CTkFont(family=self.font_family, size=14, weight="bold")
        self.font_input = ctk.CTkFont(family=self.font_family, size=14)
        self.font_log = ctk.CTkFont(family=self.font_family, size=13)

    def _set_window_icon(self) -> None:
        icon_path = resource_path("assets", "clipnote.ico")
        if not icon_path.exists():
            return
        try:
            self.iconbitmap(str(icon_path))
        except tk.TclError:
            pass

    def _build_ui(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        header = ctk.CTkFrame(self, fg_color="#f8fafc", corner_radius=0)
        header.grid(row=0, column=0, sticky="ew")
        header.grid_columnconfigure(0, weight=1)
        header.grid_columnconfigure(1, weight=0)

        title = ctk.CTkLabel(
            header,
            text=PRODUCT_NAME,
            font=self.font_title,
            text_color="#111827",
        )
        title.grid(row=0, column=0, padx=32, pady=(22, 4), sticky="w")
        credit = ctk.CTkLabel(
            header,
            text="developed by yeohj0710",
            font=self.font_credit,
            text_color="#2563eb",
            fg_color="#eaf2ff",
            corner_radius=6,
            padx=10,
            pady=3,
        )
        credit.grid(row=1, column=0, padx=32, pady=(0, 7), sticky="w")
        credit.configure(cursor="hand2")
        credit.bind("<Button-1>", lambda _event: self._open_developer_profile())
        subtitle = ctk.CTkLabel(
            header,
            text="릴스, 유튜브, 로컬 영상/오디오를 저장하고 전체 스크립트 TXT와 상세 요약 TXT로 변환합니다.",
            font=self.font_subtitle,
            text_color="#475569",
        )
        subtitle.grid(row=2, column=0, padx=32, pady=(0, 22), sticky="w")
        ctk.CTkButton(
            header,
            text="사용설명서 열기",
            width=172,
            height=40,
            corner_radius=8,
            font=self.font_button,
            fg_color=self.secondary_color,
            hover_color=self.secondary_hover,
            text_color=self.secondary_text,
            command=self._open_user_guide,
        ).grid(row=0, column=1, rowspan=3, padx=(12, 32), pady=26, sticky="e")

        body = ctk.CTkFrame(self, fg_color="#edf1f6", corner_radius=0)
        body.grid(row=1, column=0, sticky="nsew")
        body.grid_columnconfigure(0, weight=3)
        body.grid_columnconfigure(1, weight=2)
        body.grid_rowconfigure(0, weight=1)

        left = SmoothScrollableFrame(
            body,
            fg_color="#edf1f6",
            scrollbar_button_color="#94a3b8",
            scrollbar_button_hover_color="#64748b",
        )
        left.grid(row=0, column=0, sticky="nsew", padx=(24, 12), pady=24)
        left.grid_columnconfigure(0, weight=1)

        right = ctk.CTkFrame(body, fg_color="#ffffff", corner_radius=10)
        right.grid(row=0, column=1, sticky="nsew", padx=(12, 24), pady=24)
        right.grid_columnconfigure(0, weight=1)
        right.grid_rowconfigure(4, weight=1)

        self._source_card(left).grid(row=0, column=0, sticky="ew", pady=(0, 14))
        self._api_card(left).grid(row=1, column=0, sticky="ew", pady=(0, 14))
        self._summary_card(left).grid(row=2, column=0, sticky="ew", pady=(0, 14))
        self._output_card(left).grid(row=3, column=0, sticky="ew", pady=(0, 14))
        self._register_processing_controls()

        self._status_panel(right)

    def _card(self, parent: ctk.CTkBaseClass, title: str) -> ctk.CTkFrame:
        card = ctk.CTkFrame(parent, fg_color="#ffffff", corner_radius=10)
        card.grid_columnconfigure(0, weight=1)
        label = ctk.CTkLabel(card, text=title, font=self.font_card_title, text_color="#111827")
        label.grid(row=0, column=0, padx=22, pady=(20, 12), sticky="w")
        return card

    def _make_select_only_combo(self, combo: ctk.CTkComboBox, allowed_values: list[str]) -> None:
        def block_key_input(event: tk.Event | None = None) -> str | None:
            if event is not None and getattr(event, "keysym", "") in {"Tab", "Escape"}:
                return None
            return "break"

        def restore_if_needed(_event: tk.Event | None = None) -> None:
            current = combo.get().strip()
            if current not in allowed_values:
                combo.set(allowed_values[0])

        try:
            combo._entry.bind("<Key>", block_key_input)
            combo._entry.bind("<<Paste>>", block_key_input)
            combo._entry.bind("<FocusOut>", restore_if_needed)
        except (tk.TclError, AttributeError):
            pass

    def _helper_label(self, parent: ctk.CTkBaseClass, text: str, row: int, padx: int = 22) -> ctk.CTkLabel:
        label = ctk.CTkLabel(
            parent,
            text=text,
            font=self.font_label,
            text_color="#64748b",
            justify="left",
            anchor="w",
            wraplength=560,
        )
        label.grid(row=row, column=0, padx=padx, pady=(0, 12), sticky="ew")
        return label

    def _source_card(self, parent: ctk.CTkBaseClass) -> ctk.CTkFrame:
        card = self._card(parent, "1. 영상 가져오기")
        self.source_guide_button = ctk.CTkButton(
            card,
            text="가져오기 도움말",
            width=128,
            height=32,
            corner_radius=7,
            font=self.font_label,
            fg_color=self.secondary_color,
            hover_color=self.secondary_hover,
            text_color=self.secondary_text,
            command=self._open_source_guide,
        )
        self.source_guide_button.grid(row=0, column=0, padx=22, pady=(18, 12), sticky="e")
        self._helper_label(card, "유튜브/릴스 링크를 붙여넣거나, PC에 저장된 영상 또는 오디오 파일을 선택하는 곳입니다.", 1)

        ctk.CTkLabel(card, text="가져올 방식", font=self.font_label, text_color="#334155").grid(
            row=2, column=0, padx=22, pady=(0, 8), sticky="w"
        )
        self.source_mode_switch = ctk.CTkSegmentedButton(
            card,
            values=[SOURCE_URL_MODE, SOURCE_FILE_MODE],
            variable=self.source_type,
            command=lambda _value: self._refresh_source_mode(),
            height=40,
            corner_radius=8,
            font=self.font_button,
            fg_color="#e2e8f0",
            selected_color="#93c5fd",
            selected_hover_color="#60a5fa",
            unselected_color="#f8fafc",
            unselected_hover_color="#edf2f7",
            text_color="#1f2937",
            text_color_disabled="#94a3b8",
        )
        self.source_mode_switch.grid(row=3, column=0, padx=22, pady=(0, 16), sticky="ew")

        self.url_panel = ctk.CTkFrame(card, fg_color="#f6f8fb", corner_radius=8)
        self.url_panel.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            self.url_panel,
            text="릴스 또는 유튜브 링크",
            font=self.font_label,
            text_color="#334155",
        ).grid(row=0, column=0, padx=16, pady=(16, 7), sticky="w")
        self.url_entry = ctk.CTkEntry(
            self.url_panel,
            textvariable=self.url_var,
            placeholder_text="https://www.youtube.com/watch?v=... 또는 https://www.instagram.com/reel/...",
            height=40,
            font=self.font_input,
            corner_radius=7,
        )
        self.url_entry.grid(row=1, column=0, padx=16, pady=(0, 14), sticky="ew")
        ctk.CTkLabel(
            self.url_panel,
            text="브라우저 주소창의 영상 주소를 그대로 복사해서 붙여넣으면 됩니다.",
            font=self.font_label,
            text_color="#64748b",
            justify="left",
            anchor="w",
            wraplength=520,
        ).grid(row=2, column=0, padx=16, pady=(0, 12), sticky="ew")

        cookie_row = ctk.CTkFrame(self.url_panel, fg_color="#ffffff", corner_radius=8)
        cookie_row.grid(row=3, column=0, padx=16, pady=(0, 16), sticky="ew")
        cookie_row.grid_columnconfigure(1, weight=1)
        self.use_cookies_checkbox = ctk.CTkCheckBox(
            cookie_row,
            text="브라우저 쿠키 사용",
            variable=self.use_cookies_var,
            font=self.font_body,
            checkbox_width=24,
            checkbox_height=24,
        )
        self.use_cookies_checkbox.grid(row=0, column=0, padx=14, pady=12, sticky="w")
        self.cookie_browser_combo = ctk.CTkComboBox(
            cookie_row,
            variable=self.cookie_browser_var,
            values=["chrome", "edge", "firefox", "brave", "opera"],
            width=150,
            height=36,
            font=self.font_input,
            dropdown_font=self.font_input,
            corner_radius=7,
        )
        self.cookie_browser_combo.grid(row=0, column=1, padx=(0, 14), pady=12, sticky="e")
        ctk.CTkLabel(
            cookie_row,
            text="로그인이 필요한 릴스/유튜브가 안 받아질 때만 켜세요.",
            font=self.font_label,
            text_color="#64748b",
            justify="left",
            anchor="w",
            wraplength=480,
        ).grid(row=1, column=0, columnspan=2, padx=14, pady=(0, 12), sticky="ew")

        self.file_panel = ctk.CTkFrame(card, fg_color="#f6f8fb", corner_radius=8)
        self.file_panel.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            self.file_panel,
            text="내 컴퓨터 영상/오디오 파일",
            font=self.font_label,
            text_color="#334155",
        ).grid(row=0, column=0, padx=16, pady=(16, 7), sticky="w")
        file_row = ctk.CTkFrame(self.file_panel, fg_color="transparent")
        file_row.grid(row=1, column=0, padx=16, pady=(0, 16), sticky="ew")
        file_row.grid_columnconfigure(0, weight=1)
        self.file_entry = ctk.CTkEntry(
            file_row,
            textvariable=self.file_var,
            placeholder_text="mp4, mov, m4a, mp3, wav, amr 파일",
            height=40,
            font=self.font_input,
            corner_radius=7,
        )
        self.file_entry.grid(row=0, column=0, sticky="ew", padx=(0, 10))
        self.file_button = ctk.CTkButton(
            file_row,
            text="파일 선택",
            width=118,
            height=40,
            corner_radius=7,
            font=self.font_button,
            fg_color=self.primary_color,
            hover_color=self.primary_hover,
            command=self._choose_video_file,
        )
        self.file_button.grid(row=0, column=1, sticky="e")
        ctk.CTkLabel(
            self.file_panel,
            text="녹화 파일이나 이미 다운로드된 영상은 이 방식이 가장 안정적입니다.",
            font=self.font_label,
            text_color="#64748b",
            justify="left",
            anchor="w",
            wraplength=520,
        ).grid(row=2, column=0, padx=16, pady=(0, 14), sticky="ew")

        self._refresh_source_mode()
        return card

    def _refresh_source_mode(self) -> None:
        if not hasattr(self, "url_panel") or not hasattr(self, "file_panel"):
            return
        if self.source_type.get() == SOURCE_FILE_MODE:
            self.url_panel.grid_remove()
            self.file_panel.grid(row=4, column=0, padx=22, pady=(0, 22), sticky="ew")
        else:
            self.file_panel.grid_remove()
            self.url_panel.grid(row=4, column=0, padx=22, pady=(0, 22), sticky="ew")

    def _is_url_mode(self) -> bool:
        return self.source_type.get() != SOURCE_FILE_MODE

    def _register_processing_controls(self) -> None:
        self.processing_locked_widgets = [
            self.source_mode_switch,
            self.source_guide_button,
            self.url_entry,
            self.use_cookies_checkbox,
            self.cookie_browser_combo,
            self.file_entry,
            self.file_button,
            self.api_key_entry,
            self.api_key_lock_button,
            self.api_key_guide_button,
            self.save_api_key_checkbox,
            self.transcription_model_combo,
            self.text_model_combo,
            self.custom_text_model_entry,
            self.auto_summary_checkbox,
            self.summary_sentence_entry,
            self.output_dir_entry,
            self.output_dir_button,
        ]

    def _api_card(self, parent: ctk.CTkBaseClass) -> ctk.CTkFrame:
        card = self._card(parent, "2. OpenAI API Key 설정")
        self.api_key_guide_button = ctk.CTkButton(
            card,
            text="API 키 받는 법",
            width=122,
            height=32,
            corner_radius=7,
            font=self.font_label,
            fg_color=self.secondary_color,
            hover_color=self.secondary_hover,
            text_color=self.secondary_text,
            command=self._open_api_key_guide,
        )
        self.api_key_guide_button.grid(row=0, column=0, padx=22, pady=(18, 12), sticky="e")
        self._helper_label(card, "전사와 요약을 만들기 위해 본인 OpenAI API 키를 입력하는 곳입니다.", 1)
        ctk.CTkLabel(card, text="API 키", font=self.font_label, text_color="#334155").grid(
            row=2, column=0, padx=22, pady=(0, 7), sticky="w"
        )

        api_key_row = ctk.CTkFrame(card, fg_color="transparent")
        api_key_row.grid(row=3, column=0, padx=22, pady=(0, 8), sticky="ew")
        api_key_row.grid_columnconfigure(0, weight=1)
        self.api_key_entry = ctk.CTkEntry(
            api_key_row,
            textvariable=self.api_key_var,
            placeholder_text="sk-...",
            height=38,
            font=self.font_input,
            corner_radius=7,
        )
        self.api_key_entry.grid(row=0, column=0, sticky="ew", padx=(0, 10))
        self.api_key_lock_button = ctk.CTkButton(
            api_key_row,
            text="설정",
            width=76,
            height=38,
            corner_radius=7,
            font=self.font_button,
            command=self._toggle_api_key_lock,
        )
        self.api_key_lock_button.grid(row=0, column=1)
        ctk.CTkLabel(
            card,
            text="설정을 누르면 키 입력칸이 잠깁니다. 다시 바꾸려면 수정 버튼을 누르세요.",
            font=self.font_label,
            text_color="#64748b",
            justify="left",
            anchor="w",
            wraplength=560,
        ).grid(row=4, column=0, padx=22, pady=(0, 12), sticky="ew")
        self.save_api_key_checkbox = ctk.CTkCheckBox(
            card,
            text="이 PC에 API 키 저장",
            variable=self.save_api_key_var,
            font=self.font_body,
            checkbox_width=24,
            checkbox_height=24,
        )
        self.save_api_key_checkbox.grid(row=5, column=0, padx=22, pady=(0, 18), sticky="w")

        model_grid = ctk.CTkFrame(card, fg_color="transparent")
        model_grid.grid(row=6, column=0, padx=22, pady=(0, 22), sticky="ew")
        model_grid.grid_columnconfigure((0, 1), weight=1)
        ctk.CTkLabel(model_grid, text="전사 모델", font=self.font_label, text_color="#334155").grid(
            row=0, column=0, sticky="w"
        )
        ctk.CTkLabel(model_grid, text="문장 정리/요약 모델", font=self.font_label, text_color="#334155").grid(
            row=0, column=1, padx=(12, 0), sticky="w"
        )
        self.transcription_model_combo = ctk.CTkComboBox(
            model_grid,
            variable=self.transcription_model_var,
            values=TRANSCRIPTION_MODEL_CHOICES,
            height=38,
            font=self.font_input,
            dropdown_font=self.font_input,
            corner_radius=7,
        )
        self.transcription_model_combo.grid(row=1, column=0, sticky="ew", pady=(7, 0), padx=(0, 12))
        self._make_select_only_combo(self.transcription_model_combo, TRANSCRIPTION_MODEL_CHOICES)
        ctk.CTkLabel(
            model_grid,
            text="영상 음성을 글자로 바꾸는 모델입니다.",
            font=self.font_label,
            text_color="#64748b",
            justify="left",
            anchor="w",
            wraplength=250,
        ).grid(row=2, column=0, sticky="ew", pady=(6, 0), padx=(0, 12))
        self.text_model_combo = ctk.CTkComboBox(
            model_grid,
            variable=self.text_model_var,
            values=TEXT_MODEL_CHOICES,
            command=lambda _value: self._refresh_text_model_mode(),
            height=38,
            font=self.font_input,
            dropdown_font=self.font_input,
            corner_radius=7,
        )
        self.text_model_combo.grid(row=1, column=1, sticky="ew", pady=(7, 0), padx=(12, 0))
        self._make_select_only_combo(self.text_model_combo, TEXT_MODEL_CHOICES)
        self.custom_text_model_entry = ctk.CTkEntry(
            model_grid,
            textvariable=self.custom_text_model_var,
            placeholder_text="예: gpt-5.6-nano",
            height=36,
            font=self.font_input,
            corner_radius=7,
        )
        self.custom_text_model_entry.grid(row=2, column=1, sticky="ew", pady=(6, 0), padx=(12, 0))
        self.text_model_helper_label = ctk.CTkLabel(
            model_grid,
            text="맞춤법 정리와 요약을 맡는 모델입니다. 직접 입력은 모델 존재 확인 후 사용합니다.",
            font=self.font_label,
            text_color="#64748b",
            justify="left",
            anchor="w",
            wraplength=250,
        )
        self.text_model_helper_label.grid(row=3, column=1, sticky="ew", pady=(6, 0), padx=(12, 0))
        self._refresh_text_model_mode()
        self._refresh_api_key_lock()
        return card

    def _summary_card(self, parent: ctk.CTkBaseClass) -> ctk.CTkFrame:
        card = self._card(parent, "3. 요약 설정")
        self._helper_label(card, "요약 TXT가 얼마나 길게 만들어질지 정하는 곳입니다. 처음에는 자동을 추천합니다.", 1)
        self.auto_summary_checkbox = ctk.CTkCheckBox(
            card,
            text="자동으로 요약 길이 결정",
            variable=self.auto_summary_var,
            command=self._refresh_summary_mode,
            font=self.font_body,
            checkbox_width=24,
            checkbox_height=24,
        )
        self.auto_summary_checkbox.grid(row=2, column=0, padx=22, pady=(0, 12), sticky="w")

        summary_box = ctk.CTkFrame(card, fg_color="#f6f8fb", corner_radius=8)
        summary_box.grid(row=3, column=0, padx=22, pady=(0, 22), sticky="ew")
        summary_box.grid_columnconfigure(0, weight=1)

        self.summary_sentence_label = ctk.CTkLabel(
            summary_box,
            text="직접 지정 문장 수",
            font=self.font_label,
            text_color="#334155",
        )
        self.summary_sentence_label.grid(row=0, column=0, padx=16, pady=(14, 7), sticky="w")
        self.summary_sentence_entry = ctk.CTkEntry(
            summary_box,
            textvariable=self.summary_sentence_var,
            height=38,
            width=118,
            font=self.font_input,
            corner_radius=7,
        )
        self.summary_sentence_entry.grid(row=1, column=0, padx=16, pady=(0, 14), sticky="w")
        ctk.CTkLabel(
            summary_box,
            text="자동 기준: 전체 스크립트 문장의 약 1/5\n직접 정하려면 자동 체크를 끄고 문장 수를 입력하세요.",
            font=self.font_label,
            text_color="#64748b",
            justify="left",
            anchor="w",
            wraplength=390,
        ).grid(row=2, column=0, padx=16, pady=(0, 14), sticky="ew")

        self._refresh_summary_mode()
        return card

    def _output_card(self, parent: ctk.CTkBaseClass) -> ctk.CTkFrame:
        card = self._card(parent, "4. 저장 설정")
        self._helper_label(card, "완성된 영상, 전체 스크립트 TXT, 요약 TXT가 저장될 폴더입니다.", 1)
        output_row = ctk.CTkFrame(card, fg_color="transparent")
        output_row.grid(row=2, column=0, padx=22, pady=(0, 10), sticky="ew")
        output_row.grid_columnconfigure(0, weight=1)
        self.output_dir_entry = ctk.CTkEntry(
            output_row,
            textvariable=self.output_dir_var,
            height=38,
            font=self.font_input,
            corner_radius=7,
        )
        self.output_dir_entry.grid(row=0, column=0, sticky="ew", padx=(0, 10))
        self.output_dir_button = ctk.CTkButton(
            output_row,
            text="폴더 선택",
            width=118,
            height=38,
            corner_radius=7,
            font=self.font_button,
            fg_color=self.primary_color,
            hover_color=self.primary_hover,
            command=self._choose_output_dir,
        )
        self.output_dir_button.grid(row=0, column=1)
        ctk.CTkLabel(
            card,
            text="기본값은 repo 안의 '생성된 노트' 폴더입니다. 결과 파일을 찾기 쉬우면 그대로 두면 됩니다.",
            font=self.font_label,
            text_color="#64748b",
            justify="left",
            anchor="w",
            wraplength=560,
        ).grid(row=3, column=0, padx=22, pady=(0, 16), sticky="ew")

        action_row = ctk.CTkFrame(card, fg_color="transparent")
        action_row.grid(row=4, column=0, padx=22, pady=(0, 24), sticky="ew")
        action_row.grid_columnconfigure(0, weight=1)
        self.start_button = ctk.CTkButton(
            action_row,
            text="노트 만들기",
            height=46,
            corner_radius=8,
            font=ctk.CTkFont(family=self.font_family, size=16, weight="bold"),
            fg_color=self.primary_color,
            hover_color=self.primary_hover,
            text_color="#ffffff",
            text_color_disabled=self.disabled_text,
            command=self._start_job,
        )
        self.start_button.grid(row=0, column=0, sticky="ew", padx=(0, 10))
        self.start_button_spinner = ActivitySpinner(
            action_row,
            size=18,
            color="#ffffff",
            bg=self.primary_hover,
        )
        self.start_button_spinner.place(in_=self.start_button, relx=0.35, rely=0.5, anchor="center")
        self.start_button_spinner.place_forget()
        self.open_output_button = ctk.CTkButton(
            action_row,
            text="결과 폴더 열기",
            width=146,
            height=46,
            state="disabled",
            corner_radius=8,
            font=self.font_button,
            fg_color=self.disabled_color,
            hover_color=self.disabled_color,
            text_color="#ffffff",
            text_color_disabled=self.disabled_text,
            command=self._open_latest_output,
        )
        self.open_output_button.grid(row=0, column=1, sticky="e")
        return card

    def _status_panel(self, parent: ctk.CTkFrame) -> None:
        ctk.CTkLabel(parent, text="진행 상황", font=self.font_section_title, text_color="#111827").grid(
            row=0, column=0, padx=22, pady=(22, 10), sticky="w"
        )
        ctk.CTkLabel(
            parent,
            text="현재 작업 단계와 자세한 처리 기록을 보여줍니다.",
            font=self.font_label,
            text_color="#64748b",
            justify="left",
            anchor="w",
            wraplength=420,
        ).grid(row=1, column=0, padx=22, pady=(0, 10), sticky="ew")
        status_row = ctk.CTkFrame(parent, fg_color="transparent")
        status_row.grid(row=2, column=0, padx=22, pady=(0, 10), sticky="ew")
        status_row.grid_columnconfigure(1, weight=1)
        self.activity_spinner = ActivitySpinner(
            status_row,
            size=18,
            color=self.primary_color,
            bg="#ffffff",
        )
        self.activity_spinner.grid(row=0, column=0, padx=(0, 8), sticky="w")
        self.activity_spinner.grid_remove()
        self.status_label = ctk.CTkLabel(status_row, text="대기 중", text_color="#334155", font=self.font_body)
        self.status_label.grid(row=0, column=1, sticky="w")
        self.progress_bar = ctk.CTkProgressBar(
            parent,
            height=10,
            corner_radius=5,
            progress_color=self.primary_color,
        )
        self.progress_bar.grid(row=3, column=0, padx=22, pady=(0, 18), sticky="ew")
        self.progress_bar.set(0)
        self.log_box = ctk.CTkTextbox(
            parent,
            wrap="word",
            fg_color="#101827",
            text_color="#f1f5f9",
            font=self.font_log,
            corner_radius=8,
            border_width=0,
            border_spacing=12,
            scrollbar_button_color="#475569",
            scrollbar_button_hover_color="#64748b",
        )
        self.log_box.grid(row=4, column=0, padx=22, pady=(0, 22), sticky="nsew")
        self.log_box.insert("end", "준비되었습니다.\n")
        self.log_box.configure(state="disabled")

    def _choose_video_file(self) -> None:
        if self.is_processing:
            return
        path = filedialog.askopenfilename(
            title="영상 또는 오디오 파일 선택",
            filetypes=[
                ("영상/오디오 파일", MEDIA_FILE_PATTERN),
                ("영상 파일", VIDEO_FILE_PATTERN),
                ("오디오 파일", AUDIO_FILE_PATTERN),
                ("모든 파일", "*.*"),
            ],
        )
        if path:
            self.file_var.set(path)
            self.source_type.set(SOURCE_FILE_MODE)
            self._refresh_source_mode()

    def _ensure_user_folders(self) -> None:
        try:
            Path(self.output_dir_var.get()).expanduser().mkdir(parents=True, exist_ok=True)
        except OSError:
            pass

    def _choose_output_dir(self) -> None:
        if self.is_processing:
            return
        path = filedialog.askdirectory(title="출력 폴더 선택")
        if path:
            self.output_dir_var.set(path)

    def _toggle_api_key_lock(self) -> None:
        if self.is_processing:
            return
        if self.api_key_locked:
            self.api_key_locked = False
            self._refresh_api_key_lock()
            self.api_key_entry.focus_set()
            return

        if not self.api_key_var.get().strip():
            messagebox.showwarning("API 키 필요", "OpenAI API 키를 입력한 뒤 설정해 주세요.")
            self.api_key_entry.focus_set()
            return

        self.api_key_locked = True
        self._collect_settings()
        self._refresh_api_key_lock()

    def _refresh_api_key_lock(self) -> None:
        if not hasattr(self, "api_key_entry") or not hasattr(self, "api_key_lock_button"):
            return

        if self.is_processing:
            self.api_key_entry.configure(state="disabled", fg_color="#edf2f7", border_color="#cbd5e1", text_color="#94a3b8")
            self.api_key_lock_button.configure(
                state="disabled",
                fg_color=self.disabled_color,
                hover_color=self.disabled_color,
                text_color_disabled=self.disabled_text,
            )
            return

        if self.api_key_locked:
            self.api_key_entry.configure(state="disabled", fg_color="#edf2f7", border_color="#cbd5e1", text_color="#475569")
            self.api_key_lock_button.configure(
                state="normal",
                text="수정",
                fg_color=self.secondary_color,
                hover_color=self.secondary_hover,
                text_color=self.secondary_text,
            )
            self._set_widget_cursor(self.api_key_entry, "no")
        else:
            self.api_key_entry.configure(state="normal", fg_color="#ffffff", border_color="#94a3b8", text_color="#111827")
            self.api_key_lock_button.configure(
                state="normal",
                text="설정",
                fg_color=self.primary_color,
                hover_color=self.primary_hover,
                text_color="#ffffff",
            )
            self._set_widget_cursor(self.api_key_entry, "")

    def _refresh_summary_mode(self) -> None:
        if not hasattr(self, "summary_sentence_entry"):
            return

        if self.is_processing:
            self.summary_sentence_entry.configure(state="disabled", fg_color="#edf2f7", border_color="#cbd5e1", text_color="#94a3b8")
            self.summary_sentence_label.configure(text_color="#94a3b8")
            return

        if self.auto_summary_var.get():
            self.summary_sentence_entry.configure(state="disabled", fg_color="#edf2f7", border_color="#cbd5e1", text_color="#94a3b8")
            self.summary_sentence_label.configure(text_color="#94a3b8")
            self._set_widget_cursor(self.summary_sentence_entry, "no")
        else:
            self.summary_sentence_entry.configure(state="normal", fg_color="#ffffff", border_color="#94a3b8", text_color="#111827")
            self.summary_sentence_label.configure(text_color="#475569")
            self._set_widget_cursor(self.summary_sentence_entry, "")

    def _refresh_text_model_mode(self) -> None:
        if not hasattr(self, "custom_text_model_entry"):
            return

        custom_selected = self.text_model_var.get() == CUSTOM_TEXT_MODEL_OPTION
        if custom_selected:
            self.custom_text_model_entry.grid()
            self.text_model_helper_label.grid(row=3, column=1, sticky="ew", pady=(6, 0), padx=(12, 0))
        else:
            self.custom_text_model_entry.grid_remove()
            self.text_model_helper_label.grid(row=2, column=1, sticky="ew", pady=(6, 0), padx=(12, 0))

        if self.is_processing or not custom_selected:
            self.custom_text_model_entry.configure(
                state="disabled",
                fg_color="#edf2f7",
                border_color="#cbd5e1",
                text_color="#94a3b8",
            )
            self._set_widget_cursor(self.custom_text_model_entry, "no" if custom_selected else "")
            return

        self.custom_text_model_entry.configure(
            state="normal",
            fg_color="#ffffff",
            border_color="#94a3b8",
            text_color="#111827",
        )
        self._set_widget_cursor(self.custom_text_model_entry, "")

    def _refresh_scene_count_mode(self) -> None:
        if not hasattr(self, "fixed_scene_entry"):
            return

        if self.is_processing:
            for entry, label in (
                (self.fixed_scene_entry, self.fixed_scene_label),
                (self.min_scene_entry, self.min_scene_label),
                (self.max_scene_entry, self.max_scene_label),
            ):
                entry.configure(state="disabled", fg_color="#edf2f7", border_color="#cbd5e1", text_color="#94a3b8")
                label.configure(text_color="#94a3b8")
            return

        auto = bool(self.auto_scene_var.get())
        enabled_label = "#475569"
        disabled_label = "#94a3b8"

        def set_entry(entry: ctk.CTkEntry, label: ctk.CTkLabel, enabled: bool) -> None:
            if enabled:
                entry.configure(state="normal", fg_color="#ffffff", border_color="#94a3b8", text_color="#111827")
                label.configure(text_color=enabled_label)
            else:
                entry.configure(state="disabled", fg_color="#edf2f7", border_color="#cbd5e1", text_color="#94a3b8")
                label.configure(text_color=disabled_label)

        set_entry(self.fixed_scene_entry, self.fixed_scene_label, not auto)
        set_entry(self.min_scene_entry, self.min_scene_label, auto)
        set_entry(self.max_scene_entry, self.max_scene_label, auto)

    def _set_processing_indicator(self, active: bool) -> None:
        self.is_processing = active
        if not hasattr(self, "activity_spinner"):
            return

        if active:
            self.activity_spinner.grid()
            self.activity_spinner.start()
        else:
            self.activity_spinner.stop()
            self.activity_spinner.grid_remove()

    def _set_widget_cursor(self, widget: object, cursor: str) -> None:
        targets = [
            widget,
            getattr(widget, "_canvas", None),
            getattr(widget, "_entry", None),
            getattr(widget, "_button", None),
            getattr(widget, "_text_label", None),
            getattr(widget, "_check_state", None),
        ]
        for target in targets:
            if target is None:
                continue
            try:
                target.configure(cursor=cursor)
            except (tk.TclError, AttributeError, ValueError):
                pass

    def _set_controls_locked(self, locked: bool) -> None:
        cursor = "no" if locked else ""
        for widget in self.processing_locked_widgets:
            try:
                widget.configure(state="disabled" if locked else "normal")
            except (tk.TclError, ValueError):
                pass
            self._set_widget_cursor(widget, cursor)

        if locked:
            disabled_entry_options = {
                "state": "disabled",
                "fg_color": "#edf2f7",
                "border_color": "#cbd5e1",
                "text_color": "#94a3b8",
            }
            for entry in (self.url_entry, self.file_entry, self.output_dir_entry, self.custom_text_model_entry):
                entry.configure(**disabled_entry_options)
            for button in (self.file_button, self.output_dir_button):
                button.configure(
                    state="disabled",
                    fg_color=self.disabled_color,
                    hover_color=self.disabled_color,
                    text_color_disabled=self.disabled_text,
                )
            for combo in (self.cookie_browser_combo, self.transcription_model_combo, self.text_model_combo):
                combo.configure(state="disabled", fg_color="#edf2f7", border_color="#cbd5e1", button_color="#cbd5e1")
            self._refresh_api_key_lock()
            self._refresh_summary_mode()
            self._refresh_text_model_mode()
            self._refresh_scene_count_mode()
            return

        for entry in (self.url_entry, self.file_entry, self.output_dir_entry):
            entry.configure(state="normal", fg_color="#ffffff", border_color="#94a3b8", text_color="#111827")
        for button in (self.file_button, self.output_dir_button):
            button.configure(
                state="normal",
                fg_color=self.primary_color,
                hover_color=self.primary_hover,
                text_color="#ffffff",
                text_color_disabled=self.disabled_text,
            )
        for combo in (self.cookie_browser_combo, self.transcription_model_combo, self.text_model_combo):
            combo.configure(state="normal", fg_color="#ffffff", border_color="#94a3b8", button_color="#9ca3af")
        self._refresh_api_key_lock()
        self._refresh_summary_mode()
        self._refresh_text_model_mode()
        self._refresh_scene_count_mode()

    def _set_start_button_busy(self, busy: bool) -> None:
        if busy:
            self.start_button.configure(
                state="disabled",
                text="    처리 중",
                fg_color=self.primary_hover,
                hover_color=self.primary_hover,
                text_color_disabled="#ffffff",
            )
            self.start_button_spinner.place(in_=self.start_button, relx=0.38, rely=0.5, anchor="center")
            self.start_button_spinner.start()
            self._set_processing_indicator(True)
        else:
            self._set_processing_indicator(False)
            self.start_button_spinner.stop()
            self.start_button_spinner.place_forget()
            self.start_button.configure(
                state="normal",
                text="노트 만들기",
                fg_color=self.primary_color,
                hover_color=self.primary_hover,
                text_color="#ffffff",
                text_color_disabled=self.disabled_text,
            )

    def _set_output_button_enabled(self, enabled: bool) -> None:
        if enabled:
            self.open_output_button.configure(
                state="normal",
                fg_color=self.success_color,
                hover_color=self.success_hover,
                text_color="#ffffff",
            )
        else:
            self.open_output_button.configure(
                state="disabled",
                fg_color=self.disabled_color,
                hover_color=self.disabled_color,
                text_color_disabled=self.disabled_text,
            )

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
        summary_sentence_count = as_int(self.summary_sentence_var.get(), 30, 3, 160)
        output_dir = self.output_dir_var.get().strip() or str(default_output_dir())
        text_model = self.text_model_var.get().strip() or DEFAULT_TEXT_MODEL
        if text_model == CUSTOM_TEXT_MODEL_OPTION:
            text_model = self.custom_text_model_var.get().strip() or DEFAULT_TEXT_MODEL
        transcription_model = self.transcription_model_var.get().strip() or "gpt-4o-mini-transcribe"
        if transcription_model not in TRANSCRIPTION_MODEL_CHOICES:
            transcription_model = "gpt-4o-mini-transcribe"
        settings = AppSettings(
            api_key=self.api_key_var.get().strip(),
            save_api_key=bool(self.save_api_key_var.get()),
            transcription_model=transcription_model,
            text_model=text_model,
            output_dir=output_dir,
            output_dir_custom=not is_current_default_output_dir(output_dir),
            auto_summary_sentences=bool(self.auto_summary_var.get()),
            summary_sentence_count=summary_sentence_count,
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

    def _prepare_text_model_for_start(self, settings: AppSettings) -> AppSettings:
        if self.text_model_var.get() != CUSTOM_TEXT_MODEL_OPTION:
            return settings

        custom_model = self.custom_text_model_var.get().strip()
        if not custom_model:
            settings.text_model = DEFAULT_TEXT_MODEL
            self.text_model_var.set(DEFAULT_TEXT_MODEL)
            self._refresh_text_model_mode()
            self._append_log(f"직접 입력 모델명이 비어 있어 기본 모델({DEFAULT_TEXT_MODEL})로 진행합니다.")
            save_settings(settings)
            self.settings = settings
            return settings

        self._set_status("모델 확인 중", 0.01)
        self._append_log(f"직접 입력한 모델 확인 중: {custom_model}")
        if self._openai_model_exists(settings.api_key, custom_model):
            settings.text_model = custom_model
            self._append_log(f"모델 확인 완료: {custom_model}")
        else:
            settings.text_model = DEFAULT_TEXT_MODEL
            self.text_model_var.set(DEFAULT_TEXT_MODEL)
            self._refresh_text_model_mode()
            self._append_log(f"모델을 찾지 못해 기본 모델({DEFAULT_TEXT_MODEL})로 진행합니다.")
        save_settings(settings)
        self.settings = settings
        return settings

    @staticmethod
    def _openai_model_exists(api_key: str, model: str) -> bool:
        try:
            OpenAI(api_key=api_key).models.retrieve(model)
            return True
        except Exception:
            return False

    def _start_job(self) -> None:
        if self.worker_thread and self.worker_thread.is_alive():
            return

        settings = self._collect_settings()
        is_url_mode = self._is_url_mode()
        source = self.url_var.get().strip() if is_url_mode else self.file_var.get().strip()
        if not source:
            if is_url_mode:
                messagebox.showwarning("링크 필요", "릴스 또는 유튜브 링크를 입력해 주세요.")
            else:
                messagebox.showwarning("파일 필요", "내 컴퓨터의 영상 또는 오디오 파일을 선택해 주세요.")
            return
        if is_url_mode and not source.lower().startswith(("http://", "https://")):
            messagebox.showwarning("링크 확인", "링크는 http:// 또는 https://로 시작해야 합니다.")
            return
        if not is_url_mode and not Path(source).expanduser().exists():
            messagebox.showwarning("파일 확인", "선택한 영상 또는 오디오 파일을 찾을 수 없습니다.")
            return
        if not settings.api_key:
            messagebox.showwarning("API 키 필요", "OpenAI API 키를 입력해 주세요.")
            return
        settings = self._prepare_text_model_for_start(settings)

        self.latest_result = None
        self._set_output_button_enabled(False)
        self._set_start_button_busy(True)
        self._set_controls_locked(True)
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
        except BaseException as exc:
            if isinstance(exc, UserFacingError):
                self.events.put(("error", str(exc)))
                return
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
                self._append_log(self.latest_result.cost_report.format_for_log())
                self._set_start_button_busy(False)
                self._set_controls_locked(False)
                self._set_output_button_enabled(True)
                messagebox.showinfo("완료", f"영상, 스크립트, 요약 파일이 저장되었습니다.\n\n{self.latest_result.output_dir}")
            elif kind == "error":
                self._set_status("오류", 0)
                self._append_log(str(payload))
                self._set_start_button_busy(False)
                self._set_controls_locked(False)
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

    def _api_key_guide_path(self) -> Path:
        if getattr(sys, "frozen", False):
            return Path(sys.executable).resolve().parent / "프로그램 구성 파일" / "openai_api_key_guide.html"
        return Path(__file__).resolve().parents[2] / "openai_api_key_guide.html"

    def _source_guide_path(self) -> Path:
        if getattr(sys, "frozen", False):
            return Path(sys.executable).resolve().parent / "프로그램 구성 파일" / "video_source_guide.html"
        return Path(__file__).resolve().parents[2] / "video_source_guide.html"

    def _open_user_guide(self) -> None:
        path = self._guide_path()
        if not path.exists():
            messagebox.showwarning("사용설명서 없음", f"사용설명서 파일을 찾지 못했습니다.\n\n{path}")
            return
        if os.name == "nt":
            os.startfile(path)  # type: ignore[attr-defined]
        else:
            webbrowser.open(path.as_uri())

    def _open_api_key_guide(self) -> None:
        path = self._api_key_guide_path()
        if not path.exists():
            messagebox.showwarning("API 키 가이드 없음", f"API 키 가이드 파일을 찾지 못했습니다.\n\n{path}")
            return
        if os.name == "nt":
            os.startfile(path)  # type: ignore[attr-defined]
        else:
            webbrowser.open(path.as_uri())

    def _open_source_guide(self) -> None:
        path = self._source_guide_path()
        if not path.exists():
            messagebox.showwarning("영상 가져오기 도움말 없음", f"영상 가져오기 도움말 파일을 찾지 못했습니다.\n\n{path}")
            return
        if os.name == "nt":
            os.startfile(path)  # type: ignore[attr-defined]
        else:
            webbrowser.open(path.as_uri())

    @staticmethod
    def _open_developer_profile() -> None:
        webbrowser.open("https://github.com/yeohj0710")

    def _on_close(self) -> None:
        self._set_processing_indicator(False)
        self._collect_settings()
        self.destroy()


def main() -> None:
    app = ClipNoteApp()
    app.mainloop()
