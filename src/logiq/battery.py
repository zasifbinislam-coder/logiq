"""
LogIQ — Battery cycle tracker.

ArduPilot logs do not include a stable battery serial, so we infer "battery
sessions" per airframe and track per-flight voltage sag patterns. Useful
signals:
  * voltage range collapsing over time → ageing
  * resting-volt drift downward → cell degradation
  * mAh / minute trending up → reduced energy density
"""
from __future__ import annotations

import json
from collections import defaultdict

from logiq.db import get_conn


def per_airframe_battery_trends() -> list[dict]:
    con = get_conn()
    rows = con.execute("""
        SELECT f.id, f.flown_at, f.duration_s, af.bucket, feat.data
        FROM flights f
        LEFT JOIN airframes af ON af.id = f.airframe_id
        LEFT JOIN features feat ON feat.flight_id = f.id
        WHERE f.parse_error IS NULL AND f.flown_at IS NOT NULL
        ORDER BY f.flown_at ASC
    """).fetchall()
    con.close()

    by_bucket: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        d = json.loads(r["data"]) if r["data"] else {}
        vmax, vmin = d.get("volt_max"), d.get("volt_min")
        if not (vmax and vmin and vmax > 0 and vmin > 0):
            continue
        by_bucket[r["bucket"] or "OTHER"].append({
            "flight_id": r["id"],
            "flown_at": r["flown_at"][:10] if r["flown_at"] else None,
            "duration_s": r["duration_s"] or 0,
            "v_max": vmax,
            "v_min": vmin,
            "v_drop": round(vmax - vmin, 2),
            "energy_wh": d.get("energy_total_wh"),
        })

    out = []
    for bucket, flights in by_bucket.items():
        if len(flights) < 3:
            continue
        first_half = flights[: len(flights) // 2]
        last_half = flights[len(flights) // 2:]
        avg_drop_early = sum(f["v_drop"] for f in first_half) / max(len(first_half), 1)
        avg_drop_late = sum(f["v_drop"] for f in last_half) / max(len(last_half), 1)
        drift = round(avg_drop_late - avg_drop_early, 2)
        status = "good"
        if drift > 0.4: status = "poor"
        elif drift > 0.2: status = "fair"
        out.append({
            "bucket": bucket,
            "n_flights_with_battery_data": len(flights),
            "first_date": flights[0]["flown_at"],
            "last_date": flights[-1]["flown_at"],
            "avg_v_drop_early": round(avg_drop_early, 2),
            "avg_v_drop_late": round(avg_drop_late, 2),
            "drift": drift,
            "status": status,
            "advice_en": "Battery ageing — voltage sag has grown over time. Consider cycling or replacing." if drift > 0.2 else "Battery behaviour stable.",
            "advice_bn": "Battery age hoye gechhe — voltage sag baarchhe. Replace or cycle koro." if drift > 0.2 else "Battery normal behaviour.",
            "history": flights,
        })
    out.sort(key=lambda b: -b["n_flights_with_battery_data"])
    return out
