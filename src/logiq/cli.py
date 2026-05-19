"""
LogIQ — Command-line tool.

Usage:
    py -m logiq.cli <logfile>                # show verdict in terminal
    py -m logiq.cli <logfile> --json         # output verdict as JSON
    py -m logiq.cli <logfile> --pdf out.pdf  # also write PDF
    py -m logiq.cli <logfile> --lang bn      # Banglish output
    py -m logiq.cli --batch <folder>         # walk folder, summarize each
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from logiq.extract import extract_features
from logiq.verdict import compute_verdict


COLORS = {
    "good":     "\033[32m",  # green
    "fair":     "\033[33m",  # yellow
    "poor":     "\033[38;5;208m",  # orange
    "critical": "\033[31m",  # red
    "reset":    "\033[0m",
    "bold":     "\033[1m",
    "dim":      "\033[2m",
}


def _color(text: str, status: str) -> str:
    if sys.stdout.isatty():
        return f"{COLORS.get(status, '')}{text}{COLORS['reset']}"
    return text


def _emoji_for(status: str) -> str:
    return {"good": "🟢", "fair": "🟡", "poor": "🟠", "critical": "🔴"}.get(status, "·")


def _bar(score: int, width: int = 20) -> str:
    filled = int(width * score / 100)
    return "█" * filled + "░" * (width - filled)


def print_verdict(verdict: dict, lang: str = "en", flight_name: str = "") -> None:
    status = verdict["overall_status"]
    score = verdict["overall_score"]

    print()
    print(_color("=" * 64, "bold"))
    print(_color(f" LogIQ Verdict — {flight_name or 'flight'}", "bold"))
    print(_color("=" * 64, "bold"))
    print()
    print(f"  {_emoji_for(status)} {_color(f'Overall: {score}/100', status)} {_color(f'[{status.upper()}]', status)}")
    print(f"     {_bar(score, 40)}")
    print()
    summary = verdict.get(f"summary_{lang}") or verdict.get("summary_en", "")
    print(f"  {summary}")
    print()
    print(_color("  HEALTH BY CATEGORY", "bold"))
    for c in verdict["categories"]:
        cscore = c["score"]
        cstatus = c["status"]
        name_key = "name_bn" if lang == "bn" else "name_en"
        name = c.get(name_key, c["name_en"])
        print(f"    {c['icon']} {name:18s} {_color(str(cscore).rjust(3), cstatus)}/100  {_bar(cscore, 20)}")
        for issue in c.get(f"issues_{lang}", c.get("issues_en", []))[:2]:
            print(_color(f"        - {issue}", "dim"))
    print()
    actions = verdict.get("actions", [])
    if actions:
        print(_color("  WHAT TO DO NEXT", "bold"))
        for i, a in enumerate(actions[:6], 1):
            text = a.get(lang, a.get("en", ""))
            print(f"    {i}. {_color('●', a.get('priority', 'fair'))} {a.get('icon', '·')} {a.get('category', '')}")
            print(f"       {text}")
    else:
        print(_color("  ✓ Nothing to fix — drone is healthy", "good"))
    print()
    print(_color("=" * 64, "dim"))


def cmd_analyze(args: argparse.Namespace) -> int:
    path = Path(args.logfile)
    if not path.exists():
        print(f"File not found: {path}", file=sys.stderr)
        return 2

    print(f"Parsing {path.name} ({path.stat().st_size / 1024 / 1024:.1f} MB) …")
    feats = extract_features(path)
    if feats.get("parse_error"):
        print(f"Parse error: {feats['parse_error']}", file=sys.stderr)
        return 3
    verdict = compute_verdict(feats)

    if args.json:
        out = {"features": feats, "verdict": verdict}
        print(json.dumps(out, indent=2, ensure_ascii=False, default=str))
    else:
        verdict["flight"] = {"file_name": path.name}
        print_verdict(verdict, lang=args.lang, flight_name=path.name)

    if args.pdf:
        from logiq.pdf_report import build_pdf
        verdict.setdefault("flight", {})
        verdict["flight"].update({
            "file_name": path.name, "format": feats.get("format"),
            "duration_s": feats.get("duration_s"), "flown_at": feats.get("mtime"),
            "firmware": feats.get("firmware"), "bucket": "cli",
        })
        pdf_bytes = build_pdf(verdict)
        Path(args.pdf).write_bytes(pdf_bytes)
        print(f"\nPDF written: {args.pdf}  ({len(pdf_bytes):,} bytes)")

    return 0 if verdict["overall_status"] in ("good", "fair") else 1


def cmd_batch(args: argparse.Namespace) -> int:
    root = Path(args.folder)
    if not root.is_dir():
        print(f"Not a folder: {root}", file=sys.stderr)
        return 2

    files = sorted([p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in (".bin", ".tlog")])
    print(f"Found {len(files)} logs")
    print(f"{'STATUS':10s} {'SCORE':>5s}   FILE")
    print("-" * 80)
    for f in files:
        try:
            feats = extract_features(f)
            if feats.get("parse_error"):
                print(f"{'ERROR':10s} {'  -':>5s}   {f.name}  ({feats['parse_error']})")
                continue
            v = compute_verdict(feats)
            print(f"{_color(v['overall_status'].upper().ljust(10), v['overall_status'])} {v['overall_score']:>5d}   {f.name}")
        except Exception as e:
            print(f"{'CRASH':10s} {'  -':>5s}   {f.name}  ({e})")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(prog="logiq", description="LogIQ — UAV flight log analyzer")
    sub = ap.add_subparsers(dest="cmd")

    a = sub.add_parser("analyze", help="Analyze one log file")
    a.add_argument("logfile")
    a.add_argument("--json", action="store_true", help="JSON output")
    a.add_argument("--pdf", help="Also write a PDF report to this path")
    a.add_argument("--lang", choices=["en", "bn"], default="en")
    a.set_defaults(func=cmd_analyze)

    b = sub.add_parser("batch", help="Analyze every log in a folder")
    b.add_argument("folder")
    b.set_defaults(func=cmd_batch)

    # Shortcut: `logiq <file>` -> analyze ; `logiq <folder>` -> batch
    if len(sys.argv) >= 2 and sys.argv[1] not in ("analyze", "batch", "-h", "--help"):
        first = sys.argv[1]
        p = Path(first)
        if p.is_file():
            sys.argv = [sys.argv[0], "analyze"] + sys.argv[1:]
        elif p.is_dir():
            sys.argv = [sys.argv[0], "batch"] + sys.argv[1:]

    args = ap.parse_args()
    if not getattr(args, "func", None):
        ap.print_help()
        return 1
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
