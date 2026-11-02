"""Runs scripted customer conversations through the real agent and saves them as Markdown.

Usage:
    uv run python -m emporio.examples            # all scenarios
    uv run python -m emporio.examples 5          # one scenario, by number
    uv run python -m emporio.examples late-order-escalation
"""

import argparse
import shutil
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from pathlib import Path

from langchain_core.messages import AIMessage, AnyMessage
from langgraph.graph.state import CompiledStateGraph
from openai import RateLimitError

from emporio.agent import build_agent, open_checkpointer, reply
from emporio.conversations import (
    ASSISTANT_ROLE,
    USER_ROLE,
    load_history,
    load_messages,
    new_conversation_id,
)
from emporio.seed import ensure_store_seeded
from emporio.settings import PROJECT_ROOT, RUNTIME_DIR, Settings, load_settings

EXAMPLES_DIR = PROJECT_ROOT / "examples"
# Scratch state of the example runs, kept apart from the app's own files so that
# regenerating the examples never adds records to the app's escalation log or
# conversation history.
SCRATCH_DIR = RUNTIME_DIR / "examples"

# The model account allows 3 requests per minute and one turn can take several.
PAUSE_BETWEEN_TURNS_SECONDS = 25
RATE_LIMIT_WAIT_SECONDS = 61
MAX_RATE_LIMIT_RETRIES = 5

CUSTOMER_LABEL = "Cliente"
ASSISTANT_LABEL = "Lia"
ROLE_LABELS = {USER_ROLE: CUSTOMER_LABEL, ASSISTANT_ROLE: ASSISTANT_LABEL}
REFERENCE_DATE_DISPLAY_FORMAT = "%Y-%m-%d %H:%M"

Sleep = Callable[[float], None]


@dataclass(frozen=True)
class Scenario:
    number: int
    slug: str
    title: str
    demonstrates: str
    turns: tuple[str, ...]

    @property
    def file_name(self) -> str:
        return f"{self.number:02d}-{self.slug}.md"


SCENARIOS: tuple[Scenario, ...] = (
    Scenario(
        number=1,
        slug="guitars-up-to-1000",
        title="Filtered catalog search",
        demonstrates=(
            "An open question with a price ceiling is answered from the catalog "
            "search tool, listing only available guitars at their Final Price."
        ),
        turns=("Quais opções de violões disponíveis custando até R$1000?",),
    ),
    Scenario(
        number=2,
        slug="expired-promotion-and-installments",
        title="Expired promotion, Pix price and installments",
        demonstrates=(
            "A promotion the customer remembers has already ended and is not offered. "
            "The current price, the installment answer and the Pix price come from "
            "the payment options tool, never from the model's own arithmetic."
        ),
        turns=(
            "Oi! Quanto está o violão Takamine GD20? Eu vi uma promoção dele por aí.",
            "Dá pra parcelar em 10x?",
            "E no Pix, fica quanto?",
        ),
    ),
    Scenario(
        number=3,
        slug="return-request-order-7",
        title="Return request: Identity Check and after-sales deadlines",
        demonstrates=(
            "Lia asks for the order number and the purchase contact before saying "
            "anything about the order, then reports each right with its date: the "
            "Withdrawal Right has expired and the Legal Warranty is still open."
        ),
        turns=(
            "Me arrependi da minha compra, posso devolver?",
            "É o pedido 7. O e-mail da compra é leticia.rocha@jmail.com",
        ),
    ),
    Scenario(
        number=4,
        slug="scope-catalog-and-store-info",
        title="Out of Scope, Out of Catalog and store information",
        demonstrates=(
            "Three kinds of answer in one conversation: guitar strings are an "
            "accessory the store does not sell (Out of Scope, no invented partner "
            "stores), a saxophone belongs to the store's line but is not in the "
            "catalog (Out of Catalog, no promises), and the address comes from the "
            "store information."
        ),
        turns=(
            "Vocês vendem um jogo de cordas novas para violão?",
            "Entendi. E saxofone, vocês têm?",
            "Qual é o endereço da loja?",
        ),
    ),
    Scenario(
        number=5,
        slug="late-order-escalation",
        title="Late order: failed Identity Check, then Escalation",
        demonstrates=(
            "A wrong contact reveals nothing about the order. With the correct "
            "contact Lia reports the order is late by the right number of days and "
            "records an Escalation for the team without promising more than that."
        ),
        turns=(
            "Oi, queria saber onde está o meu pedido, o número 8.",
            "O e-mail que usei na compra é ana.ferreira@coldmail.com",
            "Ah, errei o e-mail. O correto é anacarol.ferreira@coldmail.com",
        ),
    ),
)


def find_scenarios(selectors: Sequence[str]) -> list[Scenario]:
    """Resolves numbers or slugs to scenarios; no selector means all of them."""
    if not selectors:
        return list(SCENARIOS)
    return [_find_scenario(selector) for selector in selectors]


def _find_scenario(selector: str) -> Scenario:
    for scenario in SCENARIOS:
        if selector == str(scenario.number) or selector == scenario.slug:
            return scenario
    valid = ", ".join(f"{s.number} ({s.slug})" for s in SCENARIOS)
    raise ValueError(f"Unknown scenario '{selector}'. Valid scenarios: {valid}.")


def extract_tool_names(messages: Sequence[AnyMessage]) -> list[str]:
    """Names of every tool the agent called, in call order."""
    return [
        call["name"]
        for message in messages
        if isinstance(message, AIMessage)
        for call in message.tool_calls
    ]


def render_markdown(
    scenario: Scenario,
    history: Sequence[tuple[str, str]],
    tool_names: Sequence[str],
    settings: Settings,
) -> str:
    tools = ", ".join(f"`{name}`" for name in tool_names) or "none"
    reference = settings.reference_date.strftime(REFERENCE_DATE_DISPLAY_FORMAT)
    header = [
        f"# Example {scenario.number}: {scenario.title}",
        "",
        f"**What it demonstrates:** {scenario.demonstrates}",
        "",
        f"**Tools called, in order:** {tools}",
        "",
        f"**Model:** `{settings.llm_model}`. **Reference date:** {reference} "
        f"({settings.store_timezone.key}). The conversation is in Brazilian Portuguese.",
        "",
        "---",
    ]
    turns = [_render_turn(role, text) for role, text in history]
    return "\n\n".join(["\n".join(header), *turns]) + "\n"


def _render_turn(role: str, text: str) -> str:
    quoted = "\n".join(f"> {line}".rstrip() for line in text.strip().splitlines())
    return f"**{ROLE_LABELS[role]}**\n\n{quoted}"


def send_turn(
    agent: CompiledStateGraph, conversation_id: str, message: str, sleep: Sleep = time.sleep
) -> str:
    """Sends one message, waiting and retrying when the model rate limit is hit."""
    for attempt in range(MAX_RATE_LIMIT_RETRIES):
        try:
            return reply(agent, conversation_id, message)
        except RateLimitError:
            print(
                f"Rate limited (attempt {attempt + 1}/{MAX_RATE_LIMIT_RETRIES}); "
                f"waiting {RATE_LIMIT_WAIT_SECONDS}s.",
                flush=True,
            )
            sleep(RATE_LIMIT_WAIT_SECONDS)
    return reply(agent, conversation_id, message)


def run_scenario(
    agent: CompiledStateGraph,
    scenario: Scenario,
    settings: Settings,
    sleep: Sleep = time.sleep,
) -> str:
    """Plays the scenario in a fresh conversation and returns it as Markdown."""
    conversation_id = new_conversation_id()
    for position, message in enumerate(scenario.turns):
        if position > 0:
            sleep(PAUSE_BETWEEN_TURNS_SECONDS)
        print(f"  turn {position + 1}/{len(scenario.turns)}: {message}", flush=True)
        send_turn(agent, conversation_id, message, sleep)
    history = load_history(agent, conversation_id)
    tool_names = extract_tool_names(load_messages(agent, conversation_id))
    return render_markdown(scenario, history, tool_names, settings)


def scratch_settings(settings: Settings, scratch_dir: Path = SCRATCH_DIR) -> Settings:
    return replace(
        settings,
        store_db_path=scratch_dir / "store.db",
        conversations_db_path=scratch_dir / "conversations.db",
        escalation_log_path=scratch_dir / "escalations.jsonl",
    )


def build_example_agent(settings: Settings) -> CompiledStateGraph:
    shutil.rmtree(settings.store_db_path.parent, ignore_errors=True)
    ensure_store_seeded(settings.store_db_path)
    return build_agent(settings, open_checkpointer(settings.conversations_db_path))


def write_example(scenario: Scenario, markdown: str, output_dir: Path = EXAMPLES_DIR) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / scenario.file_name
    path.write_text(markdown, encoding="utf-8")
    return path


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Regenerate the example conversations with the real model."
    )
    parser.add_argument(
        "scenario",
        nargs="*",
        help="Scenario number or name; omit to run all.",
    )
    selectors = parser.parse_args(argv).scenario
    scenarios = find_scenarios(selectors)
    settings = scratch_settings(load_settings())
    agent = build_example_agent(settings)
    for scenario in scenarios:
        print(f"Scenario {scenario.number}: {scenario.title}", flush=True)
        markdown = run_scenario(agent, scenario, settings)
        print(f"  wrote {write_example(scenario, markdown).relative_to(PROJECT_ROOT)}", flush=True)


if __name__ == "__main__":
    main()
