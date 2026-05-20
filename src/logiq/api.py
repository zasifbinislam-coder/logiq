"""
LogIQ — FastAPI backend.

REST endpoints:
  GET  /api/stats              -> KPIs
  GET  /api/airframes          -> list buckets
  GET  /api/flights            -> list flights (paginated, filterable)
  GET  /api/flight/{id}        -> single flight w/ features + anomaly
  GET  /api/anomalies          -> top anomalies
  GET  /api/trends             -> monthly aggregates
  POST /api/upload             -> upload a .bin or .tlog, extract features, return flight id

Static:
  /reports/...                 -> serves the pre-generated HTML reports
  /                            -> main dashboard
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional
import json
import os
import uuid

from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Query
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from logiq.db import get_conn, DB_PATH, folder_label, upsert_airframe, init_schema
from logiq.extract import extract_features
from logiq.verdict import compute_verdict
from logiq.pdf_report import build_pdf
from logiq.quickcheck import QUESTIONS as QUICK_QUESTIONS, assess as quick_assess
from logiq.labels import LABELS as LABEL_OPTIONS, set_label as set_flight_label, get_label as get_flight_label, init as init_labels, stats as label_stats
from logiq.photo_check import analyze_photo
from logiq.notify import alert_if_anomaly
from logiq.flight_path import extract_path
from logiq.cost import estimate_cost
from logiq.achievements import compute as compute_badges
from logiq.maintenance import (
    init as init_maint, add_entry as add_maint, list_for_flight as maint_for_flight,
    list_all as maint_list, stats as maint_stats, MAINT_TYPES
)
from logiq.battery import per_airframe_battery_trends
from logiq.components import per_airframe_component_status
from logiq.autotag import suggest_tag
from logiq.leaderboard import airframe_leaderboard
from logiq.weather import fetch_weather, correlate_with_anomalies
from logiq.insurance_pdf import build_insurance_pdf
from logiq import users as users_mod
from logiq import hardware as hw_mod
from logiq import compatibility as compat_mod
from logiq import component_db
from logiq import compliance as compliance_mod
from logiq import quiz as quiz_mod
from logiq import public_share as share_mod
from logiq.logbook import build_logbook_pdf
from fastapi import Cookie, Depends
try:
    from logiq.whatsapp import router as whatsapp_router
except Exception:
    whatsapp_router = None

# Core SQL schema (fleets / airframes / flights / features / anomalies).
# Without this, a fresh container hits "no such table: fleets" on first
# signup. Idempotent — safe to call on every boot.
init_schema()
init_labels()
init_maint()
users_mod.init()
hw_mod.init()

# Production-only cookie hardening — set LOGIQ_COOKIE_SECURE=1 when deployed
# behind HTTPS so session cookies aren't sent over plain HTTP.
_COOKIE_SECURE = os.environ.get("LOGIQ_COOKIE_SECURE", "").lower() in ("1", "true", "yes")


# Derive the repo root from this file's location so the app is portable
# across machines/drives. Override with LOGIQ_BASE_DIR if needed.
BASE_DIR = Path(os.environ.get("LOGIQ_BASE_DIR") or Path(__file__).resolve().parents[2])
REPORTS_DIR = BASE_DIR / "reports"
UPLOADS_DIR = BASE_DIR / "data" / "uploads"
WEB_DIR = BASE_DIR / "web"

UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="LogIQ API", version="0.0.2")
if whatsapp_router is not None:
    app.include_router(whatsapp_router, prefix="/api")


def _row_to_dict(row) -> dict:
    return {k: row[k] for k in row.keys()}


@app.get("/api/stats")
def stats():
    con = get_conn()
    n_flights = con.execute("SELECT COUNT(*) AS n FROM flights WHERE parse_error IS NULL").fetchone()["n"]
    tot_hours = con.execute("SELECT ROUND(SUM(duration_s)/3600.0,1) AS h FROM flights WHERE parse_error IS NULL").fetchone()["h"]
    n_anom = con.execute("SELECT COUNT(*) AS n FROM anomalies WHERE is_anomaly = 1").fetchone()["n"]
    by_airframe = con.execute("""
        SELECT a.bucket, COUNT(f.id) AS flights,
               ROUND(SUM(f.duration_s)/3600.0, 1) AS hours,
               (SELECT COUNT(*) FROM anomalies an JOIN flights ff ON ff.id = an.flight_id
                WHERE ff.airframe_id = a.id AND an.is_anomaly = 1) AS anomalies
        FROM airframes a LEFT JOIN flights f ON f.airframe_id = a.id
        GROUP BY a.bucket
        ORDER BY hours DESC
    """).fetchall()
    by_format = con.execute("""
        SELECT format, COUNT(*) AS n FROM flights WHERE parse_error IS NULL GROUP BY format
    """).fetchall()
    firmwares = con.execute("""
        SELECT firmware, COUNT(*) AS n FROM flights WHERE firmware IS NOT NULL GROUP BY firmware ORDER BY n DESC LIMIT 10
    """).fetchall()
    con.close()
    return {
        "total_flights": n_flights,
        "total_hours": tot_hours,
        "total_anomalies": n_anom,
        "by_airframe": [_row_to_dict(r) for r in by_airframe],
        "by_format": [_row_to_dict(r) for r in by_format],
        "firmwares": [_row_to_dict(r) for r in firmwares],
    }


@app.get("/api/demo")
def demo_flight():
    """Return one critical demo flight id so beginners can try without uploading."""
    con = get_conn()
    # prefer the catastrophic 2023-02-02 if present, else worst anomaly we have
    row = con.execute("""
        SELECT f.id FROM flights f WHERE f.file_name LIKE '%2023-02-02 23-16-05%' LIMIT 1
    """).fetchone()
    if not row:
        row = con.execute("""
            SELECT f.id FROM flights f JOIN anomalies a ON a.flight_id = f.id
            WHERE a.is_anomaly = 1 AND f.parse_error IS NULL
            ORDER BY a.score DESC LIMIT 1
        """).fetchone()
    con.close()
    if not row:
        raise HTTPException(404, "no demo flight available")
    return {"flight_id": row["id"]}


@app.get("/api/glossary")
def glossary():
    from logiq.verdict import GLOSSARY
    return GLOSSARY


@app.get("/api/calendar")
def calendar(months: int = 6):
    """Return per-day flight summaries for a heatmap visualization."""
    con = get_conn()
    rows = con.execute("""
        SELECT f.id, substr(f.flown_at, 1, 10) AS day,
               f.duration_s, feat.data
        FROM flights f
        LEFT JOIN features feat ON feat.flight_id = f.id
        WHERE f.parse_error IS NULL AND f.flown_at IS NOT NULL
    """).fetchall()
    con.close()

    from collections import defaultdict
    by_day: dict[str, dict] = defaultdict(lambda: {"flights": 0, "worst_score": 100, "total_hours": 0.0})
    for r in rows:
        d = r["day"]
        if not d: continue
        feat = json.loads(r["data"]) if r["data"] else {}
        # rough health proxy: combine vibration, clip, control error
        v = feat.get("vibe_z_p95") or 0
        c = feat.get("clip_events_total") or 0
        re = feat.get("roll_err_deg_p95") or 0
        # crude health 0-100
        score = 100
        if v > 30: score = min(score, 10)
        elif v > 15: score = min(score, 50)
        elif v > 5: score = min(score, 75)
        if c > 10000: score = min(score, 10)
        elif c > 1000: score = min(score, 35)
        if re > 20: score = min(score, 10)
        elif re > 10: score = min(score, 40)
        elif re > 5: score = min(score, 70)
        by_day[d]["flights"] += 1
        by_day[d]["worst_score"] = min(by_day[d]["worst_score"], score)
        by_day[d]["total_hours"] += (r["duration_s"] or 0) / 3600.0

    out = []
    for day in sorted(by_day.keys()):
        b = by_day[day]
        out.append({"day": day, "flights": b["flights"],
                    "worst_score": b["worst_score"],
                    "total_hours": round(b["total_hours"], 2)})
    return out


@app.get("/api/preflight")
def preflight_checklist():
    """Personalized pre-flight checklist built from recent issues."""
    con = get_conn()
    # recent 30 flights
    rows = con.execute("""
        SELECT f.id, f.flown_at, feat.data, af.bucket
        FROM flights f
        LEFT JOIN features feat ON feat.flight_id = f.id
        LEFT JOIN airframes af ON af.id = f.airframe_id
        WHERE f.parse_error IS NULL
        ORDER BY f.flown_at DESC LIMIT 30
    """).fetchall()
    con.close()

    from collections import Counter
    issues = Counter()
    last_features = {}
    if rows:
        last_features = json.loads(rows[0]["data"]) if rows[0]["data"] else {}

    for r in rows:
        d = json.loads(r["data"]) if r["data"] else {}
        if (d.get("vibe_z_p95") or 0) > 15:    issues["vibration"] += 1
        if (d.get("clip_events_total") or 0) > 1000: issues["clipping"] += 1
        if (d.get("roll_err_deg_p95") or 0) > 5: issues["tuning"] += 1
        if (d.get("gps_hdop_max") or 0) > 2.5 and (d.get("gps_hdop_max") or 0) < 50: issues["gps"] += 1
        if (d.get("ekf_mag_var_p95") or 0) > 0.3: issues["compass"] += 1
        if (d.get("esc_rpm_range_pct") or 0) > 10: issues["motor"] += 1

    items: list[dict] = []
    # Universal pre-flight
    items.append({"key": "battery", "en": "Battery fully charged and balanced", "bn": "Battery fully charge ar balanced", "priority": "always"})
    items.append({"key": "props", "en": "Propellers undamaged and tightly mounted", "bn": "Propeller damage nai ar tight mount kora", "priority": "always"})
    items.append({"key": "gps_wait", "en": "Wait for 8+ GPS satellites locked", "bn": "8+ GPS satellite lock holo na porjonto wait koro", "priority": "always"})

    # Personalized
    if issues.get("vibration", 0) >= 3:
        items.append({"key": "vib", "en": f"Re-balance propellers — vibration noted in {issues['vibration']} recent flights", "bn": f"Propeller re-balance koro — last {issues['vibration']} flight e vibration paya gechhe", "priority": "high"})
    if issues.get("clipping", 0) >= 2:
        items.append({"key": "clip", "en": "Inspect frame and motor mounts for looseness — IMU has been clipping", "bn": "Frame ar motor mount check koro — IMU clip korchhilo", "priority": "high"})
    if issues.get("tuning", 0) >= 3:
        items.append({"key": "tune", "en": "Re-tune PID gains — drone has been sluggish recently", "bn": "PID re-tune koro — drone slow chhilo recent flight e", "priority": "medium"})
    if issues.get("gps", 0) >= 3:
        items.append({"key": "gps_env", "en": "Check takeoff area — recent GPS issues suggest interference", "bn": "Takeoff area dekho — recent flight e GPS issue paya gechhe", "priority": "medium"})
    if issues.get("compass", 0) >= 2:
        items.append({"key": "compass_cal", "en": "Re-calibrate compass — recent EKF compass variance high", "bn": "Compass re-calibrate koro — compass variance high chhilo", "priority": "medium"})
    if issues.get("motor", 0) >= 2:
        items.append({"key": "motor_inspect", "en": "Inspect motors — RPM imbalance pattern detected", "bn": "Motor inspect koro — RPM imbalance detect hoyechhe", "priority": "high"})

    return {
        "recent_flights_analyzed": len(rows),
        "items": items,
        "summary_en": f"Generated from your last {len(rows)} flights. {sum(issues.values())} issue patterns found.",
        "summary_bn": f"Tomar last {len(rows)} flight theke generate. {sum(issues.values())} issue pattern paya gechhe.",
        "issue_counts": dict(issues),
    }


@app.get("/api/motor_health/{flight_id}")
def motor_health(flight_id: str):
    """Per-motor health breakdown for the quad/hex diagram."""
    con = get_conn()
    feat = con.execute("SELECT data FROM features WHERE flight_id = ?", (flight_id,)).fetchone()
    f = con.execute("SELECT format FROM flights WHERE id = ?", (flight_id,)).fetchone()
    con.close()
    if not feat or not feat["data"]:
        raise HTTPException(404, "no features")
    d = json.loads(feat["data"])

    n_motors = d.get("rcout_motor_count") or d.get("esc_count") or 0
    worst = d.get("esc_worst_motor")
    range_pct = d.get("esc_rpm_range_pct") or 0
    motors: list[dict] = []
    # 4 motors default for quad — emit health per motor inferred from imbalance
    for i in range(max(int(n_motors or 0), 4)):
        score = 100
        notes = []
        if worst is not None and int(worst) == i:
            score -= min(int(range_pct * 3), 60)
            notes.append(f"highest RPM deviation (~{range_pct:.1f}%)")
        if score < 0: score = 0
        motors.append({"motor": i + 1, "score": score, "notes": notes})

    return {
        "n_motors": int(n_motors or 4),
        "format": f["format"] if f else None,
        "motors": motors,
        "imbalance_pct": range_pct,
        "data_available": (n_motors or 0) > 0,
    }


@app.get("/api/path/{flight_id}")
def flight_path(flight_id: str):
    con = get_conn()
    f = con.execute("SELECT source_path FROM flights WHERE id = ?", (flight_id,)).fetchone()
    con.close()
    if not f or not f["source_path"]:
        raise HTTPException(404, "log source path missing")
    p = Path(f["source_path"])
    if not p.exists():
        # try uploads folder
        alt = UPLOADS_DIR / f"{flight_id}{p.suffix}"
        if alt.exists():
            p = alt
        else:
            raise HTTPException(404, f"log file not found on disk: {p}")
    return extract_path(p)


@app.get("/api/cost/{flight_id}")
def cost(flight_id: str):
    con = get_conn()
    f = con.execute("SELECT f.*, af.bucket FROM flights f LEFT JOIN airframes af ON af.id = f.airframe_id WHERE f.id = ?", (flight_id,)).fetchone()
    feat = con.execute("SELECT data FROM features WHERE flight_id = ?", (flight_id,)).fetchone()
    con.close()
    if not feat or not feat["data"]:
        raise HTTPException(404, "no features")
    features = json.loads(feat["data"])
    v = compute_verdict(features)
    v["flight"] = {"id": f["id"], "file_name": f["file_name"], "bucket": f["bucket"]}
    return estimate_cost(v)


@app.get("/api/achievements")
def achievements():
    return compute_badges()


@app.get("/api/maintenance/types")
def maintenance_types():
    return [{"key": k, "label": v} for k, v in MAINT_TYPES]


@app.get("/api/maintenance/all")
def maintenance_all(limit: int = 100):
    return maint_list(limit=limit)


@app.get("/api/maintenance/stats")
def maintenance_stats_endpoint():
    return maint_stats()


@app.get("/api/flight/{flight_id}/maintenance")
def get_flight_maintenance(flight_id: str):
    return maint_for_flight(flight_id)


class MaintEntry(BaseModel):
    type: str
    description: str = ""
    cost_bdt: float | None = None


@app.post("/api/flight/{flight_id}/maintenance")
def add_flight_maintenance(flight_id: str, payload: MaintEntry):
    mid = add_maint(flight_id, payload.type, payload.description, payload.cost_bdt)
    return {"id": mid, "ok": True}


@app.get("/api/export.csv")
def export_csv(only_anomalies: bool = False):
    """Bulk CSV export of all flights with their features for analysis."""
    import csv, io
    con = get_conn()
    where = "f.parse_error IS NULL"
    if only_anomalies:
        where += " AND a.is_anomaly = 1"
    rows = con.execute(f"""
        SELECT f.id, f.file_name, f.format, f.flown_at, f.duration_s, f.firmware,
               f.is_simulation, af.bucket, a.score, a.is_anomaly,
               l.label, feat.data
        FROM flights f
        LEFT JOIN airframes af ON af.id = f.airframe_id
        LEFT JOIN anomalies a ON a.flight_id = f.id
        LEFT JOIN labels l ON l.flight_id = f.id
        LEFT JOIN features feat ON feat.flight_id = f.id
        WHERE {where}
        ORDER BY f.flown_at DESC
    """).fetchall()
    con.close()

    # Collect feature keys
    parsed = []
    keys: set[str] = set()
    for r in rows:
        d = json.loads(r["data"]) if r["data"] else {}
        keys.update(d.keys())
        parsed.append((dict(r), d))
    feat_keys = sorted(keys - {"path", "errors", "unique_modes"})

    base_cols = ["id", "file_name", "format", "flown_at", "duration_s", "firmware",
                 "is_simulation", "bucket", "anomaly_score", "is_anomaly", "label"]

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(base_cols + feat_keys)
    for meta, feats in parsed:
        row = [
            meta["id"], meta["file_name"], meta["format"], meta["flown_at"],
            meta["duration_s"], meta["firmware"], meta["is_simulation"],
            meta["bucket"], meta["score"], meta["is_anomaly"], meta["label"] or "",
        ]
        row += [feats.get(k, "") for k in feat_keys]
        w.writerow(row)

    return Response(content=buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": 'attachment; filename="logiq-fleet.csv"'})


@app.get("/api/compare")
def compare_flights(a: str, b: str):
    """Return side-by-side verdicts + diff."""
    def _get(fid):
        con = get_conn()
        f = con.execute("SELECT f.*, af.bucket FROM flights f LEFT JOIN airframes af ON af.id = f.airframe_id WHERE f.id = ?", (fid,)).fetchone()
        feat = con.execute("SELECT data FROM features WHERE flight_id = ?", (fid,)).fetchone()
        con.close()
        if not f or not feat:
            return None
        feats = json.loads(feat["data"])
        v = compute_verdict(feats)
        v["flight"] = {
            "id": f["id"], "file_name": f["file_name"], "format": f["format"],
            "duration_s": f["duration_s"], "flown_at": f["flown_at"],
            "firmware": f["firmware"], "bucket": f["bucket"],
        }
        v["features"] = feats
        return v

    A, B = _get(a), _get(b)
    if not A or not B:
        raise HTTPException(404, "one of the flights not found")
    # category-by-category diff
    cat_diff = []
    for ca, cb in zip(A["categories"], B["categories"]):
        cat_diff.append({
            "key": ca["key"], "name": ca["name_en"], "icon": ca["icon"],
            "a_score": ca["score"], "b_score": cb["score"],
            "delta": cb["score"] - ca["score"],
        })
    return {
        "a": A, "b": B,
        "score_delta": B["overall_score"] - A["overall_score"],
        "category_diff": cat_diff,
    }


def current_user(logiq_token: str | None = Cookie(default=None)):
    return users_mod.get_user_by_token(logiq_token)


class SignupPayload(BaseModel):
    email: str
    password: str
    display_name: str = ""
    phone: str = ""
    organization: str = ""


class LoginPayload(BaseModel):
    email: str
    password: str


@app.post("/api/auth/signup")
def signup(p: SignupPayload):
    try:
        u = users_mod.create_user(p.email, p.password, p.display_name, p.phone, p.organization)
    except ValueError as e:
        raise HTTPException(400, str(e))
    token = users_mod.create_session(u["id"])
    resp = JSONResponse({"user": u})
    resp.set_cookie("logiq_token", token, max_age=30*24*3600, httponly=True, samesite="lax", secure=_COOKIE_SECURE)
    return resp


@app.post("/api/auth/login")
def login(p: LoginPayload):
    u = users_mod.authenticate(p.email, p.password)
    if not u:
        raise HTTPException(401, "invalid credentials")
    token = users_mod.create_session(u["id"])
    resp = JSONResponse({"user": u})
    resp.set_cookie("logiq_token", token, max_age=30*24*3600, httponly=True, samesite="lax", secure=_COOKIE_SECURE)
    return resp


@app.post("/api/auth/logout")
def logout(logiq_token: str | None = Cookie(default=None)):
    if logiq_token:
        users_mod.delete_session(logiq_token)
    resp = JSONResponse({"ok": True})
    resp.delete_cookie("logiq_token")
    return resp


@app.get("/api/auth/me")
def me(user=Depends(current_user)):
    return user or {}


class ProfilePayload(BaseModel):
    display_name: str | None = None
    phone: str | None = None
    organization: str | None = None
    country: str | None = None


@app.put("/api/auth/profile")
def update_profile_endpoint(p: ProfilePayload, user=Depends(current_user)):
    if not user:
        raise HTTPException(401, "login required")
    return users_mod.update_profile(user["id"], display_name=p.display_name, phone=p.phone,
                                    organization=p.organization, country=p.country)


# ---- Drone hardware profiles ----

class AirframePayload(BaseModel):
    name: str
    description: str = ""
    frame_class: str = "quad"
    frame_size_mm: int | None = None
    motor_count: int = 4
    auw_g: float | None = None
    notes: str = ""


@app.get("/api/drones")
def list_drones(user=Depends(current_user)):
    if not user:
        raise HTTPException(401, "login required")
    return hw_mod.list_airframes(user["id"])


@app.post("/api/drones")
def create_drone(p: AirframePayload, user=Depends(current_user)):
    if not user:
        raise HTTPException(401, "login required")
    return hw_mod.create_airframe(user["id"], **p.model_dump())


# Literal /api/drones/* routes MUST be declared before the /{drone_id}
# placeholder route — otherwise FastAPI matches "templates" / "from-template"
# as a drone_id and the literal handler is never reached.
@app.get("/api/drones/templates")
def list_drone_templates():
    return [{"key": k, **{kk: vv for kk, vv in v.items() if kk != "components"},
             "component_count": len(v["components"])}
            for k, v in hw_mod.TEMPLATES.items()]


class TemplateInstall(BaseModel):
    template_key: str
    custom_name: str = ""


@app.post("/api/drones/from-template")
def create_drone_from_template(p: TemplateInstall, user=Depends(current_user)):
    if not user:
        raise HTTPException(401, "login required")
    try:
        return hw_mod.create_from_template(user["id"], p.template_key, p.custom_name)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/api/drones/{drone_id}")
def get_drone(drone_id: str, user=Depends(current_user)):
    if not user:
        raise HTTPException(401, "login required")
    af = hw_mod.get_airframe(drone_id)
    if not af or af["user_id"] != user["id"]:
        raise HTTPException(404, "drone not found")
    return af


@app.put("/api/drones/{drone_id}")
def update_drone(drone_id: str, p: AirframePayload, user=Depends(current_user)):
    if not user:
        raise HTTPException(401, "login required")
    af = hw_mod.get_airframe(drone_id)
    if not af or af["user_id"] != user["id"]:
        raise HTTPException(404, "drone not found")
    return hw_mod.update_airframe(drone_id, **p.model_dump())


@app.delete("/api/drones/{drone_id}")
def delete_drone(drone_id: str, user=Depends(current_user)):
    if not user:
        raise HTTPException(401, "login required")
    af = hw_mod.get_airframe(drone_id)
    if not af or af["user_id"] != user["id"]:
        raise HTTPException(404, "drone not found")
    hw_mod.delete_airframe(drone_id)
    return {"ok": True}


class ComponentPayload(BaseModel):
    type: str
    catalog_id: str | None = None
    custom_name: str = ""
    quantity: int = 1
    notes: str = ""
    unit_price_bdt: float | None = None
    vendor: str = ""
    purchased_at: str = ""


@app.post("/api/drones/{drone_id}/components")
def add_drone_component(drone_id: str, p: ComponentPayload, user=Depends(current_user)):
    if not user:
        raise HTTPException(401, "login required")
    af = hw_mod.get_airframe(drone_id)
    if not af or af["user_id"] != user["id"]:
        raise HTTPException(404, "drone not found")
    return hw_mod.add_component(drone_id, **p.model_dump())


@app.delete("/api/components/{component_id}")
def delete_drone_component(component_id: str, user=Depends(current_user)):
    if not user:
        raise HTTPException(401, "login required")
    c = hw_mod.get_component(component_id)
    if not c:
        raise HTTPException(404, "component not found")
    af = hw_mod.get_airframe(c["airframe_id"])
    if not af or af["user_id"] != user["id"]:
        raise HTTPException(403, "not your component")
    hw_mod.delete_component(component_id)
    return {"ok": True}


@app.get("/api/drones/{drone_id}/cost")
def drone_cost(drone_id: str, user=Depends(current_user)):
    if not user:
        raise HTTPException(401, "login required")
    af = hw_mod.get_airframe(drone_id)
    if not af or af["user_id"] != user["id"]:
        raise HTTPException(404, "drone not found")
    return hw_mod.total_build_cost(drone_id)


@app.get("/api/drones/{drone_id}/compatibility")
def drone_compatibility(drone_id: str, user=Depends(current_user)):
    if not user:
        raise HTTPException(401, "login required")
    af = hw_mod.get_airframe(drone_id)
    if not af or af["user_id"] != user["id"]:
        raise HTTPException(404, "drone not found")
    return compat_mod.analyze(drone_id)


@app.get("/api/catalog/{component_type}")
def catalog_search(component_type: str, q: str = "", limit: int = 50):
    return component_db.search(component_type, q, limit)


# ---- Compliance ----
@app.get("/api/compliance/checklist")
def compliance_checklist():
    return {"items": compliance_mod.CHECKLIST, "weight_categories": compliance_mod.WEIGHT_CATEGORIES}


class CompliancePayload(BaseModel):
    answers: dict[str, str] = {}
    drone_weight_g: float | None = None


@app.post("/api/compliance/assess")
def compliance_assess(p: CompliancePayload):
    return compliance_mod.assess(p.answers, p.drone_weight_g)


# ---- Quiz ----
@app.get("/api/quiz/questions")
def quiz_questions():
    return quiz_mod.QUESTIONS


class QuizPayload(BaseModel):
    answers: dict[str, int] = {}  # JSON keys are strings


@app.post("/api/quiz/grade")
def quiz_grade(p: QuizPayload):
    parsed = {int(k): v for k, v in p.answers.items()}
    return quiz_mod.grade(parsed)


# ---- Logbook ----
@app.get("/api/logbook.pdf")
def logbook_pdf(user=Depends(current_user)):
    if not user:
        raise HTTPException(401, "login required")
    con = get_conn()
    rows = con.execute("""
        SELECT f.flown_at, f.file_name, f.firmware, f.duration_s,
               af.bucket, a.score, l.label
        FROM flights f
        LEFT JOIN airframes af ON af.id = f.airframe_id
        LEFT JOIN anomalies a ON a.flight_id = f.id
        LEFT JOIN labels l ON l.flight_id = f.id
        WHERE f.parse_error IS NULL AND f.flown_at IS NOT NULL
        ORDER BY f.flown_at ASC
    """).fetchall()
    con.close()
    flights = []
    total_s = 0
    for r in rows:
        d = dict(r)
        total_s += d.get("duration_s") or 0
        flights.append({
            "date": d["flown_at"], "file_name": d["file_name"],
            "firmware": d["firmware"], "duration_s": d["duration_s"] or 0,
            "airframe": d["bucket"], "anomaly_score": d["score"],
            "label": d["label"],
        })
    pdf = build_logbook_pdf(user.get("display_name") or user["email"], flights, total_s / 3600.0)
    return Response(content=pdf, media_type="application/pdf",
                    headers={"Content-Disposition": 'attachment; filename="logiq-logbook.pdf"'})


# ---- Public share ----
class ShareCreate(BaseModel):
    scope: str = "fleet"
    target_id: str | None = None
    ttl_days: int = 365


@app.post("/api/share/create")
def share_create(p: ShareCreate, user=Depends(current_user)):
    if not user:
        raise HTTPException(401, "login required")
    tok = share_mod.create_token(user["id"], p.scope, p.target_id, p.ttl_days)
    return {"token": tok, "url": f"/p/{tok}"}


@app.get("/api/share/list")
def share_list(user=Depends(current_user)):
    if not user:
        raise HTTPException(401, "login required")
    return share_mod.list_for_user(user["id"])


@app.post("/api/share/revoke/{token}")
def share_revoke(token: str, user=Depends(current_user)):
    if not user:
        raise HTTPException(401, "login required")
    share_mod.revoke(token)
    return {"ok": True}


@app.get("/p/{token}", response_class=HTMLResponse)
def public_view(token: str):
    info = share_mod.resolve(token)
    if not info:
        return HTMLResponse("<h2 style='font-family:sans-serif; padding:40px;'>This share link is invalid or expired.</h2>", status_code=404)
    # Build read-only stats for the user's fleet
    con = get_conn()
    user_row = con.execute("SELECT display_name, email, organization FROM users WHERE id = ?", (info["user_id"],)).fetchone()
    fleet = con.execute("""
        SELECT COUNT(*) AS n, ROUND(SUM(f.duration_s)/3600.0, 1) AS hrs
        FROM flights f
        JOIN users u ON u.fleet_id = f.fleet_id
        WHERE u.id = ? AND f.parse_error IS NULL
    """, (info["user_id"],)).fetchone()
    anoms = con.execute("""
        SELECT COUNT(*) AS n FROM anomalies a
        JOIN flights f ON f.id = a.flight_id
        JOIN users u ON u.fleet_id = f.fleet_id
        WHERE u.id = ? AND a.is_anomaly = 1
    """, (info["user_id"],)).fetchone()
    con.close()
    name = (user_row["display_name"] or user_row["email"]) if user_row else "Pilot"
    org = (user_row["organization"] or "") if user_row else ""
    hrs = (fleet["hrs"] or 0) if fleet else 0
    html = f"""<!DOCTYPE html><html><head><meta charset=utf-8><title>LogIQ — {name}</title>
<style>body{{font-family:system-ui,sans-serif;margin:0;background:#f4f6f9;color:#1a1a1a;}}
.hero{{background:linear-gradient(135deg,#0a6,#084);color:white;padding:40px 24px;text-align:center;}}
.hero h1{{margin:0;font-size:32px;}} .hero p{{margin:8px 0 0;opacity:0.9;}}
.stats{{max-width:900px;margin:-30px auto 20px;padding:24px;background:white;border-radius:16px;box-shadow:0 4px 16px rgba(0,0,0,0.08);display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:14px;}}
.stat{{text-align:center;padding:12px;}}.stat .v{{font-size:36px;font-weight:700;color:#0a6;}}
.stat .l{{font-size:12px;color:#777;text-transform:uppercase;letter-spacing:0.5px;margin-top:4px;}}
.f{{text-align:center;padding:18px;color:#888;font-size:12px;}}
</style></head><body>
<div class="hero">
  <h1>🚁 {name}</h1>
  <p>{org or 'UAV Pilot'} · Public fleet snapshot</p>
</div>
<div class="stats">
  <div class="stat"><div class="v">{fleet['n'] if fleet else 0}</div><div class="l">Total flights</div></div>
  <div class="stat"><div class="v">{hrs}h</div><div class="l">Flight hours</div></div>
  <div class="stat"><div class="v">{anoms['n'] if anoms else 0}</div><div class="l">Anomalies caught</div></div>
</div>
<div class="f">Powered by <a href="/" style="color:#0a6;text-decoration:none;">LogIQ</a> — UAV health analytics</div>
</body></html>"""
    return HTMLResponse(html)


@app.get("/api/battery/trends")
def battery_trends():
    return per_airframe_battery_trends()


@app.get("/api/components")
def components():
    return per_airframe_component_status()


@app.get("/api/autotag/{flight_id}")
def autotag(flight_id: str):
    con = get_conn()
    feat = con.execute("SELECT data FROM features WHERE flight_id = ?", (flight_id,)).fetchone()
    f = con.execute("SELECT * FROM flights WHERE id = ?", (flight_id,)).fetchone()
    con.close()
    if not feat or not feat["data"]:
        raise HTTPException(404, "no features")
    v = compute_verdict(json.loads(feat["data"]))
    v["flight"] = {"id": flight_id, "duration_s": f["duration_s"] if f else None, "is_simulation": bool(f["is_simulation"]) if f else False}
    return suggest_tag(v)


@app.get("/api/leaderboard")
def leaderboard():
    return airframe_leaderboard()


@app.get("/api/weather/correlation")
def weather_correlation_endpoint(sample: int = 50):
    """Stub: sample some flights, generate (or fetch) weather, return correlation."""
    con = get_conn()
    rows = con.execute("""
        SELECT f.id, f.flown_at, a.is_anomaly, feat.data
        FROM flights f
        LEFT JOIN anomalies a ON a.flight_id = f.id
        LEFT JOIN features feat ON feat.flight_id = f.id
        WHERE f.parse_error IS NULL AND f.flown_at IS NOT NULL
        ORDER BY f.flown_at DESC LIMIT ?
    """, (sample,)).fetchall()
    con.close()
    with_weather = []
    for r in rows:
        d = json.loads(r["data"]) if r["data"] else {}
        # try to pull lat from features (telemetry doesn't always store lat in features)
        lat = 22.46  # Chittagong fallback
        lng = 91.81
        w = fetch_weather(lat, lng, (r["flown_at"] or "2024-01-01")[:10])
        with_weather.append({
            "flight_id": r["id"], "is_anomaly": bool(r["is_anomaly"]),
            "weather": w,
        })
    return {
        "summary": correlate_with_anomalies(with_weather),
        "n_samples": len(with_weather),
    }


@app.get("/api/insurance/{flight_id}")
def insurance_pdf(flight_id: str):
    con = get_conn()
    f = con.execute("SELECT f.*, af.bucket FROM flights f LEFT JOIN airframes af ON af.id = f.airframe_id WHERE f.id = ?", (flight_id,)).fetchone()
    feat = con.execute("SELECT data FROM features WHERE flight_id = ?", (flight_id,)).fetchone()
    con.close()
    if not feat or not feat["data"]:
        raise HTTPException(404, "no features")
    v = compute_verdict(json.loads(feat["data"]))
    v["flight"] = {
        "id": f["id"], "file_name": f["file_name"], "format": f["format"],
        "duration_s": f["duration_s"], "flown_at": f["flown_at"],
        "firmware": f["firmware"], "bucket": f["bucket"],
    }
    pdf_bytes = build_insurance_pdf(v)
    safe = (f["file_name"] or "flight").replace(" ", "_").replace(":", "-")
    return Response(
        content=pdf_bytes, media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="logiq-insurance-{safe}.pdf"'},
    )


# === PWA assets ===
@app.get("/manifest.webmanifest")
def manifest():
    return FileResponse(str(WEB_DIR / "manifest.webmanifest"), media_type="application/manifest+json")


@app.get("/sw.js")
def service_worker():
    return FileResponse(str(WEB_DIR / "sw.js"), media_type="application/javascript")


@app.get("/api/airframes")
def airframes():
    con = get_conn()
    rows = con.execute("SELECT id, bucket, name FROM airframes ORDER BY bucket").fetchall()
    con.close()
    return [_row_to_dict(r) for r in rows]


@app.get("/api/flights")
def flights(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    bucket: Optional[str] = None,
    only_anomalies: bool = False,
    sort: str = "score",
):
    con = get_conn()
    where = ["f.parse_error IS NULL"]
    args: list = []
    if bucket:
        where.append("af.bucket = ?")
        args.append(bucket)
    if only_anomalies:
        where.append("a.is_anomaly = 1")
    wsql = " AND ".join(where)
    order = "a.score DESC NULLS LAST" if sort == "score" else "f.flown_at DESC"
    q = f"""
        SELECT f.id, f.file_name, f.format, f.duration_s, f.flown_at, f.firmware,
               af.bucket, a.score, a.is_anomaly, a.reasons
        FROM flights f
        LEFT JOIN airframes af ON af.id = f.airframe_id
        LEFT JOIN anomalies a ON a.flight_id = f.id
        WHERE {wsql}
        ORDER BY {order}
        LIMIT ? OFFSET ?
    """
    args.extend([limit, offset])
    rows = con.execute(q, args).fetchall()
    total = con.execute(f"""
        SELECT COUNT(*) AS n FROM flights f
        LEFT JOIN airframes af ON af.id = f.airframe_id
        LEFT JOIN anomalies a ON a.flight_id = f.id
        WHERE {wsql}
    """, args[:-2]).fetchone()["n"]
    con.close()
    out = []
    for r in rows:
        d = _row_to_dict(r)
        if d.get("reasons"):
            try: d["reasons"] = json.loads(d["reasons"])
            except: pass
        out.append(d)
    return {"total": total, "rows": out}


@app.get("/api/flight/{flight_id}")
def flight(flight_id: str):
    con = get_conn()
    f = con.execute("""
        SELECT f.*, af.bucket
        FROM flights f LEFT JOIN airframes af ON af.id = f.airframe_id
        WHERE f.id = ?
    """, (flight_id,)).fetchone()
    if not f:
        raise HTTPException(404, "flight not found")
    feat = con.execute("SELECT data FROM features WHERE flight_id = ?", (flight_id,)).fetchone()
    anom = con.execute("SELECT * FROM anomalies WHERE flight_id = ? ORDER BY detected_at DESC LIMIT 1", (flight_id,)).fetchone()
    con.close()
    out = _row_to_dict(f)
    out["features"] = json.loads(feat["data"]) if feat and feat["data"] else {}
    if anom:
        a = _row_to_dict(anom)
        if a.get("reasons"):
            try: a["reasons"] = json.loads(a["reasons"])
            except: pass
        out["anomaly"] = a
    return out


@app.get("/api/verdict/{flight_id}")
def verdict(flight_id: str):
    con = get_conn()
    f = con.execute("SELECT f.*, af.bucket FROM flights f LEFT JOIN airframes af ON af.id = f.airframe_id WHERE f.id = ?", (flight_id,)).fetchone()
    if not f:
        raise HTTPException(404, "flight not found")
    feat = con.execute("SELECT data FROM features WHERE flight_id = ?", (flight_id,)).fetchone()
    con.close()
    if not feat or not feat["data"]:
        raise HTTPException(404, "no features")
    features = json.loads(feat["data"])
    v = compute_verdict(features)
    v["flight"] = {
        "id": f["id"],
        "file_name": f["file_name"],
        "format": f["format"],
        "duration_s": f["duration_s"],
        "flown_at": f["flown_at"],
        "firmware": f["firmware"],
        "bucket": f["bucket"],
        "is_simulation": bool(f["is_simulation"]),
    }
    return v


@app.get("/api/anomalies")
def anomalies(limit: int = Query(30, ge=1, le=200)):
    con = get_conn()
    rows = con.execute("""
        SELECT f.id, f.file_name, f.flown_at, f.firmware, af.bucket,
               a.score, a.is_anomaly, a.reasons
        FROM anomalies a
        JOIN flights f ON f.id = a.flight_id
        LEFT JOIN airframes af ON af.id = f.airframe_id
        WHERE a.is_anomaly = 1
        ORDER BY a.score DESC
        LIMIT ?
    """, (limit,)).fetchall()
    con.close()
    out = []
    for r in rows:
        d = _row_to_dict(r)
        if d.get("reasons"):
            try: d["reasons"] = json.loads(d["reasons"])
            except: pass
        out.append(d)
    return out


@app.get("/api/trends")
def trends():
    con = get_conn()
    # Monthly aggregates by joining feature JSON; do this in Python since SQLite JSON1 may not have ARRAY ops
    rows = con.execute("""
        SELECT f.id, f.flown_at, f.duration_s, af.bucket, feat.data
        FROM flights f
        LEFT JOIN airframes af ON af.id = f.airframe_id
        LEFT JOIN features feat ON feat.flight_id = f.id
        WHERE f.parse_error IS NULL AND f.flown_at IS NOT NULL
    """).fetchall()
    con.close()

    import collections
    by_month = collections.defaultdict(lambda: {"flights": 0, "hours": 0.0, "vibe_z_max": 0.0, "clip_total": 0})
    for r in rows:
        month = (r["flown_at"] or "")[:7]
        if not month:
            continue
        d = json.loads(r["data"]) if r["data"] else {}
        b = by_month[month]
        b["flights"] += 1
        b["hours"] += (r["duration_s"] or 0) / 3600.0
        v = d.get("vibe_z_p95") or 0
        if v and v > b["vibe_z_max"]:
            b["vibe_z_max"] = v
        c = d.get("clip_events_total") or 0
        if c: b["clip_total"] += int(c)

    months = sorted(by_month.keys())
    return {
        "months": months,
        "flights": [by_month[m]["flights"] for m in months],
        "hours": [round(by_month[m]["hours"], 2) for m in months],
        "vibe_z_max": [round(by_month[m]["vibe_z_max"], 2) for m in months],
        "clip_total": [by_month[m]["clip_total"] for m in months],
    }


@app.post("/api/upload")
async def upload(file: UploadFile = File(...)):
    """Accept a .bin or .tlog upload, parse it, write to DB, return flight id."""
    suffix = Path(file.filename).suffix.lower()
    if suffix not in (".bin", ".tlog"):
        raise HTTPException(400, "Only .bin and .tlog files accepted")

    fid = str(uuid.uuid4())
    saved = UPLOADS_DIR / f"{fid}{suffix}"
    content = await file.read()
    saved.write_bytes(content)

    try:
        feats = extract_features(saved)
    except Exception as e:
        raise HTTPException(500, f"parse failed: {e}")

    if feats.get("parse_error"):
        raise HTTPException(400, f"parse error: {feats['parse_error']}")

    bucket = folder_label(str(saved))
    if bucket == "OTHER":
        # fall back to a default bucket
        bucket = "UPLOAD"

    con = get_conn()
    # ensure fleet + airframe
    fleet_row = con.execute("SELECT id FROM fleets LIMIT 1").fetchone()
    if not fleet_row:
        from logiq.db import upsert_fleet
        fleet_id = upsert_fleet(con)
    else:
        fleet_id = fleet_row["id"]
    af_id = upsert_airframe(con, fleet_id, bucket)

    con.execute(
        """INSERT INTO flights (id, fleet_id, airframe_id, file_name, source_path, format,
                                size_mb, flown_at, duration_s, firmware, is_simulation, parse_error)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            fid, fleet_id, af_id, file.filename, str(saved), feats.get("format"),
            feats.get("size_mb"), feats.get("mtime"), feats.get("duration_s"),
            feats.get("firmware"), 1 if feats.get("is_simulation") else 0, None,
        ),
    )
    con.execute("INSERT INTO features (flight_id, data) VALUES (?, ?)", (fid, json.dumps(feats, default=str)))
    con.commit()
    con.close()

    v = compute_verdict(feats)
    v["flight"] = {
        "id": fid, "file_name": file.filename, "format": feats.get("format"),
        "duration_s": feats.get("duration_s"), "flown_at": feats.get("mtime"),
        "firmware": feats.get("firmware"), "bucket": bucket,
        "is_simulation": feats.get("is_simulation", False),
    }
    # Background-fire alert (only when configured)
    try:
        alert_if_anomaly(v, threshold=50)
    except Exception:
        pass
    return {"flight_id": fid, "features": feats, "verdict": v}


# ============= PDF REPORT =============
@app.get("/api/pdf/{flight_id}")
def pdf(flight_id: str):
    con = get_conn()
    f = con.execute("SELECT f.*, af.bucket FROM flights f LEFT JOIN airframes af ON af.id = f.airframe_id WHERE f.id = ?", (flight_id,)).fetchone()
    if not f:
        raise HTTPException(404, "flight not found")
    feat = con.execute("SELECT data FROM features WHERE flight_id = ?", (flight_id,)).fetchone()
    con.close()
    if not feat or not feat["data"]:
        raise HTTPException(404, "no features")
    features = json.loads(feat["data"])
    v = compute_verdict(features)
    v["flight"] = {
        "id": f["id"], "file_name": f["file_name"], "format": f["format"],
        "duration_s": f["duration_s"], "flown_at": f["flown_at"],
        "firmware": f["firmware"], "bucket": f["bucket"],
    }
    pdf_bytes = build_pdf(v)
    safe_name = (f["file_name"] or "flight").replace(" ", "_").replace(":", "-").replace("/", "_")
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="logiq-{safe_name}.pdf"'},
    )


# ============= QUICK HEALTH CHECK =============
@app.get("/api/quickcheck/questions")
def quickcheck_questions():
    return QUICK_QUESTIONS


class QuickCheckAnswers(BaseModel):
    answers: dict


@app.post("/api/quickcheck/assess")
def quickcheck_assess(payload: QuickCheckAnswers):
    return quick_assess(payload.answers)


# ============= LABELS =============
@app.get("/api/labels/options")
def labels_options():
    return [{"key": k, "description": d} for k, d in LABEL_OPTIONS]


@app.get("/api/labels/stats")
def labels_stats():
    return label_stats()


class LabelPayload(BaseModel):
    label: str
    notes: str | None = ""


@app.post("/api/flight/{flight_id}/label")
def label_flight(flight_id: str, payload: LabelPayload):
    try:
        set_flight_label(flight_id, payload.label, payload.notes or "")
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True, "label": get_flight_label(flight_id)}


@app.get("/api/flight/{flight_id}/label")
def get_label_endpoint(flight_id: str):
    return get_flight_label(flight_id) or {"label": None}


# ============= PHOTO DAMAGE CHECK =============
@app.post("/api/photo")
async def photo_upload(file: UploadFile = File(...), notes: str = Form("")):
    if not (file.content_type or "").startswith("image/"):
        raise HTTPException(400, "Please upload an image (.jpg/.png/.webp)")
    data = await file.read()
    return analyze_photo(data, user_notes=notes)


# --- Static UI ---

if WEB_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")
if REPORTS_DIR.exists():
    app.mount("/reports", StaticFiles(directory=str(REPORTS_DIR)), name="reports")


@app.get("/", response_class=HTMLResponse)
def index():
    idx = WEB_DIR / "index.html"
    if idx.exists():
        return FileResponse(str(idx))
    return HTMLResponse("<h1>LogIQ API running. UI not built yet.</h1>")


if __name__ == "__main__":
    import uvicorn
    # PORT comes from the host platform (Railway / Fly / Render).
    # HOST=0.0.0.0 binds to every interface so the container is reachable.
    port = int(os.environ.get("PORT", "8765"))
    host = os.environ.get("HOST", "127.0.0.1")
    uvicorn.run(
        "logiq.api:app", host=host, port=port, reload=False,
        proxy_headers=True, forwarded_allow_ips="*",
    )
