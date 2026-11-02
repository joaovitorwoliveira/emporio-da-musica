import uuid

from langchain_core.messages import AIMessage, AnyMessage, RemoveMessage
from langchain_core.runnables import RunnableConfig
from langgraph.constants import START
from langgraph.graph.state import CompiledStateGraph

USER_ROLE = "user"
ASSISTANT_ROLE = "assistant"


def new_conversation_id() -> str:
    return str(uuid.uuid4())


def parse_conversation_id(raw: str | None) -> str | None:
    """Returns the canonical id, or None when `raw` is missing or not a UUID."""
    if not raw:
        return None
    try:
        return str(uuid.UUID(raw))
    except ValueError:
        return None


def thread_config(conversation_id: str) -> RunnableConfig:
    return {"configurable": {"thread_id": conversation_id}}


def load_messages(agent: CompiledStateGraph, conversation_id: str) -> list[AnyMessage]:
    return agent.get_state(thread_config(conversation_id)).values.get("messages", [])


def load_history(agent: CompiledStateGraph, conversation_id: str) -> list[tuple[str, str]]:
    """Customer messages and Lia's final answers, as the customer saw them live.

    Tool results and AI messages that call tools are dropped, including any
    narration that comes with the call, because the live chat only shows the
    answer that ends the turn.
    """
    history: list[tuple[str, str]] = []
    for message in load_messages(agent, conversation_id):
        if not message.text.strip():
            continue
        if message.type == "human":
            history.append((USER_ROLE, message.text))
        elif isinstance(message, AIMessage) and not message.tool_calls:
            history.append((ASSISTANT_ROLE, message.text))
    return history


def discard_messages_added_since(
    agent: CompiledStateGraph, conversation_id: str, known_ids: set[str | None]
) -> None:
    added = [m for m in load_messages(agent, conversation_id) if m.id not in known_ids]
    if not added:
        return
    removals = [RemoveMessage(id=m.id) for m in added if m.id is not None]
    # Writing as START avoids routing from the last node, which would run the
    # agent's branch on a state that may have no messages left.
    agent.update_state(thread_config(conversation_id), {"messages": removals}, as_node=START)
