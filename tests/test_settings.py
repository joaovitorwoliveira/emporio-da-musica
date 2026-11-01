from datetime import timedelta

import pytest

from emporio.agent import uses_kimi_k26
from emporio.settings import SettingsError, load_settings


def test_missing_api_key_fails_with_instructions(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LLM_API_KEY", "")

    with pytest.raises(SettingsError, match=r"Copy \.env\.example to \.env"):
        load_settings()


def test_placeholder_api_key_is_treated_as_missing(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LLM_API_KEY", "your-api-key-here")

    with pytest.raises(SettingsError, match="LLM_API_KEY"):
        load_settings()


def test_invalid_reference_date_fails_loudly(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("REFERENCE_DATE", "23/03/2026")

    with pytest.raises(SettingsError, match="REFERENCE_DATE"):
        load_settings()


def test_reference_date_is_read_in_the_store_timezone(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LLM_API_KEY", "test-key")
    monkeypatch.setenv("REFERENCE_DATE", "2026-03-23T10:00")
    monkeypatch.setenv("STORE_TIMEZONE", "America/Campo_Grande")

    settings = load_settings()

    assert settings.reference_date.utcoffset() == timedelta(hours=-4)


@pytest.mark.parametrize(
    "model_id, expected",
    [
        ("kimi-k2.6", True),
        ("kimi-k2.7-code", False),
        ("kimi-k3", False),
        ("gpt-4o", False),
    ],
)
def test_thinking_is_disabled_only_for_kimi_k26(model_id: str, expected: bool):
    assert uses_kimi_k26(model_id) is expected
