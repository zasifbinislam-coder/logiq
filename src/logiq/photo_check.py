"""
LogIQ — Photo damage check (lightweight).

The operator uploads a photo of their drone. We:
  1. Compute a sharpness/blur score so blurry uploads can be rejected.
  2. Run a basic edge/contour analysis to detect candidate damage regions (chips, cracks).
  3. Optionally accept user-tagged regions of concern.
  4. Return a structured "inspection" record (not a diagnosis — we're not a vision-AI yet).

This is a deliberately conservative first version. Real damage detection
needs a labeled CV model; we lay the API and storage scaffold here so a
future ML model drops in cleanly.
"""
from __future__ import annotations

import io
import json
import os
import uuid
from pathlib import Path
from typing import Any

from PIL import Image, ImageFilter, ImageStat


PHOTO_DIR = Path(r"C:\Users\zasif bin islam\Desktop\LogIQ\data\photos")


def _variance_of_laplacian(img: Image.Image) -> float:
    """Approximate Laplacian variance — higher = sharper."""
    gray = img.convert("L")
    laplacian = gray.filter(ImageFilter.Kernel((3, 3), [0, -1, 0, -1, 4, -1, 0, -1, 0], scale=1))
    stat = ImageStat.Stat(laplacian)
    return float(stat.stddev[0] ** 2)


def _high_contrast_blob_count(img: Image.Image, threshold: int = 60) -> int:
    """Count edge-heavy regions as a crude 'damage candidate' indicator."""
    gray = img.convert("L").resize((640, int(640 * img.height / max(img.width, 1))))
    edges = gray.filter(ImageFilter.FIND_EDGES)
    bw = edges.point(lambda p: 255 if p > threshold else 0)
    # count "on" pixels as a proxy
    on_pixels = sum(1 for p in bw.getdata() if p > 0)
    return on_pixels


def analyze_photo(image_bytes: bytes, user_notes: str = "") -> dict[str, Any]:
    """Analyze an uploaded drone photo. Returns inspection record."""
    PHOTO_DIR.mkdir(parents=True, exist_ok=True)
    inspection_id = str(uuid.uuid4())
    fp = PHOTO_DIR / f"{inspection_id}.jpg"

    try:
        img = Image.open(io.BytesIO(image_bytes))
    except Exception as e:
        return {"id": inspection_id, "ok": False, "error": f"Could not read image: {e}"}

    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    img.thumbnail((1600, 1600))
    img.save(fp, "JPEG", quality=85)

    sharpness = _variance_of_laplacian(img)
    edge_score = _high_contrast_blob_count(img)
    width, height = img.size

    blurry = sharpness < 80
    edge_dense = edge_score > (width * height * 0.03)

    advice_en: list[str] = []
    advice_bn: list[str] = []

    if blurry:
        advice_en.append("Photo is blurry. Re-take with steadier hands and good light.")
        advice_bn.append("Photo blur. Steady hath e ar valo light e abar tulen.")

    if edge_dense and not blurry:
        advice_en.append("Many high-contrast edges detected — could be damage, dirt, or just busy background. Inspect close-up.")
        advice_bn.append("Onek edge paya gechhe — damage, dirt, ba busy background hote pare. Close-up e dekho.")

    if user_notes:
        # Echo user notes back into the record so it shows up in reports
        advice_en.append(f"Operator note: {user_notes}")
        advice_bn.append(f"Operator note: {user_notes}")

    # Risk score: combination of sharpness (good) and edge density (warning)
    risk_score = 0
    if blurry: risk_score += 30
    if edge_dense: risk_score += 25
    if user_notes.strip(): risk_score += 20  # operator concerned

    record = {
        "id": inspection_id,
        "ok": True,
        "stored_path": str(fp),
        "size": [width, height],
        "sharpness_score": round(sharpness, 1),
        "edge_score": int(edge_score),
        "blurry": blurry,
        "edge_dense": edge_dense,
        "risk_score": min(risk_score, 100),
        "advice_en": advice_en,
        "advice_bn": advice_bn,
        "notes": user_notes,
    }

    # Persist as JSON next to image
    sidecar = fp.with_suffix(".json")
    sidecar.write_text(json.dumps(record, indent=2), encoding="utf-8")
    return record
