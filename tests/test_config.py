"""E0 acceptance criteria: settings load without secrets and the clock is controllable."""

from __future__ import annotations

from datetime import datetime

import pytest

from emporio import config


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Start every test from an environment with none of our variables set."""
    for name in (
        "LLM_API_KEY",
        "OPENAI_API_KEY",
        "LLM_BASE_URL",
        "LLM_MODEL",
        "LLM_TEMPERATURE",
        "LLM_TIMEOUT_S",
        "MAX_TOOL_STEPS",
        "HISTORY_WINDOW",
        "EMPORIO_TODAY",
        "EMPORIO_DATA_DIR",
    ):
        monkeypatch.delenv(name, raising=False)


def test_defaults_match_architecture_section_8() -> None:
    settings = config.load_settings()
    assert settings.llm_model == "gpt-4o-mini"
    assert settings.llm_temperature == pytest.approx(0.2)
    assert settings.llm_timeout_s == 30
    assert settings.max_tool_steps == 5
    assert settings.history_window == 20
    assert settings.emporio_today is None


def test_loads_without_api_key() -> None:
    """E0 AC4: importing/loading config must not require a key."""
    settings = config.load_settings()
    assert settings.llm_api_key is None


def test_require_api_key_explains_how_to_fix() -> None:
    settings = config.load_settings()
    with pytest.raises(RuntimeError, match="LLM_API_KEY"):
        settings.require_api_key()


def test_llm_api_key_is_preferred_over_the_openai_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The client speaks the OpenAI protocol to any provider, so the key is role-named."""
    monkeypatch.setenv("OPENAI_API_KEY", "legacy")
    monkeypatch.setenv("LLM_API_KEY", "current")
    assert config.load_settings().llm_api_key == "current"


def test_openai_api_key_still_works(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "legacy")
    assert config.load_settings().llm_api_key == "legacy"


def test_empty_env_var_falls_back_to_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """.env.example ships empty values; an empty string must not override the default."""
    monkeypatch.setenv("LLM_MODEL", "")
    monkeypatch.setenv("MAX_TOOL_STEPS", "")
    settings = config.load_settings()
    assert settings.llm_model == "gpt-4o-mini"
    assert settings.max_tool_steps == 5


def test_env_overrides_are_applied(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_MODEL", "deepseek-chat")
    monkeypatch.setenv("LLM_BASE_URL", "https://api.deepseek.com")
    monkeypatch.setenv("MAX_TOOL_STEPS", "8")
    settings = config.load_settings()
    assert settings.llm_model == "deepseek-chat"
    assert settings.llm_base_url == "https://api.deepseek.com"
    assert settings.max_tool_steps == 8


def test_invalid_int_is_reported_with_the_variable_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HISTORY_WINDOW", "twenty")
    with pytest.raises(ValueError, match="HISTORY_WINDOW"):
        config.load_settings()


def test_derived_paths_hang_off_the_data_dir(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("EMPORIO_DATA_DIR", str(tmp_path))
    settings = config.load_settings()
    assert settings.raw_dir == tmp_path / "raw"
    assert settings.db_path == tmp_path / "processed" / "emporio.db"
    assert settings.policies_path == tmp_path / "processed" / "policies.md"


def test_now_uses_the_store_timezone() -> None:
    assert config.now().tzinfo is config.STORE_TZ
    # Mato Grosso do Sul is UTC-4 all year (Brazil dropped DST in 2019).
    assert config.now().utcoffset().total_seconds() == -4 * 3600


def test_emporio_today_override_naive(monkeypatch: pytest.MonkeyPatch) -> None:
    """DECISIONS D13: a fixed clock makes examples and tests reproducible."""
    monkeypatch.setenv("EMPORIO_TODAY", "2026-11-01T12:20:00")
    frozen = config.now()
    assert frozen == datetime(2026, 11, 1, 12, 20, tzinfo=config.STORE_TZ)
    assert frozen.weekday() == 6  # Sunday, the date used by the examples


def test_emporio_today_override_with_offset_is_converted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("EMPORIO_TODAY", "2026-11-01T15:20:00-01:00")
    frozen = config.now()
    assert frozen.hour == 12  # -01:00 15:20 is 12:20 in Campo Grande (-04:00)
