import hashlib
import hmac
import os
import sqlite3
from datetime import timedelta, timezone
from datetime import datetime as _datetime

from dotenv import load_dotenv

load_dotenv()

DB_FILE = "tracker.db"
IST = timezone(timedelta(hours=5, minutes=30))

STATE_RANK = {"seen": 0, "tracked": 1, "applied": 2, "over": 3}
ACTION_TO_STATE = {"track": "tracked", "applied": "applied"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    event_id     TEXT PRIMARY KEY,
    title        TEXT NOT NULL,
    url          TEXT NOT NULL,
    host         TEXT,
    source       TEXT,
    event_start  TEXT,
    event_end    TEXT,
    state        TEXT NOT NULL DEFAULT 'seen'
                 CHECK (state IN ('seen','tracked','applied','over')),
    outcome      TEXT
                 CHECK (outcome IS NULL OR outcome IN
                        ('did_not_participate','participated','won')),
    first_seen   TEXT NOT NULL,
    tracked_at   TEXT,
    applied_at   TEXT,
    over_at      TEXT,
    updated_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS action_log (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id     TEXT NOT NULL,
    action       TEXT NOT NULL,
    result       TEXT NOT NULL,
    occurred_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_events_state ON events(state);
"""


def _now_ist():
    return _datetime.now(IST).isoformat()


def connect(db_path=None):
    """Opens (creating if needed) the tracker SQLite database, sets WAL mode
    and a busy timeout so the always-on tracker service and the weekly digest
    script can safely interleave writes, and ensures the schema exists.
    Idempotent: safe to call repeatedly against the same file."""
    path = db_path or DB_FILE
    conn = sqlite3.connect(path, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def upsert_seen(conn, items):
    """Inserts each item as a new 'seen' row, or refreshes its denormalized
    metadata on an existing row without touching participation state. Only
    the weekly digest run calls this; the tracker service never inserts."""
    now = _now_ist()
    for item in items:
        event_id = item.get("event_id")
        if not event_id:
            continue
        conn.execute(
            """
            INSERT INTO events (event_id, title, url, host, source,
                                event_start, event_end, state, first_seen, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'seen', ?, ?)
            ON CONFLICT(event_id) DO UPDATE SET
                title       = excluded.title,
                url         = excluded.url,
                host        = excluded.host,
                source      = excluded.source,
                event_start = COALESCE(excluded.event_start, events.event_start),
                event_end   = COALESCE(excluded.event_end,   events.event_end),
                updated_at  = excluded.updated_at
            """,
            (
                event_id,
                item.get("title") or "Unknown",
                item.get("url") or "",
                item.get("host"),
                item.get("source"),
                item.get("event_start"),
                item.get("event_end"),
                now,
                now,
            ),
        )
    conn.commit()


def log_action(conn, event_id, action, result):
    """Appends one row to the action_log audit trail. Exposed publicly so the
    tracker service can log a bad_token rejection (which never reaches
    apply_action, since the signature is checked first)."""
    conn.execute(
        "INSERT INTO action_log (event_id, action, result, occurred_at) VALUES (?, ?, ?, ?)",
        (event_id, action, result, _now_ist()),
    )
    conn.commit()


def apply_action(conn, action, event_id):
    """Applies a track/applied action to an existing row.

    Returns (result, row) where result is one of "ok", "noop",
    "unknown_event". Never inserts a new row (only upsert_seen does that), so
    every call here either updates a row the digest run already created or
    reports unknown_event. Every call, including unknown/noop, is logged to
    action_log. State only ever moves upward (seen < tracked < applied);
    an out-of-order or repeat click is a noop, never a downgrade or an error.
    """
    now = _now_ist()
    target_state = ACTION_TO_STATE[action]
    row = conn.execute(
        "SELECT * FROM events WHERE event_id = ?", (event_id,)
    ).fetchone()

    if row is None:
        log_action(conn, event_id, action, "unknown_event")
        return "unknown_event", None

    if STATE_RANK[row["state"]] >= STATE_RANK[target_state]:
        log_action(conn, event_id, action, "noop")
        return "noop", row

    ts_column = "tracked_at" if target_state == "tracked" else "applied_at"
    conn.execute(
        f"UPDATE events SET state = ?, {ts_column} = ?, updated_at = ? WHERE event_id = ?",
        (target_state, now, now, event_id),
    )
    conn.commit()
    log_action(conn, event_id, action, "ok")
    row = conn.execute("SELECT * FROM events WHERE event_id = ?", (event_id,)).fetchone()
    # (2.5 note: a future calendar trigger attaches exactly here, after a
    #  successful "ok" transition: POST event details to an n8n webhook that
    #  creates the Google Calendar entry. OAuth lives in n8n, not here. Not
    #  built; this comment only marks the attach point.)
    return "ok", row


def get_tracked_open(conn, today_str):
    """Tracked events not yet lapsed, for the digest's reminder section."""
    return conn.execute(
        """
        SELECT * FROM events
        WHERE state = 'tracked'
          AND (COALESCE(event_end, event_start) IS NULL
               OR COALESCE(event_end, event_start) >= ?)
        ORDER BY COALESCE(event_start, '9999-12-31')
        """,
        (today_str,),
    ).fetchall()


def get_applied_open(conn, today_str):
    """Applied events not yet past their end date, for the participation log."""
    return conn.execute(
        """
        SELECT * FROM events
        WHERE state = 'applied'
          AND (event_end IS NULL OR event_end >= ?)
        ORDER BY COALESCE(event_start, '9999-12-31')
        """,
        (today_str,),
    ).fetchall()


def get_all_events(conn):
    """Every row in the store, every state, most recently updated first.
    Read-only helper for the tracker service's /list view; never used by
    any state-changing code path."""
    return conn.execute("SELECT * FROM events ORDER BY updated_at DESC").fetchall()


def sign_action(action, event_id, secret=None):
    """HMAC-SHA256 of "action:event_id" under TRACKER_SECRET, hex, truncated
    to 20 chars. Binding the action into the MAC means a Track link cannot be
    replayed as an Applied link. Returns None if no secret is configured
    (callers use this to skip rendering unsigned dead links)."""
    key = os.getenv("TRACKER_SECRET") if secret is None else secret
    if not key:
        return None
    message = f"{action}:{event_id}".encode()
    return hmac.new(key.encode(), message, hashlib.sha256).hexdigest()[:20]


def verify_action(action, event_id, token, secret=None):
    """Constant-time verification of a signed action link. False on a
    missing token, a missing secret, or a mismatch."""
    if not token:
        return False
    expected = sign_action(action, event_id, secret=secret)
    if expected is None:
        return False
    return hmac.compare_digest(expected, token)
