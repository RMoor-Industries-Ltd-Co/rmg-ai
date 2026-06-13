"""ALLEN platform data layer — its own Postgres. Holds projects (per-project API
keys + namespaces) and namespaced memory, so ALLEN/ALLIE can serve multiple
projects (Atelier, Axis, Cappo, Relationship Ledger) with isolated data."""

import secrets
import time
from contextlib import contextmanager
from typing import Optional

from .config import settings

_pool = None


def db_ready() -> bool:
    return bool(settings.database_url)


def _get_pool():
    global _pool
    if _pool is None and settings.database_url:
        from psycopg2.pool import SimpleConnectionPool

        _pool = SimpleConnectionPool(1, 8, settings.database_url)
    return _pool


@contextmanager
def _cursor():
    from psycopg2.extras import RealDictCursor

    pool = _get_pool()
    if pool is None:
        raise RuntimeError("DATABASE_URL not configured")
    conn = pool.getconn()
    try:
        conn.autocommit = True
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            yield cur
    finally:
        pool.putconn(conn)


def init_db() -> None:
    with _cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS projects (
                id text PRIMARY KEY,
                name text NOT NULL,
                namespace text UNIQUE NOT NULL,
                api_key text UNIQUE NOT NULL,
                created_at timestamptz DEFAULT now()
            );
            CREATE TABLE IF NOT EXISTS memories (
                id text PRIMARY KEY,
                namespace text NOT NULL,
                brand text,
                content text NOT NULL,
                source text NOT NULL DEFAULT 'user',
                created_at timestamptz DEFAULT now()
            );
            ALTER TABLE memories ADD COLUMN IF NOT EXISTS lane text;
            ALTER TABLE memories ADD COLUMN IF NOT EXISTS silo text;
            ALTER TABLE memories ADD COLUMN IF NOT EXISTS pinned boolean NOT NULL DEFAULT false;
            CREATE INDEX IF NOT EXISTS memories_ns_idx ON memories (namespace);
            CREATE INDEX IF NOT EXISTS memories_lane_silo_idx ON memories (namespace, lane, silo);

            CREATE TABLE IF NOT EXISTS conversations (
                id text PRIMARY KEY,
                namespace text NOT NULL,
                folder text NOT NULL DEFAULT 'General',
                title text NOT NULL DEFAULT 'New chat',
                created_at timestamptz DEFAULT now(),
                updated_at timestamptz DEFAULT now()
            );
            CREATE TABLE IF NOT EXISTS messages (
                id text PRIMARY KEY,
                conversation_id text NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                role text NOT NULL,
                content text NOT NULL,
                created_at timestamptz DEFAULT now()
            );
            CREATE INDEX IF NOT EXISTS conversations_ns_idx ON conversations (namespace, updated_at DESC);
            CREATE INDEX IF NOT EXISTS messages_conv_idx ON messages (conversation_id, created_at);

            CREATE TABLE IF NOT EXISTS inspirations (
                id text PRIMARY KEY,
                namespace text NOT NULL,
                text text NOT NULL,
                rating int NOT NULL DEFAULT 2,
                created_at timestamptz DEFAULT now()
            );
            CREATE INDEX IF NOT EXISTS inspirations_ns_idx ON inspirations (namespace);
            """
        )


def seed_default() -> None:
    """Default 'atelier' project keyed by the shared ALLEN_API_KEY so existing callers keep working."""
    if not settings.allen_api_key:
        return
    with _cursor() as cur:
        cur.execute("SELECT 1 FROM projects WHERE namespace = %s", ("atelier",))
        if cur.fetchone():
            return
        cur.execute(
            "INSERT INTO projects (id, name, namespace, api_key) VALUES (%s, %s, %s, %s) "
            "ON CONFLICT DO NOTHING",
            ("proj-atelier", "Master Atelier", "atelier", settings.allen_api_key),
        )


# ---- projects ----
def project_by_key(key: str) -> Optional[dict]:
    if not key:
        return None
    with _cursor() as cur:
        cur.execute("SELECT id, name, namespace FROM projects WHERE api_key = %s", (key,))
        return cur.fetchone()


def list_projects() -> list[dict]:
    with _cursor() as cur:
        cur.execute("SELECT id, name, namespace, created_at FROM projects ORDER BY created_at")
        return list(cur.fetchall())


def create_project(name: str, namespace: str) -> dict:
    key = "av_" + secrets.token_urlsafe(24)
    pid = f"proj-{namespace}"
    with _cursor() as cur:
        cur.execute(
            "INSERT INTO projects (id, name, namespace, api_key) VALUES (%s, %s, %s, %s) "
            "RETURNING id, name, namespace",
            (pid, name, namespace, key),
        )
        row = cur.fetchone()
    return {**row, "api_key": key}


# ---- namespaced memory (lane = business|personal, silo = granular topic) ----
def list_memories(namespace: str) -> list[dict]:
    with _cursor() as cur:
        cur.execute(
            "SELECT id, namespace, brand, content, source, lane, silo, pinned, created_at FROM memories "
            "WHERE namespace = %s ORDER BY pinned DESC, created_at DESC",
            (namespace,),
        )
        return list(cur.fetchall())


def add_memory(
    namespace: str,
    content: str,
    lane: Optional[str] = None,
    silo: Optional[str] = None,
    brand: Optional[str] = None,
    source: str = "user",
    pinned: bool = False,
) -> dict:
    mid = f"mem-{int(time.time() * 1000)}-{secrets.randbelow(10000)}"
    with _cursor() as cur:
        cur.execute(
            "INSERT INTO memories (id, namespace, brand, content, source, lane, silo, pinned) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) "
            "RETURNING id, namespace, brand, content, source, lane, silo, pinned, created_at",
            (mid, namespace, brand, content, source, lane, silo, pinned),
        )
        return cur.fetchone()


def set_pinned(namespace: str, mid: str, pinned: bool) -> None:
    with _cursor() as cur:
        cur.execute("UPDATE memories SET pinned = %s WHERE id = %s AND namespace = %s", (pinned, mid, namespace))


def update_memory(namespace: str, mid: str, content: str) -> None:
    with _cursor() as cur:
        cur.execute("UPDATE memories SET content = %s WHERE id = %s AND namespace = %s", (content, mid, namespace))


def delete_memory(namespace: str, mid: str) -> None:
    with _cursor() as cur:
        cur.execute("DELETE FROM memories WHERE id = %s AND namespace = %s", (mid, namespace))


# ---- conversations + messages (chat history, organized into project folders) ----
def create_conversation(namespace: str, folder: str = "General", title: str = "New chat") -> dict:
    cid = f"conv-{int(time.time() * 1000)}-{secrets.randbelow(10000)}"
    with _cursor() as cur:
        cur.execute(
            "INSERT INTO conversations (id, namespace, folder, title) VALUES (%s, %s, %s, %s) "
            "RETURNING id, namespace, folder, title, created_at, updated_at",
            (cid, namespace, folder or "General", title or "New chat"),
        )
        return cur.fetchone()


def list_conversations(namespace: str) -> list[dict]:
    with _cursor() as cur:
        cur.execute(
            "SELECT id, folder, title, updated_at FROM conversations WHERE namespace = %s "
            "ORDER BY updated_at DESC",
            (namespace,),
        )
        return list(cur.fetchall())


def get_conversation(namespace: str, cid: str) -> Optional[dict]:
    with _cursor() as cur:
        cur.execute(
            "SELECT id, folder, title, created_at, updated_at FROM conversations "
            "WHERE id = %s AND namespace = %s",
            (cid, namespace),
        )
        return cur.fetchone()


def get_messages(conversation_id: str) -> list[dict]:
    with _cursor() as cur:
        cur.execute(
            "SELECT role, content, created_at FROM messages WHERE conversation_id = %s ORDER BY created_at",
            (conversation_id,),
        )
        return list(cur.fetchall())


def add_message(conversation_id: str, role: str, content: str) -> None:
    mid = f"msg-{int(time.time() * 1000)}-{secrets.randbelow(100000)}"
    with _cursor() as cur:
        cur.execute(
            "INSERT INTO messages (id, conversation_id, role, content) VALUES (%s, %s, %s, %s)",
            (mid, conversation_id, role, content),
        )
        cur.execute("UPDATE conversations SET updated_at = now() WHERE id = %s", (conversation_id,))


def rename_conversation(namespace: str, cid: str, title: Optional[str], folder: Optional[str]) -> None:
    sets, args = [], []
    if title is not None:
        sets.append("title = %s")
        args.append(title)
    if folder is not None:
        sets.append("folder = %s")
        args.append(folder)
    if not sets:
        return
    args.extend([cid, namespace])
    with _cursor() as cur:
        cur.execute(f"UPDATE conversations SET {', '.join(sets)} WHERE id = %s AND namespace = %s", args)


def delete_conversation(namespace: str, cid: str) -> None:
    with _cursor() as cur:
        cur.execute("DELETE FROM conversations WHERE id = %s AND namespace = %s", (cid, namespace))


# ---- inspirations (home-screen greetings, rated 0-3 thumbs; higher rating shows more often) ----
_SEED_INSPIRATIONS = [
    "Discipline is the bridge between goals and accomplishment.",
    "Clarity comes from action, not thought. Start, then see.",
    "The work you avoid is usually the work that matters most.",
    "Done beats perfect. Ship it, then make it better.",
    "Consistency compounds. Show up again today.",
    "Your standards are your future. Hold the line.",
    "Comfort is a slow leak. Choose the harder, better thing.",
    "Build the day before the day builds you.",
    "Small hinges swing big doors. Do the small thing well.",
    "The brand is built in the unglamorous reps.",
    "Rest is part of the work, not a reward for finishing it.",
    "Make something today your future self will thank you for.",
    "Protect your mornings — they set the tone for everything.",
    "Speak less, build more.",
    "Momentum is a currency. Finish what you start.",
    "Greatness is just discipline, repeated.",
    "You are the standard. Act like it.",
    "Calm is a superpower. Move with intention, not noise.",
]


def seed_inspirations(namespace: str) -> None:
    with _cursor() as cur:
        cur.execute("SELECT count(*) AS n FROM inspirations WHERE namespace = %s", (namespace,))
        if cur.fetchone()["n"]:
            return
        for i, t in enumerate(_SEED_INSPIRATIONS):
            cur.execute(
                "INSERT INTO inspirations (id, namespace, text, rating) VALUES (%s, %s, %s, 2) "
                "ON CONFLICT DO NOTHING",
                (f"insp-seed-{namespace}-{i}", namespace, t),
            )


def random_inspiration(namespace: str) -> Optional[dict]:
    import random

    seed_inspirations(namespace)
    with _cursor() as cur:
        cur.execute("SELECT id, text, rating FROM inspirations WHERE namespace = %s", (namespace,))
        rows = list(cur.fetchall())
    if not rows:
        return None
    weights = [max(0, r["rating"]) for r in rows]  # 0 thumbs = excluded from the rotation
    if sum(weights) == 0:
        weights = [1] * len(rows)
    return random.choices(rows, weights=weights, k=1)[0]


def rate_inspiration(namespace: str, iid: str, rating: int) -> None:
    rating = max(0, min(3, int(rating)))
    with _cursor() as cur:
        cur.execute("UPDATE inspirations SET rating = %s WHERE id = %s AND namespace = %s", (rating, iid, namespace))


def add_inspiration(namespace: str, text: str) -> str:
    iid = f"insp-{int(time.time() * 1000)}-{secrets.randbelow(10000)}"
    with _cursor() as cur:
        cur.execute("INSERT INTO inspirations (id, namespace, text, rating) VALUES (%s, %s, %s, 2)", (iid, namespace, text))
    return iid
