---
title: LogIQ
emoji: 🚁
colorFrom: green
colorTo: blue
sdk: docker
app_port: 8765
pinned: false
short_description: AI flight log analytics for ArduPilot — 80 features, anomaly detection, drift alerts
---

# LogIQ — AI Flight Log Analytics for ArduPilot

**Status:** v0.0.1 — Full MVP, web app live (Day 1: 2026-05-19)
**Owner:** Zasif Bin Islam (Diligite Ltd. R&D)
**Stack:** Python · pymavlink · pandas · scikit-learn · SQLite · FastAPI · Plotly · HTML/JS

## What's built

| Component | File | Purpose |
|-----------|------|---------|
| Feature extractor | `src/logiq/extract.py` | Parses `.bin`/`.tlog` → ~80 features. Auto-format detection. FFT on IMU. Per-motor ESC analytics. EKF tracking. |
| Parallel batch | `src/logiq/batch.py` | 7-worker ingestion at 12.7 logs/sec |
| Database | `src/logiq/db.py` | SQLite: fleets, airframes, flights, features, anomalies |
| Anomaly model | `src/logiq/anomaly.py` | IsolationForest with **per-airframe baselines** + human-readable diagnostics |
| Predictive maintenance | `src/logiq/predictive.py` | Cross-flight drift detection (baseline vs current window) |
| Static reports | `src/logiq/report.py` `trends.py` `flight_detail.py` | HTML dashboards with Plotly charts |
| FastAPI backend | `src/logiq/api.py` | REST: `/api/stats`, `/api/flights`, `/api/flight/{id}`, `/api/trends`, `/api/anomalies`, `POST /api/upload` |
| Web dashboard | `web/index.html` | Single-page app: upload, list, drill-down, filters |
| Paper draft | `docs/PAPER_DRAFT.md` | IEEE Aerospace Conference 2027 — 13.6KB, real numbers, 3 case studies |
| Architecture | `docs/ARCHITECTURE.md` | Target-state design + cost projection |

## Real validation on 575 flights, 29.3 flight-hours, 2021–2026

| Metric | Value |
|--------|-------|
| Logs processed | 576 (575 parseable) |
| Total flight time | 29.3 hours |
| Date span | 2021-08-15 → 2026-04-20 |
| Airframe classes | 6 (QUADROTOR, ADSB, SMALL, BAD, SITL, GENERIC) |
| Firmware versions | 4 ArduCopter + 478 legacy |
| Anomalies flagged | 68 (per-class + global model) |
| Drift alerts | 2 (ADSB VIBE Z/Y both up ~11×) |
| Throughput | 12.7 logs/sec on 7 workers |

## Top real findings (auto-detected by the model)

1. **2021-08-17 QUADROTOR near-crash:** 45,238 IMU clips + 71.9° roll tracking error
2. **2023-02-02 QUADROTOR vibration failure:** VIBE Z = 37.4 m/s² (>30 = DANGER)
3. **2024-05-21 ADSB:** 241,189 IMU clips in 13 minutes + GPS HDOP = 35
4. **ADSB drift over time:** vibration baseline 0.31 → current 3.47 m/s² (z=6.03) — undetectable from any single flight

## Run it

```powershell
# Initial setup
py -m pip install pymavlink pandas numpy matplotlib scikit-learn pyarrow tqdm fastapi uvicorn python-multipart
$env:PYTHONPATH = "C:\Users\zasif bin islam\Desktop\LogIQ\src"

# Process all logs
py -m logiq.batch "C:\Users\zasif bin islam\Documents\Mission Planner\logs"

# Build DB
py -m logiq.db

# Train anomaly model
py -m logiq.anomaly

# Find drift
py -m logiq.predictive

# Generate static reports
py -m logiq.report
py -m logiq.trends

# Launch web app
py -m logiq.api
# open http://127.0.0.1:8765
```

## What's next (priority order)

1. **Label dataset**: Manually tag 30-50 flights {ok / bad-tune / vibration / crash / gps-loss} → train supervised classifier
2. **Per-prop-size baselines**: Within QUADROTOR, separate 10" vs 15" prop normal models
3. **LSTM autoencoder**: Sub-flight anomaly segmentation (which 30s window is bad, not just whole-flight)
4. **Multi-tenancy & auth**: NextAuth.js + per-fleet isolation
5. **Real-time MAVLink streaming**: In-flight monitoring via UDP
6. **Deploy**: Railway/Fly.io + Cloudflare R2 for raw logs ($27/mo total)
7. **Submit paper to IEEE Aerospace 2027** (deadline October 2026)
