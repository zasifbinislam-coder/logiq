"""
LogIQ — User drone hardware profiles.

A drone-profile is a named build with attached components. Lives separately
from the auto-detected airframe buckets (those come from Mission Planner
folder structure).

Tables:
  user_airframes  — user-named drone builds
  user_components — components attached to a build
"""
from __future__ import annotations

import json
import uuid

from logiq.db import get_conn
from logiq.component_db import get_by_id


SCHEMA_EXTRA = """
CREATE TABLE IF NOT EXISTS user_airframes (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  name TEXT NOT NULL,
  description TEXT,
  frame_class TEXT,           -- quad / hex / octo / plane / vtol
  frame_size_mm INTEGER,
  motor_count INTEGER DEFAULT 4,
  auw_g REAL,                 -- all-up weight in grams
  notes TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_user_airframes_user ON user_airframes(user_id);

CREATE TABLE IF NOT EXISTS user_components (
  id TEXT PRIMARY KEY,
  airframe_id TEXT NOT NULL REFERENCES user_airframes(id) ON DELETE CASCADE,
  type TEXT NOT NULL,         -- motor, esc, prop, battery, fc
  catalog_id TEXT,            -- reference into component_db.CATALOG
  custom_name TEXT,           -- user can free-form
  quantity INTEGER DEFAULT 1,
  specs_json TEXT,            -- frozen snapshot of catalog spec at add time
  notes TEXT,
  added_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_user_components_airframe ON user_components(airframe_id);
"""


def init():
    con = get_conn()
    con.executescript(SCHEMA_EXTRA)
    con.commit()
    con.close()


def create_airframe(user_id: str, *, name: str, description: str = "",
                    frame_class: str = "quad", frame_size_mm: int | None = None,
                    motor_count: int = 4, auw_g: float | None = None,
                    notes: str = "") -> dict:
    init()
    aid = str(uuid.uuid4())
    con = get_conn()
    con.execute(
        """INSERT INTO user_airframes (id, user_id, name, description, frame_class, frame_size_mm, motor_count, auw_g, notes)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (aid, user_id, name, description or None, frame_class, frame_size_mm, motor_count, auw_g, notes or None),
    )
    con.commit()
    con.close()
    return get_airframe(aid)


def list_airframes(user_id: str) -> list[dict]:
    init()
    con = get_conn()
    rows = con.execute("SELECT * FROM user_airframes WHERE user_id = ? ORDER BY created_at DESC", (user_id,)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["components"] = list_components(d["id"])
        out.append(d)
    con.close()
    return out


def get_airframe(airframe_id: str) -> dict | None:
    con = get_conn()
    r = con.execute("SELECT * FROM user_airframes WHERE id = ?", (airframe_id,)).fetchone()
    con.close()
    if not r:
        return None
    d = dict(r)
    d["components"] = list_components(airframe_id)
    return d


def update_airframe(airframe_id: str, **fields) -> dict | None:
    if not fields:
        return get_airframe(airframe_id)
    allowed = {"name", "description", "frame_class", "frame_size_mm", "motor_count", "auw_g", "notes"}
    sets, vals = [], []
    for k, v in fields.items():
        if k in allowed and v is not None:
            sets.append(f"{k} = ?")
            vals.append(v)
    if not sets:
        return get_airframe(airframe_id)
    vals.append(airframe_id)
    con = get_conn()
    con.execute(f"UPDATE user_airframes SET {', '.join(sets)} WHERE id = ?", vals)
    con.commit()
    con.close()
    return get_airframe(airframe_id)


def delete_airframe(airframe_id: str):
    con = get_conn()
    con.execute("DELETE FROM user_components WHERE airframe_id = ?", (airframe_id,))
    con.execute("DELETE FROM user_airframes WHERE id = ?", (airframe_id,))
    con.commit()
    con.close()


def add_component(airframe_id: str, *, type: str, catalog_id: str | None = None,
                  custom_name: str = "", quantity: int = 1, notes: str = "") -> dict:
    init()
    cid = str(uuid.uuid4())
    specs = None
    if catalog_id:
        c = get_by_id(type, catalog_id)
        if c:
            specs = json.dumps(c)
    con = get_conn()
    con.execute(
        """INSERT INTO user_components (id, airframe_id, type, catalog_id, custom_name, quantity, specs_json, notes)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (cid, airframe_id, type, catalog_id, custom_name or None, quantity, specs, notes or None),
    )
    con.commit()
    con.close()
    return get_component(cid)


def list_components(airframe_id: str) -> list[dict]:
    con = get_conn()
    rows = con.execute("SELECT * FROM user_components WHERE airframe_id = ? ORDER BY type, added_at", (airframe_id,)).fetchall()
    con.close()
    out = []
    for r in rows:
        d = dict(r)
        if d.get("specs_json"):
            try:
                d["specs"] = json.loads(d["specs_json"])
            except Exception:
                d["specs"] = None
        out.append(d)
    return out


def get_component(component_id: str) -> dict | None:
    con = get_conn()
    r = con.execute("SELECT * FROM user_components WHERE id = ?", (component_id,)).fetchone()
    con.close()
    if not r:
        return None
    d = dict(r)
    if d.get("specs_json"):
        try:
            d["specs"] = json.loads(d["specs_json"])
        except Exception:
            d["specs"] = None
    return d


def delete_component(component_id: str):
    con = get_conn()
    con.execute("DELETE FROM user_components WHERE id = ?", (component_id,))
    con.commit()
    con.close()
