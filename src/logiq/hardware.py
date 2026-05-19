"""
LogIQ — User drone hardware profiles.

A drone-profile is a named build with attached components. Lives separately
from the auto-detected airframe buckets (those come from Mission Planner
folder structure).

Tables:
  user_airframes  — user-named drone builds
  user_components — components attached to a build
"""
from __future__ import annotations

import json
import uuid

from logiq.db import get_conn
from logiq.component_db import get_by_id


SCHEMA_EXTRA = """
CREATE TABLE IF NOT EXISTS user_airframes (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  name TEXT NOT NULL,
  description TEXT,
  frame_class TEXT,           -- quad / hex / octo / plane / vtol
  frame_size_mm INTEGER,
  motor_count INTEGER DEFAULT 4,
  auw_g REAL,                 -- all-up weight in grams
  notes TEXT,
  created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_user_airframes_user ON user_airframes(user_id);

CREATE TABLE IF NOT EXISTS user_components (
  id TEXT PRIMARY KEY,
  airframe_id TEXT NOT NULL REFERENCES user_airframes(id) ON DELETE CASCADE,
  type TEXT NOT NULL,         -- motor, esc, prop, battery, fc
  catalog_id TEXT,            -- reference into component_db.CATALOG
  custom_name TEXT,           -- user can free-form
  quantity INTEGER DEFAULT 1,
  specs_json TEXT,            -- frozen snapshot of catalog spec at add time
  unit_price_bdt REAL,
  vendor TEXT,
  purchased_at TEXT,
  notes TEXT,
  added_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_user_components_airframe ON user_components(airframe_id);
"""


def _migrate():
    """Add new price columns if they don't exist (idempotent)."""
    con = get_conn()
    cols = {r["name"] for r in con.execute("PRAGMA table_info(user_components)").fetchall()}
    for col, sqltype in [("unit_price_bdt", "REAL"), ("vendor", "TEXT"), ("purchased_at", "TEXT")]:
        if col not in cols:
            con.execute(f"ALTER TABLE user_components ADD COLUMN {col} {sqltype}")
    con.commit()
    con.close()


def init():
    con = get_conn()
    con.executescript(SCHEMA_EXTRA)
    con.commit()
    con.close()
    _migrate()


def create_airframe(user_id: str, *, name: str, description: str = "",
                    frame_class: str = "quad", frame_size_mm: int | None = None,
                    motor_count: int = 4, auw_g: float | None = None,
                    notes: str = "") -> dict:
    init()
    aid = str(uuid.uuid4())
    con = get_conn()
    con.execute(
        """INSERT INTO user_airframes (id, user_id, name, description, frame_class, frame_size_mm, motor_count, auw_g, notes)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (aid, user_id, name, description or None, frame_class, frame_size_mm, motor_count, auw_g, notes or None),
    )
    con.commit()
    con.close()
    return get_airframe(aid)


def list_airframes(user_id: str) -> list[dict]:
    init()
    con = get_conn()
    rows = con.execute("SELECT * FROM user_airframes WHERE user_id = ? ORDER BY created_at DESC", (user_id,)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["components"] = list_components(d["id"])
        out.append(d)
    con.close()
    return out


def get_airframe(airframe_id: str) -> dict | None:
    con = get_conn()
    r = con.execute("SELECT * FROM user_airframes WHERE id = ?", (airframe_id,)).fetchone()
    con.close()
    if not r:
        return None
    d = dict(r)
    d["components"] = list_components(airframe_id)
    return d


def update_airframe(airframe_id: str, **fields) -> dict | None:
    if not fields:
        return get_airframe(airframe_id)
    allowed = {"name", "description", "frame_class", "frame_size_mm", "motor_count", "auw_g", "notes"}
    sets, vals = [], []
    for k, v in fields.items():
        if k in allowed and v is not None:
            sets.append(f"{k} = ?")
            vals.append(v)
    if not sets:
        return get_airframe(airframe_id)
    vals.append(airframe_id)
    con = get_conn()
    con.execute(f"UPDATE user_airframes SET {', '.join(sets)} WHERE id = ?", vals)
    con.commit()
    con.close()
    return get_airframe(airframe_id)


def delete_airframe(airframe_id: str):
    con = get_conn()
    con.execute("DELETE FROM user_components WHERE airframe_id = ?", (airframe_id,))
    con.execute("DELETE FROM user_airframes WHERE id = ?", (airframe_id,))
    con.commit()
    con.close()


def add_component(airframe_id: str, *, type: str, catalog_id: str | None = None,
                  custom_name: str = "", quantity: int = 1, notes: str = "",
                  unit_price_bdt: float | None = None, vendor: str = "",
                  purchased_at: str = "") -> dict:
    init()
    cid = str(uuid.uuid4())
    specs = None
    if catalog_id:
        c = get_by_id(type, catalog_id)
        if c:
            specs = json.dumps(c)
    con = get_conn()
    con.execute(
        """INSERT INTO user_components (id, airframe_id, type, catalog_id, custom_name, quantity, specs_json, notes, unit_price_bdt, vendor, purchased_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (cid, airframe_id, type, catalog_id, custom_name or None, quantity, specs, notes or None,
         unit_price_bdt, vendor or None, purchased_at or None),
    )
    con.commit()
    con.close()
    return get_component(cid)


def total_build_cost(airframe_id: str) -> dict:
    """Sum component prices for one drone build."""
    comps = list_components(airframe_id)
    total = 0.0
    by_type: dict[str, float] = {}
    have_prices = 0
    missing_prices = 0
    for c in comps:
        unit = c.get("unit_price_bdt")
        qty = c.get("quantity") or 1
        if unit is not None:
            line = unit * qty
            total += line
            by_type[c["type"]] = by_type.get(c["type"], 0) + line
            have_prices += 1
        else:
            missing_prices += 1
    return {
        "total_bdt": round(total, 2),
        "by_type": {k: round(v, 2) for k, v in by_type.items()},
        "components_with_price": have_prices,
        "components_missing_price": missing_prices,
    }


def list_components(airframe_id: str) -> list[dict]:
    con = get_conn()
    rows = con.execute("SELECT * FROM user_components WHERE airframe_id = ? ORDER BY type, added_at", (airframe_id,)).fetchall()
    con.close()
    out = []
    for r in rows:
        d = dict(r)
        if d.get("specs_json"):
            try:
                d["specs"] = json.loads(d["specs_json"])
            except Exception:
                d["specs"] = None
        out.append(d)
    return out


def get_component(component_id: str) -> dict | None:
    con = get_conn()
    r = con.execute("SELECT * FROM user_components WHERE id = ?", (component_id,)).fetchone()
    con.close()
    if not r:
        return None
    d = dict(r)
    if d.get("specs_json"):
        try:
            d["specs"] = json.loads(d["specs_json"])
        except Exception:
            d["specs"] = None
    return d


def delete_component(component_id: str):
    con = get_conn()
    con.execute("DELETE FROM user_components WHERE id = ?", (component_id,))
    con.commit()
    con.close()


# Pre-built drone templates (component bundle for one-click setup)
TEMPLATES = {
    "freestyle_5":  {
        "name": "Standard 5\" Freestyle",
        "description": "Typical 5-inch acro/freestyle quad with 4S/6S power",
        "frame_class": "quad", "motor_count": 4, "auw_g": 580, "frame_size_mm": 220,
        "components": [
            {"type": "motor",   "catalog_id": "iflight_xing_2207_1855", "quantity": 4},
            {"type": "esc",     "catalog_id": "holybro_tekko32_65a",    "quantity": 1},
            {"type": "prop",    "catalog_id": "hqprop_5x4_3x3",          "quantity": 4},
            {"type": "battery", "catalog_id": "cnhl_black_1500_4s_100c", "quantity": 1},
            {"type": "fc",      "catalog_id": "speedybee_f7v3",          "quantity": 1},
        ],
    },
    "cinematic_7": {
        "name": "Cinematic 7\" long-range",
        "description": "Long-range cinematic platform; 6S, big prop",
        "frame_class": "quad", "motor_count": 4, "auw_g": 850, "frame_size_mm": 295,
        "components": [
            {"type": "motor",   "catalog_id": "tmotor_f60_pro_v_1750",  "quantity": 4},
            {"type": "esc",     "catalog_id": "tmotor_f45a_v2",         "quantity": 1},
            {"type": "prop",    "catalog_id": "gemfan_5152s",            "quantity": 4},
            {"type": "battery", "catalog_id": "tattu_5200_4s_15c",       "quantity": 1},
            {"type": "fc",      "catalog_id": "matek_h743_wing",         "quantity": 1},
        ],
    },
    "tinywhoop": {
        "name": "Tinywhoop 65mm",
        "description": "Indoor / micro brushless whoop",
        "frame_class": "quad", "motor_count": 4, "auw_g": 30, "frame_size_mm": 65,
        "components": [
            {"type": "motor", "catalog_id": "happymodel_se1404_2900", "quantity": 4},
            {"type": "esc",   "catalog_id": "blheli_s_20a",            "quantity": 1},
            {"type": "prop",  "catalog_id": "hq_t3x3x3",               "quantity": 4},
            {"type": "fc",    "catalog_id": "speedybee_f7v3",          "quantity": 1},
        ],
    },
    "agri_hex_15kg": {
        "name": "Agricultural hex (15kg)",
        "description": "Heavy-lift agri-spray hex with 6S2P battery",
        "frame_class": "hex", "motor_count": 6, "auw_g": 15000, "frame_size_mm": 1200,
        "components": [
            {"type": "motor",   "catalog_id": "tmotor_u8ii_100",         "quantity": 6},
            {"type": "esc",     "catalog_id": "tmotor_alpha_60a_hv",     "quantity": 6},
            {"type": "prop",    "catalog_id": "tmotor_carbon_22x66",     "quantity": 6},
            {"type": "battery", "catalog_id": "tattu_plus_62000_6s2p_15c", "quantity": 1},
            {"type": "fc",      "catalog_id": "pixhawk_cube_orange",     "quantity": 1},
        ],
    },
    "photo_quad": {
        "name": "Photography quad (10\")",
        "description": "Aerial photo platform with 4S 5200mAh and 1045 props",
        "frame_class": "quad", "motor_count": 4, "auw_g": 1400, "frame_size_mm": 450,
        "components": [
            {"type": "motor",   "catalog_id": "dji_2212_920",        "quantity": 4},
            {"type": "esc",     "catalog_id": "hobbywing_skywalker_40a", "quantity": 4},
            {"type": "prop",    "catalog_id": "dji_1045",             "quantity": 4},
            {"type": "battery", "catalog_id": "tattu_5200_4s_15c",    "quantity": 1},
            {"type": "fc",      "catalog_id": "pixhawk_6c",           "quantity": 1},
        ],
    },
}


def create_from_template(user_id: str, template_key: str, custom_name: str = "") -> dict:
    tmpl = TEMPLATES.get(template_key)
    if not tmpl:
        raise ValueError(f"unknown template: {template_key}")
    af = create_airframe(
        user_id,
        name=custom_name or tmpl["name"],
        description=tmpl["description"],
        frame_class=tmpl["frame_class"],
        frame_size_mm=tmpl["frame_size_mm"],
        motor_count=tmpl["motor_count"],
        auw_g=tmpl["auw_g"],
    )
    for c in tmpl["components"]:
        add_component(af["id"], type=c["type"], catalog_id=c["catalog_id"], quantity=c["quantity"])
    return get_airframe(af["id"])
