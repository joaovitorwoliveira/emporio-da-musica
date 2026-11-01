# Empório da Música virtual assistant

Lia is a Brazilian Portuguese text-chat assistant for Empório da Música, a musical instrument store. She answers questions about products, prices, promotions, payment options, store policies and orders, and hands off to the human team when she should not decide on her own.

## Quick start

```bash
uv sync
cp .env.example .env   # then set LLM_API_KEY
uv run python -m emporio.seed
uv run streamlit run emporio/app.py
```

Run the tests with `uv run pytest`.

The seed command validates the CSVs in `data/` and rebuilds the store database in `runtime/` from scratch, so it is safe to run again at any time. The app also creates the database on start when it does not exist.

## Configuration

Copy `.env.example` to `.env` and fill in the settings. Only `LLM_API_KEY` is required; the app refuses to start without it.

| Variable | Default | Meaning |
|---|---|---|
| `LLM_BASE_URL` | `https://api.moonshot.ai/v1` | OpenAI-compatible chat endpoint |
| `LLM_API_KEY` | none (required) | API key for that endpoint |
| `LLM_MODEL` | `kimi-k2.6` | Model id; thinking is switched off only for `kimi-k2.6` |
| `REFERENCE_DATE` | `2026-03-23T10:00` | The moment the assistant treats as "now", as `YYYY-MM-DDTHH:MM` in `STORE_TIMEZONE` |
| `STORE_TIMEZONE` | `America/Campo_Grande` | IANA timezone of the store |

Runtime files (store database, conversation database, escalation log) are written to the git-ignored `runtime/` directory; source data lives in `data/`.

## Technical decisions

### Framework

To be documented.

### LLM

Default model: Kimi K2.6 (`kimi-k2.6`, Moonshot AI), with its thinking mode switched off. It was picked after listing the models the account can use and running a two-turn tool-calling conversation through LangChain's OpenAI-compatible chat model and the LangGraph agent: the model calls the tool, uses the result, and keeps the context on the next turn. With thinking off a turn takes 1 to 3 seconds and about a quarter of the output tokens of the thinking variants, which fits a chat assistant. Thinking K2.6 and `kimi-k2.7-code` also worked but were 2 to 6 times slower; `kimi-k3` worked but is thinking-only and was the slowest of the four.

Any OpenAI-compatible endpoint works by changing the three `LLM_*` variables (`LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL`) in `.env`.

### Retrieval architecture

To be documented.

### Prompt strategy

To be documented.

### Interface

To be documented.

### Conversation history

To be documented.

### Data handling

To be documented.

### Privacy and identity check

Order data is only reachable through the order tool, which needs two inputs: the order number and the e-mail or phone of that order's customer. The contact is compared against the customer who placed that order and nobody else, so a valid e-mail or phone of another customer never unlocks it, and the shared e-mail in the records (two customers use it) stays unambiguous. E-mails are compared case-insensitively. Phones are compared by digits only, so any formatting works, and a leading Brazilian country code (55) is accepted because every phone on file is a national number with area code; a partial number never matches.

An unknown order, a wrong contact and a missing input all return the same generic result, so the assistant cannot confirm that an order exists. There is no way to list a customer's orders: without an order number the assistant asks for it. A successful check returns the order's status, date, items, total, payment method, tracking code and delivery estimate, plus the customer's first name; the full name, e-mail, phone and city never leave the database layer. The order total is the amount recorded by the store, even where it differs from the sum of the item prices.

The check is enforced in code, not in the prompt: the model has no tool that returns an order without it. The prompt only tells the assistant how to behave around the check (ask for the missing data, never hint at which part failed). A shipped order past its estimated delivery date on the reference date is flagged as late, with the number of days.

This is a prototype-level check: a single shared secret per order with no rate limiting or lockout. A production version would add attempt limits and a stronger factor, such as a code sent to the contact on file.

## Assumptions

### Reference date

To be documented.

## Docker

To be documented.

## Example conversations

To be documented.

## Limitations and future work

To be documented.

## AI-assisted workflow

To be documented.
