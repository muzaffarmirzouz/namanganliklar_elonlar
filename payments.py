"""To'lov: noyob summa, Payme silkasi, xabardan summani ajratib olish."""
import base64
import random
import re

from config import (AD_PRICE, CLICK_LINK, PAYME_ACCOUNT_KEY, PAYME_LINK, PAYME_MERCHANT_ID,
                    UNIQUE_AMOUNT, UNIQUE_MAX_OFFSET)


def pick_amount(used_amounts: set[int]) -> int:
    """Har bir kutilayotgan buyurtmaga boshqalardan farq qiladigan summa beradi.
    Masalan 50 000 o'rniga 50 037 — shunda Payme xabaridagi summadan kim to'laganini aniq bilamiz."""
    if not UNIQUE_AMOUNT:
        return AD_PRICE
    free = [AD_PRICE + i for i in range(1, UNIQUE_MAX_OFFSET + 1) if AD_PRICE + i not in used_amounts]
    return random.choice(free) if free else AD_PRICE


def payme_link(amount: int, order_id: int) -> str:
    if PAYME_MERCHANT_ID:
        # Payme Business checkout: summa (tiyinda) silkaning ichida bo'ladi
        params = f"m={PAYME_MERCHANT_ID};ac.{PAYME_ACCOUNT_KEY}={order_id};a={amount * 100}"
        return "https://checkout.paycom.uz/" + base64.b64encode(params.encode()).decode()
    return PAYME_LINK.replace("{amount}", str(amount)).replace("{order_id}", str(order_id))


def click_link(amount: int, order_id: int) -> str:
    return CLICK_LINK.replace("{amount}", str(amount)).replace("{order_id}", str(order_id))


_NUM = re.compile(r"\d{1,3}(?:[   .,']\d{3})+(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?")


def extract_amounts(text: str) -> set[int]:
    """Matndagi barcha mumkin bo'lgan summalarni butun so'mga aylantiradi.
    '50 037,00 UZS' -> 50037, '50.037' -> 50037, '50037.00' -> 50037."""
    out: set[int] = set()
    for m in _NUM.finditer(text):
        s = m.group()
        variants = set()
        # 1) oxirgi ajratkichdan keyin 1-2 raqam bo'lsa — bu tiyin
        dec = re.match(r"^(.*?)[.,](\d{1,2})$", s)
        if dec:
            variants.add(re.sub(r"\D", "", dec.group(1)))
        # 2) hamma ajratkichlarni olib tashlash (minglik ajratkich sifatida)
        variants.add(re.sub(r"\D", "", s))
        for v in variants:
            if v and len(v) <= 12:
                out.add(int(v))
    return out


def match_order(text: str, ai_amount: float | None, awaiting: list[dict]) -> tuple[dict | None, str]:
    """To'lov xabarini kutilayotgan buyurtmalarga moslaydi.
    Qaytaradi: (buyurtma yoki None, izoh)."""
    by_amount: dict[int, list[dict]] = {}
    for o in awaiting:
        by_amount.setdefault(o["amount"], []).append(o)

    candidates: list[int] = []
    if ai_amount:
        candidates.append(int(round(ai_amount)))
    candidates += sorted(a for a in extract_amounts(text) if a in by_amount and a not in candidates)

    for a in candidates:
        orders = by_amount.get(a, [])
        if len(orders) == 1:
            return orders[0], f"summa {a}"
        if len(orders) > 1:
            return None, f"{a} so'mlik {len(orders)} ta buyurtma bor — qaysi biri ekanini admin tanlasin"
    return None, "mos buyurtma topilmadi"
