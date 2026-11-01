import streamlit as st
from langgraph.graph.state import CompiledStateGraph
from openai import RateLimitError

from emporio.agent import build_agent, reply
from emporio.seed import ensure_store_seeded
from emporio.settings import Settings, SettingsError, load_settings

PAGE_TITLE = "Lia | Empório da Música"
INPUT_PLACEHOLDER = "Escreva sua mensagem"
HISTORY_KEY = "history"
USER_ROLE = "user"
ASSISTANT_ROLE = "assistant"
GREETING = "Oi! Eu sou a Lia, da Empório da Música. Como posso ajudar?"
RATE_LIMIT_MESSAGE = (
    "Recebi mensagens demais em pouco tempo e preciso de uma pausa. "
    "Aguarde cerca de um minuto e envie sua mensagem de novo."
)


@st.cache_resource
def get_agent(_settings: Settings) -> CompiledStateGraph:
    ensure_store_seeded(_settings.store_db_path)
    return build_agent(_settings)


def load_settings_or_stop() -> Settings:
    try:
        return load_settings()
    except SettingsError as error:
        st.error(str(error))
        st.stop()


def render_history(history: list[tuple[str, str]]) -> None:
    for role, content in history:
        with st.chat_message(role):
            st.markdown(content)


def answer_customer(agent: CompiledStateGraph, history: list[tuple[str, str]]) -> None:
    with st.chat_message(ASSISTANT_ROLE):
        try:
            with st.spinner("Lia está digitando..."):
                answer = reply(agent, history)
        except RateLimitError:
            history.pop()
            st.warning(RATE_LIMIT_MESSAGE)
            return
        st.markdown(answer)
    history.append((ASSISTANT_ROLE, answer))


def main() -> None:
    st.set_page_config(page_title=PAGE_TITLE)
    st.title(PAGE_TITLE)
    agent = get_agent(load_settings_or_stop())
    history: list[tuple[str, str]] = st.session_state.setdefault(HISTORY_KEY, [])

    with st.chat_message(ASSISTANT_ROLE):
        st.markdown(GREETING)
    render_history(history)

    message = st.chat_input(INPUT_PLACEHOLDER)
    if not message:
        return
    history.append((USER_ROLE, message))
    with st.chat_message(USER_ROLE):
        st.markdown(message)
    answer_customer(agent, history)


if __name__ == "__main__":
    main()
