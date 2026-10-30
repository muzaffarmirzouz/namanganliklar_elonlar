"""Buyurtma qoidalari: tarif, narx, yetishmayotgan ma'lumotlar, e'lon joylashga tayyormi."""
from config import TARIFFS
from formatting import is_nonsale

REQUIRED = {"category": "kategoriya", "title": "sarlavha", "price": "narx",
            "location": "manzil", "phone": "telefon"}


def order_days(order: dict) -> int:
    d = int(order["data"].get("_days") or 1)
    return d if d in TARIFFS else 1


def order_price(order: dict) -> int:
    return TARIFFS[order_days(order)]


def missing_fields(order: dict) -> list[str]:
    if order["data"].get("_ready"):  # tayyor reklama: faqat mazmuni bo'lsa yetarli
        return [] if (order["photos"] or order["data"].get("_ready_html")) else ["tayyor reklama mazmuni"]
    miss = [name for key, name in REQUIRED.items() if not order["data"].get(key)]
    if not order["photos"] and not is_nonsale(order["data"]):  # xizmat va vakansiyada rasm ixtiyoriy
        miss.append("kamida 1 ta rasm")
    return miss


def known_item(order: dict) -> bool:
    """To'lovga o'tish uchun yetarli: nima e'lon qilinishi aniq (kategoriya + sarlavha yoki tayyor reklama)."""
    d = order["data"]
    return bool(d.get("_ready") or (d.get("category") and d.get("title")))


def ready_to_publish(order: dict) -> bool:
    """Hamma ma'lumot bor VA mijoz tayyor e'lonni ko'rib tasdiqlagan."""
    return not missing_fields(order) and bool(order["data"].get("_confirmed"))
