from clipnote_ai.pipeline import VideoNotePipeline
from clipnote_ai.settings import AppSettings


def test_download_tries_next_browser_cookie_when_selected_browser_fails(tmp_path):
    pipeline = VideoNotePipeline.__new__(VideoNotePipeline)
    pipeline.settings = AppSettings(use_browser_cookies=True, cookie_browser="chrome")
    pipeline.ffmpeg = "ffmpeg"
    pipeline.progress = lambda *args: None
    video = tmp_path / "reel.mp4"
    video.write_bytes(b"video")
    calls = []

    def fake_download(_yt_dlp_module, _url, ydl_opts, _downloads_dir, _started):
        calls.append(dict(ydl_opts))
        if len(calls) == 1:
            raise RuntimeError("login required. Use --cookies-from-browser")
        if ydl_opts.get("cookiesfrombrowser") == ("edge",):
            return video, "retry success"
        raise RuntimeError("browser cookie failed")

    pipeline._download_with_ytdlp = fake_download

    downloaded, title = pipeline._download_video("https://www.instagram.com/reel/example/", "2605101200", tmp_path)

    assert downloaded == video.resolve()
    assert title == "retry success"
    assert calls[0]["cookiesfrombrowser"] == ("chrome",)
    assert calls[1]["cookiesfrombrowser"] == ("edge",)


def test_non_instagram_cookie_error_also_retries_with_browser_cookies(tmp_path):
    pipeline = VideoNotePipeline.__new__(VideoNotePipeline)
    pipeline.settings = AppSettings(use_browser_cookies=False, cookie_browser="chrome")
    pipeline.ffmpeg = "ffmpeg"
    pipeline.progress = lambda *args: None
    video = tmp_path / "youtube.mp4"
    video.write_bytes(b"video")
    calls = []

    def fake_download(_yt_dlp_module, _url, ydl_opts, _downloads_dir, _started):
        calls.append(dict(ydl_opts))
        if len(calls) == 1:
            raise RuntimeError("Sign in to confirm your age. Use --cookies-from-browser")
        return video, "youtube success"

    pipeline._download_with_ytdlp = fake_download

    downloaded, title = pipeline._download_video("https://www.youtube.com/watch?v=example", "2605101200", tmp_path)

    assert downloaded == video.resolve()
    assert title == "youtube success"
    assert "cookiesfrombrowser" not in calls[0]
    assert calls[1]["cookiesfrombrowser"] == ("chrome",)
