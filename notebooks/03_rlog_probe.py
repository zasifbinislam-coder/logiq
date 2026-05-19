"""Probe .rlog with mavlogfile."""
from pymavlink.mavutil import mavlogfile
import os

p = r"C:\Users\zasif bin islam\Documents\Mission Planner\logs\ADSB\1\2023-02-11 19-14-50.rlog"
print("Size:", os.path.getsize(p))
try:
    m = mavlogfile(p)
    msg_count = 0
    types: dict[str, int] = {}
    while True:
        x = m.recv_match(blocking=False)
        if x is None:
            break
        msg_count += 1
        types[x.get_type()] = types.get(x.get_type(), 0) + 1
        if msg_count > 50000:
            break
    print("Parsed", msg_count, "messages")
    for k, v in sorted(types.items(), key=lambda x: -x[1])[:15]:
        print(f"  {k:30s} {v}")
except Exception as e:
    print("ERR:", type(e).__name__, e)

# Also try a bigger .rlog
p2 = r"C:\Users\zasif bin islam\Documents\Mission Planner\logs\QUADROTOR\1\2023-10-11 19-33-14.rlog"
print()
print("Bigger rlog:", os.path.getsize(p2))
try:
    m = mavlogfile(p2)
    msg_count = 0
    types = {}
    while True:
        x = m.recv_match(blocking=False)
        if x is None:
            break
        msg_count += 1
        types[x.get_type()] = types.get(x.get_type(), 0) + 1
        if msg_count > 50000:
            break
    print("Parsed", msg_count, "messages")
    for k, v in sorted(types.items(), key=lambda x: -x[1])[:15]:
        print(f"  {k:30s} {v}")
except Exception as e:
    print("ERR:", type(e).__name__, e)
