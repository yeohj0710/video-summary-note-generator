from clipnote_ai.pipeline import VideoNotePipeline


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


def test_caption_title_strips_instagram_prefix_and_hashtags():
    title = VideoNotePipeline._caption_title(
        "1,234 likes, 56 comments - reels_drgn: Hidden Speedy AI로 만드는 법 #ai #tutorial"
    )

    assert title == "Hidden Speedy AI로 만드는 법"
