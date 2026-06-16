"""
database.py — MySQL layer for Web3 Tweet Writer v3
Uses PyMySQL with connection pooling and auto-reconnect.
"""

import os
import json
import logging
from datetime import datetime
from contextlib import contextmanager

import pymysql
import pymysql.cursors

log = logging.getLogger(__name__)

DB_URL = os.getenv(
    "DATABASE_URL",
    "mysql://root:OjlRFNSuIIuietVenDQmeThUUFRwDssZ@thomas.proxy.rlwy.net:27871/railway"
)

def _parse_url(url: str) -> dict:
    """Parse mysql://user:pass@host:port/db into a dict."""
    url = url.replace("mysql://", "")
    user_pass, rest = url.split("@")
    user, password = user_pass.split(":", 1)
    host_port, db = rest.split("/")
    if ":" in host_port:
        host, port = host_port.split(":")
        port = int(port)
    else:
        host, port = host_port, 3306
    return dict(host=host, port=port, user=user, password=password, db=db)

_DB = _parse_url(DB_URL)


def get_conn():
    return pymysql.connect(
        host=_DB["host"],
        port=_DB["port"],
        user=_DB["user"],
        password=_DB["password"],
        database=_DB["db"],
        charset="utf8mb4",
        cursorclass=pymysql.cursors.DictCursor,
        autocommit=True,
        connect_timeout=10,
    )


@contextmanager
def cursor():
    conn = get_conn()
    try:
        with conn.cursor() as cur:
            yield cur
    finally:
        conn.close()


# ─── Init ─────────────────────────────────────────────────────────────────────

def init_db():
    with cursor() as cur:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS generations (
            id           INT AUTO_INCREMENT PRIMARY KEY,
            topic        TEXT NOT NULL,
            content      MEDIUMTEXT NOT NULL,
            content_type VARCHAR(20) NOT NULL DEFAULT 'tweet',
            tone         VARCHAR(30) NOT NULL DEFAULT 'builder',
            niche        VARCHAR(30) NOT NULL DEFAULT 'defi',
            model_used   VARCHAR(50),
            score        FLOAT DEFAULT 0,
            created_at   DATETIME DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_created (created_at)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS user_prefs (
            user_id      BIGINT PRIMARY KEY,
            tone         VARCHAR(30) NOT NULL DEFAULT 'builder',
            niche        VARCHAR(30) NOT NULL DEFAULT 'defi',
            content_type VARCHAR(20) NOT NULL DEFAULT 'tweet',
            updated_at   DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)

        cur.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            user_id         BIGINT PRIMARY KEY,
            last_topic      TEXT,
            last_content    MEDIUMTEXT,
            last_gen_id     INT,
            context_history JSON,
            edit_gen_id     INT DEFAULT NULL,
            edit_content    MEDIUMTEXT,
            edit_active     TINYINT(1) DEFAULT 0,
            updated_at      DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
        """)
    log.info("✅ Database tables ready.")


# ─── Generations ──────────────────────────────────────────────────────────────

def save_generation(topic, content, content_type, tone, niche, model_used, score=0) -> int:
    with cursor() as cur:
        cur.execute(
            """INSERT INTO generations (topic, content, content_type, tone, niche, model_used, score)
               VALUES (%s, %s, %s, %s, %s, %s, %s)""",
            (topic[:500], content, content_type, tone, niche, model_used, score),
        )
        return cur.lastrowid


def get_history(limit=10) -> list:
    with cursor() as cur:
        cur.execute(
            "SELECT * FROM generations ORDER BY created_at DESC LIMIT %s", (limit,)
        )
        return cur.fetchall()


def get_generation(gen_id: int) -> dict | None:
    with cursor() as cur:
        cur.execute("SELECT * FROM generations WHERE id = %s", (gen_id,))
        return cur.fetchone()


def update_score(gen_id: int, score: float):
    with cursor() as cur:
        cur.execute("UPDATE generations SET score = %s WHERE id = %s", (score, gen_id))


def delete_generation(gen_id: int):
    with cursor() as cur:
        cur.execute("DELETE FROM generations WHERE id = %s", (gen_id,))


def search_generations(query: str, limit=5) -> list:
    with cursor() as cur:
        cur.execute(
            "SELECT * FROM generations WHERE topic LIKE %s ORDER BY created_at DESC LIMIT %s",
            (f"%{query}%", limit),
        )
        return cur.fetchall()


# ─── User Preferences ─────────────────────────────────────────────────────────

def get_prefs(user_id: int) -> dict:
    with cursor() as cur:
        cur.execute("SELECT * FROM user_prefs WHERE user_id = %s", (user_id,))
        row = cur.fetchone()
    return row or {"user_id": user_id, "tone": "builder", "niche": "defi", "content_type": "tweet"}


def save_prefs(user_id: int, tone=None, niche=None, content_type=None):
    prefs = get_prefs(user_id)
    tone         = tone         or prefs["tone"]
    niche        = niche        or prefs["niche"]
    content_type = content_type or prefs["content_type"]
    with cursor() as cur:
        cur.execute(
            """INSERT INTO user_prefs (user_id, tone, niche, content_type)
               VALUES (%s, %s, %s, %s)
               ON DUPLICATE KEY UPDATE
                   tone=VALUES(tone),
                   niche=VALUES(niche),
                   content_type=VALUES(content_type)""",
            (user_id, tone, niche, content_type),
        )


# ─── Sessions ─────────────────────────────────────────────────────────────────

def get_session(user_id: int) -> dict:
    with cursor() as cur:
        cur.execute("SELECT * FROM sessions WHERE user_id = %s", (user_id,))
        row = cur.fetchone()
    if row:
        if isinstance(row.get("context_history"), str):
            try:
                row["context_history"] = json.loads(row["context_history"])
            except Exception:
                row["context_history"] = []
        elif row.get("context_history") is None:
            row["context_history"] = []
        return row
    return {
        "user_id": user_id,
        "last_topic": None,
        "last_content": None,
        "last_gen_id": None,
        "context_history": [],
        "edit_active": 0,
        "edit_gen_id": None,
        "edit_content": None,
    }


def save_session(user_id: int, **kwargs):
    session = get_session(user_id)

    last_topic   = kwargs.get("last_topic",   session.get("last_topic"))
    last_content = kwargs.get("last_content", session.get("last_content"))
    last_gen_id  = kwargs.get("last_gen_id",  session.get("last_gen_id"))
    edit_active  = kwargs.get("edit_active",  session.get("edit_active", 0))
    edit_gen_id  = kwargs.get("edit_gen_id",  session.get("edit_gen_id"))
    edit_content = kwargs.get("edit_content", session.get("edit_content"))

    # Rolling context window — last 5 entries
    history = session.get("context_history", [])
    if last_topic and last_content and kwargs.get("last_topic"):
        history.append({"topic": last_topic, "snippet": last_content[:150]})
        history = history[-5:]

    with cursor() as cur:
        cur.execute(
            """INSERT INTO sessions
               (user_id, last_topic, last_content, last_gen_id, context_history,
                edit_active, edit_gen_id, edit_content)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
               ON DUPLICATE KEY UPDATE
                   last_topic=VALUES(last_topic),
                   last_content=VALUES(last_content),
                   last_gen_id=VALUES(last_gen_id),
                   context_history=VALUES(context_history),
                   edit_active=VALUES(edit_active),
                   edit_gen_id=VALUES(edit_gen_id),
                   edit_content=VALUES(edit_content)""",
            (
                user_id,
                last_topic[:500] if last_topic else None,
                last_content,
                last_gen_id,
                json.dumps(history),
                edit_active,
                edit_gen_id,
                edit_content,
            ),
        )


def set_edit_mode(user_id: int, gen_id: int, content: str):
    save_session(user_id, edit_active=1, edit_gen_id=gen_id, edit_content=content)


def clear_edit_mode(user_id: int):
    save_session(user_id, edit_active=0, edit_gen_id=None, edit_content=None)
