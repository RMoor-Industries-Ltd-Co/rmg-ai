"""ALLEN platform data layer — its own Postgres. Holds projects (per-project API
keys + namespaces) and namespaced memory, so ALLEN/ALLIE can serve multiple
projects (Atelier, Axis, Cappo, Relationship Ledger) with isolated data."""

import json
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
            ALTER TABLE memories ADD COLUMN IF NOT EXISTS unit text;
            ALTER TABLE memories ADD COLUMN IF NOT EXISTS silo text;
            ALTER TABLE memories ADD COLUMN IF NOT EXISTS pinned boolean NOT NULL DEFAULT false;
            -- governance fields (memory classes + lifecycle + audit trail)
            ALTER TABLE memories ADD COLUMN IF NOT EXISTS memory_class text;     -- core|profile|project|commitment|session|sensitive
            ALTER TABLE memories ADD COLUMN IF NOT EXISTS sensitivity text;      -- low|medium|high
            ALTER TABLE memories ADD COLUMN IF NOT EXISTS priority text;         -- constitutional|high|normal|low
            ALTER TABLE memories ADD COLUMN IF NOT EXISTS status text NOT NULL DEFAULT 'active';  -- active|superseded|tombstoned
            ALTER TABLE memories ADD COLUMN IF NOT EXISTS updated_at timestamptz;
            ALTER TABLE memories ADD COLUMN IF NOT EXISTS expires_at timestamptz;
            ALTER TABLE memories ADD COLUMN IF NOT EXISTS review_required boolean NOT NULL DEFAULT false;
            ALTER TABLE memories ADD COLUMN IF NOT EXISTS supersedes text;       -- id of the memory this one replaces
            CREATE INDEX IF NOT EXISTS memories_ns_idx ON memories (namespace);
            CREATE INDEX IF NOT EXISTS memories_lane_silo_idx ON memories (namespace, lane, silo);
            CREATE INDEX IF NOT EXISTS memories_ns_status_idx ON memories (namespace, status);

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

            CREATE TABLE IF NOT EXISTS app_config (
                key text PRIMARY KEY,
                value text,
                updated_at timestamptz DEFAULT now()
            );

            CREATE TABLE IF NOT EXISTS audit_log (
                id text PRIMARY KEY,
                namespace text NOT NULL,
                actor text NOT NULL,
                action text NOT NULL,
                detail text,
                result text,
                created_at timestamptz DEFAULT now()
            );
            CREATE INDEX IF NOT EXISTS audit_ns_idx ON audit_log (namespace, created_at DESC);

            -- Usage & cost tracking (the "$" console dashboard's source of truth). One row per
            -- billable API call — Claude (tokens), Whisper (audio seconds), ElevenLabs (characters).
            -- `project` is a PIAAR repo/product key (see allen/usage.py's PIAAR_PROJECTS); `namespace`
            -- is ALLEN's own multi-tenant namespace when applicable. cost_usd is an ESTIMATE computed
            -- at log time from a static rate table, not live provider billing.
            CREATE TABLE IF NOT EXISTS usage_log (
                id text PRIMARY KEY,
                project text NOT NULL,
                namespace text,
                feature text NOT NULL,
                provider text NOT NULL,
                model text,
                input_tokens integer,
                output_tokens integer,
                audio_seconds real,
                characters integer,
                cost_usd numeric(12,6) NOT NULL DEFAULT 0,
                meta jsonb,
                created_at timestamptz DEFAULT now()
            );
            CREATE INDEX IF NOT EXISTS usage_log_project_idx ON usage_log (project, created_at DESC);

            -- Virtual forms — structured "slot-filling" tools ALLEN uses for common
            -- requests (schedule an appointment, open a PIAAR initiative, etc). Each row
            -- becomes one dynamically-generated tool (submit_form_<key>) with its own
            -- required fields, so Claude's own tool-calling enforces "ask if missing"
            -- rather than guessing. created_by 'system' = seeded starter forms;
            -- 'allen' = ALLEN defined it himself via define_virtual_form.
            CREATE TABLE IF NOT EXISTS virtual_forms (
                id text PRIMARY KEY,
                namespace text NOT NULL,
                key text NOT NULL,
                label text NOT NULL,
                domain text NOT NULL DEFAULT 'personal',
                action text NOT NULL DEFAULT 'note',
                fields jsonb NOT NULL,
                created_by text NOT NULL DEFAULT 'system',
                created_at timestamptz DEFAULT now()
            );
            CREATE UNIQUE INDEX IF NOT EXISTS virtual_forms_ns_key_idx ON virtual_forms (namespace, key);
            """
        )


def add_audit(namespace: str, actor: str, action: str, detail: str = "", result: str = "") -> None:
    """Record an operational write or delegation. Never raises — logging must not break the work."""
    if not db_ready():
        return
    try:
        aid = f"aud-{int(time.time() * 1000)}-{secrets.randbelow(100000)}"
        with _cursor() as cur:
            cur.execute(
                "INSERT INTO audit_log (id, namespace, actor, action, detail, result) "
                "VALUES (%s, %s, %s, %s, %s, %s)",
                (aid, namespace, actor, action, (detail or "")[:1000], (result or "")[:1000]),
            )
    except Exception:
        pass


def list_audit(namespace: str, limit: int = 30) -> list[dict]:
    if not db_ready():
        return []
    with _cursor() as cur:
        cur.execute(
            "SELECT actor, action, detail, result, created_at FROM audit_log "
            "WHERE namespace = %s ORDER BY created_at DESC LIMIT %s",
            (namespace, max(1, min(int(limit or 30), 100))),
        )
        return list(cur.fetchall())


def get_config(key: str) -> Optional[str]:
    if not db_ready():
        return None
    with _cursor() as cur:
        cur.execute("SELECT value FROM app_config WHERE key = %s", (key,))
        row = cur.fetchone()
        return row["value"] if row else None


def set_config(key: str, value: str) -> None:
    with _cursor() as cur:
        cur.execute(
            "INSERT INTO app_config (key, value) VALUES (%s, %s) "
            "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()",
            (key, value),
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
# Two orthogonal axes: memory_class (core|profile|project|commitment|session|sensitive)
# governs lifecycle + retrieval priority; lane/unit/silo govern world-routing (Drive archives).
_MEMORY_COLS = (
    "id, namespace, brand, content, source, lane, unit, silo, pinned, "
    "memory_class, sensitivity, priority, status, review_required, supersedes, "
    "created_at, updated_at, expires_at"
)

# Retrieval priority (policy #5): constitutional first (oldest-enshrined first so directive #1
# precedes #2), then by class rank, then direct-from-Rahm over inferred, then most-recent.
_RETRIEVAL_ORDER = (
    "ORDER BY pinned DESC, "
    "CASE WHEN pinned THEN created_at END ASC, "
    "CASE memory_class WHEN 'core' THEN 0 WHEN 'profile' THEN 1 WHEN 'project' THEN 2 "
    "WHEN 'commitment' THEN 3 WHEN 'sensitive' THEN 4 WHEN 'session' THEN 5 ELSE 6 END, "
    "(source = 'rahm_direct') DESC, created_at DESC"
)


def list_memories(namespace: str, include_inactive: bool = False) -> list[dict]:
    """Active, non-expired memories in retrieval-priority order. Set include_inactive=True
    for an audit view that also returns superseded/tombstoned/expired records."""
    where = "WHERE namespace = %s"
    if not include_inactive:
        where += " AND status = 'active' AND (expires_at IS NULL OR expires_at > now())"
    order = "ORDER BY created_at DESC" if include_inactive else _RETRIEVAL_ORDER
    with _cursor() as cur:
        cur.execute(f"SELECT {_MEMORY_COLS} FROM memories {where} {order}", (namespace,))
        return list(cur.fetchall())


def add_memory(
    namespace: str,
    content: str,
    lane: Optional[str] = None,
    silo: Optional[str] = None,
    brand: Optional[str] = None,
    source: str = "user",
    pinned: bool = False,
    unit: Optional[str] = None,
    memory_class: Optional[str] = None,
    sensitivity: Optional[str] = None,
    priority: Optional[str] = None,
    expires_at: Optional[str] = None,
    review_required: bool = False,
    supersedes: Optional[str] = None,
) -> dict:
    mid = f"mem-{int(time.time() * 1000)}-{secrets.randbelow(10000)}"
    with _cursor() as cur:
        cur.execute(
            "INSERT INTO memories (id, namespace, brand, content, source, lane, unit, silo, pinned, "
            "memory_class, sensitivity, priority, expires_at, review_required, supersedes) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
            f"RETURNING {_MEMORY_COLS}",
            (mid, namespace, brand, content, source, lane, unit, silo, pinned,
             memory_class, sensitivity, priority, expires_at, review_required, supersedes),
        )
        return cur.fetchone()


def set_pinned(namespace: str, mid: str, pinned: bool) -> None:
    with _cursor() as cur:
        cur.execute(
            "UPDATE memories SET pinned = %s, updated_at = now() WHERE id = %s AND namespace = %s",
            (pinned, mid, namespace),
        )


def update_memory(namespace: str, mid: str, content: str) -> None:
    with _cursor() as cur:
        cur.execute(
            "UPDATE memories SET content = %s, updated_at = now() WHERE id = %s AND namespace = %s",
            (content, mid, namespace),
        )


def supersede_memory(namespace: str, old_id: str, content: str) -> Optional[dict]:
    """Correction flow (policy #3): mark the old memory 'superseded' (audit trail kept) and
    insert a new active memory that records what it supersedes — never a silent overwrite.
    The replacement inherits the old memory's class/lane/sensitivity/priority/pinned."""
    with _cursor() as cur:
        cur.execute(
            f"SELECT {_MEMORY_COLS} FROM memories WHERE id = %s AND namespace = %s", (old_id, namespace)
        )
        old = cur.fetchone()
        if not old:
            return None
        cur.execute(
            "UPDATE memories SET status = 'superseded', updated_at = now() WHERE id = %s AND namespace = %s",
            (old_id, namespace),
        )
    return add_memory(
        namespace, content,
        lane=old.get("lane"), silo=old.get("silo"), brand=old.get("brand"),
        source="rahm_direct", pinned=bool(old.get("pinned")), unit=old.get("unit"),
        memory_class=old.get("memory_class"), sensitivity=old.get("sensitivity"),
        priority=old.get("priority"), supersedes=old_id,
    )


def delete_memory(namespace: str, mid: str) -> None:
    """Deletion flow (policy #4): hard-delete ephemeral 'session' memories; tombstone everything
    else (status='tombstoned' — removed from retrieval but retained for audit)."""
    with _cursor() as cur:
        cur.execute("SELECT memory_class FROM memories WHERE id = %s AND namespace = %s", (mid, namespace))
        row = cur.fetchone()
        if row and (row.get("memory_class") or "") == "session":
            cur.execute("DELETE FROM memories WHERE id = %s AND namespace = %s", (mid, namespace))
        else:
            cur.execute(
                "UPDATE memories SET status = 'tombstoned', updated_at = now() "
                "WHERE id = %s AND namespace = %s",
                (mid, namespace),
            )


def hard_delete_memory(namespace: str, mid: str) -> None:
    """Force a hard delete regardless of class (e.g. Rahm explicitly purges a sensitive record)."""
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


# ---- usage & cost tracking ("$" console dashboard) ----
def insert_usage(
    project: str,
    namespace: str,
    feature: str,
    provider: str,
    model: Optional[str],
    input_tokens: Optional[int] = None,
    output_tokens: Optional[int] = None,
    audio_seconds: Optional[float] = None,
    characters: Optional[int] = None,
    cost_usd: float = 0.0,
    meta: Optional[dict] = None,
) -> None:
    """Record one billable API call. Never raises — usage tracking must not break the work."""
    if not db_ready():
        return
    try:
        uid = f"use-{int(time.time() * 1000)}-{secrets.randbelow(100000)}"
        with _cursor() as cur:
            cur.execute(
                "INSERT INTO usage_log (id, project, namespace, feature, provider, model, "
                "input_tokens, output_tokens, audio_seconds, characters, cost_usd, meta) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    uid, project, namespace or None, feature, provider, model,
                    input_tokens, output_tokens, audio_seconds, characters,
                    cost_usd, json.dumps(meta) if meta else None,
                ),
            )
    except Exception:
        pass


def usage_summary(project: Optional[str] = None, days: int = 30) -> list[dict]:
    """Totals grouped by project/feature/provider/model over the trailing window."""
    if not db_ready():
        return []
    where = "WHERE created_at > now() - (%s || ' days')::interval"
    args: list = [days]
    if project:
        where += " AND project = %s"
        args.append(project)
    with _cursor() as cur:
        cur.execute(
            f"SELECT project, feature, provider, model, count(*) AS calls, "
            f"sum(coalesce(input_tokens,0)) AS input_tokens, "
            f"sum(coalesce(output_tokens,0)) AS output_tokens, "
            f"sum(coalesce(audio_seconds,0)) AS audio_seconds, "
            f"sum(coalesce(characters,0)) AS characters, "
            f"sum(cost_usd) AS cost_usd "
            f"FROM usage_log {where} "
            f"GROUP BY project, feature, provider, model "
            f"ORDER BY project, cost_usd DESC",
            args,
        )
        return list(cur.fetchall())


def usage_daily(project: Optional[str] = None, days: int = 30) -> list[dict]:
    """Daily cost totals over the trailing window — feeds the trend chart + top-usage-days."""
    if not db_ready():
        return []
    where = "WHERE created_at > now() - (%s || ' days')::interval"
    args: list = [days]
    if project:
        where += " AND project = %s"
        args.append(project)
    with _cursor() as cur:
        cur.execute(
            f"SELECT (created_at AT TIME ZONE 'UTC')::date AS day, "
            f"sum(cost_usd) AS cost_usd, count(*) AS calls "
            f"FROM usage_log {where} "
            f"GROUP BY (created_at AT TIME ZONE 'UTC')::date ORDER BY day",
            args,
        )
        return list(cur.fetchall())


# ---- virtual forms (ALLEN's structured "slot-filling" tools) ----
def list_forms(namespace: str) -> list[dict]:
    if not db_ready():
        return []
    with _cursor() as cur:
        cur.execute(
            "SELECT key, label, domain, action, fields, created_by, created_at FROM virtual_forms "
            "WHERE namespace = %s ORDER BY created_at",
            (namespace,),
        )
        return list(cur.fetchall())


def get_form(namespace: str, key: str) -> Optional[dict]:
    if not db_ready():
        return None
    with _cursor() as cur:
        cur.execute(
            "SELECT key, label, domain, action, fields, created_by FROM virtual_forms "
            "WHERE namespace = %s AND key = %s",
            (namespace, key),
        )
        return cur.fetchone()


def upsert_form(
    namespace: str, key: str, label: str, domain: str, action: str,
    fields: list, created_by: str = "system",
) -> dict:
    fid = f"form-{namespace}-{key}"
    with _cursor() as cur:
        cur.execute(
            "INSERT INTO virtual_forms (id, namespace, key, label, domain, action, fields, created_by) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (namespace, key) DO UPDATE SET "
            "label = EXCLUDED.label, domain = EXCLUDED.domain, action = EXCLUDED.action, "
            "fields = EXCLUDED.fields "
            "RETURNING key, label, domain, action, fields, created_by",
            (fid, namespace, key, label, domain, action, json.dumps(fields), created_by),
        )
        return cur.fetchone()
