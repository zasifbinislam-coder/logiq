"""
LogIQ — Pilot certification quiz.

Curated multiple-choice questions for ArduPilot / multi-rotor operators,
inspired by typical RPAS / CAAB study material. Used in the gamified
quiz tab.
"""
from __future__ import annotations

import random
from typing import Any


QUESTIONS = [
    {
        "id": 1,
        "en": "What does VLOS stand for?",
        "bn": "VLOS er full form ki?",
        "options": [
            "Visual Line Of Sight",
            "Vertical Landing Of Sight",
            "Voltage Limited Operating System",
            "Vehicle Lateral Operating Speed",
        ],
        "correct": 0,
        "explain_en": "VLOS = Visual Line Of Sight. Most CAAB-class drones must be flown within VLOS.",
        "explain_bn": "VLOS = Visual Line Of Sight. CAAB rule e drone VLOS er bhitor fly korte hobe.",
        "topic": "regulation",
    },
    {
        "id": 2,
        "en": "What is the typical maximum allowed altitude AGL for hobby drone flights in Bangladesh?",
        "bn": "Bangladesh e hobby drone er max allowed altitude AGL kotota?",
        "options": ["100 ft", "200 ft", "400 ft", "1000 ft"],
        "correct": 2,
        "explain_en": "CAAB 2020 specifies 400 ft AGL as the upper limit for most categories.",
        "explain_bn": "CAAB 2020 onujayi 400 ft AGL most category er upper limit.",
        "topic": "regulation",
    },
    {
        "id": 3,
        "en": "If 'VIBE Z' is > 30 m/s² in an ArduPilot log, what is the most likely cause?",
        "bn": "ArduPilot log e VIBE Z > 30 m/s² hole most likely cause ki?",
        "options": [
            "GPS interference",
            "Damaged or unbalanced propeller",
            "Wrong compass orientation",
            "Low battery",
        ],
        "correct": 1,
        "explain_en": "Excessive Z-axis vibration almost always traces back to prop balance, prop damage, or loose motor mount.",
        "explain_bn": "Z-axis er onek vibration mane prop balance, prop damage, ba loose motor mount.",
        "topic": "diagnostics",
    },
    {
        "id": 4,
        "en": "What does IMU 'clipping' mean in a flight log?",
        "bn": "Flight log e IMU 'clipping' mane ki?",
        "options": [
            "GPS fix was lost briefly",
            "Accelerometer hit its measurement saturation limit",
            "ESC was clipped to a lower voltage",
            "Radio signal was cut",
        ],
        "correct": 1,
        "explain_en": "Clipping = accelerometer reading hit ±16g (or sensor max). High clip counts mean severe vibration.",
        "explain_bn": "Clipping = accelerometer reading max limit hit korechhe. Beshi clip = severe vibration.",
        "topic": "diagnostics",
    },
    {
        "id": 5,
        "en": "An ESC is rated for 30A continuous, 40A burst. Your motor pulls 28A max at full throttle. Is this combo safe?",
        "bn": "ESC 30A continuous, 40A burst. Motor max 28A pull kore. Safe?",
        "options": [
            "Yes — well within ESC rating",
            "Marginal — recommend 15%+ headroom",
            "No — ESC will explode",
            "Cannot say without battery cell count",
        ],
        "correct": 1,
        "explain_en": "28A vs 30A is only ~7% headroom. Best practice is ≥15% to handle prop wash, temperature, and ageing.",
        "explain_bn": "28A vs 30A = ~7% headroom. Best practice 15%+ — temperature ar ageing er jonno.",
        "topic": "hardware",
    },
    {
        "id": 6,
        "en": "What is the safe minimum voltage per cell for a LiPo at landing?",
        "bn": "LiPo cell er minimum safe voltage at landing koto?",
        "options": ["2.5 V", "3.0 V", "3.3 V", "3.7 V"],
        "correct": 2,
        "explain_en": "3.3 V per cell under load is the practical floor. Going below 3.0 V damages cells permanently.",
        "explain_bn": "Load er moddhe 3.3V/cell minimum. 3.0V er niche permanent damage hobe.",
        "topic": "hardware",
    },
    {
        "id": 7,
        "en": "What is the typical recommended thrust-to-weight ratio for a freestyle / sport quadcopter?",
        "bn": "Freestyle / sport quad er recommended thrust-to-weight ratio koto?",
        "options": ["0.8:1", "1.5:1", "≥ 2:1", "5:1+"],
        "correct": 2,
        "explain_en": "≥ 2:1 means the drone can hover at 50% throttle. Less than that = sluggish, hard to recover.",
        "explain_bn": "2:1 mane drone 50% throttle e hover korte pare. Tar kom hole sluggish.",
        "topic": "hardware",
    },
    {
        "id": 8,
        "en": "An ArduPilot 'EKF mag variance' alarm during flight indicates:",
        "bn": "ArduPilot 'EKF mag variance' alarm mane ki?",
        "options": [
            "Battery voltage sag",
            "Compass is being disturbed (metal, magnets, power wires)",
            "GPS is too accurate",
            "ESC clip detected",
        ],
        "correct": 1,
        "explain_en": "EKF mag variance high = compass disagrees with the EKF state. Usually magnetic interference.",
        "explain_bn": "EKF mag variance high = compass EKF state er sathe disagree. Usually magnetic interference.",
        "topic": "diagnostics",
    },
    {
        "id": 9,
        "en": "Before takeoff, the recommended minimum number of GPS satellites locked is:",
        "bn": "Takeoff er age minimum koto GPS satellite lock kora uchit?",
        "options": ["4", "6", "8", "12"],
        "correct": 2,
        "explain_en": "8+ satellites and HDOP < 1.5 is the practical threshold for safe autonomous flight.",
        "explain_bn": "8+ satellite ar HDOP < 1.5 — safe autonomous flight er threshold.",
        "topic": "operations",
    },
    {
        "id": 10,
        "en": "Geofence in ArduPilot is primarily a:",
        "bn": "ArduPilot geofence mane ki?",
        "options": [
            "Physical net you install around your drone",
            "Software-defined boundary that triggers a failsafe if breached",
            "Type of propeller guard",
            "Backup GPS module",
        ],
        "correct": 1,
        "explain_en": "Geofence is a software boundary. Breach triggers RTL/land/brake depending on configuration.",
        "explain_bn": "Geofence ekta software boundary. Cross korle RTL/land/brake trigger hoy.",
        "topic": "operations",
    },
]


def get_question(idx: int) -> dict:
    return QUESTIONS[idx % len(QUESTIONS)]


def grade(answers: dict[int, int]) -> dict[str, Any]:
    """answers map question_id -> chosen option index."""
    correct = 0
    total_answered = 0
    by_topic: dict[str, dict] = {}
    items: list[dict] = []
    for q in QUESTIONS:
        chosen = answers.get(q["id"])
        if chosen is None:
            items.append({**q, "chosen": None, "is_correct": None})
            continue
        total_answered += 1
        ok = chosen == q["correct"]
        if ok: correct += 1
        topic = q["topic"]
        by_topic.setdefault(topic, {"correct": 0, "total": 0})
        by_topic[topic]["total"] += 1
        if ok: by_topic[topic]["correct"] += 1
        items.append({**q, "chosen": chosen, "is_correct": ok})

    score_pct = round(100 * correct / max(total_answered, 1))
    return {
        "answered": total_answered,
        "total_questions": len(QUESTIONS),
        "correct": correct,
        "score_pct": score_pct,
        "pass": score_pct >= 70,
        "by_topic": {k: {**v, "pct": round(100 * v["correct"] / max(v["total"], 1))} for k, v in by_topic.items()},
        "items": items,
        "verdict_en": "Pass — you're certified ready for solo flight." if score_pct >= 70 else "Below pass — review the topics above.",
        "verdict_bn": "Pass — solo flight er jonno ready." if score_pct >= 70 else "Pass holo na — niche topic gulo review koro.",
    }
