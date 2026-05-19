"""
LogIQ — Plain-language verdict engine.

Converts a flight's ~80 technical features into:
  * a 0-100 overall health score
  * 5 category scores (Mechanical, Control, Navigation, Battery, Mission)
  * Plain-language issue descriptions (English + Bangla)
  * Action items the operator should take

The goal: a complete beginner who has never seen a flight log can answer
the question "Is my drone OK?" from this output alone.
"""
from __future__ import annotations

from typing import Any


def _safe(v, default=0.0):
    try:
        if v is None:
            return default
        return float(v)
    except Exception:
        return default


def _status(score: int) -> str:
    if score >= 85: return "good"
    if score >= 65: return "fair"
    if score >= 40: return "poor"
    return "critical"


def _emoji(status: str) -> str:
    return {"good": "🟢", "fair": "🟡", "poor": "🟠", "critical": "🔴"}[status]


def compute_verdict(feats: dict[str, Any]) -> dict[str, Any]:
    """Reduce a feature dict to a beginner-friendly verdict."""

    # ============= MECHANICAL HEALTH =============
    mech_score = 100
    mech_en: list[str] = []
    mech_bn: list[str] = []
    mech_actions: list[dict] = []

    vibe_z = _safe(feats.get("vibe_z_p95"))
    vibe_y = _safe(feats.get("vibe_y_p95"))
    vibe_max = max(vibe_z, vibe_y)

    if vibe_max > 30:
        mech_score = min(mech_score, 10)
        mech_en.append(f"Drone was shaking very heavily ({vibe_max:.0f} m/s²)")
        mech_bn.append(f"Drone khub joore kepechhilo ({vibe_max:.0f} m/s²)")
        mech_actions.append({
            "en": "Inspect propellers for cracks, chips, or imbalance",
            "bn": "Propeller gulo dekho — fata, fati, balance thik ase ki na"
        })
        mech_actions.append({
            "en": "Tighten all frame screws and motor mounts",
            "bn": "Frame screw + motor mount sob tight kore nao"
        })
    elif vibe_max > 15:
        mech_score = min(mech_score, 55)
        mech_en.append(f"Vibration was higher than normal ({vibe_max:.1f} m/s²)")
        mech_bn.append(f"Vibration normal cheye beshi chhilo ({vibe_max:.1f} m/s²)")
        mech_actions.append({
            "en": "Check propeller balance — use a prop balancer if you have one",
            "bn": "Propeller balance check koro — prop balancer use koro jodi thake"
        })
    elif vibe_max > 5:
        mech_score = min(mech_score, 80)
        mech_en.append(f"Slight vibration noticed ({vibe_max:.1f} m/s²)")
        mech_bn.append(f"Halka vibration ase ({vibe_max:.1f} m/s²)")

    clips = int(_safe(feats.get("clip_events_total")))
    if clips > 10000:
        mech_score = min(mech_score, 5)
        mech_en.append(f"Motion sensors completely overwhelmed ({clips:,} events) — likely prop strike or motor failure")
        mech_bn.append(f"Motion sensor purai overwhelmed ({clips:,} barr) — prop strike ba motor fail hote pare")
        mech_actions.append({
            "en": "DO NOT fly again until physical inspection complete",
            "bn": "Physical check na hoa porjonto AR FLY KORO NA"
        })
    elif clips > 1000:
        mech_score = min(mech_score, 35)
        mech_en.append(f"Sensors briefly maxed out ({clips:,} times)")
        mech_bn.append(f"Sensor maximum hit korechhe ({clips:,} barr)")
        mech_actions.append({
            "en": "Look for anything loose — screws, antennas, battery strap",
            "bn": "Loose kichu ase ki dekho — screw, antenna, battery strap"
        })

    rpm_imb = _safe(feats.get("esc_rpm_range_pct"))
    worst_motor = feats.get("esc_worst_motor")
    if rpm_imb > 15:
        mech_score = min(mech_score, 40)
        mech_en.append(f"Motors are not running evenly ({rpm_imb:.0f}% imbalance)")
        mech_bn.append(f"Motor gulo same shamane ghorchhe na ({rpm_imb:.0f}% imbalance)")
        if worst_motor is not None:
            mech_actions.append({
                "en": f"Motor #{int(worst_motor)+1} is working hardest — inspect bearings, prop, ESC",
                "bn": f"Motor #{int(worst_motor)+1} sob theke beshi kaj korchhe — bearing, prop, ESC check koro"
            })

    # ============= CONTROL HEALTH =============
    ctrl_score = 100
    ctrl_en: list[str] = []
    ctrl_bn: list[str] = []
    ctrl_actions: list[dict] = []

    roll_err = feats.get("roll_err_deg_p95")
    pitch_err = feats.get("pitch_err_deg_p95")
    max_err = max(_safe(roll_err), _safe(pitch_err))

    if max_err > 20 and roll_err is not None:
        ctrl_score = min(ctrl_score, 5)
        ctrl_en.append(f"Drone could not follow flight commands ({max_err:.0f}° off) — possible crash or severe failure")
        ctrl_bn.append(f"Drone command follow korte parchhilo na ({max_err:.0f}° off) — crash or major fail hote pare")
        ctrl_actions.append({
            "en": "Inspect frame for damage, check all props/motors visually",
            "bn": "Frame e crack ase ki dekho, sob prop/motor check koro"
        })
    elif max_err > 10:
        ctrl_score = min(ctrl_score, 40)
        ctrl_en.append(f"Drone struggled to hold its angle ({max_err:.1f}° error)")
        ctrl_bn.append(f"Drone angle hold korte kasto holo ({max_err:.1f}° error)")
        ctrl_actions.append({
            "en": "Re-tune PID gains, check for damaged components",
            "bn": "PID tune kori, damage ache ki dekho"
        })
    elif max_err > 5:
        ctrl_score = min(ctrl_score, 70)
        ctrl_en.append(f"Slightly sluggish response ({max_err:.1f}°)")
        ctrl_bn.append(f"Response ektu slow ({max_err:.1f}°)")
        ctrl_actions.append({
            "en": "Consider tuning PID gains for crisper control",
            "bn": "PID tune korle aro fast hobe"
        })

    # ============= NAVIGATION HEALTH =============
    nav_score = 100
    nav_en: list[str] = []
    nav_bn: list[str] = []
    nav_actions: list[dict] = []

    hdop = _safe(feats.get("gps_hdop_max"), -1)
    nsats = feats.get("gps_nsats_min")

    # GPS HDOP=100 from MAVLink means "no fix" — handle separately
    if hdop > 0 and hdop < 50:
        if hdop > 5:
            nav_score = min(nav_score, 25)
            nav_en.append(f"GPS signal was very poor (HDOP {hdop:.1f})")
            nav_bn.append(f"GPS signal kub kharap chhilo (HDOP {hdop:.1f})")
            nav_actions.append({
                "en": "Fly in open areas — avoid tall buildings, trees, power lines",
                "bn": "Open jaiga te fly koro — boro building, gachh, electric line avoid koro"
            })
        elif hdop > 2.5:
            nav_score = min(nav_score, 60)
            nav_en.append(f"GPS signal was weak (HDOP {hdop:.1f})")
            nav_bn.append(f"GPS signal weak chhilo (HDOP {hdop:.1f})")

    if nsats is not None and 0 < nsats < 6:
        nav_score = min(nav_score, 45)
        nav_en.append(f"Only {int(nsats)} GPS satellites locked (minimum 6 recommended)")
        nav_bn.append(f"Sudhu {int(nsats)} GPS satellite lock korechhilo (minimum 6 lage)")
        nav_actions.append({
            "en": "Wait for at least 8 satellites locked before takeoff",
            "bn": "Takeoff er age at least 8 satellite lock hoa porjonto wait koro"
        })

    mag_var = _safe(feats.get("ekf_mag_var_p95"))
    if mag_var > 0.8:
        nav_score = min(nav_score, 35)
        nav_en.append(f"Compass readings were very unreliable (variance {mag_var:.2f})")
        nav_bn.append(f"Compass reading khub unreliable chhilo (variance {mag_var:.2f})")
        nav_actions.append({
            "en": "Recalibrate compass; move away from metal/magnetic sources",
            "bn": "Compass recalibrate koro; metal/magnet er kacha theke dure jao"
        })
    elif mag_var > 0.3:
        nav_score = min(nav_score, 65)
        nav_en.append(f"Compass had some interference (variance {mag_var:.2f})")
        nav_bn.append(f"Compass e interference chhilo (variance {mag_var:.2f})")

    # ============= BATTERY HEALTH =============
    batt_score = 100
    batt_en: list[str] = []
    batt_bn: list[str] = []
    batt_actions: list[dict] = []

    volt_min = feats.get("volt_min")
    volt_max = feats.get("volt_max")
    if volt_min and volt_max and volt_min > 0 and volt_max > 0:
        # Detect cell count from max voltage. Typical: 3S=12.6, 4S=16.8, 6S=25.2 fully charged
        cells = round(volt_max / 4.2)
        if cells > 0:
            v_per_cell_min = volt_min / cells
            if v_per_cell_min < 3.3:
                batt_score = min(batt_score, 20)
                batt_en.append(f"Battery dropped dangerously low ({v_per_cell_min:.2f}V/cell)")
                batt_bn.append(f"Battery dangerously low hoyechhilo ({v_per_cell_min:.2f}V/cell)")
                batt_actions.append({
                    "en": "Land sooner next time — never fly below 3.3V/cell",
                    "bn": "Next time aage land koro — 3.3V/cell er niche kokhono jaaba na"
                })
            elif v_per_cell_min < 3.5:
                batt_score = min(batt_score, 55)
                batt_en.append(f"Battery got low ({v_per_cell_min:.2f}V/cell)")
                batt_bn.append(f"Battery low hoyechhilo ({v_per_cell_min:.2f}V/cell)")

    drop = feats.get("batt_rempct_drop")
    if drop and drop > 80:
        batt_score = min(batt_score, 40)
        batt_en.append(f"Battery drained too quickly ({drop:.0f}% used)")
        batt_bn.append(f"Battery khub fast eshes ho gechhe ({drop:.0f}% use hoyechhe)")

    # ============= MISSION HEALTH =============
    mis_score = 100
    mis_en: list[str] = []
    mis_bn: list[str] = []
    mis_actions: list[dict] = []

    errors = int(_safe(feats.get("error_count")))
    if errors > 5:
        mis_score = min(mis_score, 30)
        mis_en.append(f"{errors} error messages logged during flight")
        mis_bn.append(f"{errors} ta error message paya gechhe flight e")
    elif errors > 0:
        mis_score = min(mis_score, 70)
        mis_en.append(f"{errors} error message(s) during flight")
        mis_bn.append(f"{errors} ta error message paya gechhe")

    dur = feats.get("duration_s")
    if dur is not None and dur < 0:
        mis_score = 0
        mis_en.append("Log file is corrupted (negative duration)")
        mis_bn.append("Log file ta corrupt (duration negative)")

    arms = int(_safe(feats.get("arming_events")))
    if arms == 0 and (dur is None or dur < 60):
        mis_score = min(mis_score, 60)
        mis_en.append("Drone was not armed — no actual flight in this log")
        mis_bn.append("Drone arm hoy nai — ei log e actual flight nai")

    # ============= OVERALL =============
    categories = [
        {
            "key": "mechanical", "name_en": "Mechanical", "name_bn": "Mechanical (যান্ত্রিক)",
            "icon": "🔧", "score": mech_score, "status": _status(mech_score),
            "issues_en": mech_en, "issues_bn": mech_bn, "actions": mech_actions,
            "metric_en": "Vibration, motor balance, sensor health",
            "metric_bn": "Vibration, motor balance, sensor",
        },
        {
            "key": "control", "name_en": "Flight Control", "name_bn": "Flight Control",
            "icon": "🎯", "score": ctrl_score, "status": _status(ctrl_score),
            "issues_en": ctrl_en, "issues_bn": ctrl_bn, "actions": ctrl_actions,
            "metric_en": "How well drone followed commands",
            "metric_bn": "Drone command kemon follow korlo",
        },
        {
            "key": "navigation", "name_en": "Navigation", "name_bn": "Navigation",
            "icon": "🛰️", "score": nav_score, "status": _status(nav_score),
            "issues_en": nav_en, "issues_bn": nav_bn, "actions": nav_actions,
            "metric_en": "GPS quality, compass accuracy",
            "metric_bn": "GPS quality, compass accuracy",
        },
        {
            "key": "battery", "name_en": "Battery", "name_bn": "Battery",
            "icon": "🔋", "score": batt_score, "status": _status(batt_score),
            "issues_en": batt_en, "issues_bn": batt_bn, "actions": batt_actions,
            "metric_en": "Voltage, capacity used",
            "metric_bn": "Voltage, capacity used",
        },
        {
            "key": "mission", "name_en": "Mission", "name_bn": "Mission",
            "icon": "✓", "score": mis_score, "status": _status(mis_score),
            "issues_en": mis_en, "issues_bn": mis_bn, "actions": mis_actions,
            "metric_en": "Errors, completion, log integrity",
            "metric_bn": "Error, completion, log file",
        },
    ]

    overall = min(c["score"] for c in categories)
    overall_status = _status(overall)

    # Summary one-liner
    if overall >= 85:
        summary_en = "Looks like a good clean flight — drone is healthy."
        summary_bn = "Flight ta valo hoyechhe — drone healthy."
    elif overall >= 65:
        summary_en = "Mostly fine, but a couple of things worth checking."
        summary_bn = "Beshirvag thik ase, kintu kichu jinish check kora valo."
    elif overall >= 40:
        weak = next((c for c in categories if c["score"] == overall), None)
        wname = weak["name_en"] if weak else "something"
        summary_en = f"Concerns detected, especially around {wname}. Inspect before next flight."
        summary_bn = f"Problem ase, especially {wname} niye. Next flight er age check kore nao."
    else:
        summary_en = "Serious issues found. Do not fly until inspected and fixed."
        summary_bn = "Serious problem paya gechhe. Inspect/fix na kora porjonto fly koro na."

    # collect all actions, prioritized by category severity
    all_actions: list[dict] = []
    for c in sorted(categories, key=lambda x: x["score"]):
        for a in c["actions"]:
            all_actions.append({
                "category": c["name_en"],
                "icon": c["icon"],
                "en": a["en"],
                "bn": a["bn"],
                "priority": c["status"],
            })

    return {
        "overall_score": int(overall),
        "overall_status": overall_status,
        "overall_emoji": _emoji(overall_status),
        "summary_en": summary_en,
        "summary_bn": summary_bn,
        "categories": categories,
        "actions": all_actions[:8],  # top 8 most important
        "is_anomaly": overall < 65,
    }


# ---- demo glossary entries (for tooltip system) ----
GLOSSARY = {
    "vibration": {
        "en": "How much the drone shakes while flying. Caused by props, motors, or loose parts. Low is good.",
        "bn": "Fly korar shomoy drone koto kape. Prop, motor ba loose part theke ase. Kam holei valo.",
    },
    "hdop": {
        "en": "GPS quality number. 1.0 = perfect, above 2.5 = weak signal, above 5 = bad.",
        "bn": "GPS quality number. 1.0 = perfect, 2.5 er beshi = weak signal, 5 er beshi = kharap.",
    },
    "tracking_error": {
        "en": "Difference between what the pilot asked for and what the drone actually did. Small is good.",
        "bn": "Pilot ja chailo ar drone ja korlo - tar parthokyo. Kam holei valo.",
    },
    "imu_clipping": {
        "en": "How many times the motion sensors got 'maxed out' from severe shaking. Should be zero.",
        "bn": "Motion sensor koto bar 'maximum hit' korlo joorer vibration theke. Zero hoa uchit.",
    },
    "ekf_variance": {
        "en": "How confused the drone's brain was about where it is. High = bad.",
        "bn": "Drone er 'brain' koto confused chhilo poshition niye. Beshi = kharap.",
    },
    "rpm_imbalance": {
        "en": "Difference between motors. If one works harder, it might be worn or damaged.",
        "bn": "Motor gulor moddhe parthokyo. Ekta jodi beshi kaj kore, sheta worn or damaged hote pare.",
    },
}


if __name__ == "__main__":
    import json, sys
    from logiq.extract import extract_features
    p = sys.argv[1] if len(sys.argv) > 1 else r"C:\Users\zasif bin islam\Documents\Mission Planner\logs\QUADROTOR\1\2023-02-02 23-16-05.bin"
    feats = extract_features(p)
    v = compute_verdict(feats)
    print(json.dumps(v, indent=2, ensure_ascii=False))
