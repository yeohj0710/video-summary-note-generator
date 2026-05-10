from clipnote_ai.app import CUSTOM_TEXT_MODEL_OPTION, TEXT_MODEL_CHOICES, TRANSCRIPTION_MODEL_CHOICES
from clipnote_ai.settings import DEFAULT_TEXT_MODEL


def test_user_facing_model_choices_stay_small_and_cost_focused():
    assert TRANSCRIPTION_MODEL_CHOICES == ["gpt-4o-mini-transcribe", "gpt-4o-transcribe"]
    assert TEXT_MODEL_CHOICES == [DEFAULT_TEXT_MODEL, "gpt-4.1-nano", "gpt-4o-mini", CUSTOM_TEXT_MODEL_OPTION]
