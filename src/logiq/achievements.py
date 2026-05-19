"""
LogIQ — Achievements / badges.

Computes gamified milestones across the operator's fleet:
- Flight count tiers
- Total flight-hour tiers
- Streaks of healthy flights
- First crash detected
- Labeled-data contributor
- Multi-airframe pilot
- Long-flight badges
"""
from __future__ import annotations

import json
from typing import Any

from logiq.db import get_conn


def _badge(key: str, en: str, bn: str, icon: str, earned: bool, progress: dict | None = None) -> dict:
    return {"key": key, "en": en, "bn": bn, "icon": icon, "earned": earned, "progress": progress or {}}


def compute() -> dict[str, Any]:
    con = get_conn()
    rows = con.execute("""
        SELECT f.id, f.flown_at, f.duration_s, af.bucket, feat.data
        FROM flights f
        LEFT JOIN airframes af ON af.id = f.airframe_id
        LEFT JOIN features feat ON feat.flight_id = f.id
        WHERE f.parse_error IS NULL AND f.flown_at IS NOT NULL
        ORDER BY f.flown_at ASC
    """).fetchall()

    flights = []
    for r in rows:
        d = json.loads(r["data"]) if r["data"] else {}
        # rough health proxy
        v = d.get("vibe_z_p95") or 0
        c = d.get("clip_events_total") or 0
        re = d.get("roll_err_deg_p95") or 0
        score = 100
        if v > 30 or c > 10000 or re > 20: score = 10
        elif v > 15 or c > 1000 or re > 10: score = 40
        elif v > 5 or re > 5: score = 70
        flights.append({"id": r["id"], "score": score, "duration_s": r["duration_s"] or 0, "bucket": r["bucket"] or "?", "flown_at": r["flown_at"]})

    label_count = con.execute("SELECT COUNT(*) AS n FROM labels").fetchone()["n"]
    con.close()

    total_flights = len(flights)
    total_hours = sum(f["duration_s"] for f in flights) / 3600.0
    healthy = [f for f in flights if f["score"] >= 70]
    perfect = [f for f in flights if f["score"] >= 90]
    distinct_buckets = len({f["bucket"] for f in flights if f["bucket"] not in ("?", "BAD", "SMALL")})
    longest_s = max((f["duration_s"] for f in flights), default=0)

    # current streak: from end, consecutive healthy
    current_streak = 0
    for f in reversed(flights):
        if f["score"] >= 70: current_streak += 1
        else: break

    # longest streak ever
    longest_streak = 0; cur = 0
    for f in flights:
        if f["score"] >= 70:
            cur += 1; longest_streak = max(longest_streak, cur)
        else:
            cur = 0

    crashes_detected = sum(1 for f in flights if f["score"] < 30)

    badges: list[dict] = []

    # Flight count tiers
    for n, name_en, name_bn, icon in [(1, "First flight", "Prothom flight", "🚀"),
                                       (10, "10 flights", "10 flight", "🛫"),
                                       (50, "Half-century", "50 flight", "🥉"),
                                       (100, "Century pilot", "100 flight", "💯"),
                                       (500, "Veteran (500)", "Veteran 500", "🏆")]:
        badges.append(_badge(f"flights_{n}", name_en, name_bn, icon, total_flights >= n,
                             {"current": total_flights, "target": n}))

    # Hour tiers
    for h, name_en, name_bn, icon in [(1, "First hour", "Prothom 1 hour", "⏱️"),
                                       (10, "10 hours airborne", "10 hour", "🕐"),
                                       (50, "50 hours pilot", "50 hour pilot", "⏳"),
                                       (100, "Century-hour", "100 hour", "🥇")]:
        badges.append(_badge(f"hours_{h}", name_en, name_bn, icon, total_hours >= h,
                             {"current": round(total_hours, 1), "target": h}))

    # Healthy streaks
    badges.append(_badge("streak_5", "5 healthy in a row", "5 ta toko theek", "🟢", longest_streak >= 5,
                         {"current": longest_streak, "target": 5}))
    badges.append(_badge("streak_20", "20 healthy in a row", "20 ta theek", "🌿", longest_streak >= 20,
                         {"current": longest_streak, "target": 20}))

    # Multi-airframe
    badges.append(_badge("multi_frame", "Multi-airframe pilot", "Multi-frame pilot", "🛩️", distinct_buckets >= 2,
                         {"current": distinct_buckets, "target": 2}))
    badges.append(_badge("triple_frame", "3+ frame classes", "3+ frame class", "🪂", distinct_buckets >= 3,
                         {"current": distinct_buckets, "target": 3}))

    # Long flight
    badges.append(_badge("long_flight", "Long flight (>10 min)", "Long flight (>10 min)", "🌐", longest_s >= 600,
                         {"current": int(longest_s), "target": 600}))
    badges.append(_badge("epic_flight", "Epic flight (>30 min)", "Epic flight (>30 min)", "🌌", longest_s >= 1800,
                         {"current": int(longest_s), "target": 1800}))

    # Labeling
    badges.append(_badge("labeler", "Data labeler (10 tags)", "Data labeler (10 tag)", "🏷️", label_count >= 10,
                         {"current": label_count, "target": 10}))
    badges.append(_badge("super_labeler", "Super labeler (100 tags)", "Super labeler (100 tag)", "🎯", label_count >= 100,
                         {"current": label_count, "target": 100}))

    # Forensics
    badges.append(_badge("detective", "Crash detective", "Crash detective", "🔍", crashes_detected >= 1,
                         {"current": crashes_detected, "target": 1}))

    earned = sum(1 for b in badges if b["earned"])

    return {
        "earned_count": earned,
        "total_count": len(badges),
        "total_flights": total_flights,
        "total_hours": round(total_hours, 1),
        "healthy_flights": len(healthy),
        "perfect_flights": len(perfect),
        "current_streak": current_streak,
        "longest_streak": longest_streak,
        "distinct_buckets": distinct_buckets,
        "label_count": label_count,
        "longest_flight_s": int(longest_s),
        "crashes_detected": crashes_detected,
        "badges": badges,
    }
