"""
LogIQ — Per-airframe anomaly detection.

Trains one IsolationForest per airframe bucket (QUADROTOR, ADSB, etc.) so the
"normal" baseline is calibrated to each platform. A flight is then scored
against its own class — a vibration level that's normal for QUADROTOR may be
catastrophic for SITL.

Writes results into the anomalies table of the SQLite DB.
"""
from __future__ import annotations

import json
import sys
import uuid
from typing import Iterable

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler

from logiq.db import get_conn, DB_PATH


FEATURE_COLS = [
    "duration_s", "mode_changes", "error_count",
    "alt_m_max", "alt_m_p95",
    "gps_hdop_max", "gps_nsats_min",
    "vibe_x_p95", "vibe_y_p95", "vibe_z_p95",
    "clip_events_total",
    "rcout_motor_mean_std",
    "ekf_pos_var_p95", "ekf_mag_var_p95", "ekf_vel_var_p95",
    # dataflash-only (will be NaN for tlog):
    "roll_err_deg_p95", "pitch_err_deg_p95", "yaw_err_deg_p95",
    "esc_rpm_cv", "esc_rpm_range_pct",
]


def explain(row: pd.Series) -> list[str]:
    R: list[str] = []
    if row.get("vibe_z_p95") and row["vibe_z_p95"] > 30:
        R.append(f"VIBE Z p95={row['vibe_z_p95']:.1f} (DANGER >30)")
    elif row.get("vibe_z_p95") and row["vibe_z_p95"] > 15:
        R.append(f"VIBE Z p95={row['vibe_z_p95']:.1f} (warn >15)")
    if row.get("vibe_y_p95") and row["vibe_y_p95"] > 20:
        R.append(f"VIBE Y p95={row['vibe_y_p95']:.1f}")
    if row.get("clip_events_total", 0) and row["clip_events_total"] > 10000:
        R.append(f"IMU clipping={int(row['clip_events_total']):,} (severe saturation)")
    elif row.get("clip_events_total", 0) and row["clip_events_total"] > 100:
        R.append(f"IMU clipping={int(row['clip_events_total']):,} events")
    if row.get("roll_err_deg_p95") and row["roll_err_deg_p95"] > 20:
        R.append(f"Roll tracking err p95={row['roll_err_deg_p95']:.1f}° (CRASH-LEVEL)")
    elif row.get("roll_err_deg_p95") and row["roll_err_deg_p95"] > 5:
        R.append(f"Roll tracking err p95={row['roll_err_deg_p95']:.1f}° (poor tune)")
    if row.get("pitch_err_deg_p95") and row["pitch_err_deg_p95"] > 10:
        R.append(f"Pitch tracking err p95={row['pitch_err_deg_p95']:.1f}°")
    if row.get("gps_hdop_max") and row["gps_hdop_max"] > 3 and row.get("gps_hdop_max", 0) < 99:
        R.append(f"GPS HDOP max={row['gps_hdop_max']:.1f}")
    if row.get("esc_rpm_range_pct") and row["esc_rpm_range_pct"] > 10:
        wm = row.get("esc_worst_motor")
        dv = row.get("esc_worst_motor_dev_pct", 0)
        R.append(f"ESC RPM imbalance {row['esc_rpm_range_pct']:.1f}% (M{wm} off {dv:.1f}%)")
    if row.get("ekf_mag_var_p95") and row["ekf_mag_var_p95"] > 0.5:
        R.append(f"EKF mag variance={row['ekf_mag_var_p95']:.2f} (compass divergence)")
    if row.get("error_count", 0) and row["error_count"] > 0:
        R.append(f"{int(row['error_count'])} ERR messages")
    if row.get("duration_s") is not None and row["duration_s"] < 0:
        R.append(f"NEGATIVE duration={row['duration_s']:.1f}s (data corruption)")
    return R


def load_features_df(db_path: str = DB_PATH) -> pd.DataFrame:
    con = get_conn(db_path)
    rows = con.execute("""
        SELECT f.id AS flight_id, f.file_name, f.format, f.duration_s,
               f.firmware, f.is_simulation, f.parse_error,
               af.bucket AS bucket,
               feat.data AS feature_json
        FROM flights f
        LEFT JOIN airframes af ON af.id = f.airframe_id
        LEFT JOIN features feat ON feat.flight_id = f.id
    """).fetchall()
    con.close()
    out = []
    for r in rows:
        d = dict(r)
        try:
            feat = json.loads(d.pop("feature_json")) if d.get("feature_json") else {}
        except Exception:
            feat = {}
        d.update(feat)
        out.append(d)
    return pd.DataFrame(out)


def fit_one(df: pd.DataFrame, features: list[str], min_n: int = 4) -> tuple[pd.Series, pd.Series]:
    feats = [f for f in features if f in df.columns]
    if not feats or len(df) < min_n:
        return pd.Series([np.nan]*len(df), index=df.index), pd.Series([False]*len(df), index=df.index)
    X = df[feats].apply(pd.to_numeric, errors="coerce")
    keep = [c for c in X.columns if X[c].notna().any()]
    if not keep:
        return pd.Series([np.nan]*len(df), index=df.index), pd.Series([False]*len(df), index=df.index)
    X = X[keep]
    X_imp = SimpleImputer(strategy="median").fit_transform(X)
    X_scaled = StandardScaler().fit_transform(X_imp)
    iforest = IsolationForest(n_estimators=200, contamination="auto", random_state=42)
    iforest.fit(X_scaled)
    scores = -iforest.decision_function(X_scaled)
    flags = iforest.predict(X_scaled) == -1
    return pd.Series(scores, index=df.index), pd.Series(flags, index=df.index)


def run(db_path: str = DB_PATH) -> dict:
    df = load_features_df(db_path)
    ok = df["parse_error"].isna()
    df = df[ok].copy().reset_index(drop=True)
    print(f"Loaded {len(df)} parseable flights")

    is_sim = df["is_simulation"].fillna(0).astype(int).astype(bool)
    df["model_label"] = "skipped"
    df["anom_score"] = np.nan
    df["is_anomaly"] = False

    summary: dict[str, dict] = {}

    # 1) Global model (across all real flights)
    real_mask = ~is_sim & df["parse_error"].isna()
    s, f = fit_one(df[real_mask], FEATURE_COLS)
    df.loc[real_mask, "global_score"] = s.values
    df.loc[real_mask, "global_anom"] = f.values
    summary["global"] = {"n": int(real_mask.sum()), "anom": int(f.sum())}

    # 2) Per-airframe-bucket models
    for bucket in df["bucket"].dropna().unique():
        bmask = (df["bucket"] == bucket) & ~is_sim
        s, f = fit_one(df[bmask], FEATURE_COLS, min_n=8)
        if s.notna().any():
            df.loc[bmask, "bucket_score"] = s.values
            df.loc[bmask, "bucket_anom"] = f.values
            summary[f"bucket_{bucket}"] = {"n": int(bmask.sum()), "anom": int(f.sum())}

    # combine: a flight is anomalous if either global or bucket flagged
    df["combined_anom"] = df.get("global_anom", False).fillna(False) | df.get("bucket_anom", False).fillna(False)
    df["combined_score"] = df[["global_score", "bucket_score"]].max(axis=1, skipna=True)

    # Write to DB
    con = get_conn(db_path)
    con.execute("DELETE FROM anomalies")  # rebuild
    for _, r in df.iterrows():
        if pd.notna(r.get("combined_score")):
            reasons = explain(r)
            con.execute(
                "INSERT INTO anomalies (id, flight_id, model, score, is_anomaly, reasons) VALUES (?,?,?,?,?,?)",
                (
                    str(uuid.uuid4()),
                    r["flight_id"],
                    "iforest_combined",
                    float(r["combined_score"]),
                    1 if r["combined_anom"] else 0,
                    json.dumps(reasons),
                ),
            )
    con.commit()
    n_total_anom = int(df["combined_anom"].fillna(False).sum())
    con.close()

    summary["total_anomalies"] = n_total_anom

    # print top 15
    top = df.dropna(subset=["combined_score"]).sort_values("combined_score", ascending=False).head(15)
    print(f"\nTop 15 anomalies (combined global + per-airframe):")
    for _, r in top.iterrows():
        reasons = explain(r)
        why = "; ".join(reasons) if reasons else "multivariate outlier"
        print(f"  [{r['bucket']:9s}] {r['file_name']:35s} score={r['combined_score']:.3f}  {why}")

    return summary


if __name__ == "__main__":
    out = run()
    print()
    print("Summary:", json.dumps(out, indent=2))
