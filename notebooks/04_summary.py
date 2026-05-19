"""Final summary of fleet stats."""
import pandas as pd

df = pd.read_csv(r"C:\Users\zasif bin islam\Desktop\LogIQ\data\parquet\flights.csv")
ok = df[df["parse_error"].isna()].copy()

print(f"Total logs ingested: {len(df)}")
print(f"  Parseable: {len(ok)}")
print(f"  Errored:   {len(df) - len(ok)}")
print()
print(f"Total flight-hours: {ok['duration_s'].fillna(0).sum()/3600:.1f}h")

if "mtime" in ok.columns:
    s = ok["mtime"].dropna().astype(str)
    if len(s):
        print(f"Date range: {s.min()[:10]} -> {s.max()[:10]}")

if "firmware" in ok.columns:
    print(f"\nFirmware versions seen ({ok['firmware'].dropna().nunique()} unique):")
    print(ok["firmware"].value_counts().head(8).to_string())

print(f"\nFormat split:")
print(ok["format"].value_counts().to_string())

print(f"\nAnomaly-relevant stats (telemetry):")
tlog = ok[ok["format"] == "telemetry"]
print(f"  flights with VIBE Z p95 > 15 m/s2: {(tlog['vibe_z_p95'] > 15).sum()}")
print(f"  flights with clip_events > 100:    {(tlog['clip_events_total'] > 100).sum()}")
print(f"  flights with clip_events > 1000:   {(tlog['clip_events_total'] > 1000).sum()}")
print(f"  flights with clip_events > 10000:  {(tlog['clip_events_total'] > 10000).sum()}")

print(f"\nAnomaly-relevant stats (dataflash):")
bin_df = ok[ok["format"] == "dataflash"]
print(f"  flights with roll_err_p95 > 5deg:  {(bin_df['roll_err_deg_p95'] > 5).sum()}")
print(f"  flights with roll_err_p95 > 20deg: {(bin_df['roll_err_deg_p95'] > 20).sum()}")
print(f"  flights with VIBE Z p95 > 15:      {(bin_df['vibe_z_p95'] > 15).sum()}")
