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

Lia is a single system prompt built in code (`emporio/prompt.py`) from clearly separated sections: persona and tone, rules, store info, current date and status, the full policy text, and a clarifications block. The persona follows the manual's tone guideline (informal but professional, "a friend who knows music", short chat-style answers, no emojis) and its standard service flow: greeting, understanding, consulting the system, answering, closing. The price rules and the Identity Check rules from the order flow live in the rules section.

**Policies go whole into the prompt, not through RAG.** The manual is about 11,000 characters (roughly 3k tokens), small enough to send with every request. Keeping it whole means the model always sees every rule, including the ones that interact (promotions do not stack with the PIX discount, the installment table disagrees with the installment tiers), whereas chunked retrieval could return one clause without the clause that qualifies it. RAG would add an embedding model, a vector store and chunking decisions for a problem this corpus does not have. The decision should be revisited if the corpus grows to many documents or to a size where per-request token cost matters.

**The text is extracted from the PDF, not retyped.** `emporio/policies.py` reads `data/politicas_da_loja.pdf` with `pypdf` in layout mode and normalizes whitespace so it reads cleanly in a prompt: trailing spaces and runs of blank lines are collapsed, table column padding becomes ` | `, and the repeated page header and "Página N" footers are dropped. The wording itself is never edited, and the result is cached because the manual is static. A missing PDF or empty extraction fails loudly.

**Contradictions are resolved in a clarifications block placed after the policy text**, so the original stays traceable and the correction is the last thing the model reads:

- Installments: the tiers in section 3.1 win over the summary table in section 3 (up to 3x: installment of at least R$ 50,00; 4x to 6x: at least R$ 80,00; 7x to 12x: at least R$ 100,00).
- The store e-mail is `contato@emporiodamusica.com.br`; the accented variant in the manual is a typo.
- The WhatsApp and phone number is (67) 3341-4444; the other number in section 7 is not used.
- The catalog in the system is the source of truth for what is for sale, not the "300+ instruments" claim.
- Partner stores are never named when redirecting accessory requests: the manual says to suggest them "when possible", and there are none on record.

**Date and open status are computed in code, not by the model.** The prompt states the reference date with its weekday and time in the store's timezone, plus whether the store is open and when it closes or, when closed, when the team is back. Opening hours are constants in `emporio/store_hours.py` (Monday to Friday 09:00 to 18:00, Saturday 09:00 to 13:00, Sunday closed; closing time itself counts as closed), so the model never has to work out weekdays. The module is reusable wherever the assistant needs to say when the team returns.

**Three kinds of "no".** Out of Catalog: an instrument within the store's line that the product search does not find (a saxophone, a violin). Lia still searches first, then says the store has none available right now and offers the store contact; she never says the store does not sell that kind of instrument. Out of Scope accessories (strings, picks, cables, cases, pedals, amplifiers): she explains that the store works only with instruments and redirects the customer, without inventing partner names. Unrelated topics (weather, programming help): declined kindly and steered back to what she can help with. Questions about the store itself (address, hours, payment methods, exchanges, shipping, warranty) are answered from the policy text.

**After-sales eligibility is computed in code, not by the model.** The order tool returns, for delivered orders, each right (withdrawal, preference exchange, defect exchange, legal warranty) with whether it is still open, its deadline and the days remaining or elapsed; for orders not yet delivered it says the windows start on receipt, and for cancelled orders that there is nothing to exercise. The prompt tells Lia to explain which rights are open and which expired using only those values, to state the policy conditions (packaging, refund method and timing, exclusions), to mention the manufacturer warranty after the 30-day defect window, and never to promise a return, exchange or warranty claim.

### Catalog search

Besides the exact lookup (`find_product`, by id or partial name), the assistant has `search_catalog` for open questions such as "quais violões disponíveis até R$ 1000?". It takes any of three filters, at least one required (`emporio/catalog.py`):

- **Category**, in the customer's wording. The text is normalized (lowercase, no accents) and matched against the store's category names plus a small alias table (`violão`, `violões`, `ukulele`, `guitarras`, `sax`, `flauta`, `trompete`, `violino`, ...). A wording that matches no category does not return everything: the tool answers `category_recognized: false` with the list of valid categories so the assistant can ask. A known category with nothing available returns an empty list, which the prompt treats as Out of Catalog.
- **Maximum price**, a positive number in reais, applied to the Final Price, so a product whose list price is above the limit but whose Active Promotion brings it under is included. The Final Price comes from the same function the product lookup uses.
- **Free text**, words that must all appear in the product name or description (accents and case ignored).

Only Available Products are returned: active status and stock above zero. Discontinued, coming-soon and out-of-stock products never show up, and stock quantities are not exposed. Each result carries the original price, the Active Promotion (description and percentage, when any) and the Final Price. Results are ordered by Final Price and then product id, and capped at 15; the payload reports `total_matches`, `returned` and `has_more` so the assistant can say that more products matched and offer to narrow the search.

The search itself is a fixed parameterized query for availability and category. The price and text filters run in Python on those rows because the Final Price depends on the best Active Promotion per product and descriptions have no normalized column; with a catalog of this size that is simpler than duplicating the discount rule in SQL.

### Unavailable products, alternatives and promotions

The product lookup (`find_product`) reports an explicit availability reason: `available`, `out_of_stock`, `discontinued` or `coming_soon`, with a Portuguese label. One function (`classify_availability` in `emporio/models.py`) defines it and the catalog search uses the same function, so "Available" has a single definition. The product status wins over stock: `coming_soon` is "em breve" and `discontinued` stays discontinued even when the database shows units in stock, and an `active` product with zero stock is out of stock. The data has two such anomalies (the Kala KA-ABP-CTG ukulele is coming soon with 2 units, the Ibanez Bass 2X is discontinued with 13), and the decision is to trust the status and never offer them as available. A coming-soon product is "em breve" with no date, and stock quantities are never exposed.

For an unavailable product the lookup also returns up to 3 alternatives: Available Products of the same category whose Final Price is within 30% of the unavailable product's list price, ordered by closeness of price and then product id (`emporio/catalog.py`, `ALTERNATIVE_PRICE_TOLERANCE_PERCENT` and `MAX_ALTERNATIVES`). They carry the same price fields as search results. When nothing is in that range (the Ibanez Bass 2X costs R$ 441,00 and the cheapest available bass is above R$ 7.000), the lookup falls back to the closest-priced Available Products of the category and sets `alternatives_in_price_range` to false, which the prompt tells the assistant to say plainly instead of presenting them as equivalents. The list is empty only when the category has nothing available.

A product with no Active Promotion but with an ended one (for example the Takamine GD20) carries `ended_promotion` (description and percentage; the highest percentage, then the lowest promotion id). The assistant uses it only when the customer asks about a promotion or discount: it says the promotion is no longer active and gives the current price, and never offers or applies it. The Final Price never includes it.

`list_promotions` lists the Active Promotions on Available Products, with original price, discount percentage, promotion description and Final Price, ordered by discount (highest first) and then product id. It takes an optional category in the same wording as `search_catalog`, with the same `category_recognized: false` answer for unknown wording. A promotion on a product that is not available is never listed.

### Payment options

`get_payment_options` (`emporio/payments.py` for the rules, `emporio/tools.py` for the payload) is the only source of Pix prices and installment values, so the model never does the arithmetic. It takes either a product (`product_id` or `name`, resolved exactly like `find_product`, with up to 5 matches) or an `amount` in reais for a total the customer states, plus an optional `installments` for a specific number the customer asks about.

- **Pix.** The Pix Price is the Final Price minus 5%, rounded half up to the cent, only when the product has no Active Promotion. With one, the Pix Price equals the Final Price and the payload says why (promotions do not stack, policy 6.2). An ended promotion has no effect.
- **Installments.** The result carries the maximum interest-free installments and the value of each. A requested number gets `allowed`, the installment value when allowed, or the reason when refused (more than 12, or an installment below the minimum of its tier) together with the minimum. Fewer than 1 installment is rejected as a tool error.
- **Installment value.** Total divided by the number of installments, rounded half up to the cent. The policy does not say how a leftover cent is distributed, so the value shown can differ from the total by a few cents when multiplied back (7x of R$ 2.199,00 shows R$ 314,14).
- **Unavailable products.** An unavailable product returns its availability and `payment_options_available: false`, with no payment values; the assistant explains the availability instead of quoting conditions for something that cannot be bought.
- **A bare amount has no Pix Price.** Whether the 5% applies depends on the promotion of each product, which an amount does not carry, so the tool returns `pix_price: null` with a note and the assistant asks for the products and looks them up one by one. This is one tool with an `amount` parameter instead of a second tool because the installment rule is the same in both cases.

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

### Escalation

When Lia cannot or must not resolve something alone, she calls `escalate_to_team`, which records an Escalation for the human team. The reason is a closed set, enforced in code (`emporio/escalations.py`): `complaint`, `cancellation_request`, `policy_doubt`, `late_order` and `other`. An unknown reason or a blank summary is rejected with a message that lists the valid reasons, so the model can correct itself.

- **When she escalates.** Complaints (she listens with empathy first, as the manual's section 7.3 asks, then records), requests to cancel a pending or confirmed order (the manual has no cancellation policy, so nothing is promised and she never says the order will be cancelled), questions the manual does not answer (section 10: the team decides), shipped orders flagged as late, and anything else she should not settle alone.
- **Identity Check still applies.** Anything tied to an order (a late order, a cancellation) is recorded with the order number only after the order tool verified the customer; a complaint without an order needs no check. The summary is short and factual and never carries the customer's e-mail or phone.
- **The log.** Each Escalation is one JSON object per line in `runtime/escalations.jsonl` (git-ignored, created on first use) with `reason`, `summary`, `order_id` (null when there is none) and `recorded_at`. The timestamp is the Reference Date, not the real clock, because the Reference Date is the assistant's "now". Example:

```json
{"reason": "late_order", "summary": "Pedido enviado está atrasado e o cliente quer saber o que fazer.", "order_id": 8, "recorded_at": "2026-03-23T10:00:00-04:00"}
```

- **What the customer is told.** The tool returns, computed in code, the response time (24 business hours), whether the store is open and, when it is closed, when the team is back, using the same opening-hours module as the prompt. Lia relays exactly that.
- **No claims beyond recording.** The prompt forbids saying anything was cancelled, solved, refunded or resent, and inventing protocol numbers. Lia only says the case was forwarded when the tool returned `recorded: true`; the tool itself returns no order data.
- **Why a local file.** This is a prototype with no helpdesk to integrate, and a JSON-lines file is append-only, human-readable and trivial to inspect. In production the same call would create a ticket in a helpdesk or CRM queue, with the assignee, priority and customer notification that a file cannot provide.

## Assumptions

### Reference date

The assistant treats a configurable Reference Date as "now" for deadlines, opening hours and lateness, instead of the real clock. The store's orders end in March 2026; against the real date every return, exchange and warranty window would already be closed and a shipped order would look months late, so the policy logic could not be exercised meaningfully. The default is 2026-03-23 10:00 (the business day after the most recent order) in `America/Campo_Grande`, set through `REFERENCE_DATE` and `STORE_TIMEZONE`. In production, pointing it at the real clock is a configuration change.

- **Receipt Date** is approximated by each order's estimated delivery date, because the records do not store when the customer actually received the order. A delivered order without an estimated delivery date is treated as a data error and fails loudly.
- **Day counting** is defined once in `emporio/eligibility.py`: the deadline is the start date plus the window length in calendar days, and the deadline day itself is still open. On the deadline day the right has 0 days remaining; the next day it has expired by 1 day. Windows: Withdrawal Right and Preference Exchange 7 days from the Receipt Date, Defect Exchange 30 days from the order date, Legal Warranty 90 days from the Receipt Date.
- **Consequence:** no single date makes every record consistent. On the default date no delivered order is still inside the 7-day Withdrawal Right (the most recent delivery estimate is 2026-02-17, whose window closed on 2026-02-24), and order 8 is past its estimated delivery. These are documented rather than hidden.

### Installment minimums

Section 3.1 says installments up to 3x have "sem valor mínimo de parcela (exceto abaixo de R$ 50,00)", while the summary table in section 3 says a credit card minimum of R$ 100,00. The interpretation is that section 3.1 wins over the summary table, as in the prompt's clarifications block, and that "exceto abaixo de R$ 50,00" means an installment below R$ 50,00 is not allowed. The tiers are therefore:

| Installments | Minimum per installment |
|---|---|
| 1x (single card payment) | none, always allowed |
| 2x to 3x | R$ 50,00 |
| 4x to 6x | R$ 80,00 |
| 7x to 12x | R$ 100,00 |

The check is made on the exact total (`total >= installments x minimum`), so an installment of exactly R$ 50,00, R$ 80,00 or R$ 100,00 is allowed and one cent less in the total is not, even if the rounded installment value would display as the minimum. The maximum interest-free installments of a product is the largest number that passes. The rule about combining payment methods (for example Pix plus card above R$ 2.000,00) is left to the policy text and is not computed by the tool.

## Docker

To be documented.

## Example conversations

To be documented.

## Limitations and future work

- There is no holiday calendar. The manual says the store is closed on holidays, but without a source of holiday dates the open or closed status only considers the weekday and the time; on a holiday that falls on a weekday, Lia would report the store as open.

## AI-assisted workflow

To be documented.
