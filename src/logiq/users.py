"""
LogIQ — User accounts.

Tables:
  users       — credentials and profile
  sessions    — random-token sessions linked to a user
  (extends existing fleets table — each user gets one default fleet)

Password hashing uses bcrypt.
Session tokens are random 32-byte hex strings stored as cookies.
"""
from __future__ import annotations

import json
import secrets
import sqlite3
import time
import uuid
from typing import Any

import bcrypt

from logiq.db import get_conn


SCHEMA_EXTRA = """
CREATE TABLE IF NOT EXISTS users (
  id TEXT PRIMARY KEY,
  email TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  display_name TEXT,
  fleet_id TEXT REFERENCES fleets(id),
  phone TEXT,
  organization TEXT,
  country TEXT DEFAULT 'BD',
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);

CREATE TABLE IF NOT EXISTS sessions (
  token TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id),
  created_at TEXT DEFAULT CURRENT_TIMESTAMP,
  last_used_at TEXT DEFAULT CURRENT_TIMESTAMP,
  expires_at INTEGER
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
"""


def init():
    con = get_conn()
    con.executescript(SCHEMA_EXTRA)
    con.commit()
    con.close()


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=10)).decode("utf-8")


def check_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
    except Exception:
        return False


def create_user(email: str, password: str, display_name: str = "",
                phone: str = "", organization: str = "") -> dict:
    init()
    if len(password) < 6:
        raise ValueError("password must be at least 6 characters")
    email = (email or "").strip().lower()
    if "@" not in email or "." not in email:
        raise ValueError("invalid email")

    con = get_conn()
    try:
        row = con.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
        if row:
            raise ValueError("email already registered")

        uid = str(uuid.uuid4())
        fleet_id = str(uuid.uuid4())
        con.execute("INSERT INTO fleets (id, name, owner_email) VALUES (?, ?, ?)",
                    (fleet_id, display_name or email.split("@")[0] + "'s fleet", email))
        con.execute(
            """INSERT INTO users (id, email, password_hash, display_name, fleet_id, phone, organization)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (uid, email, hash_password(password), display_name or None, fleet_id, phone or None, organization or None),
        )
        con.commit()
        return {"id": uid, "email": email, "display_name": display_name, "fleet_id": fleet_id}
    finally:
        con.close()


def authenticate(email: str, password: str) -> dict | None:
    email = (email or "").strip().lower()
    con = get_conn()
    row = con.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    con.close()
    if not row:
        return None
    if not check_password(password, row["password_hash"]):
        return None
    return {"id": row["id"], "email": row["email"], "display_name": row["display_name"], "fleet_id": row["fleet_id"]}


def create_session(user_id: str, ttl_seconds: int = 30 * 24 * 3600) -> str:
    init()
    token = secrets.token_hex(32)
    expires = int(time.time()) + ttl_seconds
    con = get_conn()
    con.execute("INSERT INTO sessions (token, user_id, expires_at) VALUES (?, ?, ?)",
                (token, user_id, expires))
    con.commit()
    con.close()
    return token


def get_user_by_token(token: str | None) -> dict | None:
    if not token:
        return None
    con = get_conn()
    row = con.execute("""
        SELECT u.*, s.expires_at FROM sessions s
        JOIN users u ON u.id = s.user_id
        WHERE s.token = ?
    """, (token,)).fetchone()
    if not row:
        con.close()
        return None
    if row["expires_at"] and row["expires_at"] < int(time.time()):
        con.execute("DELETE FROM sessions WHERE token = ?", (token,))
        con.commit()
        con.close()
        return None
    con.execute("UPDATE sessions SET last_used_at = CURRENT_TIMESTAMP WHERE token = ?", (token,))
    con.commit()
    con.close()
    return {
        "id": row["id"], "email": row["email"], "display_name": row["display_name"],
        "fleet_id": row["fleet_id"], "phone": row["phone"], "organization": row["organization"],
        "country": row["country"], "created_at": row["created_at"],
    }


def delete_session(token: str):
    con = get_conn()
    con.execute("DELETE FROM sessions WHERE token = ?", (token,))
    con.commit()
    con.close()


def update_profile(user_id: str, *, display_name: str | None = None, phone: str | None = None,
                   organization: str | None = None, country: str | None = None) -> dict:
    con = get_conn()
    fields, vals = [], []
    for k, v in [("display_name", display_name), ("phone", phone),
                 ("organization", organization), ("country", country)]:
        if v is not None:
            fields.append(f"{k} = ?")
            vals.append(v)
    if fields:
        vals.append(user_id)
        con.execute(f"UPDATE users SET {', '.join(fields)} WHERE id = ?", vals)
        con.commit()
    row = con.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    con.close()
    return dict(row) if row else {}
