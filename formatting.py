"""E'lon matnini kanal uchun chiroyli qilib bezash (HTML)."""
import re
from html import escape, unescape

CATEGORY_STYLE = {
    "kvartira":   ("🏢", "KVARTIRA"),
    "hovli":      ("🏡", "HOVLI"),
    "uy":         ("🏠", "UY"),
    "yer":        ("🌳", "YER_UCHASTKA"),
    "tijorat":    ("🏪", "TIJORAT_BINO"),
    "avtomobil":  ("🚗", "AVTOMOBIL"),
    "moto":       ("🏍", "MOTO"),
    "ehtiyot":    ("⚙️", "EHTIYOT_QISM"),
    "texnika":    ("📺", "MAISHIY_TEXNIKA"),
    "telefon":    ("📱", "TELEFON"),
    "kompyuter":  ("💻", "KOMPYUTER"),
    "mebel":      ("🛋", "MEBEL"),
    "qurilish":   ("🧱", "QURILISH"),
    "kiyim":      ("👕", "KIYIM"),
    "bolalar":    ("🧸", "BOLALAR_UCHUN"),
    "chorva":     ("🐄", "CHORVA"),
    "uskuna":     ("🛠", "USKUNA"),
    "boshqa":     ("📦", "BOSHQA"),
}

CAPTION_LIMIT = 1024  # Telegram rasm izohi chegarasi
TEXT_LIMIT = 4096


def _e(v) -> str:
    return escape(str(v).strip(), quote=False)


def visible_len(html_text: str) -> int:
    """Telegram chegarani teglarsiz, UTF-16 birliklarda sanaydi (emoji = 2)."""
    plain = unescape(re.sub(r"<[^>]+>", "", html_text))
    return len(plain.encode("utf-16-le")) // 2


def build_caption(data: dict, footer: str = "", limit: int = CAPTION_LIMIT) -> str:
    emoji, tag = CATEGORY_STYLE.get(data.get("category", "boshqa"), CATEGORY_STYLE["boshqa"])

    head = [f"{emoji} <b>#{tag}</b> | #SOTILADI", ""]
    if data.get("title"):
        head.append(f"<b>{_e(str(data['title']).upper())}</b>")
        head.append("")

    info = []
    if data.get("price"):
        info.append(f"💰 <b>Narxi:</b> {_e(data['price'])}")
    if data.get("location"):
        info.append(f"📍 <b>Manzil:</b> {_e(data['location'])}")
    if data.get("condition"):
        info.append(f"✨ <b>Holati:</b> {_e(data['condition'])}")
    for line in data.get("details") or []:
        info.append(f"▫️ {_e(line)}")

    contact = []
    if data.get("phone"):
        contact.append(f"📞 <b>Aloqa:</b> {_e(data['phone'])}")
    if data.get("telegram"):
        contact.append(f"✈️ <b>Telegram:</b> {_e(data['telegram'])}")

    tail = ["", "━━━━━━━━━━━━━━"] + ([footer] if footer else [])

    def assemble(desc: str) -> str:
        parts = head + info
        if desc:
            parts += ["", f"📝 {desc}"]
        parts += [""] + contact + tail
        return "\n".join(parts)

    desc = _e(data.get("description", ""))
    text = assemble(desc)
    # Sig'masa — tavsifni qisqartiramiz (HTML teglar buzilmasligi uchun faqat tavsifni kesamiz)
    while visible_len(text) > limit and desc:
        overflow = visible_len(text) - limit
        desc = desc[: max(0, len(desc) - overflow - 2)].rstrip()
        # escape qilingan belgini (&amp;) o'rtasidan kesib qo'ymaslik
        amp = desc.rfind("&")
        if amp != -1 and ";" not in desc[amp:]:
            desc = desc[:amp]
        desc = (desc + "…") if desc else ""
        text = assemble(desc)
    return text


def build_footer(channel_username: str, channel_title: str, bot_username: str) -> str:
    lines = []
    if channel_username:
        lines.append(f'📢 <a href="https://t.me/{channel_username}">{_e(channel_title)}</a>')
    if bot_username:
        lines.append(f'✍️ E\'lon berish: @{bot_username}')
    return "\n".join(lines)


def fmt_sum(n: int) -> str:
    return f"{n:,}".replace(",", " ")
