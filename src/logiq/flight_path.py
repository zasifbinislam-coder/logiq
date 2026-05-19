"""
LogIQ — Extract GPS trajectory for 3D flight path visualization.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from pymavlink import mavutil


def extract_path(log_path: str | Path, max_points: int = 2000) -> dict[str, Any]:
    """Return (lat, lng, alt, t) arrays for a flight log. Downsamples to max_points."""
    p = Path(log_path)
    suffix = p.suffix.lower()
    is_dataflash = suffix == ".bin"

    try:
        mlog = mavutil.mavlink_connection(str(p))
    except Exception as e:
        return {"ok": False, "error": str(e)}

    lats: list[float] = []
    lngs: list[float] = []
    alts: list[float] = []
    ts: list[float] = []
    t0_us = None

    while True:
        try:
            m = mlog.recv_match(blocking=False)
        except Exception:
            continue
        if m is None:
            break
        t = m.get_type()
        d = m.to_dict()

        if is_dataflash:
            if t in ("POS", "AHR2", "GPS"):
                la = d.get("Lat"); ln = d.get("Lng"); al = d.get("Alt") or d.get("RelHomeAlt")
                tus = d.get("TimeUS")
                if la and ln and abs(la) > 0.001 and abs(ln) > 0.001:
                    if t0_us is None and tus: t0_us = tus
                    lats.append(la); lngs.append(ln); alts.append(al or 0)
                    ts.append((tus - t0_us) / 1e6 if t0_us and tus else 0)
        else:
            if t == "GLOBAL_POSITION_INT":
                la = d.get("lat") / 1e7 if d.get("lat") else None
                ln = d.get("lon") / 1e7 if d.get("lon") else None
                al = (d.get("relative_alt") or 0) / 1000.0
                tb = d.get("time_boot_ms") or 0
                if la and ln and abs(la) > 0.001 and abs(ln) > 0.001:
                    if t0_us is None: t0_us = tb * 1000
                    lats.append(la); lngs.append(ln); alts.append(al)
                    ts.append((tb * 1000 - t0_us) / 1e6 if t0_us else 0)

    n = len(lats)
    if n == 0:
        return {"ok": False, "error": "no GPS data in log"}

    # Downsample
    if n > max_points:
        step = n // max_points
        lats = lats[::step]; lngs = lngs[::step]; alts = alts[::step]; ts = ts[::step]

    return {
        "ok": True,
        "n_points": n,
        "downsampled_to": len(lats),
        "lat": lats,
        "lng": lngs,
        "alt": alts,
        "t": ts,
        "lat_min": min(lats), "lat_max": max(lats),
        "lng_min": min(lngs), "lng_max": max(lngs),
        "alt_min": min(alts), "alt_max": max(alts),
    }
