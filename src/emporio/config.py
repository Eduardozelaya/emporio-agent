"""Runtime configuration.

Importing this module must never fail because of a missing API key: the key is only
required when the LLM is actually called (epic E0, acceptance criterion 4).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()

STORE_TZ = ZoneInfo("America/Campo_Grande")

PACKAGE_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_ROOT.parent.parent


def _env_str(name: str, default: str) -> str:
    """Read an env var, treating an empty value as "not set"."""
    value = os.getenv(name)
    return value if value else default


def _env_int(name: str, default: int) -> int:
    raw = _env_str(name, str(default))
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer, got {raw!r}") from exc


def _env_float(name: str, default: float) -> float:
    raw = _env_str(name, str(default))
    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a number, got {raw!r}") from exc


@dataclass(frozen=True)
class Settings:
    """Everything configurable from the environment (01_ARCHITECTURE section 8)."""

    llm_api_key: str | None
    llm_base_url: str | None
    llm_model: str
    llm_temperature: float
    llm_timeout_s: int
    max_tool_steps: int
    history_window: int
    emporio_today: str | None
    data_dir: Path

    @property
    def raw_dir(self) -> Path:
        return self.data_dir / "raw"

    @property
    def processed_dir(self) -> Path:
        return self.data_dir / "processed"

    @property
    def db_path(self) -> Path:
        return self.processed_dir / "emporio.db"

    @property
    def app_db_path(self) -> Path:
        return self.processed_dir / "app.db"

    @property
    def policies_path(self) -> Path:
        return self.processed_dir / "policies.md"

    def require_api_key(self) -> str:
        """Return the API key or fail with an actionable message (used only by llm.py)."""
        if not self.llm_api_key:
            raise RuntimeError(
                "No API key. Copy .env.example to .env and set LLM_API_KEY "
                "(OPENAI_API_KEY also works), or export it before running this command."
            )
        return self.llm_api_key


def load_settings() -> Settings:
    """Build Settings from the current environment. Not cached, so tests can monkeypatch."""
    data_dir = Path(_env_str("EMPORIO_DATA_DIR", "data"))
    if not data_dir.is_absolute():
        data_dir = PROJECT_ROOT / data_dir
    return Settings(
        # The client speaks the OpenAI protocol to whatever LLM_BASE_URL points at, so the
        # credential is named after the role, not the vendor. OPENAI_API_KEY still works.
        llm_api_key=os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY") or None,
        llm_base_url=os.getenv("LLM_BASE_URL") or None,
        llm_model=_env_str("LLM_MODEL", "gpt-4o-mini"),
        llm_temperature=_env_float("LLM_TEMPERATURE", 0.2),
        llm_timeout_s=_env_int("LLM_TIMEOUT_S", 30),
        max_tool_steps=_env_int("MAX_TOOL_STEPS", 5),
        history_window=_env_int("HISTORY_WINDOW", 20),
        emporio_today=os.getenv("EMPORIO_TODAY") or None,
        data_dir=data_dir,
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings. Call load_settings() directly when you need a fresh read."""
    return load_settings()


def now() -> datetime:
    """Current time in the store's timezone, overridable by EMPORIO_TODAY (DECISIONS D13).

    Always use this instead of datetime.now(): store hours, stale-order detection and the
    example conversations all depend on a controllable clock.
    """
    override = os.getenv("EMPORIO_TODAY")
    if override:
        parsed = datetime.fromisoformat(override)
        # A bare date/datetime is read as local store time.
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=STORE_TZ)
        return parsed.astimezone(STORE_TZ)
    return datetime.now(STORE_TZ)
