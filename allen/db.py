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
            CREATE INDEX IF NOT EXISTS memories_ns_idx ON memories (namespace);
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


# ---- namespaced memory ----
def list_memories(namespace: str) -> list[dict]:
    with _cursor() as cur:
        cur.execute(
            "SELECT id, namespace, brand, content, source, created_at FROM memories "
            "WHERE namespace = %s ORDER BY created_at DESC",
            (namespace,),
        )
        return list(cur.fetchall())


def add_memory(namespace: str, content: str, brand: Optional[str] = None, source: str = "user") -> dict:
    mid = f"mem-{int(time.time() * 1000)}-{secrets.randbelow(10000)}"
    with _cursor() as cur:
        cur.execute(
            "INSERT INTO memories (id, namespace, brand, content, source) VALUES (%s, %s, %s, %s, %s) "
            "RETURNING id, namespace, brand, content, source, created_at",
            (mid, namespace, brand, content, source),
        )
        return cur.fetchone()


def update_memory(namespace: str, mid: str, content: str) -> None:
    with _cursor() as cur:
        cur.execute("UPDATE memories SET content = %s WHERE id = %s AND namespace = %s", (content, mid, namespace))


def delete_memory(namespace: str, mid: str) -> None:
    with _cursor() as cur:
        cur.execute("DELETE FROM memories WHERE id = %s AND namespace = %s", (mid, namespace))
