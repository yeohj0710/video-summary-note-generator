from clipnote_ai.utils import extract_json_object, format_timecode, parse_timecode, sanitize_filename, suggest_scene_count


def test_format_and_parse_timecode():
    assert format_timecode(65) == "00:01:05"
    assert format_timecode(3661) == "01:01:01"
    assert parse_timecode("01:01:01") == 3661
    assert parse_timecode("03:20") == 200


def test_sanitize_filename():
    assert sanitize_filename('a/b:c* "clip"') == "a_b_c_ _clip_"
    assert sanitize_filename("   ") == "media"


def test_extract_json_object_from_markdown():
    payload = extract_json_object('```json\n{"title": "테스트", "scenes": []}\n```')
    assert payload["title"] == "테스트"


def test_suggest_scene_count_scales_with_duration():
    short = suggest_scene_count(45, 4, 24)
    long = suggest_scene_count(3600, 4, 24)
    assert short >= 4
    assert long > short
    assert long <= 24

