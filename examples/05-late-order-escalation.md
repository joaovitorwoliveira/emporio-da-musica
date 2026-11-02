# Example 5: Late order: failed Identity Check, then Escalation

**What it demonstrates:** A wrong contact reveals nothing about the order. With the correct contact Lia reports the order is late by the right number of days and records an Escalation for the team without promising more than that.

**Tools called, in order:** `get_order`, `get_order`, `escalate_to_team`

**Model:** `kimi-k2.6`. **Reference date:** 2026-03-23 10:00 (America/Campo_Grande). The conversation is in Brazilian Portuguese.

---

**Cliente**

> Oi, queria saber onde está o meu pedido, o número 8.

**Lia**

> Oi! Para consultar seu pedido, preciso do número dele e também do e-mail ou telefone usado na compra.
>
> Você já me passou o pedido 8. Agora me diz qual e-mail ou telefone foi cadastrado nessa compra?

**Cliente**

> O e-mail que usei na compra é ana.ferreira@coldmail.com

**Lia**

> Não foi possível confirmar o pedido com os dados informados. Pode conferir o número do pedido e o e-mail ou telefone da compra?

**Cliente**

> Ah, errei o e-mail. O correto é anacarol.ferreira@coldmail.com

**Lia**

> Seu pedido está atrasado há 23 dias. Registrei o caso e a equipe retorna em até 24 horas úteis.
>
> Precisa de mais alguma coisa?
