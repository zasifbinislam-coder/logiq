"""
LogIQ — WhatsApp bot (Twilio-compatible).

Receives WhatsApp messages via Twilio webhook. If the message contains a media
attachment (.bin or .tlog), download → analyze → reply with verdict.

Local testing without Twilio:
  py -m logiq.whatsapp test <log_path>      # simulate webhook locally
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Optional

from logiq.extract import extract_features
from logiq.verdict import compute_verdict


def format_verdict_for_whatsapp(verdict: dict, lang: str = "en") -> str:
    """Build a WhatsApp-friendly text message (≤ 1600 chars)."""
    emoji = verdict.get("overall_emoji", "•")
    score = verdict.get("overall_score", 0)
    status = verdict.get("overall_status", "fair").upper()
    summary = verdict.get(f"summary_{lang}") or verdict.get("summary_en", "")

    lines = [
        f"{emoji} *LogIQ Verdict*",
        f"*{score}/100* — {status}",
        "",
        summary,
        "",
        "*Categories:*"
    ]
    for c in verdict.get("categories", []):
        name = c.get("name_bn" if lang == "bn" else "name_en", c["name_en"])
        icon = c["icon"]
        emoji2 = {"good": "✅", "fair": "🟡", "poor": "🟠", "critical": "🔴"}.get(c["status"], "•")
        lines.append(f"{emoji2} {icon} {name}: {c['score']}/100")

    actions = verdict.get("actions", [])
    if actions:
        lines.append("")
        lines.append("*Actions:*")
        for i, a in enumerate(actions[:5], 1):
            text = a.get(lang, a.get("en", ""))
            lines.append(f"{i}. {a.get('icon','•')} {text}")
    else:
        lines.append("")
        lines.append("✅ Nothing to fix — drone is healthy.")

    msg = "\n".join(lines)
    return msg[:1600]


def process_message(body: str, media_path: Optional[str], from_number: str = "unknown", lang: str = "en") -> str:
    """Main bot handler. Returns the reply text."""
    body = (body or "").strip().lower()

    if media_path and Path(media_path).exists():
        if Path(media_path).suffix.lower() not in (".bin", ".tlog"):
            return "Please send a .bin or .tlog flight log file."
        feats = extract_features(media_path)
        if feats.get("parse_error"):
            return f"Could not parse the log: {feats['parse_error']}"
        verdict = compute_verdict(feats)
        return format_verdict_for_whatsapp(verdict, lang=lang)

    if body in ("help", "start", "hi", "hello", "salam"):
        return (
            "👋 Welcome to LogIQ!\n\n"
            "Send me your drone flight log file (.bin or .tlog from Mission Planner / SD card) "
            "and I'll tell you in plain language how your drone did.\n\n"
            "Commands:\n"
            "• 'help' — this message\n"
            "• 'bn' — switch to Banglish replies\n"
            "• Send a log file directly to analyze it"
        )

    if body in ("bn", "bangla"):
        return "Banglish reply mode on. Tomar flight log .bin or .tlog file pathaiye dao."

    return "Hi! Send me a .bin or .tlog flight log file to analyze. Type 'help' for info."


# === Twilio FastAPI integration (drop-in route) ===
try:
    from fastapi import APIRouter, Form, Request
    from fastapi.responses import PlainTextResponse
    import httpx

    router = APIRouter()

    @router.post("/whatsapp/webhook", response_class=PlainTextResponse)
    async def whatsapp_webhook(
        request: Request,
        Body: str = Form(""),
        From: str = Form(""),
        NumMedia: int = Form(0),
        MediaUrl0: str = Form(""),
        MediaContentType0: str = Form(""),
    ):
        """Twilio sends a form-encoded POST with these fields."""
        media_path = None
        if NumMedia and MediaUrl0:
            # Download media
            suffix = ".bin" if "bin" in MediaContentType0.lower() else ".tlog"
            uploads = Path(r"C:\Users\zasif bin islam\Desktop\LogIQ\data\uploads")
            uploads.mkdir(parents=True, exist_ok=True)
            media_path = str(uploads / f"wa-{From.replace(':','-')}-{NumMedia}{suffix}")
            try:
                async with httpx.AsyncClient(timeout=60) as cli:
                    r = await cli.get(MediaUrl0)
                    Path(media_path).write_bytes(r.content)
            except Exception as e:
                return f"Failed to download attachment: {e}"

        lang = "bn" if "bn" in (Body or "").lower() else "en"
        reply = process_message(Body, media_path, from_number=From, lang=lang)

        # TwiML format
        twiml = f"<?xml version='1.0' encoding='UTF-8'?><Response><Message>{reply}</Message></Response>"
        return PlainTextResponse(content=twiml, media_type="application/xml")

except ImportError:
    router = None


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "test":
        log = sys.argv[2]
        msg = process_message("analyze this", log, from_number="+8801234567890", lang="en")
        print("---- bot reply (EN) ----")
        print(msg)
        print()
        msg = process_message("bn", log, from_number="+8801234567890", lang="bn")
        print("---- bot reply (BN) ----")
        print(msg)
    else:
        print(process_message("help", None))
