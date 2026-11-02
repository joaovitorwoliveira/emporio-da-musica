# Empório da Música virtual assistant

Lia is a Brazilian Portuguese text-chat assistant for Empório da Música, a musical instrument store. She answers questions about products, prices, promotions, payment options, store policies and orders, and hands off to the human team when she should not decide alone.

## Quick start

Both paths need an API key for an OpenAI-compatible chat model with tool calling (default: Kimi K2.6 from Moonshot AI).

With [uv](https://docs.astral.sh/uv/) (it installs Python 3.12 from `.python-version` if missing):

```bash
uv sync
cp .env.example .env   # then set LLM_API_KEY in .env
uv run python -m emporio.seed
uv run streamlit run emporio/app.py
```

Open http://localhost:8501 (Streamlit may ask for an e-mail on first run; press Enter). The seed command validates the CSVs in `data/`, rebuilds the store database in `runtime/` and prints a data quality report; it is safe to rerun. Tests: `uv run pytest` (scripted model, no API key needed).

With Docker (Compose is the only prerequisite):

```bash
cp .env.example .env   # then set LLM_API_KEY
docker compose up
```

The named volume `runtime` keeps the databases and the escalation log across `docker compose down`; `docker compose down -v` wipes them. `.env` is kept out of the image and passed at start through `env_file`.

## Configuration

Set these in `.env`. Only `LLM_API_KEY` is required; the app refuses to start without it or with the template placeholder.

- `LLM_BASE_URL`: OpenAI-compatible endpoint (default `https://api.moonshot.ai/v1`)
- `LLM_API_KEY`: key for that endpoint
- `LLM_MODEL`: model id (default `kimi-k2.6`)
- `REFERENCE_DATE`: the moment the assistant treats as "now", `YYYY-MM-DDTHH:MM` (default `2026-03-23T10:00`)
- `STORE_TIMEZONE`: IANA timezone (default `America/Campo_Grande`)

Any OpenAI-compatible provider with tool calling works by changing the three `LLM_*` variables; only `kimi-k2.6` was run through the full assistant. The Moonshot-specific flag that disables thinking is sent only when `LLM_MODEL` starts with `kimi-k2.6`. Moonshot said K2-series models stop being offered to new accounts from 2026-10-31; if yours lacks `kimi-k2.6`, pick another model it lists.

## Technical decisions

**Framework.** LangGraph's prebuilt ReAct agent (`create_react_agent`, `emporio/agent.py`) with plain Python tools (`emporio/tools.py`). The loop, message state and persistence come with the library, so the project code is tools, rules and prompt; a hand-written loop or a multi-node graph adds code this scope does not need. LangGraph marks `create_react_agent` as deprecated; it works, so it is kept. Lia's abilities are exactly her tools:

- `find_product`, `search_catalog`: exact lookup and filtered search (category, maximum final price, free text) over available products only. An unavailable product returns its reason and up to 3 similar alternatives.
- `list_promotions`: active promotions on available products.
- `get_payment_options`: Pix price (5% off, not combined with a promotion), maximum interest-free installments and installment values.
- `get_order`: status, items, total, tracking and return, exchange and warranty eligibility; needs the order number and the customer's e-mail or phone.
- `escalate_to_team`: appends a reason and summary to `runtime/escalations.jsonl` and returns the response time.

Prices, Pix values, installments, deadlines, lateness and opening hours are computed in code, never by the model.

**LLM.** Kimi K2.6 through Moonshot's OpenAI-compatible endpoint, with thinking off. On a two-turn tool conversation (one run each, so an indication and not a benchmark), K2.6 with thinking off took 2.4 s and 1.3 s and 68 output tokens; with thinking on, 14.9 s, 9.8 s and 306 tokens. `kimi-k2.7-code` and `kimi-k3` always think and were slower. K2.6 is the only one that lets thinking be switched off, which suits a chat assistant.

**Retrieval.** The policy manual (a PDF of about 11,000 characters) goes whole into the system prompt instead of RAG: it is small, and rules that interact (a promotion cancels the Pix discount, a specific section overrides a summary) must be read together. Catalog, promotions, payments and orders are reached only through fixed, parameterized SQLite queries inside the tools. Embeddings cannot express "under R$ 1000" or "in stock", and text-to-SQL cannot guarantee the Identity Check and leaves arithmetic to the model. If the policies grow into many documents, retrieval becomes the right tool.

**Prompt.** One Brazilian Portuguese system prompt built in code (`emporio/prompt.py`): persona and tone from the manual, rules, store info, current date and open status, the full policy text and a clarifications block. The rules name the tool and field they apply to, and several were added after a live run showed a failure. The policy text is extracted from the PDF with `pypdf`; contradictions in the manual are resolved in the clarifications block after it. It separates three kinds of "no": out of catalog (searched first, nothing promised), out-of-scope accessories (redirected) and unrelated topics.

**Interface.** A Streamlit chat page (`emporio/app.py`): Python only, one process, no API layer or front-end build. It is not a production channel: no login, no WhatsApp, no streaming. A rate-limit error (`RateLimitError`) shows a friendly wait message; any other model error reaches Streamlit's default error display, although the failed turn is rolled back.

**Conversation history.** Each visit gets a random UUID in the URL (`?conversa=<id>`), used as the thread id of LangGraph's SQLite checkpointer, so every turn is saved to `runtime/conversations.db` and the same URL shows the history after a reload or restart. It is separate from the store database, which the seed rebuilds. A failed model call removes that turn from the saved conversation. The id is the only key, so anyone with the link can read the conversation.

**Data handling.** Every CSV row goes through a Pydantic model before it is stored, so a malformed row stops the seed with the file and line. Cleaning only touches representation (types, digit-only phones, lowercased e-mails, prices as integer cents). Historical records are never rewritten: anomalies (order totals that differ from the item sum, Pix orders without the discount, installments below the minimum, a shared e-mail, empty categories) are reported by `uv run python -m emporio.data_quality` and handled in code or in the prompt. Orders are reachable only through `get_order`, which compares the contact against that order's customer and returns the same generic result on any failure. The identity check before an escalation is enforced by the prompt, not by the tool.

## Assumptions

- **Reference Date.** "Now" is frozen at 2026-03-23 10:00 America/Campo_Grande, the first business day after the latest order. Against the real clock every return and warranty window would have expired and the one shipped order would look months late. On this date no delivered order is within its 7-day Withdrawal Right, and order 8 is late.
- **Receipt Date and day counting.** The data has no receipt date, so the estimated delivery date stands in for it. The deadline is the start date plus the window in calendar days, and the deadline day itself is still open. Withdrawal Right and Preference Exchange: 7 days from receipt; Defect Exchange: 30 days from the order date; Legal Warranty: 90 days from receipt.
- **Online purchases.** The Withdrawal Right applies to online purchases and the records have no sales channel, so every order is treated as online.
- **Installment minimums.** The manual's summary says R$ 100,00, while section 3.1 has tiers. Section 3.1 wins, and "exceto abaixo de R$ 50,00" means an installment below R$ 50,00 is not allowed: 2x to 3x R$ 50,00, 4x to 6x R$ 80,00, 7x to 12x R$ 100,00, checked on the exact total.
- **Other inconsistencies.** The store e-mail is `contato@emporiodamusica.com.br`, the phone is (67) 3341-4444, and the catalog (65 products) overrides the "300+ instruments" claim. The manual has no cancellation policy, so Lia promises nothing and escalates.

## Example conversations

`examples/` holds five conversations generated by running scripted customer messages through the same agent, each with an English header and the conversation in Portuguese. To regenerate them (real model, a few minutes): `uv run python -m emporio.examples`.

## Limitations and future work

- No holiday calendar: on a weekday holiday Lia reports the store as open.
- Model rate limits on the default account, and `kimi-k2.6` is planned to retire at the end of December 2026.
- Only rate-limit errors are handled gracefully.
- Escalation is a local file with no deduplication, and a failed turn after an escalation can record the case twice. The Identity Check has no attempt limit.
- Alternatives for unavailable products match by category and price only. Search filters run in Python, fine at 65 products but not at scale.
- Real model behavior is checked by reading the examples, not by automated tests.
- SQLite files in a local volume support one instance only.

With more time: LLM-as-judge evaluations on scripted conversations; the real clock with a holiday calendar; Postgres and authenticated sessions; a FastAPI backend with a streaming front end; vector retrieval once the policies outgrow the prompt; helpdesk integration; stronger identity checks.

## AI-assisted workflow

The project was built with Claude Code, Anthropic's command-line coding assistant, working in the repository from the first commit. Before any code, the assistant interviewed me about the brief, the data and the policy manual, one decision at a time, until requirements and edge cases were pinned down, and the outcome was a written plan and a glossary of domain terms used the same way in code, prompt and this README. The plan was cut into vertical slices, starting with a tracer bullet from the chat page through the agent, a tool and the database, and a short spike chose the model from measurements first. Each slice was delegated to sub-agents given the slice and the project conventions; I reviewed the result and committed by hand. Every slice was checked with the tests, a diff review and a live run against the real model. When a live run showed wrong behavior, the fix went into the prompt rule or the tool payload and the scenario was run again, instead of patching an answer (for example, the model repeated an earlier refusal instead of calling the order tool again with new data, which became an explicit rule). I read the generated examples myself, and problems found there went back into the prompt before a rerun.
