"""
LogIQ — Fleet report + anomaly detection (v2 with expanded features).

Reads flights.csv, runs Isolation Forest separately on real vs simulation flights,
and writes a static HTML report with anomaly badges, KPIs, and per-flight detail
links.
"""
from __future__ import annotations

from pathlib import Path
import sys
import os

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler


# Features that work for BOTH dataflash and telemetry
COMMON_FEATURES = [
    "duration_s", "mode_changes", "error_count",
    "alt_m_max", "alt_m_p95",
    "gps_hdop_max", "gps_nsats_min",
    "vibe_x_p95", "vibe_y_p95", "vibe_z_p95",
    "clip_events_total",
    "rcout_motor_mean_std",
    "ekf_pos_var_p95", "ekf_mag_var_p95", "ekf_vel_var_p95",
]

# Features only present in DataFlash logs
DATAFLASH_FEATURES = [
    "roll_err_deg_p95", "pitch_err_deg_p95", "yaw_err_deg_p95",
    "esc_rpm_cv", "esc_rpm_range_pct", "esc_worst_motor_dev_pct",
    "esc_curr_cv", "esc_temp_max",
    "imu_fft_peak1_mag", "imu_fft_peak2_mag",
]


def fit_anomaly_model(df: pd.DataFrame, features: list[str]) -> tuple[pd.Series, pd.Series]:
    """Return (scores, flags) for the given dataframe slice."""
    feats_avail = [f for f in features if f in df.columns]
    if not feats_avail or len(df) < 4:
        return pd.Series([np.nan] * len(df), index=df.index), pd.Series([False] * len(df), index=df.index)
    X = df[feats_avail].copy()
    X_imp = SimpleImputer(strategy="median").fit_transform(X)
    X_scaled = StandardScaler().fit_transform(X_imp)
    iforest = IsolationForest(n_estimators=200, contamination="auto", random_state=42)
    iforest.fit(X_scaled)
    scores = -iforest.decision_function(X_scaled)  # higher = more anomalous
    flags = iforest.predict(X_scaled) == -1
    return pd.Series(scores, index=df.index), pd.Series(flags, index=df.index)


def explain_anomaly(row: pd.Series) -> list[str]:
    reasons: list[str] = []
    if row.get("vibe_z_p95") and row["vibe_z_p95"] > 30:
        reasons.append(f"VIBE Z p95={row['vibe_z_p95']:.1f} (>30 = danger)")
    elif row.get("vibe_z_p95") and row["vibe_z_p95"] > 15:
        reasons.append(f"VIBE Z p95={row['vibe_z_p95']:.1f} (>15 = warn)")
    if row.get("vibe_y_p95") and row["vibe_y_p95"] > 20:
        reasons.append(f"VIBE Y p95={row['vibe_y_p95']:.1f}")
    if row.get("clip_events_total", 0) and row["clip_events_total"] > 100:
        reasons.append(f"IMU clipping={int(row['clip_events_total'])} events (saturation)")
    if row.get("roll_err_deg_p95") and row["roll_err_deg_p95"] > 10:
        reasons.append(f"Roll tracking err p95={row['roll_err_deg_p95']:.1f}° (control failure)")
    elif row.get("roll_err_deg_p95") and row["roll_err_deg_p95"] > 5:
        reasons.append(f"Roll tracking err p95={row['roll_err_deg_p95']:.1f}° (poor tune)")
    if row.get("pitch_err_deg_p95") and row["pitch_err_deg_p95"] > 10:
        reasons.append(f"Pitch tracking err p95={row['pitch_err_deg_p95']:.1f}°")
    if row.get("gps_hdop_max") and row["gps_hdop_max"] > 3:
        reasons.append(f"GPS HDOP max={row['gps_hdop_max']:.1f} (poor GPS)")
    if row.get("gps_nsats_min") is not None and row["gps_nsats_min"] < 6 and row.get("gps_hdop_max", 0) < 99:
        reasons.append(f"GPS sats={int(row['gps_nsats_min'])} (loss-of-fix risk)")
    if row.get("esc_rpm_range_pct") and row["esc_rpm_range_pct"] > 10:
        wm = row.get("esc_worst_motor")
        dv = row.get("esc_worst_motor_dev_pct", 0)
        reasons.append(f"ESC RPM imbalance={row['esc_rpm_range_pct']:.1f}% (motor {wm} off by {dv:.1f}%)")
    if row.get("esc_temp_max") and row["esc_temp_max"] > 80:
        reasons.append(f"ESC max temp={row['esc_temp_max']:.0f}°C (hot)")
    if row.get("ekf_mag_var_p95") and row["ekf_mag_var_p95"] > 0.5:
        reasons.append(f"EKF mag variance={row['ekf_mag_var_p95']:.2f} (compass divergence)")
    if row.get("error_count", 0) and row["error_count"] > 0:
        reasons.append(f"{int(row['error_count'])} ERR messages")
    return reasons


def run(csv_in: str, report_html: str) -> None:
    df = pd.read_csv(csv_in)
    print(f"Loaded {len(df)} log files")

    ok = df["parse_error"].isna()
    print(f"  parseable: {ok.sum()}, errored: {(~ok).sum()}")
    df = df[ok].copy().reset_index(drop=True)

    # Split by format
    if "format" not in df.columns:
        df["format"] = "dataflash"
    is_sim = df.get("is_simulation", False).fillna(False).astype(bool)
    is_df_real = (df["format"] == "dataflash") & ~is_sim
    is_tlog = df["format"] == "telemetry"

    print(f"  dataflash real: {is_df_real.sum()}")
    print(f"  dataflash sim:  {is_sim.sum()}")
    print(f"  telemetry:      {is_tlog.sum()}")

    df["anomaly_score"] = np.nan
    df["is_anomaly"] = False

    # Fit separate models per group (so simulation doesn't contaminate real anomaly thresholds)
    for label, mask, features in (
        ("dataflash_real", is_df_real, COMMON_FEATURES + DATAFLASH_FEATURES),
        ("telemetry",     is_tlog,    COMMON_FEATURES),
    ):
        if mask.sum() >= 4:
            scores, flags = fit_anomaly_model(df[mask], features)
            df.loc[mask, "anomaly_score"] = scores.values
            df.loc[mask, "is_anomaly"] = flags.values
            print(f"  trained model on {mask.sum()} {label} flights, flagged {flags.sum()}")
        else:
            print(f"  skipping {label} model: only {mask.sum()} flights")

    # Pretty table for stdout
    show = ["file", "format", "is_simulation", "duration_s", "vibe_z_p95",
            "clip_events_total", "roll_err_deg_p95", "pitch_err_deg_p95",
            "esc_rpm_range_pct", "anomaly_score", "is_anomaly"]
    show = [c for c in show if c in df.columns]
    print("\nTop 10 most anomalous flights overall:")
    with pd.option_context("display.max_rows", 30, "display.width", 200):
        print(df.sort_values("anomaly_score", ascending=False).head(10)[show].to_string(index=False))

    # Aggregate stats
    by_fmt = df.groupby("format").agg(
        flights=("file", "count"),
        total_duration_h=("duration_s", lambda s: round(s.fillna(0).sum() / 3600, 1)),
        anomalies=("is_anomaly", "sum"),
    )
    print("\nFleet totals by format:")
    print(by_fmt.to_string())

    # ---- HTML report ----
    df_sorted = df.sort_values("anomaly_score", ascending=False, na_position="last")

    cols = ["file", "format", "mtime", "duration_s",
            "vibe_z_p95", "clip_events_total",
            "roll_err_deg_p95", "pitch_err_deg_p95",
            "esc_rpm_range_pct", "esc_temp_max",
            "ekf_mag_var_p95", "gps_hdop_max", "gps_nsats_min",
            "error_count", "anomaly_score", "is_anomaly"]
    cols = [c for c in cols if c in df.columns]

    html = ["""<!DOCTYPE html><html><head><meta charset='utf-8'>
<title>LogIQ — Fleet Report</title>
<style>
body{font-family:system-ui,Segoe UI,sans-serif;margin:24px;color:#222;}
h1{color:#0a3;} h2{margin-top:32px;border-bottom:1px solid #ddd;padding-bottom:4px;}
.summary{display:flex;gap:20px;margin:16px 0;}
.card{background:#f6f6f6;border-radius:8px;padding:12px 18px;}
.card .v{font-size:24px;font-weight:600;color:#0a3;}
.card .l{font-size:11px;color:#666;text-transform:uppercase;}
table{border-collapse:collapse;margin:12px 0;width:100%;font-size:12px;}
th,td{border:1px solid #ddd;padding:5px 7px;text-align:left;}
th{background:#f6f6f6;position:sticky;top:0;}
tr.anom{background:#fff3cd;}
tr.crit{background:#fcd;}
.pill{display:inline-block;padding:2px 8px;border-radius:10px;font-size:11px;}
.sim{background:#e0e0e0;color:#444;}
.real{background:#d0f0d0;color:#060;}
.bad{background:#fcd;color:#900;}
.tlog{background:#ddeeff;color:#024;}
.df{background:#ffeedd;color:#640;}
ul.reasons{margin:4px 0;padding-left:18px;}
ul.reasons li{font-size:12px;}
</style></head><body>"""]
    html.append("<h1>🚁 LogIQ — Fleet Analytics Report</h1>")
    html.append(f"<p>Source: <code>{csv_in}</code></p>")

    n_anom = int(df['is_anomaly'].sum())
    total_dur = df['duration_s'].fillna(0).sum() / 3600
    html.append("<div class='summary'>")
    html.append(f"<div class='card'><div class='l'>Total flights</div><div class='v'>{len(df)}</div></div>")
    html.append(f"<div class='card'><div class='l'>Total flight-hours</div><div class='v'>{total_dur:.1f}</div></div>")
    html.append(f"<div class='card'><div class='l'>Anomalies flagged</div><div class='v'>{n_anom}</div></div>")
    html.append(f"<div class='card'><div class='l'>DataFlash logs</div><div class='v'>{(df['format']=='dataflash').sum()}</div></div>")
    html.append(f"<div class='card'><div class='l'>Telemetry logs</div><div class='v'>{(df['format']=='telemetry').sum()}</div></div>")
    html.append("</div>")

    # Top anomalies with reasons
    html.append("<h2>🚨 Top anomalies with diagnostics</h2><ul class='reasons'>")
    for _, r in df_sorted[df_sorted["is_anomaly"]].head(15).iterrows():
        reasons = explain_anomaly(r)
        if not reasons:
            reasons = ["multivariate outlier — model picked up an unusual combination"]
        html.append(f"<li><b>{r['file']}</b> [{r.get('format')}, {r.get('duration_s', '?')}s] — " + "; ".join(reasons) + "</li>")
    html.append("</ul>")

    # Full table
    html.append("<h2>All flights (sorted by anomaly score)</h2>")
    html.append("<table><thead><tr>")
    for c in cols: html.append(f"<th>{c}</th>")
    html.append("</tr></thead><tbody>")
    for _, r in df_sorted.iterrows():
        score = r.get("anomaly_score") or 0
        cls = "crit" if score > 0.15 else ("anom" if r.get("is_anomaly") else "")
        html.append(f"<tr class='{cls}'>")
        for c in cols:
            v = r.get(c)
            if c == "format":
                p = "df" if v == "dataflash" else "tlog"
                v = f"<span class='pill {p}'>{v}</span>"
            elif c == "is_anomaly":
                if v:
                    v = "<span class='pill bad'>ANOMALY</span>"
                else:
                    v = ""
            elif isinstance(v, float):
                if pd.isna(v): v = ""
                else: v = f"{v:.2f}"
            html.append(f"<td>{v if v is not None else ''}</td>")
        html.append("</tr>")
    html.append("</tbody></table>")
    html.append("</body></html>")

    Path(report_html).write_text("".join(html), encoding="utf-8")
    print(f"\nWrote report -> {report_html}")


if __name__ == "__main__":
    csv_in = sys.argv[1] if len(sys.argv) > 1 else r"C:\Users\zasif bin islam\Desktop\LogIQ\data\parquet\flights.csv"
    html_out = sys.argv[2] if len(sys.argv) > 2 else r"C:\Users\zasif bin islam\Desktop\LogIQ\reports\fleet_report.html"
    run(csv_in, html_out)
