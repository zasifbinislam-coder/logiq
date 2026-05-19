"""Probe a .tlog file to see what MAVLink messages are present."""
from pymavlink import mavutil
from collections import Counter
import os

LOG = r"C:\Users\zasif bin islam\Documents\Mission Planner\logs\QUADROTOR\1\2023-10-11 19-33-14.tlog"
print(f"Opening tlog: {LOG}")
print(f"Size: {os.path.getsize(LOG)/1024/1024:.2f} MB\n")

mlog = mavutil.mavlink_connection(LOG)

counts = Counter()
samples = {}
count = 0
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
    counts[t] += 1
    count += 1
    if t not in samples and t in (
        "ATTITUDE", "GLOBAL_POSITION_INT", "GPS_RAW_INT", "BATTERY_STATUS",
        "VIBRATION", "RC_CHANNELS", "SERVO_OUTPUT_RAW", "ESC_STATUS",
        "ESC_INFO", "SYS_STATUS", "HEARTBEAT", "STATUSTEXT", "EKF_STATUS_REPORT",
        "VFR_HUD"):
        samples[t] = m.to_dict()
    if count > 500_000:
        break

print(f"Total messages: {count:,}\n")
print("Top message types:")
for typ, cnt in counts.most_common(25):
    print(f"  {typ:30s} {cnt:>6,}")

print("\n--- Samples ---")
for k, v in samples.items():
    print(f"\n[{k}]")
    for kk, vv in list(v.items())[:12]:
        print(f"  {kk}: {vv}")
