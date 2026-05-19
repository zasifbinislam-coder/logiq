"""
LogIQ — Public share links.

Generate a random token mapped to a (user_id, scope) tuple. Anyone with
the token sees a read-only summary view at /p/<token>.
"""
from __future__ import annotations

import secrets
import time
import uuid

from logiq.db import get_conn


SCHEMA_EXTRA = """
CREATE TABLE IF NOT EXISTS share_tokens (
  token TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  scope TEXT NOT NULL DEFAULT 'fleet',  -- fleet | flight | drone
  target_id TEXT,                       -- flight_id or drone_id when scoped
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  expires_at INTEGER,
  revoked INTEGER DEFAULT 0
);
"""


def init():
    con = get_conn()
    con.executescript(SCHEMA_EXTRA)
    con.commit()
    con.close()


def create_token(user_id: str, scope: str = "fleet", target_id: str | None = None, ttl_days: int = 365) -> str:
    init()
    tok = secrets.token_urlsafe(16)
    expires = int(time.time()) + ttl_days * 24 * 3600
    con = get_conn()
    con.execute(
        "INSERT INTO share_tokens (token, user_id, scope, target_id, expires_at) VALUES (?, ?, ?, ?, ?)",
        (tok, user_id, scope, target_id, expires),
    )
    con.commit()
    con.close()
    return tok


def resolve(token: str) -> dict | None:
    init()
    con = get_conn()
    r = con.execute("SELECT * FROM share_tokens WHERE token = ? AND revoked = 0", (token,)).fetchone()
    con.close()
    if not r:
        return None
    if r["expires_at"] and r["expires_at"] < int(time.time()):
        return None
    return dict(r)


def revoke(token: str):
    con = get_conn()
    con.execute("UPDATE share_tokens SET revoked = 1 WHERE token = ?", (token,))
    con.commit()
    con.close()


def list_for_user(user_id: str) -> list[dict]:
    init()
    con = get_conn()
    rows = con.execute("SELECT * FROM share_tokens WHERE user_id = ? ORDER BY created_at DESC", (user_id,)).fetchall()
    con.close()
    return [dict(r) for r in rows]
