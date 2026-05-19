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
import uuid

from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Query
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from logiq.db import get_conn, DB_PATH, folder_label, upsert_airframe
from logiq.extract import extract_features
from logiq.verdict import compute_verdict
from logiq.pdf_report import build_pdf
from logiq.quickcheck import QUESTIONS as QUICK_QUESTIONS, assess as quick_assess
from logiq.labels import LABELS as LABEL_OPTIONS, set_label as set_flight_label, get_label as get_flight_label, init as init_labels, stats as label_stats
from logiq.photo_check import analyze_photo
from logiq.notify import alert_if_anomaly
try:
    from logiq.whatsapp import router as whatsapp_router
except Exception:
    whatsapp_router = None

init_labels()


BASE_DIR = Path(r"C:\Users\zasif bin islam\Desktop\LogIQ")
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
    uvicorn.run("logiq.api:app", host="127.0.0.1", port=8765, reload=False)
