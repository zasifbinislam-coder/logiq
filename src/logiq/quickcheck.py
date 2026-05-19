"""
LogIQ — Quick health check wizard.

Pre-flight 5-question survey for operators who don't have a log file ready.
Maps yes/no answers to risk score + action list.
"""
from __future__ import annotations


QUESTIONS = [
    {
        "key": "vibration",
        "en": "Did you hear unusual buzzing or feel extra shaking last flight?",
        "bn": "Last flight e drone abnormal buzz korechilo ba beshi shaking chilo?",
        "yes_weight": 35,
        "advice_en": "Inspect propellers for cracks, balance them, tighten motor screws.",
        "advice_bn": "Propeller crack ase ki dekho, balance koro, motor screw tight koro.",
    },
    {
        "key": "control",
        "en": "Did the drone struggle to follow your control inputs?",
        "bn": "Drone tomar command thik moto follow korte parchhilo na?",
        "yes_weight": 30,
        "advice_en": "Re-tune PID gains, check for damaged props or frame.",
        "advice_bn": "PID re-tune koro, prop or frame e damage ase ki dekho.",
    },
    {
        "key": "gps",
        "en": "Was the GPS slow to lock or unreliable during flight?",
        "bn": "GPS lock korte slow chhilo ba reliable na?",
        "yes_weight": 20,
        "advice_en": "Wait for 8+ satellites before takeoff; fly in open area away from buildings.",
        "advice_bn": "Takeoff er age 8+ satellite lock kore nao; open jaiga te fly koro.",
    },
    {
        "key": "battery",
        "en": "Did the battery feel hot or did flight time drop a lot?",
        "bn": "Battery garam hoyechhilo ba flight time onek kome gechhe?",
        "yes_weight": 25,
        "advice_en": "Cycle the battery, check cell voltages, retire if any cell is sagging.",
        "advice_bn": "Battery cycle koro, cell voltage check koro, kono cell sag korle replace koro.",
    },
    {
        "key": "physical",
        "en": "Any visible damage on props, motors, frame, or wires?",
        "bn": "Prop, motor, frame, wire e kono visible damage ase?",
        "yes_weight": 40,
        "advice_en": "DO NOT fly. Replace damaged parts before next flight.",
        "advice_bn": "FLY KORO NA. Damaged part replace na kora porjonto na.",
    },
]


def assess(answers: dict[str, bool]) -> dict:
    """answers maps question key -> True (yes) / False (no)."""
    risk = 0
    actions_en: list[str] = []
    actions_bn: list[str] = []
    answered = 0
    yes_count = 0

    for q in QUESTIONS:
        if q["key"] not in answers:
            continue
        answered += 1
        ans = bool(answers[q["key"]])
        if ans:
            yes_count += 1
            risk += q["yes_weight"]
            actions_en.append(q["advice_en"])
            actions_bn.append(q["advice_bn"])

    risk = min(risk, 100)
    health = max(0, 100 - risk)

    if health >= 85:
        status, summary_en, summary_bn = "good", "Drone seems fine to fly.", "Drone fly korar moto theek ase."
    elif health >= 65:
        status, summary_en, summary_bn = "fair", "Mostly fine, but address the items below.", "Beshirvag theek, kintu niche er item gulo dekho."
    elif health >= 40:
        status, summary_en, summary_bn = "poor", "Concerns detected. Inspect before next flight.", "Problem paya gechhe. Next flight er age check koro."
    else:
        status, summary_en, summary_bn = "critical", "DO NOT FLY. Multiple serious issues.", "FLY KORO NA. Onek serious problem ase."

    return {
        "health_score": health,
        "risk_score": risk,
        "status": status,
        "summary_en": summary_en,
        "summary_bn": summary_bn,
        "answered": answered,
        "yes_count": yes_count,
        "actions_en": actions_en,
        "actions_bn": actions_bn,
    }
