"""
LogIQ — SQLite schema + load helpers.

Tables:
  fleets       — top-level org/user (single-tenant for MVP)
  airframes    — frame class per fleet (QUADROTOR, ADSB, etc.)
  flights      — one row per uploaded log file
  features     — flat JSON feature blob per flight
  anomalies    — model verdicts per flight (one row per model run)

We keep the schema thin and use JSON columns aggressively. Migrate to typed
Postgres when we have actual customers.
"""
from __future__ import annotations

from pathlib import Path
import json
import os
import sqlite3
import sys
import uuid

# DB_PATH defaults to the workstation install path; override with the
# LOGIQ_DB_PATH env var for tests / alt environments.
DB_PATH = os.environ.get("LOGIQ_DB_PATH", r"C:\Users\zasif bin islam\Desktop\LogIQ\data\logiq.db")


SCHEMA = """
CREATE TABLE IF NOT EXISTS fleets (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  owner_email TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS airframes (
  id TEXT PRIMARY KEY,
  fleet_id TEXT NOT NULL REFERENCES fleets(id),
  bucket TEXT NOT NULL,        -- QUADROTOR, ADSB, etc.
  name TEXT,
  frame_class TEXT,
  prop_size_in REAL,
  mass_kg REAL,
  battery_cells INTEGER,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_airframes_fleet_bucket ON airframes(fleet_id, bucket);

CREATE TABLE IF NOT EXISTS flights (
  id TEXT PRIMARY KEY,
  fleet_id TEXT NOT NULL REFERENCES fleets(id),
  airframe_id TEXT REFERENCES airframes(id),
  file_name TEXT NOT NULL,
  source_path TEXT,
  format TEXT,                 -- dataflash | telemetry
  size_mb REAL,
  flown_at TEXT,
  duration_s REAL,
  firmware TEXT,
  is_simulation INTEGER,
  parse_error TEXT,
  uploaded_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_flights_fleet_date ON flights(fleet_id, flown_at);
CREATE INDEX IF NOT EXISTS idx_flights_airframe ON flights(airframe_id);

CREATE TABLE IF NOT EXISTS features (
  flight_id TEXT PRIMARY KEY REFERENCES flights(id),
  data TEXT NOT NULL           -- JSON blob
);

CREATE TABLE IF NOT EXISTS anomalies (
  id TEXT PRIMARY KEY,
  flight_id TEXT NOT NULL REFERENCES flights(id),
  model TEXT,                  -- iforest_global, iforest_per_airframe, etc.
  score REAL,
  is_anomaly INTEGER,
  reasons TEXT,                -- JSON array of strings
  detected_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_anomalies_flight ON anomalies(flight_id);
"""


def get_conn(db_path: str = DB_PATH) -> sqlite3.Connection:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path)
    con.execute("PRAGMA foreign_keys = ON")
    con.row_factory = sqlite3.Row
    return con


def init_schema(db_path: str = DB_PATH) -> None:
    con = get_conn(db_path)
    con.executescript(SCHEMA)
    con.commit()
    con.close()


def folder_label(path_str: str) -> str:
    p = (path_str or "").replace("\\", "/").lower()
    for key in ("quadrotor", "adsb", "sitl", "hexarotor", "octorotor", "plane", "rover", "small", "bad", "generic"):
        if f"/{key}/" in p:
            return key.upper()
    return "OTHER"


def upsert_fleet(con: sqlite3.Connection, name: str = "Default Fleet", owner_email: str = "zasifbinislam@gmail.com") -> str:
    row = con.execute("SELECT id FROM fleets WHERE name = ?", (name,)).fetchone()
    if row:
        return row["id"]
    fid = str(uuid.uuid4())
    con.execute("INSERT INTO fleets (id, name, owner_email) VALUES (?, ?, ?)", (fid, name, owner_email))
    return fid


def upsert_airframe(con: sqlite3.Connection, fleet_id: str, bucket: str) -> str:
    row = con.execute("SELECT id FROM airframes WHERE fleet_id = ? AND bucket = ?", (fleet_id, bucket)).fetchone()
    if row:
        return row["id"]
    aid = str(uuid.uuid4())
    con.execute("INSERT INTO airframes (id, fleet_id, bucket, name) VALUES (?, ?, ?, ?)", (aid, fleet_id, bucket, bucket))
    return aid


def load_csv(csv_path: str, db_path: str = DB_PATH) -> dict:
    """Migrate flights.csv into the DB."""
    import pandas as pd
    init_schema(db_path)
    df = pd.read_csv(csv_path)
    con = get_conn(db_path)

    fleet_id = upsert_fleet(con)
    inserted, skipped = 0, 0

    # build bucket cache
    bucket_cache: dict[str, str] = {}

    for _, r in df.iterrows():
        path = r.get("path", "") or ""
        bucket = folder_label(path)
        if bucket not in bucket_cache:
            bucket_cache[bucket] = upsert_airframe(con, fleet_id, bucket)
        airframe_id = bucket_cache[bucket]

        fid = str(uuid.uuid4())
        try:
            con.execute(
                """INSERT INTO flights (id, fleet_id, airframe_id, file_name, source_path, format,
                                        size_mb, flown_at, duration_s, firmware, is_simulation, parse_error)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    fid, fleet_id, airframe_id,
                    r.get("file"), path, r.get("format"),
                    r.get("size_mb"),
                    r.get("mtime"),
                    None if pd.isna(r.get("duration_s")) else float(r["duration_s"]),
                    r.get("firmware"),
                    1 if r.get("is_simulation") else 0,
                    r.get("parse_error"),
                ),
            )
            feats = {k: v for k, v in r.items() if not (isinstance(v, float) and pd.isna(v))}
            con.execute("INSERT INTO features (flight_id, data) VALUES (?, ?)",
                        (fid, json.dumps(feats, default=str)))
            inserted += 1
        except Exception as e:
            skipped += 1
            print(f"  skip {r.get('file')}: {e}")

    con.commit()
    summary = {
        "inserted": inserted,
        "skipped": skipped,
        "fleet_id": fleet_id,
        "airframes": dict(bucket_cache),
    }
    con.close()
    return summary


def stats(db_path: str = DB_PATH) -> dict:
    con = get_conn(db_path)
    n_flights = con.execute("SELECT COUNT(*) AS n FROM flights").fetchone()["n"]
    n_feats = con.execute("SELECT COUNT(*) AS n FROM features").fetchone()["n"]
    n_anom = con.execute("SELECT COUNT(*) AS n FROM anomalies").fetchone()["n"]
    by_airframe = con.execute("""
        SELECT a.bucket, COUNT(f.id) AS flights, ROUND(SUM(f.duration_s)/3600.0, 1) AS hours
        FROM airframes a LEFT JOIN flights f ON f.airframe_id = a.id
        GROUP BY a.bucket ORDER BY hours DESC NULLS LAST
    """).fetchall()
    con.close()
    return {
        "flights": n_flights,
        "features": n_feats,
        "anomalies": n_anom,
        "by_airframe": [dict(r) for r in by_airframe],
    }


if __name__ == "__main__":
    csv_in = sys.argv[1] if len(sys.argv) > 1 else r"C:\Users\zasif bin islam\Desktop\LogIQ\data\parquet\flights.csv"
    print(f"Loading {csv_in} into {DB_PATH}")
    s = load_csv(csv_in)
    print(json.dumps(s, indent=2, default=str))
    print()
    print("DB stats:")
    print(json.dumps(stats(), indent=2, default=str))
