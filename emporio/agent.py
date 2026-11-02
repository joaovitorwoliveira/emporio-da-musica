import sqlite3
import warnings
from pathlib import Path

from langchain_core.language_models import BaseChatModel
from langchain_core.tools import BaseTool
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.sqlite import SqliteSaver
from langchain_openai import ChatOpenAI
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import create_react_agent
from langgraph.warnings import LangGraphDeprecatedSinceV10

from emporio.conversations import discard_messages_added_since, load_messages, thread_config
from emporio.prompt import build_system_prompt
from emporio.settings import Settings
from emporio.tools import build_tools

KIMI_K26_MODEL_ID = "kimi-k2.6"
KIMI_DISABLE_THINKING = {"thinking": {"type": "disabled"}}


def uses_kimi_k26(model_id: str) -> bool:
    return model_id.lower().startswith(KIMI_K26_MODEL_ID)


def build_llm(settings: Settings) -> ChatOpenAI:
    extra_body = KIMI_DISABLE_THINKING if uses_kimi_k26(settings.llm_model) else None
    return ChatOpenAI(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        model=settings.llm_model,
        extra_body=extra_body,
    )


def open_checkpointer(db_path: Path) -> SqliteSaver:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    # Streamlit runs each session's script in its own thread; SqliteSaver
    # serializes access to the connection with a lock, so sharing is safe.
    return SqliteSaver(sqlite3.connect(db_path, check_same_thread=False))


def build_agent(
    settings: Settings, checkpointer: BaseCheckpointSaver, llm: BaseChatModel | None = None
) -> CompiledStateGraph:
    tools: list[BaseTool] = build_tools(
        settings.store_db_path, settings.escalation_log_path, settings.reference_date
    )
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=LangGraphDeprecatedSinceV10)
        return create_react_agent(
            llm or build_llm(settings),
            tools,
            prompt=build_system_prompt(settings),
            checkpointer=checkpointer,
        )


def reply(agent: CompiledStateGraph, conversation_id: str, message: str) -> str:
    """Sends one customer message and returns Lia's answer.

    A failed turn is rolled back so the saved conversation never keeps the
    customer message (or a dangling tool call) of a turn that got no answer.
    """
    known_ids = {m.id for m in load_messages(agent, conversation_id)}
    try:
        result = agent.invoke(
            {"messages": [("user", message)]}, thread_config(conversation_id)
        )
        answer = result["messages"][-1].text
        if not answer.strip():
            raise RuntimeError("The model returned an empty reply.")
    except Exception:
        discard_messages_added_since(agent, conversation_id, known_ids)
        raise
    return answer
