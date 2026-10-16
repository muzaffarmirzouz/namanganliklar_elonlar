"""SQLite: foydalanuvchilar, buyurtmalar (e'lonlar), to'lov xabarlari."""
import asyncio
import json
import time

import aiosqlite

from config import DB_PATH

_db: aiosqlite.Connection | None = None

ACTIVE = ("draft", "awaiting_payment", "paid")


async def init() -> None:
    global _db
    _db = await aiosqlite.connect(DB_PATH)
    _db.row_factory = aiosqlite.Row
    await _db.executescript(
        """
        CREATE TABLE IF NOT EXISTS users(
            user_id INTEGER PRIMARY KEY,
            username TEXT, full_name TEXT,
            history TEXT DEFAULT '[]',
            created_at INTEGER
        );
        CREATE TABLE IF NOT EXISTS orders(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            status TEXT NOT NULL,          -- draft | awaiting_payment | paid | published | cancelled | expired
            data TEXT DEFAULT '{}',
            photos TEXT DEFAULT '[]',
            amount INTEGER,
            created_at INTEGER,
            pay_requested_at INTEGER,
            paid_at INTEGER,
            paid_by TEXT,
            published_at INTEGER,
            channel_msgs TEXT DEFAULT '[]',
            deleted INTEGER DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_orders_user ON orders(user_id, status);
        CREATE TABLE IF NOT EXISTS payments(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            msg_key TEXT UNIQUE,
            raw TEXT, amount INTEGER, order_id INTEGER,
            created_at INTEGER
        );
        """
    )
    # Business rejimi uchun ustunlar (eski bazaga ham qo'shiladi)
    for col in ("bc_id TEXT", "paused_until INTEGER DEFAULT 0"):
        try:
            await _db.execute(f"ALTER TABLE users ADD COLUMN {col}")
        except aiosqlite.OperationalError:
            pass  # allaqachon bor
    await _db.commit()


def _order(row) -> dict | None:
    if row is None:
        return None
    o = dict(row)
    o["data"] = json.loads(o["data"] or "{}")
    o["photos"] = json.loads(o["photos"] or "[]")
    o["channel_msgs"] = json.loads(o["channel_msgs"] or "[]")
    return o


# ---------- users ----------
async def upsert_user(user_id: int, username: str | None, full_name: str, bc_id: str | None = None) -> None:
    """bc_id — mijoz sizning business lichkangizga yozgan bo'lsa connection ID, botga to'g'ridan yozsa None.
    Keyingi barcha javoblar mijoz oxirgi marta qayerdan yozgan bo'lsa, o'sha yerga boradi."""
    await _db.execute(
        "INSERT INTO users(user_id, username, full_name, bc_id, created_at) VALUES(?,?,?,?,?) "
        "ON CONFLICT(user_id) DO UPDATE SET username=excluded.username, full_name=excluded.full_name, "
        "bc_id=excluded.bc_id",
        (user_id, username, full_name, bc_id, int(time.time())),
    )
    await _db.commit()


async def get_user(user_id: int) -> dict | None:
    cur = await _db.execute("SELECT user_id, username, full_name, bc_id FROM users WHERE user_id=?", (user_id,))
    row = await cur.fetchone()
    return dict(row) if row else None


async def bc_id(user_id: int) -> str | None:
    cur = await _db.execute("SELECT bc_id FROM users WHERE user_id=?", (user_id,))
    row = await cur.fetchone()
    return row["bc_id"] if row else None


async def send_kw(user_id: int) -> dict:
    """Mijozga xabar yuborishda qo'shiladigan parametrlar (business lichka bo'lsa connection ID)."""
    bc = await bc_id(user_id)
    return {"business_connection_id": bc} if bc else {}


async def set_pause(user_id: int, until: int) -> None:
    await _db.execute("INSERT OR IGNORE INTO users(user_id, created_at) VALUES(?,?)", (user_id, int(time.time())))
    await _db.execute("UPDATE users SET paused_until=? WHERE user_id=?", (until, user_id))
    await _db.commit()


async def is_paused(user_id: int) -> bool:
    cur = await _db.execute("SELECT paused_until FROM users WHERE user_id=?", (user_id,))
    row = await cur.fetchone()
    return bool(row and (row["paused_until"] or 0) > time.time())


async def get_history(user_id: int) -> list:
    cur = await _db.execute("SELECT history FROM users WHERE user_id=?", (user_id,))
    row = await cur.fetchone()
    return json.loads(row["history"]) if row else []


async def save_history(user_id: int, history: list, keep: int = 24) -> None:
    history = history[-keep:]
    # Claude tarixida birinchi xabar "user" bo'lishi kerak
    while history and history[0]["role"] != "user":
        history.pop(0)
    await _db.execute("UPDATE users SET history=? WHERE user_id=?",
                      (json.dumps(history, ensure_ascii=False), user_id))
    await _db.commit()


# ---------- orders ----------
async def get_order(order_id: int) -> dict | None:
    cur = await _db.execute("SELECT * FROM orders WHERE id=?", (order_id,))
    return _order(await cur.fetchone())


async def active_order(user_id: int) -> dict | None:
    cur = await _db.execute(
        f"SELECT * FROM orders WHERE user_id=? AND status IN {ACTIVE} ORDER BY id DESC LIMIT 1",
        (user_id,),
    )
    return _order(await cur.fetchone())


_create_lock = asyncio.Lock()


async def get_or_create_draft(user_id: int) -> dict:
    async with _create_lock:  # rasm va matn bir vaqtda kelsa ikkita qoralama ochilmasin
        o = await active_order(user_id)
        if o:
            return o
        cur = await _db.execute(
            "INSERT INTO orders(user_id, status, created_at) VALUES(?, 'draft', ?)",
            (user_id, int(time.time())),
        )
        await _db.commit()
        return await get_order(cur.lastrowid)


async def update_data(order_id: int, fields: dict) -> dict:
    o = await get_order(order_id)
    data = o["data"]
    for k, v in fields.items():
        if v in (None, "", []):
            continue
        data[k] = v
    await _db.execute("UPDATE orders SET data=? WHERE id=?",
                      (json.dumps(data, ensure_ascii=False), order_id))
    await _db.commit()
    return data


async def set_preview_shown(order_id: int, shown: bool) -> None:
    """Mijozga tayyor e'lon ko'rsatilganmi (lichkada 'ha' deb tasdiqlash uchun kerak)."""
    o = await get_order(order_id)
    data = o["data"]
    data["_preview"] = shown
    await _db.execute("UPDATE orders SET data=? WHERE id=?",
                      (json.dumps(data, ensure_ascii=False), order_id))
    await _db.commit()


async def set_photos(order_id: int, photos: list[str]) -> None:
    await _db.execute("UPDATE orders SET photos=? WHERE id=?", (json.dumps(photos), order_id))
    await _db.commit()


async def set_status(order_id: int, status: str, **extra) -> None:
    cols = ", ".join(f"{k}=?" for k in extra)
    sql = "UPDATE orders SET status=?" + (", " + cols if cols else "") + " WHERE id=?"
    await _db.execute(sql, (status, *extra.values(), order_id))
    await _db.commit()


async def request_payment(order_id: int, amount: int) -> None:
    await set_status(order_id, "awaiting_payment", amount=amount, pay_requested_at=int(time.time()))


async def mark_paid(order_id: int, paid_by: str, allow_expired: bool = False) -> bool:
    """Atomik: faqat to'lov kutayotgan buyurtma 'paid' bo'ladi (ikki marta tasdiqlanmaydi).
    allow_expired=True — admin muddati o'tgan buyurtmani qo'lda tasdiqlashi uchun."""
    statuses = "('awaiting_payment','expired')" if allow_expired else "('awaiting_payment')"
    cur = await _db.execute(
        f"UPDATE orders SET status='paid', paid_at=?, paid_by=? WHERE id=? AND status IN {statuses}",
        (int(time.time()), paid_by, order_id),
    )
    await _db.commit()
    return cur.rowcount == 1


async def mark_published(order_id: int, msg_ids: list[int]) -> None:
    await set_status(order_id, "published", published_at=int(time.time()),
                     channel_msgs=json.dumps(msg_ids))


async def awaiting_orders() -> list[dict]:
    cur = await _db.execute("SELECT * FROM orders WHERE status='awaiting_payment' ORDER BY id")
    return [_order(r) for r in await cur.fetchall()]


async def reserved_amounts(window_sec: int = 3 * 86400) -> set[int]:
    """Band summalar: kutilayotganlar + yaqinda muddati o'tganlar (kech to'lov boshqa buyurtmaga tushib qolmasin)."""
    cur = await _db.execute(
        "SELECT amount FROM orders WHERE amount IS NOT NULL AND "
        "(status='awaiting_payment' OR (status='expired' AND pay_requested_at > ?))",
        (int(time.time()) - window_sec,),
    )
    return {r["amount"] for r in await cur.fetchall()}


async def expired_awaiting(ttl_sec: int) -> list[dict]:
    cur = await _db.execute(
        "SELECT * FROM orders WHERE status='awaiting_payment' AND pay_requested_at < ?",
        (int(time.time()) - ttl_sec,),
    )
    return [_order(r) for r in await cur.fetchall()]


async def to_autodelete(age_sec: int) -> list[dict]:
    cur = await _db.execute(
        "SELECT * FROM orders WHERE status='published' AND deleted=0 AND published_at < ?",
        (int(time.time()) - age_sec,),
    )
    return [_order(r) for r in await cur.fetchall()]


async def mark_deleted(order_id: int) -> None:
    await _db.execute("UPDATE orders SET deleted=1 WHERE id=?", (order_id,))
    await _db.commit()


# ---------- payments ----------
async def payment_seen(msg_key: str) -> bool:
    cur = await _db.execute("SELECT 1 FROM payments WHERE msg_key=?", (msg_key,))
    return await cur.fetchone() is not None


async def log_payment(msg_key: str, raw: str, amount: int | None, order_id: int | None) -> None:
    await _db.execute(
        "INSERT OR IGNORE INTO payments(msg_key, raw, amount, order_id, created_at) VALUES(?,?,?,?,?)",
        (msg_key, raw[:2000], amount, order_id, int(time.time())),
    )
    await _db.commit()


async def stats(since: int) -> dict:
    cur = await _db.execute(
        "SELECT COUNT(*) c, COALESCE(SUM(amount),0) s FROM orders "
        "WHERE status='published' AND published_at>=?", (since,))
    pub = await cur.fetchone()
    cur = await _db.execute("SELECT COUNT(*) c FROM orders WHERE status='awaiting_payment'")
    wait = await cur.fetchone()
    cur = await _db.execute("SELECT COUNT(*) c FROM users")
    users = await cur.fetchone()
    return {"published": pub["c"], "sum": pub["s"], "awaiting": wait["c"], "users": users["c"]}
