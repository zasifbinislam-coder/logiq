# Cross-Airframe Anomaly Detection in Multi-Rotor UAV Telemetry Using Lightweight Ensemble Models and Per-Class Baselining

**Authors:** Zasif Bin Islam¹, Md. Monjurul Hasan², Md. Mosharraf Hossain², M. Moshiul Hoque²
¹Diligite Ltd., R&D Division, Bangladesh
²Department of CSE, Chittagong University of Engineering and Technology (CUET), Bangladesh

**Target venue:** IEEE Aerospace Conference 2027 (Big Sky, MT) — submission deadline October 2026
**Backup venue:** ICUAS 2027 (June, Wichita KS) — submission deadline November 2026

---

## Abstract (draft)

Operators of commercial multi-rotor UAVs accumulate hundreds of flight logs per
airframe, but lack a practical tool to surface degrading flights before they
become incidents. Existing analyzers (Mission Planner's PR4-Log, log_analyzer.py)
flag rule-based threshold breaches per flight in isolation, missing cumulative
drift and class-specific baselines. We present **LogIQ**, an open-source
analytics pipeline that (a) parses both ArduPilot DataFlash (.bin) and MAVLink
telemetry (.tlog) streams into a unified ~80-feature representation, (b) trains
an Isolation Forest anomaly detector per airframe class so the "normal" baseline
is calibrated to platform-specific vibration, control, and EKF characteristics,
and (c) detects cross-flight drift in safety-critical signals to surface
predictive-maintenance alerts. Evaluated on a 4.6-year, 575-flight, 29.3-hour
real-world dataset across multiple ArduCopter firmware versions and airframe
classes, LogIQ surfaced 68 anomalous flights — including a documented
near-crash (71° roll tracking error), a catastrophic vibration event (37 m/s²
VIBE Z, IMU saturation), and a previously unrecognized 11× vibration drift on
one airframe class — none of which were detected by Mission Planner's built-in
analyzer. The system runs at 12.7 logs/sec on a 7-core laptop, making
real-time post-flight analysis practical for fleet operators.

**Keywords:** UAV, ArduPilot, anomaly detection, telemetry analytics, predictive maintenance, isolation forest

---

## 1. Introduction

The growth of commercial multi-rotor UAV operations — agricultural spraying,
aerial photography, inspection, search-and-rescue — has produced large
quantities of operational telemetry that operators struggle to analyze
efficiently. A single hexacopter mission can generate 30+ MB of DataFlash log
data with 80+ message types sampled at up to 400 Hz. Open-source tools like
Mission Planner's log analyzer and the ArduPilot project's `log_analyzer.py`
apply hard-coded threshold checks per flight (e.g., "VIBE Z above 30 m/s² is
abnormal"). These miss two important regimes:

1. **Cross-airframe variation:** A vibration level that is normal for a heavy
   octocopter is alarming on a light quadcopter. A single global threshold
   either over-alerts on the heavy frame or misses warnings on the light frame.
2. **Cumulative drift:** Mechanical wear, bearing degradation, prop balance loss
   manifest as slow upward drifts in vibration and motor RPM imbalance over
   weeks of flying — never breaching a per-flight threshold but visible in
   fleet-level trends.

LogIQ addresses both gaps with per-class baselining and cross-flight drift
detection.

---

## 2. Related work

- **PR4-Log / log_analyzer.py** (ArduPilot project): rule-based threshold
  checks on a single flight. No baseline learning, no cross-flight context.
- **APM PlannerLog Analyzer**: visualization-only.
- **Auterion, FlightHub, DroneDeploy**: closed-source SaaS; cost-prohibitive
  for academic and small-operator use.
- **Academic anomaly detection on UAVs**: most prior work uses simulated data
  or labeled crash datasets (e.g., [Cao 2018, Sadhu 2021, Khan 2023]), with
  little open-source code to reproduce on operator data.

LogIQ is positioned as the open-source, real-data, multi-airframe analogue.

---

## 3. Dataset

The dataset comprises **575 successfully-parsed flight logs** collected from a
mixed UAV fleet operated by Diligite Ltd. and CUET researchers between
2021-08-15 and 2026-04-20:

| Format          | Count | Total bytes | Avg msg/log |
|-----------------|-------|-------------|-------------|
| DataFlash (.bin)| 19    | 70 MB       | ~60,000     |
| Telemetry (.tlog)| 556  | ~280 MB     | ~2,000      |

The fleet spans **6 airframe classes** as organized by Mission Planner:
QUADROTOR (370 flights, 22.0 h), ADSB (116 flights, 6.7 h), SMALL (72), BAD (8),
SITL (4, simulation), and GENERIC (5). Four ArduCopter firmware versions are
represented (V4.0.7, V4.1.5, V4.3.6, V4.5.3-beta1), plus 478 logs from earlier
ArduPilot versions identified only via HEARTBEAT.

Total operational flight time: **29.3 hours**.

---

## 4. Feature engineering

`extract.py` parses each log with pymavlink and emits a flat ~80-feature
vector. Features fall into seven groups:

| Group | Examples | DataFlash | Telemetry |
|-------|----------|-----------|-----------|
| Mission metadata | `duration_s`, `mode_changes`, `arming_events` | ✓ | ✓ |
| Battery | `volt_p95`, `curr_max`, `batt_rempct_drop` | ✓ | partial |
| Attitude tracking | `roll_err_deg_p95`, `pitch_err_deg_p95`, `yaw_err_deg_p95` | ✓ | – |
| Vibration | `vibe_x_p95`, `vibe_y_p95`, `vibe_z_p95`, `clip_events_total` | ✓ | ✓ |
| GPS | `gps_hdop_max`, `gps_nsats_min`, `gps_fixtype_mode` | ✓ | ✓ |
| EKF | `ekf_pos_var_p95`, `ekf_vel_var_p95`, `ekf_mag_var_p95` | ✓ | ✓ |
| Motor balance / ESC | `esc_rpm_cv`, `esc_rpm_range_pct`, `esc_worst_motor_dev_pct` | ✓ | – |

Tracking-error features (DesRoll vs Roll difference) and per-motor ESC
analytics are only present in DataFlash logs because MAVLink telemetry omits
the desired attitude stream and high-rate ESC data.

For each numerical feature we compute (min, max, mean, median, 95th
percentile) when applicable. FFT of raw IMU acceleration is computed when the
log has ≥256 IMU samples, yielding three dominant frequency peaks (used to
detect prop imbalance and motor bearing resonance).

---

## 5. Methodology

### 5.1 Isolation Forest with per-class baselines

We train one IsolationForest (n_estimators=200, contamination='auto',
random_state=42) per airframe class with ≥8 flights. Features are
median-imputed and StandardScaler-normalized within each class. A flight is
labeled anomalous if either (a) the global model OR (b) the per-class model
flags it as -1.

This dual-flag approach catches both **fleet-wide** outliers (a flight that's
weird by any standard) and **class-specific** outliers (a quadrotor that's
weird *compared to other quadrotors*).

### 5.2 Cross-flight drift detection

For each airframe class and each safety-critical metric M, we compare:

- **Baseline:** mean of M across the first half of flights
- **Current:** mean of M across the last 5 flights

We flag drift if `(current - baseline) / σ_baseline > 1.0` AND
`current > 1.5 × baseline`. The conjunction prevents false alerts on
low-baseline classes where small absolute changes blow up the z-score.

### 5.3 Heuristic explanation layer

Numeric flags don't help operators take action. We layer a deterministic
"explanation" function over the model output that translates flagged feature
values into human-readable diagnostics:

```
VIBE Z p95 = 37.4  →  "VIBE Z p95=37.4 (DANGER >30)"
clip_events = 241189 →  "IMU clipping=241,189 (severe saturation)"
roll_err_p95 = 71.9  →  "Roll tracking err p95=71.9° (CRASH-LEVEL)"
```

---

## 6. Results

### 6.1 Anomaly detection performance

LogIQ flagged **68 of 575 flights as anomalous** (11.8%). Breakdown by trigger:

| Trigger             | Count |
|---------------------|-------|
| Global model only   | 31    |
| Per-class model only| 37    |
| Both                | (subset of above) |

Per-class anomaly rates:

| Class     | Flights | Anomalies | Rate  |
|-----------|---------|-----------|-------|
| QUADROTOR | 370     | 24        | 6.5%  |
| ADSB      | 116     | 11        | 9.5%  |
| SMALL     | 72      | 30        | 41.7% |
| BAD       | 8       | 2         | 25.0% |
| SITL      | 4       | 1         | n/a   |
| GENERIC   | 5       | 0         | 0.0%  |

The very high "SMALL" rate is expected: this Mission Planner bucket contains
short bench-tests and connection sanity checks rather than actual flights. The
BAD bucket is the operator's manual quarantine for known-bad flights, so a
25% rate there *under-counts* the truly bad subset (those flights are short
and lack telemetry depth for the model to flag them).

### 6.2 Case study: 2021-08-17 near-crash

A 65-second QUADROTOR flight on 2021-08-17 was flagged with the maximum
diagnostic severity:

- **45,238 IMU clip events** (300+/second mean rate — total saturation)
- **Roll tracking error p95 = 71.9°** (commanded vs achieved roll)
- 5 ERR messages
- VIBE Z = 12.4 m/s² (below typical alarm thresholds in isolation)

The operator confirmed this corresponds to a documented prop-strike event
during early platform validation. Critically, **no single feature except the
71.9° tracking error exceeds Mission Planner's default warning thresholds** —
the diagnostic depends on the *combination* of features, which is precisely
what Isolation Forest detects and rule-based analyzers miss.

### 6.3 Case study: 2023-02-02 vibration failure

A 293-second QUADROTOR DataFlash log shows:

- **VIBE Z p95 = 37.4 m/s²** (DANGER >30)
- VIBE Y p95 = 27.2 m/s²
- VIBE X p95 = 9.5 m/s²
- 1 ERR message logged

Spectral analysis (FFT) of the raw AccZ stream revealed a dominant peak at
~93 Hz, consistent with prop blade-pass frequency at ~2800 RPM, indicating
prop imbalance rather than frame resonance.

### 6.4 Case study: ADSB class vibration drift

The most novel finding: predictive drift detection on the ADSB airframe class
(N=116 flights, 2021-08 → 2024-05):

| Metric       | Baseline | Current (last 5) | Δ      | z-score |
|--------------|----------|------------------|--------|---------|
| VIBE Z p95   | 0.31     | 3.47             | +3.16  | **6.03** |
| VIBE Y p95   | 0.38     | 3.00             | +2.62  | **4.36** |

This 11× vibration increase is invisible in any single-flight view — Mission
Planner's log analyzer reports each flight individually, and 3.5 m/s² is well
below the 30 m/s² warning threshold. The drift only emerges from cross-flight
aggregation, suggesting cumulative mechanical wear (motor bearings, prop
balance loss, or frame fastener loosening) that warrants inspection before
the next flight.

### 6.5 Throughput

Parallel batch ingestion (7-worker `ProcessPoolExecutor` on Intel Core i5
with 8 logical cores) processed 576 logs in **46.7 seconds**, sustaining **12.7
logs/second**. The full pipeline — parse, feature extraction, anomaly
scoring, HTML report generation — completes for a fresh dataset in under one
minute. This makes end-of-day batch analysis trivially fast even for
medium-fleet operators (50–200 flights/day).

---

## 7. Implementation and reproducibility

LogIQ is implemented in ~62 KB of Python (pymavlink, pandas, scikit-learn,
FastAPI) with a single-page HTML+Plotly dashboard. The codebase is organized
as:

```
src/logiq/
  extract.py      (22 KB)   format-agnostic feature extraction
  batch.py        ( 4 KB)   parallel ingestion
  db.py           ( 5 KB)   SQLite schema + load
  anomaly.py      ( 7 KB)   per-class IsolationForest + explanation
  predictive.py   ( 8 KB)   drift detection
  report.py       (11 KB)   static HTML reports
  flight_detail.py(13 KB)   per-flight Plotly drill-down
  trends.py       (12 KB)   fleet trends dashboard
  api.py          ( 7 KB)   FastAPI backend
```

We release source, evaluation scripts, and the de-identified flight log
dataset (CSV feature matrix; raw logs available on request) at:
`https://github.com/zasifbinislam/logiq` (TBD).

---

## 8. Discussion and limitations

**Limitations:**
- Per-class models require ≥8 flights per class; new airframes need a
  bootstrap period.
- IsolationForest is unsupervised; rare anomalies in heavily-skewed datasets
  may be underweighted. A labeled set of crash/near-crash flights would
  enable a hybrid supervised/unsupervised ensemble.
- `.tlog` lacks the desired-attitude stream, so tracking-error features are
  DataFlash-only. Operators relying on telemetry-only logs lose ~25% of
  the feature space.
- FFT features require ≥256 raw IMU samples; many short bench tests fall
  below this threshold.

**Future work:**
- LSTM autoencoder on per-flight time series for finer-grained anomaly
  segmentation (which 30-second window of the flight is anomalous, not just
  whole-flight scoring).
- Real-time streaming (MAVLink-over-UDP) for in-flight monitoring.
- Per-prop-size baselines (separate model for 10" vs 15" props within
  QUADROTOR class).

---

## 9. Conclusion

LogIQ demonstrates that lightweight, open-source flight-log analytics can
deliver insights that closed-source commercial tools and rule-based
analyzers miss — particularly per-class anomaly baselining and cross-flight
drift detection. A 575-flight, 29.3-hour real-world dataset surfaced 68
anomalies including a documented near-crash, a catastrophic vibration event,
and a previously unrecognized 11× drift on one airframe class. The system
is small enough to run on operator laptops, fast enough for daily batch use,
and accurate enough that all flagged top-15 anomalies correspond to
operator-confirmable real events.

---

## References (placeholder)

1. Cao, S. et al. (2018). Anomaly detection on quadrotor flight data. *Sensors*.
2. Sadhu, A. et al. (2021). UAV anomaly detection using LSTM autoencoders. *IEEE Sensors J.*
3. ArduPilot Project. (2024). log_analyzer.py source. https://github.com/ArduPilot/ardupilot
4. Mission Planner. (2024). Log Analysis documentation.
5. pymavlink Project. (2024). https://github.com/ArduPilot/pymavlink

---

## Appendix A: Feature list (selected)

(see `src/logiq/extract.py` for the complete list of ~80 features)
