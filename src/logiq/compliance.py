"""
LogIQ — CAAB / Bangladesh drone compliance checker.

References Civil Aviation Authority of Bangladesh (CAAB) Drone Rules 2020 and
typical operational requirements. Each rule returns a structured check that
the operator can answer Yes / No / Not applicable.
"""
from __future__ import annotations

from typing import Any


# Weight categories per CAAB 2020 (kg)
WEIGHT_CATEGORIES = [
    {"key": "A", "min_kg": 0,    "max_kg": 0.25, "label_en": "Toy",         "label_bn": "Khelna",      "license_required": False, "registration_required": False},
    {"key": "B", "min_kg": 0.25, "max_kg": 2.0,  "label_en": "Micro",       "label_bn": "Micro",       "license_required": False, "registration_required": True},
    {"key": "C", "min_kg": 2.0,  "max_kg": 25,   "label_en": "Small",       "label_bn": "Small",       "license_required": True,  "registration_required": True},
    {"key": "D", "min_kg": 25,   "max_kg": 150,  "label_en": "Medium",      "label_bn": "Medium",      "license_required": True,  "registration_required": True},
    {"key": "E", "min_kg": 150,  "max_kg": 9999, "label_en": "Large",       "label_bn": "Large",       "license_required": True,  "registration_required": True},
]


CHECKLIST = [
    {"id": "weight_known",    "en": "I know the all-up weight of my drone",                "bn": "Drone er AUW ami janli",                       "category": "registration"},
    {"id": "caab_registered", "en": "Drone is registered with CAAB (Form D-1)",            "bn": "Drone CAAB e registered (Form D-1)",           "category": "registration"},
    {"id": "rpas_license",    "en": "I hold a valid RPAS pilot license",                   "bn": "Amar valid RPAS pilot license ase",            "category": "license"},
    {"id": "insurance",       "en": "Drone is covered by third-party liability insurance", "bn": "Drone er third-party insurance ase",           "category": "insurance"},
    {"id": "vlos",            "en": "I will fly within visual line of sight (VLOS) only",  "bn": "VLOS er bhitor e fly korbo",                   "category": "ops"},
    {"id": "altitude",        "en": "I will stay below 400 ft AGL",                        "bn": "400 ft AGL er niche thakbo",                   "category": "ops"},
    {"id": "daytime",         "en": "Flight is during daylight hours only",                "bn": "Flight sudhu day-time e",                      "category": "ops"},
    {"id": "no_fly_zone",     "en": "Takeoff site is not in a restricted / no-fly zone",   "bn": "Takeoff jaiga restricted / no-fly zone na",    "category": "ops"},
    {"id": "people_distance", "en": "I will maintain ≥50 m distance from people",          "bn": "Manuser theke 50m+ dur thakbo",                "category": "ops"},
    {"id": "weather",         "en": "Weather is within drone operational limits",          "bn": "Weather drone er operating limit er moddhe",   "category": "ops"},
    {"id": "preflight_check", "en": "Pre-flight checklist completed",                      "bn": "Pre-flight checklist complete",                "category": "ops"},
    {"id": "log_retained",    "en": "Flight log will be retained for ≥6 months",           "bn": "Flight log 6 mash store korbo",                "category": "records"},
    {"id": "remote_id",       "en": "Remote ID broadcasting (if applicable in your area)", "bn": "Remote ID broadcasting (jodi require kore)",   "category": "tech"},
    {"id": "geofence",        "en": "Geofence configured around takeoff site",             "bn": "Geofence configured",                          "category": "tech"},
    {"id": "rth",             "en": "Return-to-home tested and working",                   "bn": "RTH test kora ar working",                     "category": "tech"},
    {"id": "failsafe",        "en": "Battery failsafe and signal-loss failsafe configured", "bn": "Battery + signal-loss failsafe configured",   "category": "tech"},
]


def weight_class_for(weight_g: float | None) -> dict:
    if weight_g is None:
        return WEIGHT_CATEGORIES[1]
    wkg = weight_g / 1000.0
    for cat in WEIGHT_CATEGORIES:
        if cat["min_kg"] <= wkg < cat["max_kg"]:
            return cat
    return WEIGHT_CATEGORIES[-1]


def assess(answers: dict[str, str] | None = None, drone_weight_g: float | None = None) -> dict[str, Any]:
    """answers map id -> 'yes' | 'no' | 'na'.  Returns compliance score and items."""
    answers = answers or {}
    cat = weight_class_for(drone_weight_g)
    yes_count = 0
    no_count = 0
    na_count = 0
    pending = 0
    items: list[dict] = []
    for c in CHECKLIST:
        ans = answers.get(c["id"], "")
        applies = True
        # Some checks only apply by weight class
        if c["id"] == "caab_registered" and not cat["registration_required"]:
            applies = False
        if c["id"] == "rpas_license" and not cat["license_required"]:
            applies = False
        if not applies:
            items.append({**c, "answer": "na", "applies": False})
            continue
        items.append({**c, "answer": ans or "pending", "applies": True})
        if ans == "yes": yes_count += 1
        elif ans == "no": no_count += 1
        elif ans == "na": na_count += 1
        else: pending += 1

    answerable = sum(1 for i in items if i["applies"])
    score_pct = round(100 * yes_count / max(answerable, 1))
    status = "good" if no_count == 0 and pending == 0 else ("poor" if no_count else "fair")

    return {
        "weight_class": cat,
        "drone_weight_g": drone_weight_g,
        "score_pct": score_pct,
        "status": status,
        "summary_en": (
            f"All applicable checks pass. {cat['label_en']} class ({cat['min_kg']}–{cat['max_kg']} kg)."
            if no_count == 0 and pending == 0 else
            f"{no_count} non-compliant item(s), {pending} unanswered. {cat['label_en']} class."
        ),
        "summary_bn": (
            f"Sob applicable check pass. {cat['label_bn']} class ({cat['min_kg']}–{cat['max_kg']} kg)."
            if no_count == 0 and pending == 0 else
            f"{no_count} ta non-compliant, {pending} ta answer nai. {cat['label_bn']} class."
        ),
        "yes": yes_count,
        "no": no_count,
        "na": na_count,
        "pending": pending,
        "items": items,
    }
