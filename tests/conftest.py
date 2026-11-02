from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from langchain_core.tools import BaseTool

from emporio.seed import seed_store
from emporio.settings import DEFAULT_STORE_TIMEZONE
from emporio.tools import build_tools

DEFAULT_REFERENCE_DATE = datetime(
    2026, 3, 23, 10, 0, tzinfo=ZoneInfo(DEFAULT_STORE_TIMEZONE)
)


@pytest.fixture
def store_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "store.db"
    seed_store(db_path)
    return db_path


@pytest.fixture
def reference_date() -> datetime:
    return DEFAULT_REFERENCE_DATE


@pytest.fixture
def escalation_log(tmp_path: Path) -> Path:
    return tmp_path / "runtime" / "escalations.jsonl"


@pytest.fixture
def tools(
    store_db: Path, escalation_log: Path, reference_date: datetime
) -> dict[str, BaseTool]:
    return {
        tool.name: tool for tool in build_tools(store_db, escalation_log, reference_date)
    }
