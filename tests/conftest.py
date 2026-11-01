from pathlib import Path

import pytest

from emporio.seed import seed_store


@pytest.fixture
def store_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "store.db"
    seed_store(db_path)
    return db_path
