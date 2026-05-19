"""
LogIQ — Per-flight detail viewer.

Takes a single log file, extracts time-series of key signals, and renders an
interactive HTML page with Plotly charts. This is the drill-down view that
sits behind every row in the main dashboard.
"""
from __future__ import annotations

from pathlib import Path
import json
import sys
from collections import defaultdict

from pymavlink import mavutil


def collect_timeseries(path: str | Path) -> dict:
    """Walk a log and collect per-message time-series."""
    path = Path(path)
    mlog = mavutil.mavlink_connection(str(path))
    fmt = "dataflash" if path.suffix.lower() == ".bin" else "telemetry"

    ts = {
        "format": fmt,
        "file": path.name,
        "att": {"t": [], "roll": [], "pitch": [], "yaw": [], "desRoll": [], "desPitch": [], "desYaw": []},
        "bat": {"t": [], "volt": [], "curr": []},
        "vibe": {"t": [], "x": [], "y": [], "z": []},
        "pos": {"t": [], "alt": []},
        "gps": {"t": [], "hdop": [], "nsats": [], "fixtype": []},
        "esc": defaultdict(lambda: {"t": [], "rpm": [], "curr": [], "temp": []}),
        "rcout": defaultdict(lambda: {"t": [], "v": []}),
        "modes": [],  # (t, mode_num)
        "ekf": {"t": [], "pos_var": [], "vel_var": [], "mag_var": []},
    }

    t0_us = None

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

        # unify time
        tus = d.get("TimeUS")
        if tus is None:
            tus = d.get("time_usec")
        if tus is None:
            tb = d.get("time_boot_ms")
            if tb is not None: tus = tb * 1000
        if tus is None:
            continue
        if t0_us is None:
            t0_us = tus
        ts_sec = (tus - t0_us) / 1e6

        if fmt == "dataflash":
            if t == "ATT":
                ts["att"]["t"].append(ts_sec)
                ts["att"]["roll"].append(d.get("Roll", 0))
                ts["att"]["pitch"].append(d.get("Pitch", 0))
                ts["att"]["yaw"].append(d.get("Yaw", 0))
                ts["att"]["desRoll"].append(d.get("DesRoll", 0))
                ts["att"]["desPitch"].append(d.get("DesPitch", 0))
                ts["att"]["desYaw"].append(d.get("DesYaw", 0))
            elif t == "BAT" and d.get("Inst", 0) == 0:
                ts["bat"]["t"].append(ts_sec)
                ts["bat"]["volt"].append(d.get("Volt") or 0)
                ts["bat"]["curr"].append(d.get("Curr") or 0)
            elif t == "VIBE":
                ts["vibe"]["t"].append(ts_sec)
                ts["vibe"]["x"].append(d.get("VibeX") or 0)
                ts["vibe"]["y"].append(d.get("VibeY") or 0)
                ts["vibe"]["z"].append(d.get("VibeZ") or 0)
            elif t in ("POS", "AHR2"):
                a = d.get("Alt") or d.get("RelHomeAlt")
                if a is not None:
                    ts["pos"]["t"].append(ts_sec)
                    ts["pos"]["alt"].append(a)
            elif t == "GPS":
                ts["gps"]["t"].append(ts_sec)
                ts["gps"]["hdop"].append(d.get("HDop"))
                ts["gps"]["nsats"].append(d.get("NSats"))
            elif t == "ESC":
                inst = d.get("Instance", 0)
                ts["esc"][inst]["t"].append(ts_sec)
                ts["esc"][inst]["rpm"].append(d.get("RPM") or 0)
                ts["esc"][inst]["curr"].append(d.get("Curr") or 0)
                ts["esc"][inst]["temp"].append(d.get("Temp") or 0)
            elif t == "RCOU":
                for i in range(1, 9):
                    v = d.get(f"C{i}")
                    if v is not None and v > 0:
                        ts["rcout"][i]["t"].append(ts_sec)
                        ts["rcout"][i]["v"].append(v)
            elif t == "MODE":
                ts["modes"].append((ts_sec, d.get("Mode", -1)))
            elif t == "XKF4":
                ts["ekf"]["t"].append(ts_sec)
                ts["ekf"]["pos_var"].append(d.get("SP") or 0)
                ts["ekf"]["vel_var"].append(d.get("SV") or 0)
                ts["ekf"]["mag_var"].append(d.get("SM") or 0)
        else:
            # telemetry
            import math
            if t == "ATTITUDE":
                ts["att"]["t"].append(ts_sec)
                ts["att"]["roll"].append(math.degrees(d.get("roll", 0)))
                ts["att"]["pitch"].append(math.degrees(d.get("pitch", 0)))
                ts["att"]["yaw"].append(math.degrees(d.get("yaw", 0)))
            elif t == "SYS_STATUS":
                v = d.get("voltage_battery"); c = d.get("current_battery")
                if v and v > 0:
                    ts["bat"]["t"].append(ts_sec)
                    ts["bat"]["volt"].append(v / 1000.0)
                    ts["bat"]["curr"].append(c / 100.0 if c and c >= 0 else 0)
            elif t == "VIBRATION":
                ts["vibe"]["t"].append(ts_sec)
                ts["vibe"]["x"].append(d.get("vibration_x") or 0)
                ts["vibe"]["y"].append(d.get("vibration_y") or 0)
                ts["vibe"]["z"].append(d.get("vibration_z") or 0)
            elif t == "GLOBAL_POSITION_INT":
                ra = d.get("relative_alt")
                if ra is not None:
                    ts["pos"]["t"].append(ts_sec)
                    ts["pos"]["alt"].append(ra / 1000.0)
            elif t == "GPS_RAW_INT":
                ts["gps"]["t"].append(ts_sec)
                eph = d.get("eph"); ns = d.get("satellites_visible")
                ts["gps"]["hdop"].append(eph / 100.0 if eph and eph < 9999 else None)
                ts["gps"]["nsats"].append(ns)
            elif t == "SERVO_OUTPUT_RAW":
                for i in range(1, 9):
                    v = d.get(f"servo{i}_raw")
                    if v is not None and v > 0:
                        ts["rcout"][i]["t"].append(ts_sec)
                        ts["rcout"][i]["v"].append(v)
            elif t == "EKF_STATUS_REPORT":
                ts["ekf"]["t"].append(ts_sec)
                ts["ekf"]["pos_var"].append(d.get("pos_horiz_variance") or 0)
                ts["ekf"]["vel_var"].append(d.get("velocity_variance") or 0)
                ts["ekf"]["mag_var"].append(d.get("compass_variance") or 0)

    # convert defaultdicts for json
    ts["esc"] = {k: dict(v) for k, v in ts["esc"].items()}
    ts["rcout"] = {k: dict(v) for k, v in ts["rcout"].items()}
    return ts


def render_html(ts: dict, out_path: str) -> None:
    """Build a self-contained HTML page with Plotly charts."""
    data_json = json.dumps(ts, default=str)
    html = """<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>LogIQ - Flight Detail</title>
<script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>
<style>
body{font-family:system-ui,sans-serif;margin:20px;color:#222;background:#fafafa;}
h1{color:#0a3;margin-bottom:6px;} h2{margin-top:30px;color:#333;}
.meta{color:#666;font-size:13px;margin-bottom:20px;}
.chart{background:#fff;border:1px solid #e0e0e0;border-radius:6px;padding:10px;margin:14px 0;}
.kpi{display:inline-block;padding:6px 12px;background:#f0f0f0;border-radius:14px;font-size:12px;margin-right:6px;}
.bad{background:#ffd0d0;color:#900;} .good{background:#d0f0d0;color:#060;}
</style></head><body>
<h1 id="title">Flight Detail</h1>
<div class="meta" id="meta"></div>
<div id="kpis"></div>
<div class="chart"><div id="chart_att"></div></div>
<div class="chart"><div id="chart_vibe"></div></div>
<div class="chart"><div id="chart_alt"></div></div>
<div class="chart"><div id="chart_bat"></div></div>
<div class="chart"><div id="chart_esc"></div></div>
<div class="chart"><div id="chart_rcout"></div></div>
<div class="chart"><div id="chart_ekf"></div></div>
<script>
const ts = __DATA__;

document.getElementById("title").textContent = "Flight: " + ts.file;
document.getElementById("meta").textContent = "Format: " + ts.format + " | ATT samples: " + ts.att.t.length + " | VIBE samples: " + ts.vibe.t.length + " | ESC motors: " + Object.keys(ts.esc).length;

// KPIs
let kpis = "";
const vibeMax = Math.max(...ts.vibe.z, 0);
kpis += "<span class='kpi " + (vibeMax > 15 ? "bad" : "good") + "'>VIBE Z max: " + vibeMax.toFixed(2) + " m/s2</span>";
if (ts.bat.volt.length) {
  const vmin = Math.min(...ts.bat.volt.filter(v => v > 0));
  kpis += "<span class='kpi'>Vmin: " + vmin.toFixed(2) + " V</span>";
}
if (ts.pos.alt.length) {
  const amax = Math.max(...ts.pos.alt);
  kpis += "<span class='kpi'>Alt max: " + amax.toFixed(1) + " m</span>";
}
document.getElementById("kpis").innerHTML = kpis;

// Attitude
if (ts.att.t.length > 0) {
  const traces = [
    {x: ts.att.t, y: ts.att.roll, name: "Roll", line:{color:"#d33"}},
    {x: ts.att.t, y: ts.att.pitch, name: "Pitch", line:{color:"#3a3"}},
    {x: ts.att.t, y: ts.att.yaw, name: "Yaw", line:{color:"#33d"}}
  ];
  if (ts.att.desRoll.length > 0 && ts.att.desRoll.some(v => v !== 0)) {
    traces.push({x: ts.att.t, y: ts.att.desRoll, name: "DesRoll", line:{color:"#d33", dash:"dot"}});
    traces.push({x: ts.att.t, y: ts.att.desPitch, name: "DesPitch", line:{color:"#3a3", dash:"dot"}});
  }
  Plotly.newPlot("chart_att", traces, {title:"Attitude (deg)", xaxis:{title:"t (s)"}, height:300, margin:{t:40,b:40}});
}

// Vibration
if (ts.vibe.t.length > 0) {
  Plotly.newPlot("chart_vibe", [
    {x: ts.vibe.t, y: ts.vibe.x, name: "VibeX", line:{color:"#d33"}},
    {x: ts.vibe.t, y: ts.vibe.y, name: "VibeY", line:{color:"#3a3"}},
    {x: ts.vibe.t, y: ts.vibe.z, name: "VibeZ", line:{color:"#33d"}},
    {x: [ts.vibe.t[0], ts.vibe.t[ts.vibe.t.length-1]], y: [15,15], name: "warn", line:{color:"#f80",dash:"dash"}, hoverinfo:"skip"},
    {x: [ts.vibe.t[0], ts.vibe.t[ts.vibe.t.length-1]], y: [30,30], name: "danger", line:{color:"#d00",dash:"dash"}, hoverinfo:"skip"}
  ], {title:"Vibration (m/s2)", xaxis:{title:"t (s)"}, height:300, margin:{t:40,b:40}});
}

// Altitude
if (ts.pos.t.length > 0) {
  Plotly.newPlot("chart_alt", [
    {x: ts.pos.t, y: ts.pos.alt, name: "Alt", line:{color:"#06c"}, fill:"tozeroy", fillcolor:"rgba(0,100,200,0.1)"}
  ], {title:"Altitude (m)", xaxis:{title:"t (s)"}, height:240, margin:{t:40,b:40}});
}

// Battery
if (ts.bat.t.length > 0) {
  Plotly.newPlot("chart_bat", [
    {x: ts.bat.t, y: ts.bat.volt, name: "Voltage (V)", yaxis:"y1", line:{color:"#0a3"}},
    {x: ts.bat.t, y: ts.bat.curr, name: "Current (A)", yaxis:"y2", line:{color:"#c30"}}
  ], {
    title:"Battery", xaxis:{title:"t (s)"}, height:280, margin:{t:40,b:40},
    yaxis:{title:"V", side:"left"},
    yaxis2:{title:"A", overlaying:"y", side:"right"}
  });
}

// ESC RPM per motor
const escIds = Object.keys(ts.esc).filter(k => ts.esc[k].t.length > 0);
if (escIds.length > 0) {
  const colors = ["#d33","#3a3","#33d","#d80","#909","#0aa","#666","#a52"];
  const traces = escIds.map((k, i) => ({
    x: ts.esc[k].t, y: ts.esc[k].rpm,
    name: "M" + (parseInt(k)+1),
    line: {color: colors[i % colors.length]}
  }));
  Plotly.newPlot("chart_esc", traces, {title:"ESC RPM per motor", xaxis:{title:"t (s)"}, yaxis:{title:"RPM"}, height:300, margin:{t:40,b:40}});
} else {
  document.getElementById("chart_esc").textContent = "(no ESC telemetry in this log)";
}

// RCOU per motor
const rcIds = Object.keys(ts.rcout).filter(k => ts.rcout[k].t.length > 0);
if (rcIds.length > 0) {
  const colors = ["#d33","#3a3","#33d","#d80","#909","#0aa","#666","#a52"];
  const traces = rcIds.map((k, i) => ({
    x: ts.rcout[k].t, y: ts.rcout[k].v,
    name: "Servo" + k,
    line: {color: colors[i % colors.length]}
  }));
  Plotly.newPlot("chart_rcout", traces, {title:"Servo / motor PWM output (us)", xaxis:{title:"t (s)"}, yaxis:{title:"PWM"}, height:280, margin:{t:40,b:40}});
}

// EKF
if (ts.ekf.t.length > 0) {
  Plotly.newPlot("chart_ekf", [
    {x: ts.ekf.t, y: ts.ekf.pos_var, name: "Pos var"},
    {x: ts.ekf.t, y: ts.ekf.vel_var, name: "Vel var"},
    {x: ts.ekf.t, y: ts.ekf.mag_var, name: "Mag var"}
  ], {title:"EKF variances", xaxis:{title:"t (s)"}, height:280, margin:{t:40,b:40}});
}
</script>
</body></html>
"""
    html = html.replace("__DATA__", data_json)
    Path(out_path).write_text(html, encoding="utf-8")


def main():
    if len(sys.argv) < 2:
        print("Usage: py -m logiq.flight_detail <log_path> [output.html]")
        sys.exit(1)
    log_path = sys.argv[1]
    out_html = sys.argv[2] if len(sys.argv) > 2 else f"flight_detail_{Path(log_path).stem}.html"
    print(f"Collecting time-series from {log_path}...")
    ts = collect_timeseries(log_path)
    print(f"  ATT samples: {len(ts['att']['t'])}")
    print(f"  VIBE samples: {len(ts['vibe']['t'])}")
    print(f"  ESC motors: {len(ts['esc'])}")
    print(f"  BAT samples: {len(ts['bat']['t'])}")
    render_html(ts, out_html)
    print(f"Wrote {out_html}")


if __name__ == "__main__":
    main()
