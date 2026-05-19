"""
LogIQ — Auto-tag suggestion.

Suggest a likely label based on verdict patterns. Returns a single best label
plus a confidence and reasoning. Designed so the operator just confirms with
one click.
"""
from __future__ import annotations


def suggest_tag(verdict: dict) -> dict:
    overall = verdict.get("overall_score", 100)
    cats = {c["key"]: c for c in verdict.get("categories", [])}

    mech = cats.get("mechanical", {}).get("score", 100)
    ctrl = cats.get("control", {}).get("score", 100)
    nav = cats.get("navigation", {}).get("score", 100)
    batt = cats.get("battery", {}).get("score", 100)
    mis = cats.get("mission", {}).get("score", 100)

    all_issues = []
    for c in verdict.get("categories", []):
        all_issues.extend(c.get("issues_en") or [])
    flat = " ".join(all_issues).lower()

    # Crash: extremely high IMU clipping + control failure
    if "clipping" in flat and "saturation" in flat and (ctrl < 30 or mech < 20):
        return {"label": "crash", "confidence": "high",
                "reason_en": "Severe IMU clipping plus collapsed control tracking — classic crash signature.",
                "reason_bn": "Severe IMU clipping ar control tracking fail — crash signature."}

    # Vibration
    if "vibe z" in flat and ("danger" in flat or "warn" in flat) and mech < 60:
        return {"label": "vibration", "confidence": "high",
                "reason_en": "VIBE Z exceeded warn/danger threshold without other system failures.",
                "reason_bn": "VIBE Z warn/danger threshold cross — vibration issue."}

    # Bad tune
    if ("poor tune" in flat or "sluggish" in flat) and mech > 80:
        return {"label": "bad_tune", "confidence": "medium",
                "reason_en": "Tracking error exceeds normal but mechanical signals OK — looks like PID tune.",
                "reason_bn": "Tracking error beshi but mechanical OK — PID tuning issue."}

    # Compass / EKF
    if "compass" in flat or ("mag" in flat and "variance" in flat):
        return {"label": "compass_fail", "confidence": "medium",
                "reason_en": "EKF magnetic variance elevated.",
                "reason_bn": "EKF mag variance high."}

    # GPS
    if "gps" in flat and ("poor" in flat or "loss" in flat or "few" in flat):
        return {"label": "gps_loss", "confidence": "medium",
                "reason_en": "Sustained poor GPS quality.",
                "reason_bn": "GPS quality continuously kharap chhilo."}

    # Motor failure
    if "motor" in flat and ("imbalance" in flat or "rpm" in flat):
        return {"label": "motor_fail", "confidence": "medium",
                "reason_en": "Per-motor imbalance detected (likely wear).",
                "reason_bn": "Motor imbalance detect (wear hote pare)."}

    # Corrupt log
    if "data corruption" in flat or "negative duration" in flat:
        return {"label": "unknown", "confidence": "low",
                "reason_en": "Log file appears corrupted; cannot classify reliably.",
                "reason_bn": "Log file corrupt — classify kora possible na."}

    # Short bench test
    if verdict.get("flight", {}).get("duration_s") is not None and verdict["flight"]["duration_s"] < 30 and verdict.get("flight", {}).get("is_simulation"):
        return {"label": "bench_test", "confidence": "high",
                "reason_en": "Short SITL session.",
                "reason_bn": "Short SITL/simulation."}

    # Otherwise, healthy
    if overall >= 85:
        return {"label": "ok", "confidence": "high",
                "reason_en": "All categories scored high — likely a healthy flight.",
                "reason_bn": "Sob category high score — healthy flight."}

    return {"label": "unknown", "confidence": "low",
            "reason_en": "No strong single pattern; operator review recommended.",
            "reason_bn": "Specific pattern paya nai; tumi review koro."}
