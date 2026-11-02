from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.tools import BaseTool
from langgraph.graph.state import CompiledStateGraph
from pydantic import SkipValidation

from emporio.agent import build_agent, open_checkpointer
from emporio.seed import seed_store
from emporio.settings import DEFAULT_STORE_TIMEZONE, Settings
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


class ScriptedChatModel(BaseChatModel):
    """Plays back a fixed script, one item per model call; an Exception item is raised."""

    # AIMessage's validator chokes on an Exception item, so the script skips validation.
    script: SkipValidation[list[AIMessage | Exception]]
    position: int = 0

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools: Sequence[Any], **kwargs: Any) -> "ScriptedChatModel":
        return self

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        item = self.script[self.position]
        self.position += 1
        if isinstance(item, Exception):
            raise item
        return ChatResult(generations=[ChatGeneration(message=item)])


def product_lookup_call() -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[{"name": "find_product", "args": {"name": "Takamine"}, "id": "call-1"}],
    )


@pytest.fixture
def agent_settings(store_db: Path, escalation_log: Path, reference_date: datetime, tmp_path: Path) -> Settings:
    return Settings(
        llm_base_url="http://localhost",
        llm_api_key="test-key",
        llm_model="fake",
        reference_date=reference_date,
        store_timezone=ZoneInfo(DEFAULT_STORE_TIMEZONE),
        store_db_path=store_db,
        conversations_db_path=tmp_path / "runtime" / "conversations.db",
        escalation_log_path=escalation_log,
    )


@pytest.fixture
def make_agent(agent_settings: Settings) -> Callable[[list[AIMessage | Exception]], CompiledStateGraph]:
    """Builds an agent on the test conversations file; each call opens a new connection."""

    def make(script: list[AIMessage | Exception]) -> CompiledStateGraph:
        checkpointer = open_checkpointer(agent_settings.conversations_db_path)
        return build_agent(agent_settings, checkpointer, ScriptedChatModel(script=script))

    return make
