# LogIQ — Architecture (target state)

```
┌──────────────────┐    ┌──────────────────┐    ┌────────────────────┐
│  Mission Planner │    │  QGroundControl  │    │  ArduPilot SD card │
└────────┬─────────┘    └────────┬─────────┘    └─────────┬──────────┘
         │ .tlog                  │ .ulg/.tlog            │ .bin (DataFlash)
         └────────────┬───────────┴───────────────────────┘
                      ▼
         ┌──────────────────────────────┐
         │   Next.js Web App (frontend) │   ← reuses auth/components from `aki`
         │   • Upload page              │
         │   • Flight list + filters    │
         │   • Per-flight dashboard     │
         │   • Compare 2 flights        │
         │   • Fleet trends             │
         └──────────┬───────────────────┘
                    │ HTTPS
                    ▼
         ┌──────────────────────────────┐
         │   FastAPI backend (Python)   │
         │   • POST /upload  → S3       │
         │   • GET /flights, /flight/:id│
         │   • GET /anomalies, /trends  │
         └──────────┬───────────────────┘
                    │
       ┌────────────┴────────────┐
       ▼                         ▼
 ┌────────────┐         ┌─────────────────┐
 │ S3 storage │         │   Postgres      │
 │ raw logs   │         │  flights        │
 │ (.bin/.tlog)         │  features (JSONB)│
 └────────────┘         │  anomalies      │
                        │  fleets, users  │
                        └────────┬────────┘
                                 │
                                 ▼
                  ┌──────────────────────────────┐
                  │  Celery / RQ worker (Python) │
                  │  • Pull from S3              │
                  │  • Parse with pymavlink      │
                  │  • Extract features          │
                  │  • Run anomaly model         │
                  │  • Write to Postgres         │
                  │  • Email/Slack alerts        │
                  └──────────────┬───────────────┘
                                 │
                                 ▼
                  ┌──────────────────────────────┐
                  │  ML model artifacts          │
                  │  • IsolationForest (today)   │
                  │  • LSTM autoencoder (later)  │
                  │  • Per-airframe scalers      │
                  └──────────────────────────────┘
```

## Why this stack

- **Python + pymavlink** — only mature OSS parser for ArduPilot logs. Maintained by the ArduPilot team itself.
- **FastAPI** — async, OpenAPI auto-docs, ML stack lives in same process.
- **Next.js + Prisma** — already proven in your `aki` project. Auth, Tailwind, components reusable.
- **Postgres** — JSONB column for per-flight features keeps schema flexible while feature set evolves.
- **S3-compatible storage** — DigitalOcean Spaces or Backblaze B2 ($0.005/GB) for cheap raw log archive.

## Data flow

1. User drags `.bin` to upload page (multi-file, up to 100MB each)
2. Frontend gets pre-signed S3 URL, uploads directly (don't proxy through FastAPI)
3. FastAPI inserts row in `flights` table with status=`pending`
4. Worker picks up the job, pulls log from S3
5. `extract_features()` runs (same code as `src/logiq/extract.py` today)
6. Features written to `features` table (JSONB)
7. Anomaly model scores the flight, writes to `anomalies`
8. If high-score, push notification (email/Slack/webhook)
9. Frontend polls or subscribes via WebSocket for status

## Database schema (minimal)

```sql
CREATE TABLE fleets (
  id UUID PRIMARY KEY,
  name TEXT,
  owner_user_id UUID
);

CREATE TABLE airframes (
  id UUID PRIMARY KEY,
  fleet_id UUID REFERENCES fleets(id),
  name TEXT,
  frame_class TEXT,        -- quad, hex, octo, plane, vtol
  prop_size_in NUMERIC,
  mass_kg NUMERIC,
  battery_cells INT
);

CREATE TABLE flights (
  id UUID PRIMARY KEY,
  fleet_id UUID REFERENCES fleets(id),
  airframe_id UUID REFERENCES airframes(id),
  s3_key TEXT,
  file_name TEXT,
  uploaded_at TIMESTAMPTZ,
  flown_at TIMESTAMPTZ,
  duration_s NUMERIC,
  firmware TEXT,
  is_simulation BOOLEAN,
  status TEXT             -- pending, parsed, error
);

CREATE TABLE features (
  flight_id UUID PRIMARY KEY REFERENCES flights(id),
  data JSONB              -- the full feature dict from extract.py
);

CREATE TABLE anomalies (
  id UUID PRIMARY KEY,
  flight_id UUID REFERENCES flights(id),
  detected_at TIMESTAMPTZ,
  score NUMERIC,
  reasons JSONB           -- ["vibe_z_p95=37", "clip_events=45238"]
);
```

## Cost projection (MVP launch)

| Item                | Monthly | Notes |
|---------------------|---------|-------|
| Vercel (Next.js)    | $0      | Hobby tier free |
| Railway (FastAPI + Postgres + worker) | ~$20 | Starter plan |
| Backblaze B2 (raw logs) | ~$5 | 1TB |
| Domain              | ~$2     | logiq.fly or similar |
| **Total**           | **~$27/mo** | Profitable after first paying user |

## Research paper outline

**Title:** *Cross-Airframe Anomaly Detection in Multi-Rotor UAV Telemetry Using Lightweight Ensemble Models*

**Sections:**
1. Introduction — UAV operator pain: 100h flights, can't manually inspect logs
2. Related work — ArduPilot Log Analyzer (PR4-Log), commercial tools (none specialized)
3. Dataset — N flights, 9 airframes, simulation + real, labels {ok, bad-tune, vibration, crash, gps-loss}
4. Feature engineering — the ~60 features in `extract.py`
5. Model — Isolation Forest baseline → per-airframe normalized IF → LSTM autoencoder
6. Results — precision/recall on held-out labeled flights
7. Case studies — the 2021-08-17 crash, the 2023-02-02 vibration failure (visualize)
8. Deployment — operator feedback, time-to-diagnosis improvement
9. Conclusion + open dataset release (publish on Zenodo)

**Venues:**
- IEEE Aerospace Conference (March)
- AIAA SciTech Forum (January)
- ICUAS (International Conference on Unmanned Aircraft Systems, June)
