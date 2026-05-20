import time
import aiosqlite
from config import settings

_db: aiosqlite.Connection | None = None


async def init_db() -> None:
    global _db
    _db = await aiosqlite.connect(settings.DB_PATH)
    await _db.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lead_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at INTEGER DEFAULT (strftime('%s','now'))
        )
    """)
    await _db.execute("CREATE INDEX IF NOT EXISTS idx_lead_id ON messages(lead_id, created_at)")
    # State machine table — one row per lead
    await _db.execute("""
        CREATE TABLE IF NOT EXISTS leads (
            lead_id TEXT PRIMARY KEY,
            state TEXT NOT NULL DEFAULT 'active',
            paused_at INTEGER,
            last_bot_msg_at INTEGER,
            updated_at INTEGER DEFAULT (strftime('%s','now'))
        )
    """)
    await _db.commit()


async def close_db() -> None:
    global _db
    if _db:
        await _db.close()
        _db = None


# ── Message history ────────────────────────────────────────────────────────────

async def get_history(lead_id: str) -> list[dict]:
    if not _db:
        return []
    limit = settings.MAX_HISTORY_TURNS * 2
    async with _db.execute(
        "SELECT role, content FROM messages WHERE lead_id = ? ORDER BY created_at DESC LIMIT ?",
        (lead_id, limit),
    ) as cursor:
        rows = await cursor.fetchall()
    return [{"role": row[0], "content": row[1]} for row in reversed(rows)]


async def add_message(lead_id: str, role: str, content: str) -> None:
    if not _db:
        return
    await _db.execute(
        "INSERT INTO messages (lead_id, role, content) VALUES (?, ?, ?)",
        (lead_id, role, content),
    )
    await _db.commit()
    limit = settings.MAX_HISTORY_TURNS * 2
    await _db.execute(
        """
        DELETE FROM messages WHERE lead_id = ? AND id NOT IN (
            SELECT id FROM messages WHERE lead_id = ?
            ORDER BY created_at DESC LIMIT ?
        )
        """,
        (lead_id, lead_id, limit),
    )
    await _db.commit()


# ── Lead state machine ─────────────────────────────────────────────────────────
# States:
#   active          — AI agent handles incoming messages
#   paused_human    — human staff took over; agent is silent
#   bot_scheduling  — Kommo SalesBot is running; agent is silent

async def get_lead_state(lead_id: str) -> str:
    if not _db:
        return "active"
    async with _db.execute(
        "SELECT state FROM leads WHERE lead_id = ?", (lead_id,)
    ) as cursor:
        row = await cursor.fetchone()
    return row[0] if row else "active"


async def set_lead_state(lead_id: str, state: str) -> None:
    if not _db:
        return
    now = int(time.time())
    paused_at = now if state == "paused_human" else None
    last_bot = now if state == "bot_scheduling" else None
    await _db.execute(
        """
        INSERT INTO leads (lead_id, state, paused_at, last_bot_msg_at, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(lead_id) DO UPDATE SET
            state = excluded.state,
            paused_at = CASE WHEN excluded.state = 'paused_human'
                             THEN excluded.paused_at
                             ELSE leads.paused_at END,
            last_bot_msg_at = CASE WHEN excluded.state = 'bot_scheduling'
                                   THEN excluded.last_bot_msg_at
                                   ELSE leads.last_bot_msg_at END,
            updated_at = excluded.updated_at
        """,
        (lead_id, state, paused_at, last_bot, now),
    )
    await _db.commit()


async def should_resume(lead_id: str) -> bool:
    """Return True if enough time has elapsed for the agent to auto-resume."""
    if not _db:
        return True
    async with _db.execute(
        "SELECT state, paused_at, last_bot_msg_at FROM leads WHERE lead_id = ?",
        (lead_id,),
    ) as cursor:
        row = await cursor.fetchone()
    if not row:
        return True
    state, paused_at, last_bot_msg_at = row
    now = int(time.time())
    if state == "paused_human":
        return paused_at is None or (now - paused_at) > (settings.HUMAN_TIMEOUT_HOURS * 3600)
    if state == "bot_scheduling":
        return last_bot_msg_at is None or (now - last_bot_msg_at) > (settings.BOT_TIMEOUT_MINUTES * 60)
    return True
