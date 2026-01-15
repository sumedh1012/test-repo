from __future__ import annotations

import base64
import os
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import fitz  # PyMuPDF
from django.conf import settings


@dataclass(frozen=True)
class JobPaths:
    job_dir: Path
    original_pdf: Path
    edited_pdf: Path
    previews_dir: Path


def make_job_paths(job_id: str) -> JobPaths:
    job_dir = Path(settings.MEDIA_ROOT) / "jobs" / job_id
    previews_dir = job_dir / "previews"
    return JobPaths(
        job_dir=job_dir,
        original_pdf=job_dir / "original.pdf",
        edited_pdf=job_dir / "edited.pdf",
        previews_dir=previews_dir,
    )


def create_job_dir() -> JobPaths:
    job_id = uuid.uuid4().hex
    paths = make_job_paths(job_id)
    paths.previews_dir.mkdir(parents=True, exist_ok=True)
    return paths


def safe_hex_color_to_rgb01(hex_color: str) -> tuple[float, float, float]:
    # Accept "#RRGGBB" or "RRGGBB"
    s = hex_color.strip()
    if s.startswith("#"):
        s = s[1:]
    if not re.fullmatch(r"[0-9a-fA-F]{6}", s):
        return (0.0, 0.0, 0.0)
    r = int(s[0:2], 16) / 255.0
    g = int(s[2:4], 16) / 255.0
    b = int(s[4:6], 16) / 255.0
    return (r, g, b)


def render_previews(pdf_path: Path, previews_dir: Path, zoom: float = 2.0) -> list[dict[str, Any]]:
    """
    Renders each PDF page to a PNG in previews_dir.
    Returns list of metadata: page_num (0-based), width, height, preview_url_rel
    """
    doc = fitz.open(str(pdf_path))
    meta: list[dict[str, Any]] = []
    mat = fitz.Matrix(zoom, zoom)
    for i in range(len(doc)):
        page = doc[i]
        pix = page.get_pixmap(matrix=mat, alpha=False)
        out = previews_dir / f"page_{i+1:04d}.png"
        pix.save(str(out))
        rect = page.rect
        meta.append(
            {
                "page_index": i,
                "page_width": float(rect.width),
                "page_height": float(rect.height),
                "preview_rel": f"jobs/{previews_dir.parent.name}/previews/{out.name}",
            }
        )
    doc.close()
    return meta


def decode_data_url_to_bytes(data_url: str) -> bytes:
    """
    data_url like: data:image/png;base64,.....
    """
    if "," not in data_url:
        raise ValueError("Invalid data URL")
    header, b64 = data_url.split(",", 1)
    return base64.b64decode(b64)


def clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def normalize_rect(x: float, y: float, w: float, h: float) -> tuple[float, float, float, float]:
    # Ensure w,h positive
    if w < 0:
        x = x + w
        w = -w
    if h < 0:
        y = y + h
        h = -h
    return x, y, w, h