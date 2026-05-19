"""
LogIQ — Component lifetime tracker.

Estimates how much wear each airframe-attached component has accumulated.

Without explicit component IDs, we use heuristics:
  * Each motor on a quad gets total armed hours of that airframe class
  * Props are assumed replaced whenever a `prop_replaced` maintenance entry
    follows a `prop_strike`/`crash` event
  * Battery cycles ≈ flights × 1 (rough)
  * Bearings: motor_bearing maintenance entries count down expected lifetime
"""
from __future__ import annotations

import json
from typing import Any

from logiq.db import get_conn


EXPECTED_LIFETIME_HOURS = {
    "motor":   80,
    "esc":     150,
    "prop":     20,
    "battery": 250,   # cycles, not hours
    "frame":   500,
}


def per_airframe_component_status() -> list[dict]:
    con = get_conn()
    rows = con.execute("""
        SELECT af.id AS airframe_id, af.bucket,
               COUNT(f.id) AS flights,
               COALESCE(SUM(f.duration_s)/3600.0, 0) AS hours
        FROM airframes af
        LEFT JOIN flights f ON f.airframe_id = af.id AND f.parse_error IS NULL
        GROUP BY af.id ORDER BY hours DESC
    """).fetchall()

    maint_rows = con.execute("""
        SELECT airframe_id, type, COUNT(*) AS n
        FROM maintenance GROUP BY airframe_id, type
    """).fetchall()
    con.close()

    maint_index: dict[str, dict[str, int]] = {}
    for m in maint_rows:
        maint_index.setdefault(m["airframe_id"], {})[m["type"]] = m["n"]

    out = []
    for r in rows:
        af_id = r["airframe_id"]
        hours = round(r["hours"] or 0, 1)
        m = maint_index.get(af_id, {})

        components = []
        # motors — count down per replacement
        n_replaced = m.get("motor_replaced", 0)
        motor_hours = round(max(0, hours - n_replaced * EXPECTED_LIFETIME_HOURS["motor"]), 1)
        components.append({
            "component": "motors",
            "expected_lifetime_hours": EXPECTED_LIFETIME_HOURS["motor"],
            "estimated_hours": motor_hours,
            "remaining_pct": max(0, round(100 * (1 - motor_hours / EXPECTED_LIFETIME_HOURS["motor"]), 1)),
            "replacements": n_replaced,
            "note_en": "Replace at first sign of bearing noise." if motor_hours > EXPECTED_LIFETIME_HOURS["motor"] * 0.8 else "Within expected lifetime.",
            "note_bn": "Bearing er noise paile replace koro." if motor_hours > EXPECTED_LIFETIME_HOURS["motor"] * 0.8 else "Expected lifetime er moddhe.",
        })

        # ESCs
        n_esc = m.get("esc_replaced", 0)
        esc_hours = round(max(0, hours - n_esc * EXPECTED_LIFETIME_HOURS["esc"]), 1)
        components.append({
            "component": "escs",
            "expected_lifetime_hours": EXPECTED_LIFETIME_HOURS["esc"],
            "estimated_hours": esc_hours,
            "remaining_pct": max(0, round(100 * (1 - esc_hours / EXPECTED_LIFETIME_HOURS["esc"]), 1)),
            "replacements": n_esc,
            "note_en": "Monitor for high temperatures.",
            "note_bn": "Temperature high holo ki monitor koro.",
        })

        # Props
        n_prop = m.get("prop_replaced", 0) + m.get("prop_balanced", 0)
        prop_hours_per = max(0, hours / max(n_prop + 1, 1))
        components.append({
            "component": "propellers",
            "expected_lifetime_hours": EXPECTED_LIFETIME_HOURS["prop"],
            "estimated_hours": round(prop_hours_per, 1),
            "remaining_pct": max(0, round(100 * (1 - prop_hours_per / EXPECTED_LIFETIME_HOURS["prop"]), 1)),
            "replacements": n_prop,
            "note_en": "Inspect every flight for chips.",
            "note_bn": "Protek flight er por dekho.",
        })

        # Battery cycles
        n_batt = m.get("battery_replaced", 0)
        cycles = max(0, (r["flights"] or 0) - n_batt * EXPECTED_LIFETIME_HOURS["battery"])
        components.append({
            "component": "battery",
            "expected_lifetime_hours": EXPECTED_LIFETIME_HOURS["battery"],
            "estimated_hours": cycles,
            "remaining_pct": max(0, round(100 * (1 - cycles / EXPECTED_LIFETIME_HOURS["battery"]), 1)),
            "replacements": n_batt,
            "note_en": f"~{cycles} cycles. Most LiPo packs are toast after 250 cycles.",
            "note_bn": f"~{cycles} cycle. 250 cycle er por LiPo replace kora valo.",
        })

        out.append({
            "airframe_id": af_id,
            "bucket": r["bucket"],
            "total_flights": r["flights"],
            "total_hours": hours,
            "components": components,
        })

    return out
