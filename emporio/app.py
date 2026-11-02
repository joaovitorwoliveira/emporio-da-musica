import streamlit as st
from langgraph.graph.state import CompiledStateGraph
from openai import RateLimitError

from emporio.agent import build_agent, open_checkpointer, reply
from emporio.conversations import (
    ASSISTANT_ROLE,
    USER_ROLE,
    load_history,
    new_conversation_id,
    parse_conversation_id,
)
from emporio.seed import ensure_store_seeded
from emporio.settings import Settings, SettingsError, load_settings

PAGE_TITLE = "Lia | Empório da Música"
INPUT_PLACEHOLDER = "Escreva sua mensagem"
CONVERSATION_PARAM = "conversa"
NEW_CONVERSATION_LABEL = "Nova conversa"
GREETING = "Oi! Eu sou a Lia, da Empório da Música. Como posso ajudar?"
RATE_LIMIT_MESSAGE = (
    "Recebi mensagens demais em pouco tempo e preciso de uma pausa. "
    "Aguarde cerca de um minuto e envie sua mensagem de novo."
)


@st.cache_resource
def get_agent(_settings: Settings) -> CompiledStateGraph:
    ensure_store_seeded(_settings.store_db_path)
    return build_agent(_settings, open_checkpointer(_settings.conversations_db_path))


def load_settings_or_stop() -> Settings:
    try:
        return load_settings()
    except SettingsError as error:
        st.error(str(error))
        st.stop()


def start_new_conversation() -> str:
    conversation_id = new_conversation_id()
    st.query_params[CONVERSATION_PARAM] = conversation_id
    return conversation_id


def current_conversation_id() -> str:
    conversation_id = parse_conversation_id(st.query_params.get(CONVERSATION_PARAM))
    return conversation_id or start_new_conversation()


def render_history(history: list[tuple[str, str]]) -> None:
    for role, content in history:
        with st.chat_message(role):
            st.markdown(content)


def answer_customer(agent: CompiledStateGraph, conversation_id: str, message: str) -> None:
    with st.chat_message(ASSISTANT_ROLE):
        try:
            with st.spinner("Lia está digitando..."):
                answer = reply(agent, conversation_id, message)
        except RateLimitError:
            st.warning(RATE_LIMIT_MESSAGE)
            return
        st.markdown(answer)


def main() -> None:
    st.set_page_config(page_title=PAGE_TITLE)
    st.title(PAGE_TITLE)
    st.sidebar.button(NEW_CONVERSATION_LABEL, on_click=start_new_conversation)
    agent = get_agent(load_settings_or_stop())
    conversation_id = current_conversation_id()

    with st.chat_message(ASSISTANT_ROLE):
        st.markdown(GREETING)
    render_history(load_history(agent, conversation_id))

    message = st.chat_input(INPUT_PLACEHOLDER)
    if not message:
        return
    with st.chat_message(USER_ROLE):
        st.markdown(message)
    answer_customer(agent, conversation_id, message)


if __name__ == "__main__":
    main()
