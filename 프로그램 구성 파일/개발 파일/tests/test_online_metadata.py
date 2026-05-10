from clipnote_ai.pipeline import VideoNotePipeline
from clipnote_ai.settings import AppSettings


def test_best_source_title_prefers_instagram_caption_over_generic_title():
    pipeline = VideoNotePipeline.__new__(VideoNotePipeline)
    info = {
        "title": "Video by reels_drgn",
        "description": "이런 건물 폭발하는 영상 만드는 방법 알려드릴게요.\n\n#ai #reels",
    }

    assert pipeline._best_source_title(info) == "이런 건물 폭발하는 영상 만드는 방법 알려드릴게요."


def test_best_source_title_keeps_real_youtube_title():
    pipeline = VideoNotePipeline.__new__(VideoNotePipeline)
    info = {
        "title": "마케팅 프레임워크 강의 1부",
        "description": "설명란입니다.",
    }

    assert pipeline._best_source_title(info) == "마케팅 프레임워크 강의 1부"


def test_best_source_title_removes_repeated_parenthetical_suffix():
    pipeline = VideoNotePipeline.__new__(VideoNotePipeline)
    info = {
        "title": "LOV3 (Feat. Bryan Chase, Okasian) (LOV3 (Feat. Bryan Chase, Okasian))",
    }

    assert pipeline._best_source_title(info) == "LOV3 (Feat. Bryan Chase, Okasian)"


def test_caption_title_strips_instagram_prefix_and_hashtags():
    title = VideoNotePipeline._caption_title(
        "1,234 likes, 56 comments - reels_drgn: Hidden Speedy AI로 만드는 법 #ai #tutorial"
    )

    assert title == "Hidden Speedy AI로 만드는 법"


def test_instagram_download_error_tells_user_to_enable_cookies():
    pipeline = VideoNotePipeline.__new__(VideoNotePipeline)
    pipeline.settings = AppSettings(use_browser_cookies=False, cookie_browser="chrome")

    error = pipeline._friendly_download_error(
        "https://www.instagram.com/reel/example/",
        RuntimeError("Requested content is not available, rate-limit reached or login required. Use --cookies-from-browser"),
    )

    assert "브라우저 쿠키 사용" in str(error)
    assert "Instagram" in str(error)


def test_instagram_download_error_mentions_selected_browser_when_cookies_enabled():
    pipeline = VideoNotePipeline.__new__(VideoNotePipeline)
    pipeline.settings = AppSettings(use_browser_cookies=True, cookie_browser="edge")

    error = pipeline._friendly_download_error(
        "https://www.instagram.com/reel/example/",
        RuntimeError("login required"),
    )

    assert "edge" in str(error)
    assert "로그인" in str(error)


def test_instagram_download_retries_with_browser_cookies(tmp_path):
    pipeline = VideoNotePipeline.__new__(VideoNotePipeline)
    pipeline.settings = AppSettings(use_browser_cookies=False, cookie_browser="chrome")
    pipeline.ffmpeg = "ffmpeg"
    events = []
    pipeline.progress = lambda *args: events.append(args)
    video = tmp_path / "reel.mp4"
    video.write_bytes(b"video")
    calls = []

    def fake_download(_yt_dlp_module, _url, ydl_opts, _downloads_dir, _started):
        calls.append(dict(ydl_opts))
        if len(calls) == 1:
            raise RuntimeError("login required. Use --cookies-from-browser")
        return video, "릴스 제목"

    pipeline._download_with_ytdlp = fake_download

    downloaded, title = pipeline._download_video("https://www.instagram.com/reel/example/", "2605101200", tmp_path)

    assert downloaded == video.resolve()
    assert title == "릴스 제목"
    assert "cookiesfrombrowser" not in calls[0]
    assert calls[1]["cookiesfrombrowser"] == ("chrome",)
    assert any("쿠키" in str(event) for event in events)
