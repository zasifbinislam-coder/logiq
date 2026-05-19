"""
LogIQ — Maintenance log.

Closes the inspection loop: operator records what was fixed after each issue.
Helps validate the predictive model (vibration anomaly + maintenance entry =
confirmed positive).
"""
from __future__ import annotations

import json
import sys
import uuid
from typing import Any

from logiq.db import get_conn


SCHEMA_EXTRA = """
CREATE TABLE IF NOT EXISTS maintenance (
  id TEXT PRIMARY KEY,
  flight_id TEXT REFERENCES flights(id),
  airframe_id TEXT REFERENCES airframes(id),
  type TEXT NOT NULL,            -- prop_replaced, motor_replaced, frame_fix,
                                 -- pid_tuned, compass_calibrated, esc_replaced,
                                 -- battery_replaced, other
  description TEXT,
  cost_bdt REAL,
  performed_at TEXT DEFAULT CURRENT_TIMESTAMP,
  performed_by TEXT
);
CREATE INDEX IF NOT EXISTS idx_maint_flight ON maintenance(flight_id);
CREATE INDEX IF NOT EXISTS idx_maint_airframe ON maintenance(airframe_id);
"""


MAINT_TYPES = [
    ("prop_replaced",        "Propeller replaced"),
    ("prop_balanced",        "Propeller balanced"),
    ("motor_replaced",       "Motor replaced"),
    ("motor_bearing",        "Motor bearing serviced"),
    ("esc_replaced",         "ESC replaced"),
    ("frame_fix",            "Frame repaired"),
    ("frame_screws",         "Frame screws tightened"),
    ("pid_tuned",            "PID gains re-tuned"),
    ("compass_calibrated",   "Compass re-calibrated"),
    ("battery_replaced",     "Battery replaced"),
    ("gps_replaced",         "GPS module replaced / moved"),
    ("firmware_updated",     "Firmware updated"),
    ("other",                "Other"),
]


def init():
    con = get_conn()
    con.executescript(SCHEMA_EXTRA)
    con.commit()
    con.close()


def add_entry(flight_id: str | None, mtype: str, description: str = "",
              cost_bdt: float | None = None, performed_by: str = "operator") -> str:
    init()
    con = get_conn()
    mid = str(uuid.uuid4())
    af_id = None
    if flight_id:
        r = con.execute("SELECT airframe_id FROM flights WHERE id = ?", (flight_id,)).fetchone()
        if r: af_id = r["airframe_id"]
    con.execute(
        """INSERT INTO maintenance (id, flight_id, airframe_id, type, description, cost_bdt, performed_by)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (mid, flight_id, af_id, mtype, description, cost_bdt, performed_by),
    )
    con.commit()
    con.close()
    return mid


def list_for_flight(flight_id: str) -> list[dict]:
    con = get_conn()
    rows = con.execute("SELECT * FROM maintenance WHERE flight_id = ? ORDER BY performed_at DESC", (flight_id,)).fetchall()
    con.close()
    return [dict(r) for r in rows]


def list_all(limit: int = 100) -> list[dict]:
    con = get_conn()
    rows = con.execute("""
        SELECT m.*, f.file_name, af.bucket
        FROM maintenance m
        LEFT JOIN flights f ON f.id = m.flight_id
        LEFT JOIN airframes af ON af.id = m.airframe_id
        ORDER BY m.performed_at DESC LIMIT ?
    """, (limit,)).fetchall()
    con.close()
    return [dict(r) for r in rows]


def stats() -> dict:
    con = get_conn()
    n_total = con.execute("SELECT COUNT(*) AS n FROM maintenance").fetchone()["n"]
    by_type = con.execute("SELECT type, COUNT(*) AS n FROM maintenance GROUP BY type ORDER BY n DESC").fetchall()
    total_cost = con.execute("SELECT COALESCE(SUM(cost_bdt), 0) AS s FROM maintenance").fetchone()["s"]
    con.close()
    return {
        "total_entries": n_total,
        "total_cost_bdt": total_cost,
        "by_type": [dict(r) for r in by_type],
    }
