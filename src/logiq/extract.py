"""
LogIQ — Unified feature extractor for ArduPilot logs.

Supports both:
  * .bin / DataFlash logs (on-board, rich: 400Hz IMU, per-motor ESC, EKF internals)
  * .tlog / .rlog telemetry logs (MAVLink stream, lower rate but always available)

Output: a flat dict with ~80 named features. Same keys regardless of input format,
so downstream code (anomaly model, dashboard) is format-agnostic.
"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any
import math
import os
import statistics
import time

import numpy as np
from pymavlink import mavutil


# ---------- mode reasons / status flags --------------------------------------

# ArduCopter EV (event) IDs that mark arm/disarm
EV_ARMED = 10
EV_DISARMED = 11


def _percentiles(arr: list[float]) -> tuple[float, float, float, float, float] | tuple[None, None, None, None, None]:
    """Return (min, max, mean, median, p95) — or all None if empty."""
    if not arr:
        return (None, None, None, None, None)
    sa = sorted(arr)
    n = len(sa)
    p95_idx = max(0, int(n * 0.95) - 1)
    return (round(sa[0], 4),
            round(sa[-1], 4),
            round(sum(arr) / n, 4),
            round(statistics.median(arr), 4),
            round(sa[p95_idx], 4))


def _stats(name: str, arr: list[float], out: dict) -> None:
    mn, mx, me, md, p95 = _percentiles(arr)
    out[f"{name}_min"] = mn
    out[f"{name}_max"] = mx
    out[f"{name}_mean"] = me
    out[f"{name}_median"] = md
    out[f"{name}_p95"] = p95


def _fft_dominant(samples: list[float], fs: float, n_peaks: int = 3) -> list[tuple[float, float]]:
    """Return up to n_peaks (frequency_hz, magnitude) pairs from real FFT.
    Drops the DC bin. Magnitudes normalized by length."""
    n = len(samples)
    if n < 64:
        return []
    arr = np.asarray(samples, dtype=np.float32) - np.mean(samples)
    spectrum = np.abs(np.fft.rfft(arr)) / n
    freqs = np.fft.rfftfreq(n, d=1.0 / fs)
    # zero out DC
    spectrum[0] = 0.0
    # find top peaks
    idx = np.argpartition(spectrum, -n_peaks)[-n_peaks:]
    idx = idx[np.argsort(spectrum[idx])[::-1]]
    return [(float(freqs[i]), float(spectrum[i])) for i in idx]


def detect_format(path: Path) -> str:
    """Return 'dataflash' for .bin, 'telemetry' for .tlog, else 'unknown'.
    .rlog is Mission Planner's replay format — not standard MAVLink, so skipped.
    """
    suf = path.suffix.lower()
    if suf == ".bin":
        return "dataflash"
    if suf == ".tlog":
        return "telemetry"
    return "unknown"


# =============================================================================
# DataFlash (.bin) extraction
# =============================================================================

def _extract_dataflash(mlog, feats: dict) -> None:
    sim_msgs = 0
    firmware = None
    first_t_us = None
    last_t_us = None

    modes: list[int] = []
    arming_events = 0
    disarming_events = 0
    errors: list[str] = []

    # per-stream accumulators
    volt: list[float] = []
    curr: list[float] = []
    energy_total = 0.0
    rempct: list[float] = []

    roll_err: list[float] = []
    pitch_err: list[float] = []
    yaw_err: list[float] = []

    alt: list[float] = []
    gps_hdop: list[float] = []
    gps_nsats: list[int] = []

    vibe_x: list[float] = []
    vibe_y: list[float] = []
    vibe_z: list[float] = []
    vibe_clip: list[int] = []

    rcout: defaultdict[int, list[int]] = defaultdict(list)
    esc_rpm: defaultdict[int, list[float]] = defaultdict(list)
    esc_curr: defaultdict[int, list[float]] = defaultdict(list)
    esc_temp: defaultdict[int, list[float]] = defaultdict(list)
    esc_volt: defaultdict[int, list[float]] = defaultdict(list)

    # EKF innovations
    ekf_pos_var: list[float] = []
    ekf_vel_var: list[float] = []
    ekf_mag_var: list[float] = []
    ekf_baro_innov: list[float] = []

    # Raw IMU samples for FFT (downsample heavily, cap N)
    imu_accz_samples: list[float] = []
    imu_dt_us: list[int] = []
    imu_last_tus: int | None = None

    while True:
        try:
            m = mlog.recv_match(blocking=False)
        except Exception:
            continue
        if m is None:
            break
        t = m.get_type()
        if t == "BAD_DATA":
            continue
        d = m.to_dict()
        tus = d.get("TimeUS")
        if tus is not None:
            if first_t_us is None:
                first_t_us = tus
            last_t_us = tus

        if t in ("SIM", "SIM2"):
            sim_msgs += 1
            continue
        if t == "MSG":
            txt = str(d.get("Message", ""))
            if firmware is None and any(k in txt for k in ("ArduCopter", "ArduPlane", "ArduRover", "ArduSub")):
                firmware = txt
            continue
        if t == "MODE":
            modes.append(d.get("Mode", -1))
            continue
        if t == "EV":
            ev = d.get("Id")
            if ev == EV_ARMED:
                arming_events += 1
            elif ev == EV_DISARMED:
                disarming_events += 1
            continue
        if t == "ERR":
            errors.append(f"S{d.get('Subsys')}-E{d.get('ECode')}")
            continue
        if t == "BAT" and d.get("Inst", 0) == 0:
            if d.get("Volt"): volt.append(d["Volt"])
            if d.get("Curr") is not None: curr.append(d["Curr"])
            if d.get("EnrgTot"):
                energy_total = max(energy_total, d["EnrgTot"])
            if d.get("RemPct") is not None:
                rempct.append(d["RemPct"])
            continue
        if t == "ATT":
            r, dr = d.get("Roll"), d.get("DesRoll")
            p, dp = d.get("Pitch"), d.get("DesPitch")
            y, dy = d.get("Yaw"), d.get("DesYaw")
            if r is not None and dr is not None: roll_err.append(abs(r - dr))
            if p is not None and dp is not None: pitch_err.append(abs(p - dp))
            if y is not None and dy is not None:
                e = abs(y - dy)
                if e > 180: e = 360 - e
                yaw_err.append(e)
            continue
        if t in ("POS", "AHR2"):
            a = d.get("Alt") or d.get("RelHomeAlt")
            if a is not None: alt.append(a)
            continue
        if t == "GPS":
            if d.get("HDop") is not None: gps_hdop.append(d["HDop"])
            if d.get("NSats") is not None: gps_nsats.append(d["NSats"])
            continue
        if t == "VIBE":
            if d.get("VibeX") is not None: vibe_x.append(d["VibeX"])
            if d.get("VibeY") is not None: vibe_y.append(d["VibeY"])
            if d.get("VibeZ") is not None: vibe_z.append(d["VibeZ"])
            tot = sum(d.get(k, 0) or 0 for k in ("Clip0", "Clip1", "Clip2"))
            vibe_clip.append(tot)
            continue
        if t == "RCOU":
            for i in range(1, 9):
                v = d.get(f"C{i}")
                if v is not None and v > 0:
                    rcout[i].append(v)
            continue
        if t == "ESC":
            inst = d.get("Instance", 0)
            if d.get("RPM") is not None: esc_rpm[inst].append(d["RPM"])
            if d.get("Curr") is not None: esc_curr[inst].append(d["Curr"])
            if d.get("Temp") is not None: esc_temp[inst].append(d["Temp"])
            if d.get("Volt") is not None: esc_volt[inst].append(d["Volt"])
            continue
        if t == "XKF4":
            for k in ("SV", "SP", "SH", "SM", "SVT"):
                v = d.get(k)
                if v is not None:
                    if k == "SV": ekf_vel_var.append(v)
                    elif k == "SP": ekf_pos_var.append(v)
                    elif k == "SM": ekf_mag_var.append(v)
            continue
        if t == "XKFS":
            v = d.get("MagFusionType")
            continue
        if t == "IMU" and len(imu_accz_samples) < 8192:
            az = d.get("AccZ")
            if az is not None and tus is not None:
                if imu_last_tus is not None:
                    imu_dt_us.append(tus - imu_last_tus)
                imu_last_tus = tus
                imu_accz_samples.append(az)
            continue

    # ---- write features ----
    feats["msg_count"] = (last_t_us is not None) and 1 or 0  # placeholder
    # We don't expose total count here — set by caller from len of stream walk;
    # but ok to compute again:
    # (skip, caller sets msg_count if needed)
    feats["is_simulation"] = sim_msgs > 0
    feats["firmware"] = firmware
    feats["duration_s"] = round((last_t_us - first_t_us) / 1e6, 1) if first_t_us and last_t_us else None
    feats["mode_changes"] = len(modes)
    feats["unique_modes"] = sorted(set(modes))
    feats["arming_events"] = arming_events
    feats["disarming_events"] = disarming_events
    feats["error_count"] = len(errors)
    feats["errors"] = errors[:10]

    _stats("volt", volt, feats)
    _stats("curr", curr, feats)
    feats["energy_total_wh"] = round(energy_total, 2) if energy_total else None
    feats["batt_rempct_min"] = min(rempct) if rempct else None
    feats["batt_rempct_drop"] = round(rempct[0] - rempct[-1], 1) if len(rempct) > 1 else None

    _stats("roll_err_deg", roll_err, feats)
    _stats("pitch_err_deg", pitch_err, feats)
    _stats("yaw_err_deg", yaw_err, feats)
    _stats("alt_m", alt, feats)
    _stats("gps_hdop", gps_hdop, feats)
    feats["gps_nsats_min"] = min(gps_nsats) if gps_nsats else None
    feats["gps_nsats_mean"] = round(sum(gps_nsats)/len(gps_nsats), 1) if gps_nsats else None

    _stats("vibe_x", vibe_x, feats)
    _stats("vibe_y", vibe_y, feats)
    _stats("vibe_z", vibe_z, feats)
    feats["clip_events_total"] = sum(vibe_clip) if vibe_clip else 0

    # RCOU motor balance
    motor_means = [sum(a)/len(a) for a in rcout.values() if len(a) > 50]
    if len(motor_means) >= 3:
        feats["rcout_motor_count"] = len(motor_means)
        feats["rcout_motor_mean_std"] = round(statistics.stdev(motor_means), 1)
        feats["rcout_motor_mean_range"] = round(max(motor_means) - min(motor_means), 1)
    else:
        feats["rcout_motor_count"] = len(motor_means)
        feats["rcout_motor_mean_std"] = None
        feats["rcout_motor_mean_range"] = None

    # ESC per-motor analytics — the commercial gold
    esc_rpm_means = []
    for inst, arr in esc_rpm.items():
        if len(arr) > 100:
            esc_rpm_means.append(sum(arr)/len(arr))
    if len(esc_rpm_means) >= 3:
        mu = sum(esc_rpm_means) / len(esc_rpm_means)
        sd = statistics.stdev(esc_rpm_means)
        feats["esc_count"] = len(esc_rpm_means)
        feats["esc_rpm_mean"] = round(mu, 1)
        feats["esc_rpm_cv"] = round(sd / mu, 4) if mu else None  # coefficient of variation
        feats["esc_rpm_range_pct"] = round(100 * (max(esc_rpm_means) - min(esc_rpm_means)) / mu, 2) if mu else None
        # which motor is most off
        deviations = [(i, abs(m - mu) / mu * 100) for i, m in zip(esc_rpm.keys(), esc_rpm_means)]
        deviations.sort(key=lambda x: x[1], reverse=True)
        feats["esc_worst_motor"] = deviations[0][0] if deviations else None
        feats["esc_worst_motor_dev_pct"] = round(deviations[0][1], 2) if deviations else None
    else:
        feats["esc_count"] = len(esc_rpm_means)
        feats["esc_rpm_mean"] = None
        feats["esc_rpm_cv"] = None
        feats["esc_rpm_range_pct"] = None
        feats["esc_worst_motor"] = None
        feats["esc_worst_motor_dev_pct"] = None

    # ESC current imbalance
    esc_curr_means = [sum(a)/len(a) for a in esc_curr.values() if len(a) > 100]
    if len(esc_curr_means) >= 3:
        mu = sum(esc_curr_means) / len(esc_curr_means)
        feats["esc_curr_cv"] = round(statistics.stdev(esc_curr_means) / mu, 4) if mu else None
    else:
        feats["esc_curr_cv"] = None

    # ESC temperature
    esc_temp_maxes = [max(a) for a in esc_temp.values() if a]
    feats["esc_temp_max"] = max(esc_temp_maxes) if esc_temp_maxes else None
    feats["esc_temp_max_motor_delta"] = round(max(esc_temp_maxes) - min(esc_temp_maxes), 1) if len(esc_temp_maxes) >= 2 else None

    # EKF
    _stats("ekf_pos_var", ekf_pos_var, feats)
    _stats("ekf_vel_var", ekf_vel_var, feats)
    _stats("ekf_mag_var", ekf_mag_var, feats)

    # FFT on raw IMU AccZ (for prop balance & frame resonance)
    if len(imu_accz_samples) >= 256 and imu_dt_us:
        mean_dt_us = statistics.median(imu_dt_us)
        fs = 1e6 / mean_dt_us if mean_dt_us > 0 else 0
        if 50 < fs < 5000:
            peaks = _fft_dominant(imu_accz_samples, fs, n_peaks=3)
            feats["imu_sample_rate_hz"] = round(fs, 1)
            feats["imu_fft_peak_count"] = len(peaks)
            for i, (f, m) in enumerate(peaks[:3], 1):
                feats[f"imu_fft_peak{i}_hz"] = round(f, 1)
                feats[f"imu_fft_peak{i}_mag"] = round(m, 4)
    else:
        feats["imu_sample_rate_hz"] = None


# =============================================================================
# Telemetry (.tlog / .rlog) extraction
# =============================================================================

def _extract_telemetry(mlog, feats: dict) -> None:
    sim_msgs = 0
    firmware = None
    first_t_us = None
    last_t_us = None

    modes: list[int] = []
    armed_seen = False
    armed_changes = 0
    last_armed = None

    volt: list[float] = []
    curr: list[float] = []
    rempct: list[float] = []

    roll: list[float] = []
    pitch: list[float] = []
    yaw: list[float] = []

    alt: list[float] = []
    gps_hdop: list[float] = []
    gps_nsats: list[int] = []
    gps_fixtype: list[int] = []

    vibe_x: list[float] = []
    vibe_y: list[float] = []
    vibe_z: list[float] = []
    vibe_clip: list[int] = []

    servo: defaultdict[int, list[int]] = defaultdict(list)
    statustexts: list[str] = []

    ekf_pos_h_var: list[float] = []
    ekf_pos_v_var: list[float] = []
    ekf_mag_var: list[float] = []
    ekf_vel_var: list[float] = []

    base_t = None

    while True:
        try:
            m = mlog.recv_match(blocking=False)
        except Exception:
            continue
        if m is None:
            break
        t = m.get_type()
        if t == "BAD_DATA":
            continue
        d = m.to_dict()

        # tlog uses time_boot_ms or time_usec
        tus = d.get("time_usec")
        if tus is None:
            tb = d.get("time_boot_ms")
            if tb is not None:
                tus = tb * 1000
        if tus is not None and tus > 0:
            if first_t_us is None:
                first_t_us = tus
            last_t_us = tus

        if t == "HEARTBEAT":
            ap = d.get("autopilot")
            if ap == 3 and firmware is None:
                firmware = "ArduPilot (from HEARTBEAT)"
            cm = d.get("custom_mode")
            if cm is not None:
                modes.append(cm)
            base_mode = d.get("base_mode", 0)
            armed = bool(base_mode & 128)  # MAV_MODE_FLAG_SAFETY_ARMED
            if last_armed is None:
                last_armed = armed
                if armed: armed_seen = True
            elif armed != last_armed:
                armed_changes += 1
                last_armed = armed
                if armed: armed_seen = True
            continue
        if t == "STATUSTEXT":
            txt = str(d.get("text", ""))
            statustexts.append(txt)
            if firmware is None and any(k in txt for k in ("ArduCopter", "ArduPlane", "ArduRover", "ArduSub")):
                firmware = txt
            continue
        if t == "SYS_STATUS":
            v = d.get("voltage_battery")
            c = d.get("current_battery")
            r = d.get("battery_remaining")
            if v and v > 0: volt.append(v / 1000.0)
            if c is not None and c >= 0: curr.append(c / 100.0)
            if r is not None and r >= 0: rempct.append(r)
            continue
        if t == "BATTERY_STATUS":
            voltages = d.get("voltages") or []
            cellsum = 0
            for cv in voltages:
                if 0 < cv < 65535:
                    cellsum += cv
            if cellsum > 0:
                volt.append(cellsum / 1000.0)
            cc = d.get("current_battery")
            if cc is not None and cc >= 0: curr.append(cc / 100.0)
            br = d.get("battery_remaining")
            if br is not None and br >= 0: rempct.append(br)
            continue
        if t == "ATTITUDE":
            if d.get("roll") is not None: roll.append(math.degrees(d["roll"]))
            if d.get("pitch") is not None: pitch.append(math.degrees(d["pitch"]))
            if d.get("yaw") is not None: yaw.append(math.degrees(d["yaw"]))
            continue
        if t == "GLOBAL_POSITION_INT":
            ra = d.get("relative_alt")
            if ra is not None: alt.append(ra / 1000.0)
            continue
        if t == "GPS_RAW_INT":
            eph = d.get("eph"); ns = d.get("satellites_visible"); ft = d.get("fix_type")
            if eph is not None and eph < 9999: gps_hdop.append(eph / 100.0)
            if ns is not None: gps_nsats.append(ns)
            if ft is not None: gps_fixtype.append(ft)
            continue
        if t == "VIBRATION":
            if d.get("vibration_x") is not None: vibe_x.append(d["vibration_x"])
            if d.get("vibration_y") is not None: vibe_y.append(d["vibration_y"])
            if d.get("vibration_z") is not None: vibe_z.append(d["vibration_z"])
            tot = sum(d.get(k, 0) or 0 for k in ("clipping_0", "clipping_1", "clipping_2"))
            vibe_clip.append(tot)
            continue
        if t == "SERVO_OUTPUT_RAW":
            for i in range(1, 9):
                v = d.get(f"servo{i}_raw")
                if v is not None and v > 0:
                    servo[i].append(v)
            continue
        if t == "EKF_STATUS_REPORT":
            if d.get("velocity_variance") is not None: ekf_vel_var.append(d["velocity_variance"])
            if d.get("pos_horiz_variance") is not None: ekf_pos_h_var.append(d["pos_horiz_variance"])
            if d.get("pos_vert_variance") is not None: ekf_pos_v_var.append(d["pos_vert_variance"])
            if d.get("compass_variance") is not None: ekf_mag_var.append(d["compass_variance"])
            continue

    feats["is_simulation"] = False  # tlog has no SIM marker; assume real
    feats["firmware"] = firmware
    feats["duration_s"] = round((last_t_us - first_t_us) / 1e6, 1) if first_t_us and last_t_us else None
    feats["mode_changes"] = len(modes)
    feats["unique_modes"] = sorted(set(modes))
    feats["arming_events"] = (1 if armed_seen else 0) + max(0, armed_changes - 1) // 2
    feats["disarming_events"] = max(0, armed_changes - 1) // 2
    feats["error_count"] = 0
    feats["errors"] = []

    _stats("volt", volt, feats)
    _stats("curr", curr, feats)
    feats["energy_total_wh"] = None
    feats["batt_rempct_min"] = min(rempct) if rempct else None
    feats["batt_rempct_drop"] = round(rempct[0] - rempct[-1], 1) if len(rempct) > 1 else None

    # Note: ATT in tlog gives absolute angles, not error
    _stats("roll_deg", roll, feats)
    _stats("pitch_deg", pitch, feats)
    _stats("yaw_deg", yaw, feats)
    # leave the error fields None — telemetry doesn't carry DesRoll/DesPitch reliably
    for k in ("roll_err_deg_min", "roll_err_deg_max", "roll_err_deg_mean", "roll_err_deg_median", "roll_err_deg_p95",
              "pitch_err_deg_min", "pitch_err_deg_max", "pitch_err_deg_mean", "pitch_err_deg_median", "pitch_err_deg_p95",
              "yaw_err_deg_min", "yaw_err_deg_max", "yaw_err_deg_mean", "yaw_err_deg_median", "yaw_err_deg_p95"):
        feats[k] = None

    _stats("alt_m", alt, feats)
    _stats("gps_hdop", gps_hdop, feats)
    feats["gps_nsats_min"] = min(gps_nsats) if gps_nsats else None
    feats["gps_nsats_mean"] = round(sum(gps_nsats)/len(gps_nsats), 1) if gps_nsats else None
    feats["gps_fixtype_min"] = min(gps_fixtype) if gps_fixtype else None
    feats["gps_fixtype_mode"] = statistics.mode(gps_fixtype) if gps_fixtype else None

    _stats("vibe_x", vibe_x, feats)
    _stats("vibe_y", vibe_y, feats)
    _stats("vibe_z", vibe_z, feats)
    feats["clip_events_total"] = sum(vibe_clip) if vibe_clip else 0

    # servo motor balance
    motor_means = [sum(a)/len(a) for a in servo.values() if len(a) > 30]
    if len(motor_means) >= 3:
        feats["rcout_motor_count"] = len(motor_means)
        feats["rcout_motor_mean_std"] = round(statistics.stdev(motor_means), 1)
        feats["rcout_motor_mean_range"] = round(max(motor_means) - min(motor_means), 1)
    else:
        feats["rcout_motor_count"] = len(motor_means)
        feats["rcout_motor_mean_std"] = None
        feats["rcout_motor_mean_range"] = None

    # ESC data not in basic tlog → leave None
    for k in ("esc_count", "esc_rpm_mean", "esc_rpm_cv", "esc_rpm_range_pct",
              "esc_worst_motor", "esc_worst_motor_dev_pct", "esc_curr_cv",
              "esc_temp_max", "esc_temp_max_motor_delta"):
        feats[k] = None

    # EKF
    _stats("ekf_pos_var", ekf_pos_h_var, feats)
    _stats("ekf_vel_var", ekf_vel_var, feats)
    _stats("ekf_mag_var", ekf_mag_var, feats)

    # FFT not available in tlog (no raw IMU at high rate)
    feats["imu_sample_rate_hz"] = None
    for i in (1, 2, 3):
        feats[f"imu_fft_peak{i}_hz"] = None
        feats[f"imu_fft_peak{i}_mag"] = None


# =============================================================================
# Public API
# =============================================================================

def extract_features(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    fmt = detect_format(path)
    feats: dict[str, Any] = {
        "file": path.name,
        "path": str(path),
        "format": fmt,
        "size_mb": round(os.path.getsize(path) / 1024 / 1024, 2),
        "mtime": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(os.path.getmtime(path))),
        "parse_error": None,
    }

    if fmt == "unknown":
        feats["parse_error"] = "unknown_format"
        return feats

    try:
        mlog = mavutil.mavlink_connection(str(path))
    except Exception as e:
        feats["parse_error"] = f"open: {e}"
        return feats

    try:
        if fmt == "dataflash":
            _extract_dataflash(mlog, feats)
        else:
            _extract_telemetry(mlog, feats)
    except Exception as e:
        feats["parse_error"] = f"parse: {type(e).__name__}: {e}"

    return feats


if __name__ == "__main__":
    import json, sys
    p = sys.argv[1] if len(sys.argv) > 1 else r"C:\Users\zasif bin islam\Documents\Mission Planner\logs\QUADROTOR\1\2023-05-28 17-54-11.bin"
    f = extract_features(p)
    print(json.dumps(f, indent=2, default=str))
