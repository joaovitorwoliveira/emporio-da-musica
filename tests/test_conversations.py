import threading
from collections.abc import Callable
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage
from langgraph.graph.state import CompiledStateGraph

from conftest import product_lookup_call
from emporio.agent import reply
from emporio.conversations import (
    ASSISTANT_ROLE,
    USER_ROLE,
    load_history,
    load_messages,
    new_conversation_id,
    parse_conversation_id,
)
from emporio.settings import (
    CONVERSATIONS_DB_PATH,
    RUNTIME_DIR,
    STORE_DB_PATH,
    Settings,
    load_settings,
)

MakeAgent = Callable[[list[AIMessage | Exception]], CompiledStateGraph]


class ModelUnavailable(Exception):
    pass


def test_settings_expose_a_conversations_db_separate_from_the_store_db(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setenv("LLM_API_KEY", "test-key")

    settings = load_settings()

    assert CONVERSATIONS_DB_PATH == RUNTIME_DIR / "conversations.db"
    assert settings.conversations_db_path == CONVERSATIONS_DB_PATH
    assert settings.conversations_db_path != STORE_DB_PATH


def test_history_survives_rebuilding_the_agent_on_the_same_file(make_agent: MakeAgent):
    conversation_id = new_conversation_id()
    first_agent = make_agent([AIMessage(content="Oi, tudo bem?")])
    reply(first_agent, conversation_id, "Olá")

    restarted_agent = make_agent([AIMessage(content="Claro!")])

    assert load_history(restarted_agent, conversation_id) == [
        (USER_ROLE, "Olá"),
        (ASSISTANT_ROLE, "Oi, tudo bem?"),
    ]
    reply(restarted_agent, conversation_id, "Pode ajudar?")
    assert [text for _, text in load_history(restarted_agent, conversation_id)] == [
        "Olá",
        "Oi, tudo bem?",
        "Pode ajudar?",
        "Claro!",
    ]


def test_conversations_are_isolated_by_id(make_agent: MakeAgent):
    agent = make_agent([AIMessage(content="Resposta A"), AIMessage(content="Resposta B")])
    conversation_a, conversation_b = new_conversation_id(), new_conversation_id()

    reply(agent, conversation_a, "Pergunta A")
    reply(agent, conversation_b, "Pergunta B")

    assert load_history(agent, conversation_a) == [
        (USER_ROLE, "Pergunta A"),
        (ASSISTANT_ROLE, "Resposta A"),
    ]
    assert load_history(agent, conversation_b) == [
        (USER_ROLE, "Pergunta B"),
        (ASSISTANT_ROLE, "Resposta B"),
    ]


def test_unknown_conversation_has_an_empty_history(make_agent: MakeAgent):
    agent = make_agent([])

    assert load_history(agent, new_conversation_id()) == []


def test_history_shows_only_customer_and_assistant_text(make_agent: MakeAgent):
    conversation_id = new_conversation_id()
    narrated_lookup = product_lookup_call()
    narrated_lookup.content = "Vou consultar o preço."
    agent = make_agent([narrated_lookup, AIMessage(content="A Takamine custa R$ 100.")])

    reply(agent, conversation_id, "Quanto custa a Takamine?")

    stored_types = [message.type for message in load_messages(agent, conversation_id)]
    assert stored_types == ["human", "ai", "tool", "ai"]
    assert load_history(agent, conversation_id) == [
        (USER_ROLE, "Quanto custa a Takamine?"),
        (ASSISTANT_ROLE, "A Takamine custa R$ 100."),
    ]


@pytest.mark.parametrize(
    "raw",
    [None, "", "abc", "not-a-uuid", "../../etc/passwd", "1234", "' OR 1=1 --"],
)
def test_invalid_conversation_ids_are_rejected(raw: str | None):
    assert parse_conversation_id(raw) is None


def test_valid_conversation_ids_are_normalized():
    conversation_id = new_conversation_id()

    assert parse_conversation_id(conversation_id) == conversation_id
    assert parse_conversation_id(conversation_id.upper()) == conversation_id
    assert parse_conversation_id(conversation_id.replace("-", "")) == conversation_id


def test_new_conversation_ids_are_unique():
    assert new_conversation_id() != new_conversation_id()


@pytest.mark.parametrize(
    "failing_script",
    [
        pytest.param([ModelUnavailable("429")], id="fails-before-any-answer"),
        pytest.param(
            [product_lookup_call(), ModelUnavailable("429")], id="fails-after-a-tool-call"
        ),
    ],
)
def test_failed_turn_leaves_the_conversation_as_it_was(
    make_agent: MakeAgent, failing_script: list[AIMessage | Exception]
):
    conversation_id = new_conversation_id()
    agent = make_agent([AIMessage(content="Oi!"), *failing_script, AIMessage(content="Agora foi.")])
    reply(agent, conversation_id, "Olá")
    messages_before = load_messages(agent, conversation_id)

    with pytest.raises(ModelUnavailable):
        reply(agent, conversation_id, "Quanto custa a Takamine?")

    assert load_messages(agent, conversation_id) == messages_before
    assert load_history(agent, conversation_id) == [(USER_ROLE, "Olá"), (ASSISTANT_ROLE, "Oi!")]


def test_conversation_is_usable_after_a_failed_turn(make_agent: MakeAgent):
    conversation_id = new_conversation_id()
    agent = make_agent(
        [product_lookup_call(), ModelUnavailable("429"), product_lookup_call(), AIMessage(content="R$ 100.")]
    )
    with pytest.raises(ModelUnavailable):
        reply(agent, conversation_id, "Quanto custa a Takamine?")

    answer = reply(agent, conversation_id, "Quanto custa a Takamine?")

    assert answer == "R$ 100."
    assert load_history(agent, conversation_id) == [
        (USER_ROLE, "Quanto custa a Takamine?"),
        (ASSISTANT_ROLE, "R$ 100."),
    ]


def test_empty_model_reply_is_rolled_back_and_fails_loudly(make_agent: MakeAgent):
    conversation_id = new_conversation_id()
    agent = make_agent([AIMessage(content="  ")])

    with pytest.raises(RuntimeError, match="empty reply"):
        reply(agent, conversation_id, "Olá")

    assert load_messages(agent, conversation_id) == []


def test_shared_connection_works_from_another_thread(make_agent: MakeAgent):
    conversation_id = new_conversation_id()
    agent = make_agent([AIMessage(content="Oi!")])
    failures: list[BaseException] = []

    def chat_from_another_thread() -> None:
        try:
            reply(agent, conversation_id, "Olá")
        except Exception as error:
            failures.append(error)

    worker = threading.Thread(target=chat_from_another_thread)
    worker.start()
    worker.join()

    assert failures == []
    assert load_history(agent, conversation_id) == [(USER_ROLE, "Olá"), (ASSISTANT_ROLE, "Oi!")]


def test_checkpointer_creates_the_runtime_directory(make_agent: MakeAgent, agent_settings: Settings):
    assert not agent_settings.conversations_db_path.parent.exists()

    agent = make_agent([AIMessage(content="Oi!")])
    reply(agent, new_conversation_id(), "Olá")

    assert isinstance(agent_settings.conversations_db_path, Path)
    assert agent_settings.conversations_db_path.exists()
