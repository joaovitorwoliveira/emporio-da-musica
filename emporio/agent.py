import warnings

from langchain_core.tools import BaseTool
from langchain_openai import ChatOpenAI
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import create_react_agent
from langgraph.warnings import LangGraphDeprecatedSinceV10

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


def build_agent(settings: Settings) -> CompiledStateGraph:
    tools: list[BaseTool] = build_tools(
        settings.store_db_path, settings.escalation_log_path, settings.reference_date
    )
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=LangGraphDeprecatedSinceV10)
        return create_react_agent(build_llm(settings), tools, prompt=build_system_prompt(settings))


def reply(agent: CompiledStateGraph, history: list[tuple[str, str]]) -> str:
    result = agent.invoke({"messages": history})
    answer = result["messages"][-1].text
    if not answer.strip():
        raise RuntimeError("The model returned an empty reply.")
    return answer
