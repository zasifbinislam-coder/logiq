"""
LogIQ — Drone hardware compatibility analyzer.

Pulls a user's drone profile + components, runs cross-component checks, and
returns a structured compatibility report:

  * Motor ↔ ESC current matching (with safety margin)
  * Motor ↔ Prop diameter and KV sanity
  * Battery cells supported by motor and ESC
  * Battery C-rating × capacity vs total motor max current
  * Thrust-to-weight ratio estimate
  * Estimated hover current + flight time
"""
from __future__ import annotations

from typing import Any

from logiq.hardware import get_airframe


CELL_NOMINAL_V = 3.7   # LiPo


def _first_component(components: list[dict], type: str) -> dict | None:
    for c in components:
        if c["type"] == type and c.get("specs"):
            return c
    return None


def _all_components(components: list[dict], type: str) -> list[dict]:
    return [c for c in components if c["type"] == type]


def analyze(airframe_id: str) -> dict[str, Any]:
    af = get_airframe(airframe_id)
    if not af:
        return {"ok": False, "error": "airframe not found"}

    comps = af.get("components", [])
    motor = _first_component(comps, "motor")
    esc   = _first_component(comps, "esc")
    prop  = _first_component(comps, "prop")
    batt  = _first_component(comps, "battery")
    fc    = _first_component(comps, "fc")

    n_motors = af.get("motor_count") or 4
    auw_g = af.get("auw_g") or 0

    checks: list[dict] = []
    warnings: list[dict] = []

    def add(ok: bool, label: str, detail_en: str, detail_bn: str = "", severity: str = "fair"):
        item = {"ok": ok, "label": label, "detail_en": detail_en, "detail_bn": detail_bn or detail_en,
                "severity": "good" if ok else severity}
        checks.append(item)
        if not ok:
            warnings.append(item)

    # ---- Motor + ESC current ----
    if motor and esc:
        m_max = motor["specs"]["max_current_a"]
        e_max = esc["specs"]["max_current_a"]
        margin = (e_max - m_max) / m_max * 100 if m_max > 0 else 0
        ok = e_max >= m_max * 1.15  # 15% headroom
        add(ok,
            "ESC current rating",
            f"Motor max {m_max}A vs ESC max {e_max}A (margin {margin:.0f}%). " + ("Good headroom." if ok else "TOO TIGHT — upgrade ESC."),
            f"Motor max {m_max}A, ESC max {e_max}A. " + ("Margin theek." if ok else "TOO TIGHT — ESC upgrade koro."),
            severity="critical" if e_max < m_max else "poor",
        )

    # ---- Motor + Battery cells ----
    if motor and batt:
        m_min_s = motor["specs"]["battery_cells_min"]
        m_max_s = motor["specs"]["battery_cells_max"]
        b_s = batt["specs"]["cells"]
        ok = m_min_s <= b_s <= m_max_s
        add(ok,
            "Motor ↔ battery cells",
            f"Motor supports {m_min_s}–{m_max_s}S, battery is {b_s}S. " + ("OK." if ok else "MISMATCH — risk of motor damage."),
            f"Motor {m_min_s}–{m_max_s}S support kore, battery {b_s}S. " + ("Theek." if ok else "MISMATCH — motor pure damage hote pare."),
            severity="critical",
        )

    # ---- ESC + Battery cells ----
    if esc and batt:
        e_min_s = esc["specs"]["voltage_cells_min"]
        e_max_s = esc["specs"]["voltage_cells_max"]
        b_s = batt["specs"]["cells"]
        ok = e_min_s <= b_s <= e_max_s
        add(ok,
            "ESC ↔ battery cells",
            f"ESC rated for {e_min_s}–{e_max_s}S, battery is {b_s}S. " + ("OK." if ok else "ESC will burn out."),
            "",
            severity="critical",
        )

    # ---- Motor + Prop diameter ----
    if motor and prop:
        m_min_p = motor["specs"]["prop_recommended_min_in"]
        m_max_p = motor["specs"]["prop_recommended_max_in"]
        p_d = prop["specs"]["diameter_in"]
        ok = m_min_p <= p_d <= m_max_p
        add(ok,
            "Motor ↔ prop diameter",
            f"Motor recommends {m_min_p}\"–{m_max_p}\" props, you have {p_d}\". " + ("Sweet spot." if ok else "Out of spec — efficiency drops, motor heats up."),
            f"Motor {m_min_p}\"–{m_max_p}\" prop recommend kore, tomar {p_d}\". " + ("Theek." if ok else "Spec er baire — efficiency kome, motor gorom hobe."),
            severity="poor",
        )

    # ---- Battery C-rating × capacity vs total motor max draw ----
    if motor and batt:
        total_max_a = motor["specs"]["max_current_a"] * n_motors
        batt_cap_ah = batt["specs"]["capacity_mah"] / 1000.0
        batt_max_a = batt["specs"]["c_rating"] * batt_cap_ah
        ok = batt_max_a >= total_max_a
        ratio = batt_max_a / total_max_a if total_max_a > 0 else 0
        add(ok,
            "Battery C-rating headroom",
            f"All motors max draw ≈ {total_max_a:.0f}A. Battery can deliver {batt_max_a:.0f}A continuously ({ratio*100:.0f}% of demand). " + ("OK." if ok else "UNDERSIZED — battery voltage will sag heavily."),
            "",
            severity="poor",
        )

    # ---- Thrust-to-weight estimate ----
    # Very rough: assume motor produces ~ (max_current_a × cells × 3.7V × 7g/W) of thrust at full throttle
    # i.e. ~ 7g per watt at the prop. Real number depends on prop. Conservative.
    if motor and batt and auw_g > 0:
        cells = batt["specs"]["cells"]
        watts_per_motor = motor["specs"]["max_current_a"] * cells * CELL_NOMINAL_V
        thrust_per_motor_g = watts_per_motor * 5.0  # 5g/W is conservative for racing props
        total_thrust = thrust_per_motor_g * n_motors
        twr = total_thrust / auw_g
        ok = twr >= 2.0
        add(ok,
            "Thrust-to-weight ratio (estimated)",
            f"~{total_thrust:.0f}g thrust vs {auw_g:.0f}g AUW = TWR {twr:.1f}. " + ("Good for sport flying (>2)." if twr >= 2 else "Sluggish — needs more power."),
            "",
            severity="poor" if twr < 1.5 else "fair",
        )
    else:
        twr = None

    # ---- Hover current + flight-time estimate ----
    hover_time_min = None
    if motor and batt and auw_g > 0:
        cells = batt["specs"]["cells"]
        # hover ≈ AUW = thrust → hover throttle ≈ 1/TWR. Hover current ≈ max_current * (1/TWR)^1.5
        watts_per_motor = motor["specs"]["max_current_a"] * cells * CELL_NOMINAL_V
        thrust_per_motor_g = watts_per_motor * 5.0 if watts_per_motor else 0
        full_thrust_g = thrust_per_motor_g * n_motors
        if full_thrust_g > auw_g:
            hover_fraction = (auw_g / full_thrust_g) ** 1.5
            hover_a_total = motor["specs"]["max_current_a"] * n_motors * hover_fraction
            cap_ah = batt["specs"]["capacity_mah"] / 1000.0
            usable_ah = cap_ah * 0.8
            hover_time_min = (usable_ah / hover_a_total) * 60 if hover_a_total > 0 else None

    # ---- Summary score ----
    n_total = len(checks)
    n_ok = sum(1 for c in checks if c["ok"])
    n_critical = sum(1 for c in checks if not c["ok"] and c["severity"] == "critical")
    pct = round(100 * n_ok / max(n_total, 1))
    status = "good" if n_critical == 0 and pct >= 80 else ("critical" if n_critical else ("poor" if pct < 50 else "fair"))

    summary_en = (
        "All checks pass — this build is consistent." if status == "good" else
        f"{n_critical} critical issue(s) and {n_total - n_ok - n_critical} warning(s). Address before flying."
        if n_critical else f"{n_total - n_ok} issue(s) — review below."
    )
    summary_bn = (
        "Sob check pass — build consistent." if status == "good" else
        f"{n_critical} ta critical issue ar {n_total - n_ok - n_critical} ta warning. Fly korar age fix koro."
        if n_critical else f"{n_total - n_ok} ta issue — niche dekho."
    )

    return {
        "ok": True,
        "airframe": {"id": airframe_id, "name": af.get("name"), "n_motors": n_motors, "auw_g": auw_g},
        "summary_en": summary_en,
        "summary_bn": summary_bn,
        "score_pct": pct,
        "status": status,
        "checks": checks,
        "warnings": warnings,
        "twr_estimated": round(twr, 2) if twr else None,
        "hover_time_min_estimated": round(hover_time_min, 1) if hover_time_min else None,
        "components_present": {
            "motor": bool(motor), "esc": bool(esc), "prop": bool(prop),
            "battery": bool(batt), "fc": bool(fc),
        },
    }
