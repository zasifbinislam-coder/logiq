# LogIQ — Pitch Deck

*Speaker: Zasif Bin Islam · R&D Specialist, Diligite Ltd. · Bangladesh*
*Deck version: 0.0.2 · Updated 2026-05-19*

---

## Slide 1 — Title

> # LogIQ
> ### Open-source AI flight-log analytics for ArduPilot drones.
> *Catch crashes before they happen.*

---

## Slide 2 — The pain (real)

UAV commercial operators in Bangladesh and South Asia today:

- 🌾 **Agricultural spray pilots** fly 30-50 missions/week — no time or skill to read .bin files.
- 📸 **Aerial photographers / event shooters** discover damage only after a crash.
- 🏗️ **Construction-site inspection pilots** trust the drone until something snaps mid-air.
- 🎓 **Researchers** (CUET, BUET, MIST) sit on thousands of unanalyzed flights.

**Mission Planner's built-in analyzer** flags 4 rule-based thresholds per flight in isolation. It misses combinations and trends.

**Closed-source tools** (Auterion, FlightHub) start at $300+/month — out of reach for ~99% of operators.

---

## Slide 3 — What we built

**LogIQ** is the open-source alternative.

| Capability | Mission Planner | Closed SaaS ($300+/mo) | **LogIQ** |
|---|:-:|:-:|:-:|
| Parse .bin DataFlash | ✓ | ✓ | ✓ |
| Parse .tlog telemetry | ✓ | ✓ | ✓ |
| Plain-language verdict | — | partial | **✓ EN + Bangla** |
| Per-airframe baselines | — | ✓ | **✓** |
| Cross-flight drift alerts | — | ✓ | **✓** |
| PDF client report | — | ✓ | **✓** |
| WhatsApp bot | — | — | **✓** |
| CLI for automation | — | partial | **✓** |
| Web dashboard | — | ✓ | **✓** |
| Cost | free | $300+/mo | **$0–29/mo** |

---

## Slide 4 — How it works (30 seconds)

```
.bin / .tlog  ─►  pymavlink parser ─►  ~80 numeric features
                                      │
                                      ▼
                       Isolation Forest (per airframe class)
                                      │
                                      ▼
                       Plain-language verdict engine (EN + BN)
                                      │
              ┌───────────────────────┼───────────────────────┐
              ▼                       ▼                       ▼
        Web dashboard          PDF report               WhatsApp bot
```

7 Python workers process logs at **12.7 / second**. End-to-end (parse → score → deliver) in under a minute for a fleet's daily batch.

---

## Slide 5 — Validated on 575 real flights

> Real fleet, real anomalies, real drift — auto-detected with zero hand-tuning.

| Metric | Result |
|---|---|
| Logs analyzed | 575 across 4.6 years |
| Flight time | 29.3 hours |
| Anomalies flagged | 68 (11.8%) |
| **Real crash auto-detected** | 2021-08-17: 45K IMU clips + 71.9° roll error |
| **Vibration failure** | 2023-02-02: VIBE Z = 37 m/s² (DANGER) |
| **Predictive drift alert** | ADSB airframe vibration up 11× over 4 years (z=6.03) |
| Time to first verdict | <10 seconds on a laptop |

All three findings would have been missed by Mission Planner's built-in checks.

---

## Slide 6 — Live demo (90 seconds)

1. Open http://logiq.app (or local instance)
2. Drag `.bin` file onto upload zone
3. See **score 10/100, RED**, summary "Serious issues found. Do not fly until inspected."
4. **Action checklist** prioritized: "Inspect propellers", "Tighten frame screws", "Re-tune PID gains"
5. Toggle to বাংলা — every label switches to Banglish
6. Click "Download PDF" — printable client report

For the WhatsApp version: send `.bin` to bot number → reply in same format within 15 seconds.

---

## Slide 7 — Pricing

| Tier | Price/month | Limits |
|---|---|---|
| **Free / Open Source** | $0 | Self-host, unlimited |
| **Starter** | $9 | 50 flights/mo on our cloud |
| **Pro** | $29 | Unlimited flights, email alerts, PDF branding |
| **Team** | $99 | Multi-user, fleet trends, predictive maintenance |
| **Enterprise** | $499 | API, on-prem, paid support |

Cost to operate (Vercel + Railway + Backblaze + domain): **~$27/month**. Profitable from first $29 paying user.

---

## Slide 8 — Why now, why Bangladesh

- 🇧🇩 **CAAB drone regulations** rolled out 2020 → fast-growing commercial pilot base.
- 🌾 **DAE agricultural drone subsidy 2024** → expected 5,000+ spray drones deployed by 2027.
- 🇮🇳🇵🇰🇲🇲 South Asia uses ArduPilot dominantly (vs PX4 in West) — LogIQ's first focus.
- **First-mover advantage**: no Bangladesh-localized drone tool exists today.
- **CUET partnership** (Prof. Moshiul Hoque) — academic credibility + paper publication.

---

## Slide 9 — Roadmap (next 12 months)

| Quarter | Goal |
|---|---|
| Q3-2026 | Public beta launch · 100 free users · 10 paying customers |
| Q4-2026 | LSTM autoencoder for sub-flight anomaly windows · WhatsApp bot live |
| Q1-2027 | IEEE Aerospace Conference paper · 50 paying customers · CUET MOU |
| Q2-2027 | DAE / Krishi Mantranalay pilot · Bangladesh agriculture deployment |
| Q3-2027 | India + Pakistan expansion · 500 paying customers |

---

## Slide 10 — The ask

We're looking for:
- **Pilot users** — 10 commercial operators willing to upload their last 30 flights and give feedback
- **Co-investigators** — Bangladeshi academic + research labs for joint paper
- **Pre-seed** — $25k to cover one engineer (myself) for 6 months + cloud + travel for first 50 customer visits
- **CUET / SKITBI incubator placement** for office and mentorship

---

## Slide 11 — Why me

- **R&D Specialist, Diligite Ltd.** — actively shipping UAV products
- **Co-investigator, FireGuard CUET project** (BDT 34 lakh ICT Innovation Fund, 18 months)
- **1430+ real flight logs** on disk across 9+ ArduPilot airframes — best test dataset in BD
- **Built LogIQ MVP in one day** — proves shipping velocity
- **Bilingual EN + Bangla** product instincts — designed for the actual market

---

## Slide 12 — Contact

**Zasif Bin Islam**
zasifbinislam@gmail.com
Diligite Ltd., R&D Division
Chittagong, Bangladesh

📞 +880-XXXX-XXXXXX
🌐 logiq.app (coming soon)
🐙 github.com/zasifbinislam/logiq (private until launch)

> "Crashes are expensive. Inspection is cheap. LogIQ makes inspection automatic."
