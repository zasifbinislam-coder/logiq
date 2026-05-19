"""
LogIQ — Predictive maintenance (cross-flight trend detection).

For each airframe class, tracks the rolling mean of safety-critical metrics
across consecutive flights and flags when a signal is drifting in a bad
direction (e.g. vibration creeping up, motor RPM diverging, battery sag
increasing). These are the early warnings that turn LogIQ from a forensic
tool into a predictive one.

Outputs:
  * Per-bucket trend HTML (reports/predictive_<bucket>.html)
  * Top-level summary with alerts
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

from logiq.db import get_conn, DB_PATH


METRICS = [
    ("vibe_z_p95",        "Vibration Z (m/s² p95)",    "max",  15,   30,    "↑"),
    ("vibe_y_p95",        "Vibration Y (m/s² p95)",    "max",  15,   30,    "↑"),
    ("clip_events_total", "IMU clip events",            "sum", 100, 1000,    "↑"),
    ("roll_err_deg_p95",  "Roll tracking err (deg)",   "max",   5,   15,    "↑"),
    ("pitch_err_deg_p95", "Pitch tracking err (deg)",  "max",   5,   15,    "↑"),
    ("ekf_mag_var_p95",   "EKF compass variance",      "max", 0.5,  1.5,    "↑"),
    ("gps_hdop_max",      "GPS HDOP max",              "max", 2.0,  3.0,    "↑"),
    ("volt_min",          "Battery voltage min (V)",   "min",  None,None,   "↓"),
    ("esc_rpm_range_pct", "ESC RPM imbalance (%)",     "max",   5,  10,     "↑"),
]


def load_flights_with_features() -> pd.DataFrame:
    con = get_conn()
    rows = con.execute("""
        SELECT f.id, f.file_name, f.flown_at, f.duration_s, f.is_simulation, f.parse_error,
               af.bucket, feat.data
        FROM flights f
        LEFT JOIN airframes af ON af.id = f.airframe_id
        LEFT JOIN features feat ON feat.flight_id = f.id
        WHERE f.parse_error IS NULL AND f.flown_at IS NOT NULL
    """).fetchall()
    con.close()
    out = []
    for r in rows:
        d = dict(r)
        feat = json.loads(d.pop("data")) if d.get("data") else {}
        d.update(feat)
        out.append(d)
    df = pd.DataFrame(out)
    df["flown_at"] = pd.to_datetime(df["flown_at"], errors="coerce")
    return df


def detect_drift(df: pd.DataFrame, metric: str, direction: str, window: int = 5) -> dict:
    """For a single airframe-class series ordered by time, return drift signal."""
    if metric not in df.columns:
        return {"available": False}
    s = pd.to_numeric(df[metric], errors="coerce").dropna()
    if len(s) < window * 2:
        return {"available": False, "samples": len(s)}

    # baseline = first half, current = last `window` flights
    base = s.iloc[: max(window, len(s) // 2)]
    cur = s.iloc[-window:]
    base_mean, base_std = base.mean(), base.std()
    cur_mean = cur.mean()

    if direction == "↑":
        # bad if cur_mean > base_mean + 1*sigma
        delta = cur_mean - base_mean
        z = delta / base_std if base_std > 1e-6 else 0
        is_drift = z > 1.0 and cur_mean > base_mean * 1.5
    else:
        delta = base_mean - cur_mean
        z = delta / base_std if base_std > 1e-6 else 0
        is_drift = z > 1.0 and cur_mean < base_mean * 0.8

    return {
        "available": True,
        "samples": len(s),
        "baseline_mean": round(float(base_mean), 4),
        "current_mean": round(float(cur_mean), 4),
        "delta": round(float(delta), 4),
        "z_score": round(float(z), 2),
        "is_drift": bool(is_drift),
    }


def run() -> dict:
    df = load_flights_with_features()
    df = df[~df["is_simulation"].fillna(0).astype(bool)].copy()
    print(f"Loaded {len(df)} non-sim flights")
    df = df.sort_values("flown_at")

    summary = {}
    alerts = []

    for bucket, sub in df.groupby("bucket"):
        if len(sub) < 10:
            continue
        bucket_results = {}
        for metric, label, agg, warn, danger, direction in METRICS:
            r = detect_drift(sub, metric, direction)
            bucket_results[metric] = r
            if r.get("is_drift"):
                alerts.append({
                    "bucket": bucket,
                    "metric": metric,
                    "label": label,
                    "baseline": r["baseline_mean"],
                    "current": r["current_mean"],
                    "delta": r["delta"],
                    "z_score": r["z_score"],
                    "direction": direction,
                })
        summary[bucket] = {
            "flights": len(sub),
            "first": str(sub["flown_at"].min()),
            "last": str(sub["flown_at"].max()),
            "drifts": bucket_results,
        }

    print("\n=== Predictive maintenance alerts ===")
    if not alerts:
        print("(No significant drift detected)")
    for a in alerts:
        print(f"  [{a['bucket']}] {a['label']}: {a['baseline']} → {a['current']} (z={a['z_score']}, dir={a['direction']})")

    # Write per-bucket HTML report with sparklines
    reports = Path(r"C:\Users\zasif bin islam\Desktop\LogIQ\reports")
    reports.mkdir(parents=True, exist_ok=True)

    html = ["""<!DOCTYPE html><html><head><meta charset='utf-8'>
<title>LogIQ — Predictive Maintenance</title>
<script src='https://cdn.plot.ly/plotly-2.27.0.min.js'></script>
<style>
body{font-family:system-ui,Segoe UI,sans-serif;margin:24px;color:#222;background:#fafafa;}
h1{color:#0a3;} h2{margin-top:32px;border-bottom:1px solid #ddd;padding-bottom:4px;}
.alerts{background:#fff8e0;border-left:4px solid #f80;padding:12px 16px;margin:14px 0;border-radius:4px;}
.alerts h3{margin:0 0 8px;color:#a40;}
.alerts li{margin:3px 0;}
.bucket{background:white;border-radius:8px;padding:14px 18px;margin:14px 0;box-shadow:0 1px 3px rgba(0,0,0,0.05);}
.kpi{display:inline-block;margin:4px 8px 4px 0;}
.kpi b{font-size:18px;color:#0a3;}
.metric{display:grid;grid-template-columns:240px 80px 80px 80px 60px 90px;gap:8px;padding:5px 0;border-top:1px solid #f0f0f0;align-items:center;font-size:13px;}
.metric.drift{background:#ffe8d6;}
.metric .label{font-weight:500;}
.metric .num{font-family:monospace;text-align:right;}
.metric .badge{padding:1px 8px;border-radius:8px;font-size:11px;text-align:center;}
.metric .badge.ok{background:#d0f0d0;color:#060;}
.metric .badge.drift{background:#fcc;color:#900;}
</style></head><body>
<h1>🔧 LogIQ — Predictive Maintenance</h1>
<p>Cross-flight drift analysis per airframe class. Baseline = first half of fleet history; current = last 5 flights.</p>
"""]
    if alerts:
        html.append("<div class='alerts'><h3>🚨 Active drift alerts</h3><ul>")
        for a in alerts:
            html.append(f"<li><b>{a['bucket']}</b> — {a['label']}: <code>{a['baseline']}</code> → <code>{a['current']}</code> (z={a['z_score']}, {a['direction']})</li>")
        html.append("</ul></div>")
    else:
        html.append("<div class='alerts' style='border-color:#0a3;background:#e0f5e0;'><h3 style='color:#060;'>✓ No significant drift detected</h3><p>Fleet is operating within historical norms.</p></div>")

    for bucket, b in summary.items():
        html.append(f"<div class='bucket'><h2>{bucket}</h2>")
        html.append(f"<div class='kpi'>Flights: <b>{b['flights']}</b></div>")
        html.append(f"<div class='kpi'>First: <b>{b['first'][:10]}</b></div>")
        html.append(f"<div class='kpi'>Last: <b>{b['last'][:10]}</b></div>")
        html.append("<div class='metric' style='font-weight:600;background:#f8f8f8;'>")
        for h in ("Metric", "Baseline", "Current", "Δ", "z", "Status"):
            html.append(f"<div>{h}</div>")
        html.append("</div>")
        for metric, label, agg, warn, danger, direction in METRICS:
            r = b["drifts"].get(metric, {})
            if not r.get("available"):
                continue
            cls = "drift" if r.get("is_drift") else ""
            badge = "<span class='badge drift'>DRIFT</span>" if r.get("is_drift") else "<span class='badge ok'>ok</span>"
            html.append(f"<div class='metric {cls}'>")
            html.append(f"<div class='label'>{label} {direction}</div>")
            html.append(f"<div class='num'>{r['baseline_mean']}</div>")
            html.append(f"<div class='num'>{r['current_mean']}</div>")
            html.append(f"<div class='num'>{r['delta']:+}</div>")
            html.append(f"<div class='num'>{r['z_score']}</div>")
            html.append(f"<div>{badge}</div>")
            html.append("</div>")
        html.append("</div>")
    html.append("</body></html>")
    out_path = reports / "predictive.html"
    out_path.write_text("".join(html), encoding="utf-8")
    print(f"\nWrote {out_path}")

    return {"summary": summary, "alerts": alerts}


if __name__ == "__main__":
    out = run()
    print()
    print(f"Total drift alerts: {len(out['alerts'])}")
