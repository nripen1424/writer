"""
Database layer — SQLite for content history, user preferences, sessions.
"""

import sqlite3
import json
import os
from datetime import datetime

DB_PATH = os.getenv("DB_PATH", "tweet_bot.db")


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Create all tables on first run."""
    with get_conn() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS generations (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            topic       TEXT NOT NULL,
            content     TEXT NOT NULL,
            content_type TEXT NOT NULL,
            tone        TEXT DEFAULT 'builder',
            niche       TEXT DEFAULT 'defi',
            model_used  TEXT,
            score       REAL DEFAULT 0,
            created_at  TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS user_prefs (
            user_id     INTEGER PRIMARY KEY,
            tone        TEXT DEFAULT 'builder',
            niche       TEXT DEFAULT 'defi',
            content_type TEXT DEFAULT 'tweet',
            post_history TEXT DEFAULT '[]',
            updated_at  TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS sessions (
            user_id     INTEGER PRIMARY KEY,
            last_topic  TEXT,
            last_content TEXT,
            last_gen_id INTEGER,
            context_history TEXT DEFAULT '[]',
            updated_at  TEXT DEFAULT (datetime('now'))
        );
        """)


# ─── Generations ──────────────────────────────────────────────────────────────

def save_generation(topic, content, content_type, tone, niche, model_used, score=0):
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO generations (topic, content, content_type, tone, niche, model_used, score)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (topic, content, content_type, tone, niche, model_used, score),
        )
        return cur.lastrowid


def get_history(limit=10):
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM generations ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


def get_generation(gen_id):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM generations WHERE id = ?", (gen_id,)).fetchone()
    return dict(row) if row else None


def update_score(gen_id, score):
    with get_conn() as conn:
        conn.execute("UPDATE generations SET score = ? WHERE id = ?", (score, gen_id))


def delete_generation(gen_id):
    with get_conn() as conn:
        conn.execute("DELETE FROM generations WHERE id = ?", (gen_id,))


# ─── User Preferences ─────────────────────────────────────────────────────────

def get_prefs(user_id):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM user_prefs WHERE user_id = ?", (user_id,)).fetchone()
    if row:
        return dict(row)
    return {"user_id": user_id, "tone": "builder", "niche": "defi", "content_type": "tweet", "post_history": "[]"}


def save_prefs(user_id, tone=None, niche=None, content_type=None):
    prefs = get_prefs(user_id)
    tone = tone or prefs["tone"]
    niche = niche or prefs["niche"]
    content_type = content_type or prefs["content_type"]
    with get_conn() as conn:
        conn.execute(
            """INSERT INTO user_prefs (user_id, tone, niche, content_type, updated_at)
               VALUES (?, ?, ?, ?, datetime('now'))
               ON CONFLICT(user_id) DO UPDATE SET
                   tone=excluded.tone,
                   niche=excluded.niche,
                   content_type=excluded.content_type,
                   updated_at=excluded.updated_at""",
            (user_id, tone, niche, content_type),
        )


# ─── Sessions ─────────────────────────────────────────────────────────────────

def get_session(user_id):
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM sessions WHERE user_id = ?", (user_id,)).fetchone()
    if row:
        d = dict(row)
        d["context_history"] = json.loads(d.get("context_history") or "[]")
        return d
    return {"user_id": user_id, "last_topic": None, "last_content": None, "last_gen_id": None, "context_history": []}


def save_session(user_id, last_topic=None, last_content=None, last_gen_id=None, context_history=None):
    session = get_session(user_id)
    last_topic = last_topic if last_topic is not None else session.get("last_topic")
    last_content = last_content if last_content is not None else session.get("last_content")
    last_gen_id = last_gen_id if last_gen_id is not None else session.get("last_gen_id")

    # Keep rolling context window of last 5 generations
    if context_history is None:
        context_history = session.get("context_history", [])
    if last_topic and last_content:
        context_history.append({"topic": last_topic, "snippet": last_content[:200]})
        context_history = context_history[-5:]  # keep last 5

    with get_conn() as conn:
        conn.execute(
            """INSERT INTO sessions (user_id, last_topic, last_content, last_gen_id, context_history, updated_at)
               VALUES (?, ?, ?, ?, ?, datetime('now'))
               ON CONFLICT(user_id) DO UPDATE SET
                   last_topic=excluded.last_topic,
                   last_content=excluded.last_content,
                   last_gen_id=excluded.last_gen_id,
                   context_history=excluded.context_history,
                   updated_at=excluded.updated_at""",
            (user_id, last_topic, last_content, last_gen_id, json.dumps(context_history)),
        )
