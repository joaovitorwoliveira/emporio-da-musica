import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_ROOT / "data"
POLICIES_PDF_PATH = DATA_DIR / "politicas_da_loja.pdf"
RUNTIME_DIR = PROJECT_ROOT / "runtime"
STORE_DB_PATH = RUNTIME_DIR / "store.db"
CONVERSATIONS_DB_PATH = RUNTIME_DIR / "conversations.db"
ESCALATION_LOG_PATH = RUNTIME_DIR / "escalations.jsonl"
ENV_FILE = PROJECT_ROOT / ".env"

DEFAULT_LLM_BASE_URL = "https://api.moonshot.ai/v1"
DEFAULT_LLM_MODEL = "kimi-k2.6"
DEFAULT_REFERENCE_DATE = "2026-03-23T10:00"
DEFAULT_STORE_TIMEZONE = "America/Campo_Grande"
REFERENCE_DATE_FORMAT = "%Y-%m-%dT%H:%M"
API_KEY_PLACEHOLDER = "your-api-key-here"


class SettingsError(Exception):
    pass


@dataclass(frozen=True)
class Settings:
    llm_base_url: str
    llm_api_key: str
    llm_model: str
    reference_date: datetime
    store_timezone: ZoneInfo
    store_db_path: Path
    conversations_db_path: Path
    escalation_log_path: Path


def load_settings() -> Settings:
    load_dotenv(ENV_FILE)
    store_timezone = _parse_timezone(os.getenv("STORE_TIMEZONE", DEFAULT_STORE_TIMEZONE))
    return Settings(
        llm_base_url=os.getenv("LLM_BASE_URL", DEFAULT_LLM_BASE_URL),
        llm_api_key=_require_api_key(),
        llm_model=os.getenv("LLM_MODEL", DEFAULT_LLM_MODEL),
        reference_date=_parse_reference_date(
            os.getenv("REFERENCE_DATE", DEFAULT_REFERENCE_DATE), store_timezone
        ),
        store_timezone=store_timezone,
        store_db_path=STORE_DB_PATH,
        conversations_db_path=CONVERSATIONS_DB_PATH,
        escalation_log_path=ESCALATION_LOG_PATH,
    )


def _require_api_key() -> str:
    api_key = os.getenv("LLM_API_KEY", "").strip()
    if api_key and api_key != API_KEY_PLACEHOLDER:
        return api_key
    raise SettingsError(
        "LLM_API_KEY is missing. Copy .env.example to .env and set LLM_API_KEY "
        "to your API key."
    )


def _parse_timezone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError as error:
        raise SettingsError(
            f"STORE_TIMEZONE '{name}' is not a valid IANA timezone name "
            "(example: America/Campo_Grande)."
        ) from error


def _parse_reference_date(value: str, timezone: ZoneInfo) -> datetime:
    try:
        return datetime.strptime(value, REFERENCE_DATE_FORMAT).replace(tzinfo=timezone)
    except ValueError as error:
        raise SettingsError(
            f"REFERENCE_DATE '{value}' does not match YYYY-MM-DDTHH:MM "
            "(example: 2026-03-23T10:00)."
        ) from error
