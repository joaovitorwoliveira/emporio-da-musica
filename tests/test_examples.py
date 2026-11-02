from collections.abc import Callable
from pathlib import Path

import httpx
import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.graph.state import CompiledStateGraph
from openai import RateLimitError

from emporio import examples
from emporio.conversations import ASSISTANT_ROLE, USER_ROLE, load_history, new_conversation_id
from emporio.examples import (
    MAX_RATE_LIMIT_RETRIES,
    RATE_LIMIT_WAIT_SECONDS,
    SCENARIOS,
    extract_tool_names,
    find_scenarios,
    render_markdown,
    run_scenario,
    scratch_settings,
    send_turn,
    write_example,
)
from emporio.settings import RUNTIME_DIR, Settings

MakeAgent = Callable[[list[AIMessage | Exception]], CompiledStateGraph]


def tool_call_message(name: str, call_id: str) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": {}, "id": call_id}])


def rate_limit_error() -> RateLimitError:
    return RateLimitError(
        "slow down",
        response=httpx.Response(429, request=httpx.Request("POST", "http://localhost")),
        body=None,
    )


class SleepRecorder:
    def __init__(self) -> None:
        self.calls: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


def test_scenarios_are_numbered_one_to_five_with_unique_names():
    assert [s.number for s in SCENARIOS] == [1, 2, 3, 4, 5]
    assert len({s.slug for s in SCENARIOS}) == len(SCENARIOS)
    assert len({s.file_name for s in SCENARIOS}) == len(SCENARIOS)


def test_scenarios_are_well_formed():
    for scenario in SCENARIOS:
        assert scenario.title.strip()
        assert scenario.demonstrates.strip()
        assert scenario.turns
        assert all(turn.strip() for turn in scenario.turns)
        assert scenario.file_name == f"{scenario.number:02d}-{scenario.slug}.md"


def test_find_scenarios_without_selectors_returns_all():
    assert find_scenarios([]) == list(SCENARIOS)


def test_find_scenarios_accepts_numbers_and_slugs():
    assert find_scenarios(["3", SCENARIOS[4].slug]) == [SCENARIOS[2], SCENARIOS[4]]


def test_find_scenarios_rejects_unknown_selector_with_the_valid_ones():
    with pytest.raises(ValueError, match="Unknown scenario 'nine'.*late-order-escalation"):
        find_scenarios(["nine"])


def test_extract_tool_names_keeps_call_order_and_repeats():
    messages = [
        HumanMessage(content="oi"),
        tool_call_message("get_order", "c1"),
        ToolMessage(content="{}", tool_call_id="c1"),
        tool_call_message("get_order", "c2"),
        ToolMessage(content="{}", tool_call_id="c2"),
        tool_call_message("escalate_to_team", "c3"),
        ToolMessage(content="{}", tool_call_id="c3"),
        AIMessage(content="pronto"),
    ]

    assert extract_tool_names(messages) == ["get_order", "get_order", "escalate_to_team"]


def test_extract_tool_names_is_empty_without_tool_calls():
    assert extract_tool_names([HumanMessage(content="oi"), AIMessage(content="olá")]) == []


def test_render_markdown_has_header_then_quoted_conversation(agent_settings: Settings):
    history = [
        (USER_ROLE, "Quanto custa?"),
        (ASSISTANT_ROLE, "Custa:\n\n- item um\n- item dois"),
    ]

    markdown = render_markdown(SCENARIOS[1], history, ["find_product"], agent_settings)

    assert markdown.startswith("# Example 2: ")
    assert f"**What it demonstrates:** {SCENARIOS[1].demonstrates}" in markdown
    assert "**Tools called, in order:** `find_product`" in markdown
    assert "2026-03-23 10:00 (America/Campo_Grande)" in markdown
    _, conversation = markdown.split("---\n\n")
    assert conversation == (
        "**Cliente**\n\n> Quanto custa?\n\n"
        "**Lia**\n\n> Custa:\n>\n> - item um\n> - item dois\n"
    )


def test_render_markdown_says_when_no_tool_was_called(agent_settings: Settings):
    markdown = render_markdown(SCENARIOS[0], [(USER_ROLE, "oi")], [], agent_settings)

    assert "**Tools called, in order:** none" in markdown


def test_scratch_settings_moves_only_the_runtime_files(
    agent_settings: Settings, tmp_path: Path
):
    isolated = scratch_settings(agent_settings, tmp_path / "scratch")

    assert isolated.store_db_path == tmp_path / "scratch" / "store.db"
    assert isolated.conversations_db_path == tmp_path / "scratch" / "conversations.db"
    assert isolated.escalation_log_path == tmp_path / "scratch" / "escalations.jsonl"
    assert isolated.llm_model == agent_settings.llm_model
    assert isolated.reference_date == agent_settings.reference_date


def test_default_scratch_directory_is_inside_the_git_ignored_runtime_folder():
    assert examples.SCRATCH_DIR.parent == RUNTIME_DIR


def test_write_example_creates_the_folder_and_names_the_file_after_the_scenario(tmp_path: Path):
    output_dir = tmp_path / "out" / "examples"

    path = write_example(SCENARIOS[0], "conteúdo\n", output_dir)

    assert path == output_dir / SCENARIOS[0].file_name
    assert path.read_text(encoding="utf-8") == "conteúdo\n"


def test_send_turn_waits_and_retries_after_a_rate_limit(make_agent: MakeAgent):
    sleep = SleepRecorder()
    agent = make_agent([rate_limit_error(), AIMessage(content="Agora foi.")])
    conversation_id = new_conversation_id()

    answer = send_turn(agent, conversation_id, "Olá", sleep)

    assert answer == "Agora foi."
    assert sleep.calls == [RATE_LIMIT_WAIT_SECONDS]
    assert load_history(agent, conversation_id) == [
        (USER_ROLE, "Olá"),
        (ASSISTANT_ROLE, "Agora foi."),
    ]


def test_send_turn_gives_up_with_the_rate_limit_error_after_the_retries(make_agent: MakeAgent):
    sleep = SleepRecorder()
    agent = make_agent([rate_limit_error() for _ in range(MAX_RATE_LIMIT_RETRIES + 1)])

    with pytest.raises(RateLimitError):
        send_turn(agent, new_conversation_id(), "Olá", sleep)

    assert len(sleep.calls) == MAX_RATE_LIMIT_RETRIES


def test_run_scenario_plays_every_turn_in_one_conversation_and_lists_the_tools(
    make_agent: MakeAgent, agent_settings: Settings
):
    scenario = SCENARIOS[2]
    agent = make_agent(
        [
            AIMessage(content="Qual o número do pedido e o e-mail?"),
            tool_call_message("get_order", "c1"),
            AIMessage(content="Pedido encontrado."),
        ]
    )
    sleep = SleepRecorder()

    markdown = run_scenario(agent, scenario, agent_settings, sleep)

    assert "**Tools called, in order:** `get_order`" in markdown
    for turn in scenario.turns:
        assert f"> {turn}" in markdown
    assert "> Qual o número do pedido e o e-mail?" in markdown
    assert "> Pedido encontrado." in markdown
    assert len(sleep.calls) == len(scenario.turns) - 1
