"""
LogIQ — Exploratory probe of one DataFlash .bin log.
Goal: understand what message types are present and sample some fields.
"""
from pymavlink import mavutil
from collections import Counter
import sys
import os

LOG = r"C:\Users\zasif bin islam\Documents\Mission Planner\logs\QUADROTOR\1\2024-05-24 01-43-35.bin"

print(f"Opening: {LOG}")
print(f"Size: {os.path.getsize(LOG)/1024/1024:.2f} MB\n")

mlog = mavutil.mavlink_connection(LOG)

msg_counts = Counter()
fc_type = None
firmware = None
first_gps_time = None
last_gps_time = None
max_alt = 0
samples = {}

count = 0
while True:
    m = mlog.recv_match(blocking=False)
    if m is None:
        break
    t = m.get_type()
    msg_counts[t] += 1
    count += 1

    if t == "MSG" and firmware is None:
        try:
            firmware = str(m.Message)
        except Exception:
            pass

    if t == "GPS":
        try:
            if first_gps_time is None:
                first_gps_time = m.GMS
            last_gps_time = m.GMS
            if hasattr(m, "Alt") and m.Alt > max_alt:
                max_alt = m.Alt
        except Exception:
            pass

    if t not in samples and t in ("ATT", "GPS", "BAT", "CURR", "RCIN", "RCOU", "VIBE", "IMU", "MODE", "EV", "ERR", "MSG", "POS", "AHR2"):
        samples[t] = m.to_dict()

    if count > 5_000_000:
        break

print(f"Total messages parsed: {count:,}\n")
print("Top 25 message types by frequency:")
for typ, cnt in msg_counts.most_common(25):
    print(f"  {typ:10s} {cnt:>8,}")

print("\n--- Firmware / FC info ---")
print(firmware)

print("\n--- Sample messages ---")
for k, v in samples.items():
    print(f"\n[{k}]")
    for kk, vv in v.items():
        if kk == "mavpackettype":
            continue
        print(f"  {kk}: {vv}")
