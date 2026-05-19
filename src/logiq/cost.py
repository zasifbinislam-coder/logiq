"""
LogIQ — Cost estimator (Bangladesh BDT).

Maps detected anomaly types to estimated repair cost ranges. Numbers reflect
the small-to-mid market for ArduPilot hobby/commercial drones in Bangladesh
(2026 pricing). Easy to override per fleet.
"""
from __future__ import annotations

from typing import Any


# Range = (min BDT, max BDT, repair_desc)
COST_TABLE_BDT = {
    "vibration_minor":  (500, 2000,  "Propeller re-balance / tightening"),
    "vibration_major":  (3000, 12000, "Propeller replacement + motor inspection"),
    "imu_clipping":     (2000, 8000,  "Frame inspection, possible motor mount replacement"),
    "control_minor":    (500, 1500,  "PID tuning session"),
    "control_major":    (8000, 30000, "Frame damage assessment + replacement parts"),
    "crash":            (15000, 80000, "Full inspection + multiple component replacement"),
    "gps_loss":         (0, 0,      "Operational change — no parts needed"),
    "compass_fail":     (500, 3000,  "Compass re-calibration / replacement"),
    "motor_imbalance":  (1500, 6000,  "Bearing replacement on affected motor"),
    "battery_low":      (3000, 15000, "Battery replacement"),
}


def estimate_cost(verdict: dict) -> dict[str, Any]:
    """Estimate the BDT cost of fixing this flight's issues."""
    items: list[dict] = []
    total_min = 0
    total_max = 0

    cats = {c["key"]: c for c in verdict.get("categories", [])}
    mech = cats.get("mechanical", {}).get("score", 100)
    ctrl = cats.get("control", {}).get("score", 100)
    nav = cats.get("navigation", {}).get("score", 100)
    batt = cats.get("battery", {}).get("score", 100)

    flat_issues = []
    for c in verdict.get("categories", []):
        flat_issues.extend(c.get("issues_en") or [])
    issues_text = " ".join(flat_issues).lower()

    def add(key, mult=1.0):
        lo, hi, desc = COST_TABLE_BDT[key]
        lo, hi = int(lo * mult), int(hi * mult)
        items.append({"issue": key, "lo": lo, "hi": hi, "desc": desc})
        return lo, hi

    # Mechanical
    if mech < 30:
        # crash-level
        lo, hi = add("crash")
        total_min += lo; total_max += hi
    elif mech < 60:
        lo, hi = add("vibration_major")
        total_min += lo; total_max += hi
    elif mech < 85:
        lo, hi = add("vibration_minor")
        total_min += lo; total_max += hi

    if "imu clipping" in issues_text.lower() or "clip" in issues_text:
        lo, hi = add("imu_clipping")
        total_min += lo; total_max += hi

    if "motor" in issues_text.lower() or "esc rpm imbalance" in issues_text.lower():
        lo, hi = add("motor_imbalance")
        total_min += lo; total_max += hi

    # Control
    if ctrl < 30:
        lo, hi = add("control_major")
        total_min += lo; total_max += hi
    elif ctrl < 70:
        lo, hi = add("control_minor")
        total_min += lo; total_max += hi

    # Navigation
    if "compass" in issues_text.lower():
        lo, hi = add("compass_fail")
        total_min += lo; total_max += hi

    # Battery
    if batt < 40:
        lo, hi = add("battery_low")
        total_min += lo; total_max += hi

    # Hidden cost: downtime
    downtime_days = 0
    if verdict.get("overall_score", 100) < 40:
        downtime_days = 3
        total_max += 5000  # lost revenue assumption
    elif verdict.get("overall_score", 100) < 65:
        downtime_days = 1
        total_max += 1500

    summary_en = "No cost if drone inspected and confirmed OK." if not items else \
        f"Estimated parts + labour: Tk {total_min:,} – Tk {total_max:,}"
    summary_bn = "Inspection e drone theek hole kono khoroch nai." if not items else \
        f"Khoroch er estimate: Tk {total_min:,} – Tk {total_max:,}"

    return {
        "total_min_bdt": total_min,
        "total_max_bdt": total_max,
        "items": items,
        "downtime_days": downtime_days,
        "summary_en": summary_en,
        "summary_bn": summary_bn,
        "currency": "BDT",
    }
