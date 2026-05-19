"""
LogIQ — Pilot / airframe leaderboard.

Ranks airframes (proxy for pilots in single-fleet MVP) by safety score,
flight hours, and anomaly rate. Designed for fleet-manager view in
multi-operator deployments.
"""
from __future__ import annotations

import json

from logiq.db import get_conn


def airframe_leaderboard() -> list[dict]:
    con = get_conn()
    rows = con.execute("""
        SELECT af.id, af.bucket,
               COUNT(f.id) AS flights,
               COALESCE(SUM(f.duration_s)/3600.0, 0) AS hours
        FROM airframes af
        LEFT JOIN flights f ON f.airframe_id = af.id AND f.parse_error IS NULL
        GROUP BY af.id
    """).fetchall()

    out = []
    for r in rows:
        anomalies = con.execute("""
            SELECT COUNT(*) AS n FROM anomalies a
            JOIN flights f ON f.id = a.flight_id
            WHERE f.airframe_id = ? AND a.is_anomaly = 1
        """, (r["id"],)).fetchone()["n"]

        # avg health
        feats = con.execute("""
            SELECT feat.data FROM flights f
            LEFT JOIN features feat ON feat.flight_id = f.id
            WHERE f.airframe_id = ? AND f.parse_error IS NULL
        """, (r["id"],)).fetchall()

        scores = []
        for fr in feats:
            d = json.loads(fr["data"]) if fr["data"] else {}
            v = d.get("vibe_z_p95") or 0
            c = d.get("clip_events_total") or 0
            re = d.get("roll_err_deg_p95") or 0
            s = 100
            if v > 30 or c > 10000 or re > 20: s = 10
            elif v > 15 or c > 1000 or re > 10: s = 40
            elif v > 5 or re > 5: s = 70
            scores.append(s)
        avg_health = round(sum(scores) / len(scores), 1) if scores else 0

        flights = r["flights"] or 0
        anom_rate = round(100 * anomalies / max(flights, 1), 1)
        out.append({
            "airframe_id": r["id"],
            "bucket": r["bucket"],
            "flights": flights,
            "hours": round(r["hours"] or 0, 1),
            "anomalies": anomalies,
            "anomaly_rate_pct": anom_rate,
            "avg_health": avg_health,
            "rank_score": round(avg_health - anom_rate * 0.5 + r["hours"] * 0.1, 1),
        })

    con.close()
    out.sort(key=lambda x: -x["rank_score"])
    for i, item in enumerate(out, 1):
        item["rank"] = i
    return out
