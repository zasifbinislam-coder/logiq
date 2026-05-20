"""
LogIQ smoke test.

Verifies the FastAPI surface starts cleanly and the no-data-required endpoints
respond. Also exercises the signup -> drone-from-template -> list -> delete
flow end-to-end, which is the path that would have been broken by the route
shadowing bug fixed alongside this test.

Does NOT touch real logs / real DB — conftest points LOGIQ_DB_PATH at a
tempdir for the session.
"""
from __future__ import annotations

import uuid


# ---- Endpoints that should work on a fresh empty DB ---------------------

def test_stats_empty_db(client):
    r = client.get("/api/stats")
    assert r.status_code == 200
    j = r.json()
    assert j["total_flights"] == 0
    assert j["total_anomalies"] == 0
    assert j["by_airframe"] == []


def test_static_lookup_endpoints(client):
    """Endpoints that return curated static data — must not depend on DB."""
    for path in [
        "/api/glossary",
        "/api/labels/options",
        "/api/quickcheck/questions",
        "/api/quiz/questions",
        "/api/compliance/checklist",
        "/api/maintenance/types",
    ]:
        r = client.get(path)
        assert r.status_code == 200, f"{path} -> {r.status_code} {r.text[:200]}"
        body = r.json()
        # each of these returns non-empty content (list or dict-with-keys)
        assert body, f"{path} returned empty body"


def test_trends_calendar_preflight(client):
    """Aggregate endpoints should return a sensible shape even with no flights."""
    r = client.get("/api/trends")
    assert r.status_code == 200
    j = r.json()
    assert set(j.keys()) >= {"months", "flights", "hours"}

    r = client.get("/api/calendar")
    assert r.status_code == 200
    assert isinstance(r.json(), list)

    r = client.get("/api/preflight")
    assert r.status_code == 200
    j = r.json()
    assert "items" in j and len(j["items"]) >= 3  # always-on items


def test_demo_404_on_empty_db(client):
    r = client.get("/api/demo")
    assert r.status_code == 404  # no flights to demo on a fresh DB


def test_quickcheck_assess_default_inputs(client):
    """All-default answers should yield a valid assessment, not a 500."""
    q = client.get("/api/quickcheck/questions").json()
    answers = {item["key"]: item["options"][0]["key"] for item in q if item.get("options")}
    r = client.post("/api/quickcheck/assess", json={"answers": answers})
    assert r.status_code == 200, r.text


def test_compliance_assess_empty_inputs(client):
    r = client.post("/api/compliance/assess", json={"answers": {}, "drone_weight_g": 500})
    assert r.status_code == 200
    assert "summary" in r.json() or "items" in r.json() or "compliant" in r.json()


def test_quiz_grade_blank(client):
    r = client.post("/api/quiz/grade", json={"answers": {}})
    assert r.status_code == 200
    assert "score" in r.json() or "results" in r.json() or "correct" in r.json()


# ---- The bit that caught the route-shadowing bug -----------------------

def test_drone_templates_endpoint_reachable(client):
    """
    Regression guard: GET /api/drones/templates must NOT match the
    /api/drones/{drone_id} placeholder route. Was broken in commit 739f210
    until the literal route was moved above the placeholder.
    """
    r = client.get("/api/drones/templates")
    assert r.status_code == 200, (
        f"templates endpoint returned {r.status_code} — "
        "did /api/drones/{drone_id} shadow it again?"
    )
    tmpls = r.json()
    assert isinstance(tmpls, list) and len(tmpls) >= 5
    keys = {t["key"] for t in tmpls}
    assert {"freestyle_5", "cinematic_7", "tinywhoop"}.issubset(keys)
    for t in tmpls:
        assert "name" in t and "component_count" in t
        assert t["component_count"] >= 1


# ---- End-to-end auth + drone-from-template flow ------------------------

def _signup(client, email: str | None = None):
    email = email or f"smoke-{uuid.uuid4().hex[:8]}@logiq.test"
    r = client.post("/api/auth/signup", json={
        "email": email, "password": "smoke-password",
        "display_name": "Smoke Pilot",
    })
    assert r.status_code == 200, r.text
    return email


def test_full_drone_template_lifecycle(client):
    _signup(client)

    # 1. Brand new user -> no drones yet
    r = client.get("/api/drones")
    assert r.status_code == 200
    assert r.json() == []

    # 2. Install a template
    r = client.post("/api/drones/from-template", json={
        "template_key": "freestyle_5",
        "custom_name": "Smoke Test Quad",
    })
    assert r.status_code == 200, r.text
    drone = r.json()
    drone_id = drone["id"]
    assert drone["name"] == "Smoke Test Quad"
    assert drone["frame_class"] == "quad"
    assert drone["motor_count"] == 4
    # template attaches motor / esc / prop / battery / fc
    types_attached = {c["type"] for c in drone["components"]}
    assert {"motor", "esc", "prop", "battery", "fc"}.issubset(types_attached)

    # 3. List now contains the new drone
    r = client.get("/api/drones")
    assert r.status_code == 200
    drones = r.json()
    assert len(drones) == 1
    assert drones[0]["id"] == drone_id

    # 4. Fetch one
    r = client.get(f"/api/drones/{drone_id}")
    assert r.status_code == 200
    assert r.json()["id"] == drone_id

    # 5. Cost endpoint shouldn't crash even when no prices were set
    r = client.get(f"/api/drones/{drone_id}/cost")
    assert r.status_code == 200
    cost = r.json()
    assert "total_bdt" in cost

    # 6. Compatibility analyzer runs without 500
    r = client.get(f"/api/drones/{drone_id}/compatibility")
    assert r.status_code == 200

    # 7. Unknown template -> 400, not 500
    r = client.post("/api/drones/from-template", json={"template_key": "no_such_template"})
    assert r.status_code == 400

    # 8. Delete the drone -> empty list again
    r = client.delete(f"/api/drones/{drone_id}")
    assert r.status_code == 200
    r = client.get("/api/drones")
    assert r.json() == []


def test_drone_endpoints_require_auth(client):
    """Without a session cookie, every drone endpoint must reject."""
    fresh = client.__class__(client.app)  # cookie-less client
    for path, method in [
        ("/api/drones", "GET"),
        ("/api/drones", "POST"),
        ("/api/drones/anything", "GET"),
        ("/api/drones/from-template", "POST"),
    ]:
        r = fresh.request(method, path, json={})
        assert r.status_code in (401, 422), f"{method} {path} should be unauthorized, got {r.status_code}"


def test_login_logout_roundtrip(client):
    email = f"login-{uuid.uuid4().hex[:8]}@logiq.test"
    r = client.post("/api/auth/signup", json={"email": email, "password": "pw-1234"})
    assert r.status_code == 200

    r = client.post("/api/auth/logout")
    assert r.status_code == 200

    r = client.post("/api/auth/login", json={"email": email, "password": "wrong"})
    assert r.status_code == 401

    r = client.post("/api/auth/login", json={"email": email, "password": "pw-1234"})
    assert r.status_code == 200
    assert r.json()["user"]["email"] == email


# ---- Upload validation (no real binary needed) -------------------------

def test_upload_rejects_bad_extension(client):
    r = client.post(
        "/api/upload",
        files={"file": ("notalog.txt", b"hello", "text/plain")},
    )
    assert r.status_code == 400
    assert "bin" in r.json()["detail"].lower() or "tlog" in r.json()["detail"].lower()


def test_photo_rejects_non_image(client):
    r = client.post(
        "/api/photo",
        files={"file": ("readme.txt", b"hi", "text/plain")},
    )
    assert r.status_code == 400
