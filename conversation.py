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
    await _db.commit()


async def close_db() -> None:
    global _db
    if _db:
        await _db.close()
        _db = None


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
    # Prune old messages beyond MAX_HISTORY_TURNS * 2
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
