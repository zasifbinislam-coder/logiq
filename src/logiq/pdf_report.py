"""
LogIQ — PDF report generator.

Produces a client-deliverable PDF with: header, overall score, category bars,
issues list, action checklist, and a footer with branding.

Usage:
    from logiq.pdf_report import build_pdf
    pdf_bytes = build_pdf(verdict_dict)
"""
from __future__ import annotations

from datetime import datetime
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas


STATUS_COLORS = {
    "good":     colors.HexColor("#10b981"),
    "fair":     colors.HexColor("#fbbf24"),
    "poor":     colors.HexColor("#f97316"),
    "critical": colors.HexColor("#dc2626"),
}


def _draw_bar(c, x, y, width, height, fill_pct, color):
    """Draw a horizontal progress bar."""
    c.setFillColor(colors.HexColor("#e5e7eb"))
    c.rect(x, y, width, height, fill=1, stroke=0)
    fill_w = width * (fill_pct / 100.0)
    c.setFillColor(color)
    c.rect(x, y, fill_w, height, fill=1, stroke=0)


def _wrap_text(c, text, x, y, max_width, font_size=10, font_name="Helvetica"):
    """Simple word wrap, returns final y."""
    c.setFont(font_name, font_size)
    words = text.split()
    line = ""
    line_h = font_size * 1.3
    for w in words:
        candidate = (line + " " + w).strip()
        if c.stringWidth(candidate, font_name, font_size) <= max_width:
            line = candidate
        else:
            c.drawString(x, y, line)
            y -= line_h
            line = w
    if line:
        c.drawString(x, y, line)
        y -= line_h
    return y


def build_pdf(verdict: dict) -> bytes:
    """Produce a PDF report from a verdict dict. Returns bytes."""
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    W, H = A4
    margin = 18 * mm

    flight = verdict.get("flight", {})
    score = verdict.get("overall_score", 0)
    status = verdict.get("overall_status", "fair")
    color = STATUS_COLORS.get(status, colors.grey)

    # === HEADER BAND ===
    c.setFillColor(colors.HexColor("#0a6b3b"))
    c.rect(0, H - 28 * mm, W, 28 * mm, fill=1, stroke=0)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 22)
    c.drawString(margin, H - 14 * mm, "LogIQ — Flight Health Report")
    c.setFont("Helvetica", 9)
    c.drawString(margin, H - 19 * mm, f"Generated {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    c.drawRightString(W - margin, H - 14 * mm, "https://logiq.app")
    c.drawRightString(W - margin, H - 19 * mm, "Diligite Ltd. R&D")

    y = H - 38 * mm

    # === FLIGHT META ===
    c.setFillColor(colors.HexColor("#1f2937"))
    c.setFont("Helvetica-Bold", 11)
    c.drawString(margin, y, "Flight")
    c.setFont("Helvetica", 10)
    y -= 5 * mm
    c.drawString(margin, y, f"File: {flight.get('file_name', '—')}")
    y -= 5 * mm
    c.drawString(margin, y, f"Date: {(flight.get('flown_at') or '—')[:19]}")
    y -= 5 * mm
    c.drawString(margin, y, f"Airframe class: {flight.get('bucket', '—')}     "
                            f"Duration: {flight.get('duration_s') or '—'}s     "
                            f"Format: {flight.get('format', '—')}     "
                            f"Firmware: {(flight.get('firmware') or '—')[:50]}")
    y -= 9 * mm

    # === BIG SCORE BLOCK ===
    block_h = 35 * mm
    c.setFillColor(color)
    c.rect(margin, y - block_h, 50 * mm, block_h, fill=1, stroke=0)
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 38)
    c.drawCentredString(margin + 25 * mm, y - 20 * mm, str(score))
    c.setFont("Helvetica-Bold", 11)
    c.drawCentredString(margin + 25 * mm, y - 28 * mm, status.upper())

    # summary text next to score
    text_x = margin + 56 * mm
    text_w = W - text_x - margin
    c.setFillColor(colors.HexColor("#111827"))
    c.setFont("Helvetica-Bold", 12)
    c.drawString(text_x, y - 6 * mm, "Verdict")
    _wrap_text(c, verdict.get("summary_en", ""), text_x, y - 12 * mm, text_w, font_size=11)
    c.setFont("Helvetica-Oblique", 9)
    c.setFillColor(colors.HexColor("#6b7280"))
    _wrap_text(c, verdict.get("summary_bn", ""), text_x, y - 22 * mm, text_w, font_size=10, font_name="Helvetica-Oblique")

    y -= block_h + 8 * mm

    # === CATEGORY BARS ===
    c.setFillColor(colors.HexColor("#1f2937"))
    c.setFont("Helvetica-Bold", 12)
    c.drawString(margin, y, "Health by category")
    y -= 7 * mm

    bar_w = W - 2 * margin - 50 * mm
    bar_h = 4 * mm

    for cat in verdict.get("categories", []):
        cscore = cat["score"]
        cstatus = cat["status"]
        ccolor = STATUS_COLORS.get(cstatus, colors.grey)
        c.setFillColor(colors.HexColor("#374151"))
        c.setFont("Helvetica-Bold", 10)
        c.drawString(margin, y, f"{cat['icon']}  {cat['name_en']}")
        c.setFillColor(ccolor)
        c.drawRightString(margin + 45 * mm, y, f"{cscore}/100")
        _draw_bar(c, margin + 50 * mm, y - 1 * mm, bar_w, bar_h, cscore, ccolor)
        y -= 5 * mm
        if cat.get("issues_en"):
            c.setFillColor(colors.HexColor("#6b7280"))
            c.setFont("Helvetica", 9)
            for issue in cat["issues_en"][:2]:
                c.drawString(margin + 6 * mm, y, "• " + issue)
                y -= 4 * mm
        y -= 2 * mm

    # === ACTIONS ===
    if y < 80 * mm:
        c.showPage()
        y = H - margin

    y -= 4 * mm
    c.setFillColor(colors.HexColor("#1f2937"))
    c.setFont("Helvetica-Bold", 12)
    c.drawString(margin, y, "What to do next")
    y -= 7 * mm

    actions = verdict.get("actions", [])
    if not actions:
        c.setFillColor(colors.HexColor("#059669"))
        c.setFont("Helvetica", 11)
        c.drawString(margin, y, "✓ Nothing to fix — drone is healthy.")
    else:
        for i, a in enumerate(actions, 1):
            if y < 30 * mm:
                c.showPage()
                y = H - margin
            pcolor = STATUS_COLORS.get(a.get("priority", "fair"), colors.grey)
            # priority badge
            c.setFillColor(pcolor)
            c.rect(margin, y - 5 * mm, 4 * mm, 5 * mm, fill=1, stroke=0)
            c.setFillColor(colors.HexColor("#111827"))
            c.setFont("Helvetica-Bold", 10)
            c.drawString(margin + 7 * mm, y - 2 * mm, f"{i}. {a.get('icon','•')} {a.get('category','')}")
            c.setFillColor(colors.HexColor("#374151"))
            c.setFont("Helvetica", 10)
            y_after = _wrap_text(c, a.get("en", ""), margin + 7 * mm, y - 6 * mm, W - 2 * margin - 7 * mm, font_size=10)
            c.setFillColor(colors.HexColor("#6b7280"))
            c.setFont("Helvetica-Oblique", 9)
            y_after = _wrap_text(c, a.get("bn", ""), margin + 7 * mm, y_after, W - 2 * margin - 7 * mm, font_size=9, font_name="Helvetica-Oblique")
            y = y_after - 3 * mm

    # === FOOTER ===
    c.setFillColor(colors.HexColor("#9ca3af"))
    c.setFont("Helvetica", 7)
    c.drawString(margin, 10 * mm, "LogIQ v0.0.2 — UAV Flight Log Analytics — github.com/zasifbinislam/logiq (private)")
    c.drawRightString(W - margin, 10 * mm, f"Generated for flight {flight.get('id', '—')[:8]}")

    c.save()
    return buf.getvalue()


if __name__ == "__main__":
    import json, sys
    from logiq.extract import extract_features
    from logiq.verdict import compute_verdict
    p = sys.argv[1] if len(sys.argv) > 1 else r"C:\Users\zasif bin islam\Documents\Mission Planner\logs\QUADROTOR\1\2023-02-02 23-16-05.bin"
    feats = extract_features(p)
    v = compute_verdict(feats)
    v["flight"] = {"file_name": feats["file"], "format": feats["format"], "duration_s": feats["duration_s"], "flown_at": feats["mtime"], "bucket": "QUADROTOR", "firmware": feats.get("firmware"), "id": "demo"}
    pdf = build_pdf(v)
    out = r"C:\Users\zasif bin islam\Desktop\LogIQ\reports\demo_report.pdf"
    with open(out, "wb") as f:
        f.write(pdf)
    print(f"Wrote {out} ({len(pdf):,} bytes)")
