from collections.abc import Callable

import httpx
import pytest
from langchain_core.messages import AIMessage
from langgraph.graph.state import CompiledStateGraph
from openai import RateLimitError
from streamlit.testing.v1 import AppTest

import emporio.app as app_module
from emporio.agent import reply
from emporio.app import CONVERSATION_PARAM, GREETING, NEW_CONVERSATION_LABEL, RATE_LIMIT_MESSAGE
from emporio.conversations import new_conversation_id, parse_conversation_id
from emporio.settings import Settings

MakeAgent = Callable[[list[AIMessage | Exception]], CompiledStateGraph]
APP_TIMEOUT_SECONDS = 10


def run_app() -> None:
    import emporio.app

    emporio.app.main()


@pytest.fixture
def start_app(monkeypatch: pytest.MonkeyPatch, agent_settings: Settings) -> Callable[[CompiledStateGraph], AppTest]:
    def start(agent: CompiledStateGraph) -> AppTest:
        monkeypatch.setattr(app_module, "load_settings_or_stop", lambda: agent_settings)
        monkeypatch.setattr(app_module, "get_agent", lambda _settings: agent)
        return AppTest.from_function(run_app, default_timeout=APP_TIMEOUT_SECONDS)

    return start


def chat_texts(app: AppTest) -> list[str]:
    return [message.markdown[0].value for message in app.chat_message]


def test_new_visit_gets_a_conversation_id_in_the_url_and_only_the_greeting(
    start_app: Callable[[CompiledStateGraph], AppTest], make_agent: MakeAgent
):
    app = start_app(make_agent([])).run()

    assert not app.exception
    assert parse_conversation_id(app.query_params[CONVERSATION_PARAM]) is not None
    assert chat_texts(app) == [GREETING]


def test_invalid_id_in_the_url_starts_a_fresh_conversation(
    start_app: Callable[[CompiledStateGraph], AppTest], make_agent: MakeAgent
):
    app = start_app(make_agent([]))
    app.query_params[CONVERSATION_PARAM] = "not-a-uuid"

    app.run()

    assert not app.exception
    assert parse_conversation_id(app.query_params[CONVERSATION_PARAM]) is not None
    assert chat_texts(app) == [GREETING]


def test_reloading_with_the_same_url_restores_the_history(
    start_app: Callable[[CompiledStateGraph], AppTest], make_agent: MakeAgent
):
    conversation_id = new_conversation_id()
    first_visit = start_app(make_agent([AIMessage(content="Oi, tudo bem?")]))
    first_visit.query_params[CONVERSATION_PARAM] = conversation_id
    first_visit.run()
    first_visit.chat_input[0].set_value("Olá").run()
    assert chat_texts(first_visit) == [GREETING, "Olá", "Oi, tudo bem?"]

    reload = start_app(make_agent([]))
    reload.query_params[CONVERSATION_PARAM] = conversation_id
    reload.run()

    assert not reload.exception
    assert chat_texts(reload) == [GREETING, "Olá", "Oi, tudo bem?"]


def test_new_conversation_button_starts_empty_and_the_old_url_still_works(
    start_app: Callable[[CompiledStateGraph], AppTest], make_agent: MakeAgent
):
    old_id = new_conversation_id()
    agent = make_agent([AIMessage(content="Oi, tudo bem?")])
    app = start_app(agent)
    app.query_params[CONVERSATION_PARAM] = old_id
    app.run()
    app.chat_input[0].set_value("Olá").run()

    app.sidebar.button[0].click().run()

    assert app.sidebar.button[0].label == NEW_CONVERSATION_LABEL
    assert app.query_params[CONVERSATION_PARAM] != old_id
    assert parse_conversation_id(app.query_params[CONVERSATION_PARAM]) is not None
    assert chat_texts(app) == [GREETING]

    old_visit = start_app(agent)
    old_visit.query_params[CONVERSATION_PARAM] = old_id
    old_visit.run()
    assert chat_texts(old_visit) == [GREETING, "Olá", "Oi, tudo bem?"]


def test_rate_limited_turn_shows_the_warning_and_keeps_the_conversation_usable(
    start_app: Callable[[CompiledStateGraph], AppTest], make_agent: MakeAgent
):
    rate_limit = RateLimitError(
        "slow down",
        response=httpx.Response(429, request=httpx.Request("POST", "http://localhost")),
        body=None,
    )
    conversation_id = new_conversation_id()
    agent = make_agent([rate_limit, AIMessage(content="Agora foi.")])
    app = start_app(agent)
    app.query_params[CONVERSATION_PARAM] = conversation_id
    app.run()

    app.chat_input[0].set_value("Olá").run()

    assert [warning.value for warning in app.warning] == [RATE_LIMIT_MESSAGE]
    app.run()
    assert chat_texts(app) == [GREETING]

    assert reply(agent, conversation_id, "Olá") == "Agora foi."
