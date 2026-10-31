"""SQLite database access and farm/message helpers."""
import ast
import json
import os
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Optional


def get_db_path():
    data_root = os.environ.get("DATA_ROOT")
    if data_root:
        db_dir = Path(data_root) / "db"
        db_dir.mkdir(parents=True, exist_ok=True)
        return str(db_dir / "ai_swat.db")
    base = os.path.dirname(__file__)
    return os.path.join(base, "..", "ai_swat.db")


DB_PATH = get_db_path()


def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS farms (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            location TEXT,
            soil_type TEXT,
            txtinout_path TEXT,
            setup_complete INTEGER DEFAULT 0,
            data_source TEXT DEFAULT '',
            created_at TEXT
        )
    """)
    # Migrate existing databases
    cols = {row[1] for row in c.execute("PRAGMA table_info(farms)").fetchall()}
    if "setup_complete" not in cols:
        c.execute("ALTER TABLE farms ADD COLUMN setup_complete INTEGER DEFAULT 0")
    if "data_source" not in cols:
        c.execute("ALTER TABLE farms ADD COLUMN data_source TEXT DEFAULT ''")
    if "crop_type" not in cols:
        c.execute("ALTER TABLE farms ADD COLUMN crop_type TEXT DEFAULT ''")
    if "planting_date" not in cols:
        c.execute("ALTER TABLE farms ADD COLUMN planting_date TEXT DEFAULT ''")
    c.execute("""
        CREATE TABLE IF NOT EXISTS simulations (
            id TEXT PRIMARY KEY,
            farm_id TEXT,
            sim_type TEXT,
            status TEXT DEFAULT 'pending',
            parameters TEXT,
            results TEXT,
            created_at TEXT,
            completed_at TEXT,
            FOREIGN KEY (farm_id) REFERENCES farms(id)
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS messages (
            id TEXT PRIMARY KEY,
            farm_id TEXT,
            session_id TEXT,
            role TEXT,
            content TEXT,
            tools_used TEXT,
            cards_json TEXT,
            simulation_id TEXT,
            created_at TEXT,
            FOREIGN KEY (farm_id) REFERENCES farms(id)
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS chat_sessions (
            id TEXT PRIMARY KEY,
            farm_id TEXT NOT NULL,
            title TEXT NOT NULL DEFAULT 'New chat',
            created_at TEXT,
            updated_at TEXT,
            FOREIGN KEY (farm_id) REFERENCES farms(id)
        )
    """)
    msg_cols = {row[1] for row in c.execute("PRAGMA table_info(messages)").fetchall()}
    if "session_id" not in msg_cols:
        c.execute("ALTER TABLE messages ADD COLUMN session_id TEXT")
    if "cards_json" not in msg_cols:
        c.execute("ALTER TABLE messages ADD COLUMN cards_json TEXT")
    if "widgets_json" not in msg_cols:
        c.execute("ALTER TABLE messages ADD COLUMN widgets_json TEXT")
    _migrate_messages_to_sessions(c)
    c.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    conn.commit()
    conn.close()


def db_exec(query, params=None):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    if params:
        c.execute(query, params)
    else:
        c.execute(query)
    conn.commit()
    result = c.fetchall()
    conn.close()
    return result


def db_one(query, params=None):
    results = db_exec(query, params)
    return dict(results[0]) if results else None


def save_setting(key: str, value: str):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
    conn.commit()
    conn.close()


def get_setting(key: str, default=None) -> str:
    row = db_one("SELECT value FROM settings WHERE key = ?", (key,))
    return row["value"] if row else default


def get_farms():
    rows = db_exec("SELECT * FROM farms ORDER BY created_at DESC")
    return [dict(r) for r in rows]


def create_farm(name: str, location: str = "", soil_type: str = "",
                txtinout_path: str = "", data_source: str = "",
                setup_complete: bool = False) -> dict:
    farm_id = str(uuid.uuid4())
    now = datetime.now().isoformat()
    if not txtinout_path:
        try:
            import config
            config.ensure_data_dirs()
            path = config.farm_txtinout_dir(farm_id)
            path.mkdir(parents=True, exist_ok=True)
            txtinout_path = str(path)
        except Exception:
            txtinout_path = ""
    db_exec(
        """INSERT INTO farms
           (id, name, location, soil_type, txtinout_path, setup_complete, data_source, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (farm_id, name, location, soil_type, txtinout_path,
         1 if setup_complete else 0, data_source, now),
    )
    return db_one("SELECT * FROM farms WHERE id = ?", (farm_id,))


def update_farm(farm_id: str, **fields) -> Optional[dict]:
    allowed = {"name", "location", "soil_type", "txtinout_path", "setup_complete", "data_source", "crop_type", "planting_date"}
    updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if not updates:
        return db_one("SELECT * FROM farms WHERE id = ?", (farm_id,))
    if "setup_complete" in updates:
        updates["setup_complete"] = 1 if updates["setup_complete"] else 0
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    db_exec(
        f"UPDATE farms SET {set_clause} WHERE id = ?",
        (*updates.values(), farm_id),
    )
    return db_one("SELECT * FROM farms WHERE id = ?", (farm_id,))


def delete_farm(farm_id: str):
    db_exec("DELETE FROM messages WHERE farm_id = ?", (farm_id,))
    db_exec("DELETE FROM chat_sessions WHERE farm_id = ?", (farm_id,))
    db_exec("DELETE FROM farms WHERE id = ?", (farm_id,))


def _migrate_messages_to_sessions(c) -> None:
    """Assign legacy messages (no session_id) to one session per farm."""
    orphan_farms = c.execute(
        "SELECT DISTINCT farm_id FROM messages WHERE session_id IS NULL OR session_id = ''"
    ).fetchall()
    now = datetime.now().isoformat()
    for (farm_id,) in orphan_farms:
        if not farm_id:
            continue
        session_id = str(uuid.uuid4())
        c.execute(
            """INSERT INTO chat_sessions (id, farm_id, title, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?)""",
            (session_id, farm_id, "Previous chat", now, now),
        )
        c.execute(
            "UPDATE messages SET session_id = ? WHERE farm_id = ? AND (session_id IS NULL OR session_id = '')",
            (session_id, farm_id),
        )


def create_chat_session(farm_id: str, title: str = "New chat") -> dict:
    session_id = str(uuid.uuid4())
    now = datetime.now().isoformat()
    db_exec(
        """INSERT INTO chat_sessions (id, farm_id, title, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?)""",
        (session_id, farm_id, title, now, now),
    )
    return get_chat_session(session_id)


def get_chat_session(session_id: str) -> Optional[dict]:
    row = db_one("SELECT * FROM chat_sessions WHERE id = ?", (session_id,))
    return dict(row) if row else None


def list_chat_sessions(farm_id: str, limit: int = 50) -> list[dict]:
    rows = db_exec(
        """SELECT s.*,
                  (SELECT COUNT(*) FROM messages m WHERE m.session_id = s.id) AS message_count,
                  (SELECT content FROM messages m WHERE m.session_id = s.id
                   ORDER BY m.created_at DESC LIMIT 1) AS last_preview
           FROM chat_sessions s
           WHERE s.farm_id = ?
           ORDER BY s.updated_at DESC
           LIMIT ?""",
        (farm_id, limit),
    )
    return [dict(r) for r in rows]


def update_chat_session(session_id: str, **fields) -> Optional[dict]:
    allowed = {"title", "updated_at"}
    updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if not updates:
        return get_chat_session(session_id)
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    db_exec(
        f"UPDATE chat_sessions SET {set_clause} WHERE id = ?",
        (*updates.values(), session_id),
    )
    return get_chat_session(session_id)


def touch_chat_session(session_id: str) -> None:
    update_chat_session(session_id, updated_at=datetime.now().isoformat())


def delete_chat_session(session_id: str) -> bool:
    session = get_chat_session(session_id)
    if not session:
        return False
    db_exec("DELETE FROM messages WHERE session_id = ?", (session_id,))
    db_exec("DELETE FROM chat_sessions WHERE id = ?", (session_id,))
    return True


def _parse_tools_used(raw: Any) -> list[str]:
    if not raw:
        return []
    if isinstance(raw, list):
        return [str(x) for x in raw]
    text = str(raw).strip()
    if not text:
        return []
    try:
        data = json.loads(text)
        if isinstance(data, list):
            return [str(x) for x in data]
    except json.JSONDecodeError:
        pass
    try:
        data = ast.literal_eval(text)
        if isinstance(data, list):
            return [str(x) for x in data]
    except (ValueError, SyntaxError):
        pass
    return [text]


def _parse_cards_json(raw: Any) -> list[dict]:
    if not raw:
        return []
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


def _serialize_message_row(row: dict) -> dict:
    return {
        "id": row["id"],
        "farm_id": row["farm_id"],
        "session_id": row.get("session_id"),
        "role": row["role"],
        "content": row["content"],
        "tools_used": _parse_tools_used(row.get("tools_used")),
        "cards": _parse_cards_json(row.get("cards_json")),
        "widgets": _parse_cards_json(row.get("widgets_json")),
        "simulation_id": row.get("simulation_id"),
        "created_at": row.get("created_at"),
    }


def create_message(
    farm_id: str,
    role: str,
    content: str,
    session_id: str,
    tools_used: list | None = None,
    simulation_id: str | None = None,
    cards: list | None = None,
    widgets: list | None = None,
) -> str:
    msg_id = str(uuid.uuid4())
    now = datetime.now().isoformat()
    db_exec(
        """INSERT INTO messages
           (id, farm_id, session_id, role, content, tools_used, cards_json, widgets_json, simulation_id, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            msg_id,
            farm_id,
            session_id,
            role,
            content,
            json.dumps(tools_used) if tools_used else None,
            json.dumps(cards) if cards else None,
            json.dumps(widgets) if widgets else None,
            simulation_id,
            now,
        ),
    )
    touch_chat_session(session_id)
    session = get_chat_session(session_id)
    if session and session.get("title") == "New chat" and role == "user":
        title = content.strip().replace("\n", " ")[:60]
        if len(content.strip()) > 60:
            title += "…"
        if title:
            update_chat_session(session_id, title=title)
    return msg_id


def get_messages(farm_id: str, session_id: str, limit: int = 100) -> list[dict]:
    rows = db_exec(
        """SELECT * FROM messages
           WHERE farm_id = ? AND session_id = ?
           ORDER BY created_at DESC LIMIT ?""",
        (farm_id, session_id, limit),
    )
    return [_serialize_message_row(dict(r)) for r in reversed(rows)]


def get_session_messages(session_id: str, limit: int = 100) -> list[dict]:
    rows = db_exec(
        f"""SELECT * FROM messages
            WHERE session_id = ?
            ORDER BY created_at DESC LIMIT {int(limit)}""",
        (session_id,),
    )
    return [_serialize_message_row(dict(r)) for r in reversed(rows)]
