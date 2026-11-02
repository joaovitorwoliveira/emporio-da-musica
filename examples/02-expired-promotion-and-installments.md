# Example 2: Expired promotion, Pix price and installments

**What it demonstrates:** A promotion the customer remembers has already ended and is not offered. The current price, the installment answer and the Pix price come from the payment options tool, never from the model's own arithmetic.

**Tools called, in order:** `find_product`, `get_payment_options`

**Model:** `kimi-k2.6`. **Reference date:** 2026-03-23 10:00 (America/Campo_Grande). The conversation is in Brazilian Portuguese.

---

**Cliente**

> Oi! Quanto está o violão Takamine GD20? Eu vi uma promoção dele por aí.

**Lia**

> Encontrei o **Takamine GD20 Dreadnought Natural** por **R$ 2.199,00**.
>
> Sobre a promoção que você viu: teve uma oferta com 12% de desconto, mas ela não está mais vigente. O preço atual é o de tabela mesmo, R$ 2.199,00.
>
> Quer que eu consulte as condições de pagamento (Pix e parcelamento) pra você?

**Cliente**

> Dá pra parcelar em 10x?

**Lia**

> Sim, dá pra parcelar em **10x de R$ 219,90** sem juros no cartão de crédito.
>
> Só pra completar as opções:
> - **Pix**: R$ 2.089,05 (com 5% de desconto)
> - **Parcelamento máximo**: até 12x de R$ 183,25 sem juros
>
> Quer mais alguma informação sobre o violão?

**Cliente**

> E no Pix, fica quanto?

**Lia**

> No Pix o **Takamine GD20** fica por **R$ 2.089,05** — são 5% de desconto sobre o preço de tabela.
>
> Quer mais alguma coisa?
