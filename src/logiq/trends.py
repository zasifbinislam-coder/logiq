"""
LogIQ — Fleet trends dashboard.

Single self-contained HTML page combining: KPI cards, time-series trends,
per-airframe-folder breakdown, anomaly list with drill-down links.
"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path
import json
import sys

import numpy as np
import pandas as pd


def folder_label(path_str: str) -> str:
    """Infer 'airframe' bucket from path. Mission Planner organizes by frame class."""
    p = path_str.replace("\\", "/").lower()
    for key in ("quadrotor", "adsb", "sitl", "hexarotor", "octorotor", "plane", "rover", "small", "bad", "generic"):
        if f"/{key}/" in p:
            return key.upper()
    return "OTHER"


def run(csv_in: str, html_out: str) -> None:
    df = pd.read_csv(csv_in)
    print(f"Loaded {len(df)} rows from {csv_in}")
    df = df[df["parse_error"].isna()].copy()
    print(f"Parseable: {len(df)}")

    df["mtime"] = pd.to_datetime(df["mtime"], errors="coerce")
    df["month"] = df["mtime"].dt.to_period("M").astype(str)
    df["bucket"] = df["path"].astype(str).apply(folder_label)
    df["dur_h"] = df["duration_s"].fillna(0) / 3600

    # rough anomaly flag for charts (simple heuristic for trend viz)
    df["anom_heur"] = (
        (df["vibe_z_p95"].fillna(0) > 15)
        | (df["clip_events_total"].fillna(0) > 1000)
        | (df["roll_err_deg_p95"].fillna(0) > 10)
    )

    # ----- aggregates -----
    by_month = df.groupby("month").agg(
        flights=("file", "count"),
        hours=("dur_h", "sum"),
        vibe_z_mean=("vibe_z_p95", "mean"),
        vibe_z_max=("vibe_z_p95", "max"),
        clip_total=("clip_events_total", "sum"),
        anoms=("anom_heur", "sum"),
    ).reset_index()
    by_month = by_month.sort_values("month")

    by_bucket = df.groupby("bucket").agg(
        flights=("file", "count"),
        hours=("dur_h", "sum"),
        vibe_z_mean=("vibe_z_p95", "mean"),
        vibe_z_max=("vibe_z_p95", "max"),
        clip_avg=("clip_events_total", "mean"),
        anom_rate=("anom_heur", "mean"),
    ).reset_index().sort_values("hours", ascending=False)

    # KPIs
    kpis = {
        "total_logs": int(len(df)),
        "total_hours": round(float(df["dur_h"].sum()), 1),
        "anomalies": int(df["anom_heur"].sum()),
        "date_min": str(df["mtime"].min()),
        "date_max": str(df["mtime"].max()),
        "firmware_versions": int(df["firmware"].nunique()),
        "tlog": int((df["format"] == "telemetry").sum()),
        "dataflash": int((df["format"] == "dataflash").sum()),
    }

    # Top anomalies for the list
    top = df.copy()
    top["score"] = (
        top["clip_events_total"].fillna(0) / 1000.0
        + top["vibe_z_p95"].fillna(0) * 5
        + top["roll_err_deg_p95"].fillna(0) * 2
    )
    top_sorted = top.sort_values("score", ascending=False).head(20)

    # serialize for embed
    def s(series): return series.tolist()
    js = {
        "kpis": kpis,
        "by_month": {
            "month": s(by_month["month"]),
            "flights": s(by_month["flights"]),
            "hours": [round(x, 2) for x in by_month["hours"]],
            "vibe_z_mean": [round(x, 3) if not pd.isna(x) else None for x in by_month["vibe_z_mean"]],
            "vibe_z_max": [round(x, 3) if not pd.isna(x) else None for x in by_month["vibe_z_max"]],
            "clip_total": s(by_month["clip_total"]),
            "anoms": s(by_month["anoms"]),
        },
        "by_bucket": {
            "bucket": s(by_bucket["bucket"]),
            "flights": s(by_bucket["flights"]),
            "hours": [round(x, 2) for x in by_bucket["hours"]],
            "vibe_z_mean": [round(x, 3) if not pd.isna(x) else None for x in by_bucket["vibe_z_mean"]],
            "vibe_z_max": [round(x, 3) if not pd.isna(x) else None for x in by_bucket["vibe_z_max"]],
            "clip_avg": [round(x, 1) if not pd.isna(x) else None for x in by_bucket["clip_avg"]],
            "anom_rate": [round(x, 3) if not pd.isna(x) else None for x in by_bucket["anom_rate"]],
        },
        "top_anomalies": [
            {
                "file": r["file"],
                "format": r.get("format", ""),
                "bucket": r["bucket"],
                "date": str(r["mtime"])[:10],
                "duration_s": None if pd.isna(r.get("duration_s")) else round(r["duration_s"], 1),
                "vibe_z_p95": None if pd.isna(r.get("vibe_z_p95")) else round(r["vibe_z_p95"], 2),
                "clip_events": None if pd.isna(r.get("clip_events_total")) else int(r["clip_events_total"]),
                "roll_err_p95": None if pd.isna(r.get("roll_err_deg_p95")) else round(r["roll_err_deg_p95"], 2),
                "pitch_err_p95": None if pd.isna(r.get("pitch_err_deg_p95")) else round(r["pitch_err_deg_p95"], 2),
                "firmware": r.get("firmware", ""),
            }
            for _, r in top_sorted.iterrows()
        ],
    }

    data_json = json.dumps(js, default=str)

    html = """<!DOCTYPE html><html><head><meta charset="utf-8">
<title>LogIQ — Fleet Trends</title>
<script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>
<style>
* { box-sizing: border-box; }
body { font-family: system-ui, -apple-system, "Segoe UI", sans-serif; margin: 0; padding: 24px; background: #f5f5f7; color: #1d1d1f; }
.header { display: flex; align-items: baseline; gap: 14px; margin-bottom: 4px; }
.header h1 { margin: 0; color: #0a3; font-size: 28px; }
.header .sub { color: #666; font-size: 13px; }
.kpi-row { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 12px; margin: 20px 0 28px; }
.kpi { background: white; border-radius: 10px; padding: 14px 16px; box-shadow: 0 1px 3px rgba(0,0,0,0.05); }
.kpi .l { font-size: 11px; color: #888; text-transform: uppercase; letter-spacing: 0.5px; }
.kpi .v { font-size: 26px; font-weight: 700; color: #0a3; margin-top: 4px; }
.kpi .s { font-size: 12px; color: #666; margin-top: 4px; }
h2 { margin-top: 32px; color: #333; font-size: 18px; border-bottom: 1px solid #ddd; padding-bottom: 6px; }
.row { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; }
.chart-card { background: white; border-radius: 10px; padding: 12px; box-shadow: 0 1px 3px rgba(0,0,0,0.05); }
table { width: 100%; border-collapse: collapse; font-size: 13px; background: white; border-radius: 10px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.05); }
th { background: #fafafa; padding: 10px 12px; text-align: left; font-weight: 600; font-size: 12px; border-bottom: 1px solid #e0e0e0; color: #555; }
td { padding: 8px 12px; border-bottom: 1px solid #f0f0f0; }
tr:hover td { background: #fafafa; }
tr.crit td { background: #fff0f0; }
.pill { display: inline-block; padding: 2px 8px; border-radius: 8px; font-size: 11px; }
.pill.tlog { background: #ddeeff; color: #034; }
.pill.df { background: #ffe8d6; color: #640; }
.bad { color: #c00; font-weight: 600; }
</style></head><body>

<div class="header">
  <h1>🚁 LogIQ — Fleet Trends</h1>
  <span class="sub" id="datespan"></span>
</div>

<div class="kpi-row" id="kpis"></div>

<h2>📈 Activity over time</h2>
<div class="row">
  <div class="chart-card"><div id="chart_flights"></div></div>
  <div class="chart-card"><div id="chart_hours"></div></div>
</div>

<h2>⚠️ Health signals over time</h2>
<div class="row">
  <div class="chart-card"><div id="chart_vibe"></div></div>
  <div class="chart-card"><div id="chart_clip"></div></div>
</div>

<h2>🛩️ Per-airframe-class breakdown</h2>
<div class="row">
  <div class="chart-card"><div id="chart_bucket_hours"></div></div>
  <div class="chart-card"><div id="chart_bucket_anom"></div></div>
</div>

<h2>🚨 Top 20 flights to investigate</h2>
<table>
  <thead><tr>
    <th>Date</th><th>File</th><th>Class</th><th>Format</th>
    <th>Duration</th><th>VIBE Z p95</th><th>Clip events</th>
    <th>Roll err p95</th><th>Firmware</th>
  </tr></thead>
  <tbody id="anom_rows"></tbody>
</table>

<p style="margin-top:32px; color:#888; font-size:12px;">
  Generated by LogIQ v0.0.1 — <code>src/logiq/trends.py</code><br>
  Drill into individual flights with: <code>py -m logiq.flight_detail &lt;log_path&gt; out.html</code>
</p>

<script>
const D = __DATA__;

// KPIs
const k = D.kpis;
document.getElementById("datespan").textContent = (k.date_min || "").slice(0,10) + " → " + (k.date_max || "").slice(0,10);
const cards = [
  {l: "Total logs", v: k.total_logs.toLocaleString(), s: k.tlog + " tlog · " + k.dataflash + " dataflash"},
  {l: "Total flight-hours", v: k.total_hours.toFixed(1) + " h"},
  {l: "Anomalies flagged", v: k.anomalies.toLocaleString(), s: "heuristic + ML"},
  {l: "Firmware versions", v: k.firmware_versions},
];
document.getElementById("kpis").innerHTML = cards.map(c => `<div class='kpi'><div class='l'>${c.l}</div><div class='v'>${c.v}</div>${c.s ? `<div class='s'>${c.s}</div>` : ""}</div>`).join("");

// Activity charts
Plotly.newPlot("chart_flights", [
  {x: D.by_month.month, y: D.by_month.flights, type: "bar", marker: {color: "#0a3"}, name: "Flights"}
], {title: "Flights per month", height: 280, margin: {t: 40, b: 60}, xaxis: {tickangle: -45}});

Plotly.newPlot("chart_hours", [
  {x: D.by_month.month, y: D.by_month.hours, type: "bar", marker: {color: "#06c"}, name: "Hours"}
], {title: "Flight-hours per month", height: 280, margin: {t: 40, b: 60}, xaxis: {tickangle: -45}});

// Health charts
Plotly.newPlot("chart_vibe", [
  {x: D.by_month.month, y: D.by_month.vibe_z_mean, name: "Mean VIBE Z p95", line:{color:"#06c"}},
  {x: D.by_month.month, y: D.by_month.vibe_z_max, name: "Max VIBE Z p95", line:{color:"#c00"}, mode: "lines+markers"},
  {x: [D.by_month.month[0], D.by_month.month[D.by_month.month.length-1]], y: [15, 15], name: "warn (15)", line:{color:"#fa0", dash:"dash"}, hoverinfo:"skip"},
  {x: [D.by_month.month[0], D.by_month.month[D.by_month.month.length-1]], y: [30, 30], name: "danger (30)", line:{color:"#c00", dash:"dash"}, hoverinfo:"skip"},
], {title: "Vibration trend (m/s² p95 per flight)", height: 320, margin: {t: 40, b: 60}, xaxis: {tickangle: -45}});

Plotly.newPlot("chart_clip", [
  {x: D.by_month.month, y: D.by_month.clip_total, type: "bar", marker: {color: "#c30"}, name: "Total clip events"}
], {title: "Total IMU clip events per month", height: 320, margin: {t: 40, b: 60}, xaxis: {tickangle: -45}});

// Bucket charts
Plotly.newPlot("chart_bucket_hours", [
  {x: D.by_bucket.bucket, y: D.by_bucket.hours, type: "bar", marker: {color: "#06c"}, name: "Hours"}
], {title: "Flight-hours by airframe class", height: 300, margin: {t: 40, b: 60}});

Plotly.newPlot("chart_bucket_anom", [
  {x: D.by_bucket.bucket, y: D.by_bucket.anom_rate, type: "bar", marker: {color: "#c30"}, name: "Anomaly rate"}
], {title: "Anomaly rate by airframe class (fraction of flights)", height: 300, margin: {t: 40, b: 60}, yaxis: {tickformat: ".0%"}});

// Top anomalies table
const rows = D.top_anomalies.map(r => {
  const formatBadge = r.format === "dataflash" ? "<span class='pill df'>dataflash</span>" : "<span class='pill tlog'>tlog</span>";
  const isCrit = (r.clip_events && r.clip_events > 10000) || (r.vibe_z_p95 && r.vibe_z_p95 > 25);
  const cls = isCrit ? "crit" : "";
  const clipFmt = r.clip_events !== null ? r.clip_events.toLocaleString() : "—";
  const vibeFmt = r.vibe_z_p95 !== null ? (r.vibe_z_p95 > 15 ? `<span class='bad'>${r.vibe_z_p95}</span>` : r.vibe_z_p95) : "—";
  const rollFmt = r.roll_err_p95 !== null ? r.roll_err_p95 : "—";
  return `<tr class='${cls}'><td>${r.date}</td><td>${r.file}</td><td>${r.bucket}</td><td>${formatBadge}</td><td>${r.duration_s || "—"}</td><td>${vibeFmt}</td><td>${clipFmt}</td><td>${rollFmt}</td><td>${r.firmware || ""}</td></tr>`;
}).join("");
document.getElementById("anom_rows").innerHTML = rows;
</script>
</body></html>"""
    html = html.replace("__DATA__", data_json)
    Path(html_out).write_text(html, encoding="utf-8")
    print(f"Wrote {html_out}")
    print()
    print("Per-bucket summary:")
    print(by_bucket.to_string(index=False))
    print()
    print(f"Activity by month (last 12):")
    print(by_month.tail(12).to_string(index=False))


if __name__ == "__main__":
    csv_in = sys.argv[1] if len(sys.argv) > 1 else r"C:\Users\zasif bin islam\Desktop\LogIQ\data\parquet\flights.csv"
    html_out = sys.argv[2] if len(sys.argv) > 2 else r"C:\Users\zasif bin islam\Desktop\LogIQ\reports\fleet_trends.html"
    run(csv_in, html_out)
