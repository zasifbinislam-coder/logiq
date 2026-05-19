"""
LogIQ — Parallel batch ingest of ArduPilot logs (.bin, .tlog, .rlog).
"""
from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
import csv
import os
import sys
import time

from logiq.extract import extract_features


EXTENSIONS = {".bin", ".tlog"}  # .rlog skipped: Mission Planner replay format, not MAVLink


def _worker(p: str) -> dict:
    t0 = time.time()
    try:
        f = extract_features(p)
    except Exception as e:
        f = {"file": Path(p).name, "path": p, "parse_error": f"exception: {type(e).__name__}: {e}"}
    f["_parse_seconds"] = round(time.time() - t0, 2)
    return f


def run(
    log_root: str,
    out_csv: str,
    out_parquet: str | None = None,
    max_files: int | None = None,
    exts: set[str] | None = None,
    workers: int | None = None,
) -> int:
    root = Path(log_root)
    exts = exts or EXTENSIONS
    files = sorted(
        [p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in exts],
        key=lambda p: p.stat().st_size,
        reverse=True,
    )
    if max_files:
        files = files[:max_files]

    workers = workers or max(1, (os.cpu_count() or 4) - 1)
    print(f"Found {len(files)} log files ({', '.join(sorted(exts))}) under {root}", flush=True)
    print(f"Workers: {workers}", flush=True)

    rows: list[dict] = []
    paths = [str(p) for p in files]
    t_start = time.time()

    with ProcessPoolExecutor(max_workers=workers) as ex:
        futures = {ex.submit(_worker, p): p for p in paths}
        done = 0
        for fut in as_completed(futures):
            done += 1
            try:
                r = fut.result()
            except Exception as e:
                p = futures[fut]
                r = {"file": Path(p).name, "path": p, "parse_error": f"future-exception: {e}"}
            rows.append(r)
            if done % 25 == 0 or done == len(paths):
                elapsed = time.time() - t_start
                rate = done / elapsed if elapsed > 0 else 0
                eta = (len(paths) - done) / rate if rate > 0 else 0
                print(f"  [{done}/{len(paths)}]  elapsed={elapsed:.1f}s  rate={rate:.1f}/s  eta={eta:.0f}s", flush=True)

    # union of keys
    all_keys: list[str] = []
    seen: set[str] = set()
    priority = [
        "file", "format", "mtime", "size_mb", "parse_error",
        "is_simulation", "firmware", "duration_s",
        "arming_events", "disarming_events", "unique_modes", "mode_changes", "error_count",
    ]
    for k in priority:
        if k not in seen:
            all_keys.append(k); seen.add(k)
    for r in rows:
        for k in r:
            if k not in seen:
                all_keys.append(k); seen.add(k)

    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=all_keys)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k) for k in all_keys})

    print(f"\nWrote {len(rows)} rows -> {out_csv}", flush=True)

    if out_parquet:
        try:
            import pandas as pd
            df = pd.DataFrame(rows)
            for col in ("unique_modes", "errors"):
                if col in df.columns:
                    df[col] = df[col].astype(str)
            df.to_parquet(out_parquet, index=False)
            print(f"Wrote parquet -> {out_parquet}", flush=True)
        except Exception as e:
            print(f"Parquet write failed: {e}", flush=True)

    return len(rows)


if __name__ == "__main__":
    root = sys.argv[1] if len(sys.argv) > 1 else r"C:\Users\zasif bin islam\Documents\Mission Planner\logs"
    out_csv = sys.argv[2] if len(sys.argv) > 2 else r"C:\Users\zasif bin islam\Desktop\LogIQ\data\parquet\flights.csv"
    out_pq = sys.argv[3] if len(sys.argv) > 3 else r"C:\Users\zasif bin islam\Desktop\LogIQ\data\parquet\flights.parquet"
    run(root, out_csv, out_pq)
