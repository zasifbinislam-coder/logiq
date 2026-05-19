"""
LogIQ — Labeled dataset workflow.

Adds a labels table for supervised training. Provides functions to:
  * label a flight {ok, bad_tune, vibration, crash, gps_loss, hard_landing, mech_fail, unknown}
  * export training data joining features + label as a CSV
  * stats over what's labeled
"""
from __future__ import annotations

import csv
import json
import sys
import uuid
from pathlib import Path

from logiq.db import get_conn, DB_PATH


LABELS = [
    ("ok",            "Flight was clean and normal"),
    ("bad_tune",      "Drone was tuned poorly (sluggish, oscillating)"),
    ("vibration",     "Excessive vibration during flight"),
    ("crash",         "Drone crashed or had severe failure"),
    ("hard_landing",  "Hard landing but not a crash"),
    ("gps_loss",      "GPS issues during flight"),
    ("compass_fail",  "Compass / EKF divergence"),
    ("motor_fail",    "Motor or ESC failure"),
    ("prop_strike",   "Propeller hit something"),
    ("bench_test",    "Not an actual flight (bench test only)"),
    ("unknown",       "Operator not sure"),
]


SCHEMA_EXTRA = """
CREATE TABLE IF NOT EXISTS labels (
  flight_id TEXT PRIMARY KEY REFERENCES flights(id),
  label TEXT NOT NULL,
  notes TEXT,
  labeled_by TEXT,
  labeled_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_labels_label ON labels(label);
"""


def init() -> None:
    con = get_conn()
    con.executescript(SCHEMA_EXTRA)
    con.commit()
    con.close()


def set_label(flight_id: str, label: str, notes: str = "", labeled_by: str = "operator") -> None:
    if label not in {k for k, _ in LABELS}:
        raise ValueError(f"unknown label: {label}")
    con = get_conn()
    con.execute(
        """INSERT INTO labels (flight_id, label, notes, labeled_by) VALUES (?, ?, ?, ?)
           ON CONFLICT(flight_id) DO UPDATE SET label=excluded.label, notes=excluded.notes,
                                                labeled_by=excluded.labeled_by, labeled_at=CURRENT_TIMESTAMP""",
        (flight_id, label, notes, labeled_by),
    )
    con.commit()
    con.close()


def get_label(flight_id: str) -> dict | None:
    con = get_conn()
    r = con.execute("SELECT * FROM labels WHERE flight_id = ?", (flight_id,)).fetchone()
    con.close()
    return dict(r) if r else None


def stats() -> dict:
    con = get_conn()
    rows = con.execute("SELECT label, COUNT(*) AS n FROM labels GROUP BY label ORDER BY n DESC").fetchall()
    total = con.execute("SELECT COUNT(*) AS n FROM flights WHERE parse_error IS NULL").fetchone()["n"]
    labeled = con.execute("SELECT COUNT(*) AS n FROM labels").fetchone()["n"]
    con.close()
    return {
        "total_flights": total,
        "labeled": labeled,
        "labeled_pct": round(100 * labeled / max(total, 1), 1),
        "by_label": [dict(r) for r in rows],
    }


def export_training_csv(out_path: str) -> int:
    """Export labeled flights with their features as a flat CSV for ML training."""
    con = get_conn()
    rows = con.execute("""
        SELECT f.id, f.file_name, l.label, l.notes, feat.data
        FROM labels l
        JOIN flights f ON f.id = l.flight_id
        LEFT JOIN features feat ON feat.flight_id = f.id
    """).fetchall()
    con.close()

    # union of feature keys
    parsed = []
    keys = set()
    for r in rows:
        d = json.loads(r["data"]) if r["data"] else {}
        keys.update(d.keys())
        parsed.append((dict(r), d))
    keys_sorted = sorted(keys)

    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["flight_id", "file_name", "label", "notes"] + keys_sorted)
        for meta, feats in parsed:
            row = [meta["id"], meta["file_name"], meta["label"], meta["notes"] or ""]
            row += [feats.get(k, "") for k in keys_sorted]
            w.writerow(row)

    return len(parsed)


def auto_seed_labels() -> int:
    """Pre-label obvious flights from heuristics, so the user starts with seed data."""
    init()
    con = get_conn()
    seeded = 0

    # corrupted log (negative duration)
    for r in con.execute("SELECT id FROM flights WHERE duration_s < 0").fetchall():
        con.execute(
            "INSERT OR IGNORE INTO labels (flight_id, label, notes, labeled_by) VALUES (?, ?, ?, ?)",
            (r["id"], "unknown", "auto-seeded: negative duration (corrupt log)", "auto-seed"),
        )
        seeded += 1

    # very high clip events → vibration label
    rows = con.execute("""
        SELECT f.id, feat.data FROM flights f
        JOIN features feat ON feat.flight_id = f.id
        WHERE f.parse_error IS NULL
    """).fetchall()
    for r in rows:
        d = json.loads(r["data"]) if r["data"] else {}
        clip = d.get("clip_events_total") or 0
        roll_err = d.get("roll_err_deg_p95") or 0
        vibe_z = d.get("vibe_z_p95") or 0
        if clip > 30000 and roll_err > 30:
            con.execute("INSERT OR IGNORE INTO labels (flight_id, label, notes, labeled_by) VALUES (?, ?, ?, ?)",
                        (r["id"], "crash", f"auto-seeded: {int(clip)} clips, roll err {roll_err:.0f}°", "auto-seed"))
            seeded += 1
        elif vibe_z > 30:
            con.execute("INSERT OR IGNORE INTO labels (flight_id, label, notes, labeled_by) VALUES (?, ?, ?, ?)",
                        (r["id"], "vibration", f"auto-seeded: VIBE Z = {vibe_z:.1f}", "auto-seed"))
            seeded += 1

    con.commit()
    con.close()
    return seeded


if __name__ == "__main__":
    init()
    if len(sys.argv) > 1 and sys.argv[1] == "seed":
        n = auto_seed_labels()
        print(f"Auto-seeded {n} labels")
    if len(sys.argv) > 1 and sys.argv[1] == "export":
        out = sys.argv[2] if len(sys.argv) > 2 else r"C:\Users\zasif bin islam\Desktop\LogIQ\data\parquet\labeled.csv"
        n = export_training_csv(out)
        print(f"Exported {n} labeled rows -> {out}")
    print(json.dumps(stats(), indent=2))
