from __future__ import annotations
from pathlib import Path
import json
import fitz  # PyMuPDF
import img2pdf
from django.conf import settings
from django.http import FileResponse, HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_POST
import img2pdf
from django.http import HttpResponse, FileResponse
from PIL import Image

from .utils import (
    clamp,
    create_job_dir,
    decode_data_url_to_bytes,
    make_job_paths,
    normalize_rect,
    render_previews,
    safe_hex_color_to_rgb01,
)


@require_GET
def home(request):
    return render(request, "pdfkit/home.html")


@require_GET
def edit_upload(request):
    return render(request, "pdfkit/edit_upload.html")


@require_POST
def edit_upload_post(request):
    f = request.FILES.get("pdf")
    if not f:
        return HttpResponse("No PDF uploaded", status=400)

    paths = create_job_dir()
    with open(paths.original_pdf, "wb") as out:
        for chunk in f.chunks():
            out.write(chunk)

    # Render previews (server-side) for simple click-based coordinate picking
    meta = render_previews(paths.original_pdf, paths.previews_dir, zoom=2.0)

    # Save meta json for editor page
    meta_path = paths.job_dir / "meta.json"
    meta_path.write_text(json.dumps({"pages": meta}, indent=2), encoding="utf-8")

    return redirect("pdfkit:editor", job_id=paths.job_dir.name)


@require_GET
def editor(request, job_id: str):
    paths = make_job_paths(job_id)
    meta_path = paths.job_dir / "meta.json"
    if not meta_path.exists() or not paths.original_pdf.exists():
        return HttpResponse("Job not found", status=404)

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    pages = meta["pages"]

    return render(
        request,
        "pdfkit/editor.html",
        {
            "job_id": job_id,
            "pages": pages,
            "media_url": settings.MEDIA_URL,
        },
    )


@require_POST
def apply_edits(request, job_id: str):
    """
    Expects JSON body:
    {
      "ops": [
        {"type":"add_text","page":0,"x":10,"y":20,"text":"Hello","size":18,"color":"#ff0000"},
        {"type":"add_image","page":0,"x":50,"y":50,"w":200,"h":120,"dataUrl":"data:image/png;base64,..."},
        {"type":"redact","page":0,"x":100,"y":100,"w":150,"h":40}
      ]
    }
    """
    paths = make_job_paths(job_id)
    if not paths.original_pdf.exists():
        return JsonResponse({"ok": False, "error": "Job not found"}, status=404)

    try:
        payload = json.loads(request.body.decode("utf-8"))
        ops = payload.get("ops", [])
        if not isinstance(ops, list):
            raise ValueError("ops must be a list")
    except Exception as e:
        return JsonResponse({"ok": False, "error": f"Invalid JSON: {e}"}, status=400)

    doc = fitz.open(str(paths.original_pdf))

    try:
        for op in ops:
            t = op.get("type")
            page_index = int(op.get("page", 0))
            if page_index < 0 or page_index >= len(doc):
                continue
            page = doc[page_index]
            page_rect = page.rect

            if t == "add_text":
                x = float(op.get("x", 0))
                y = float(op.get("y", 0))
                text = str(op.get("text", ""))[:5000]
                size = float(op.get("size", 16))
                size = clamp(size, 6, 144)
                color = safe_hex_color_to_rgb01(str(op.get("color", "#000000")))

                x = clamp(x, 0, float(page_rect.width))
                y = clamp(y, 0, float(page_rect.height))

                page.insert_text(
                    fitz.Point(x, y),
                    text,
                    fontsize=size,
                    color=color,
                )

            elif t == "add_image":
                x = float(op.get("x", 0))
                y = float(op.get("y", 0))
                w = float(op.get("w", 200))
                h = float(op.get("h", 150))
                x, y, w, h = normalize_rect(x, y, w, h)

                # Keep within page bounds (best-effort)
                x = clamp(x, 0, float(page_rect.width))
                y = clamp(y, 0, float(page_rect.height))
                w = clamp(w, 1, float(page_rect.width) - x)
                h = clamp(h, 1, float(page_rect.height) - y)

                data_url = op.get("dataUrl")
                if not isinstance(data_url, str) or not data_url.startswith("data:image/"):
                    continue
                img_bytes = decode_data_url_to_bytes(data_url)

                rect = fitz.Rect(x, y, x + w, y + h)
                page.insert_image(rect, stream=img_bytes)

            elif t == "redact":
                # "Erase" via redaction (white fill). This actually removes content under the rectangle.
                x = float(op.get("x", 0))
                y = float(op.get("y", 0))
                w = float(op.get("w", 10))
                h = float(op.get("h", 10))
                x, y, w, h = normalize_rect(x, y, w, h)

                x = clamp(x, 0, float(page_rect.width))
                y = clamp(y, 0, float(page_rect.height))
                w = clamp(w, 1, float(page_rect.width) - x)
                h = clamp(h, 1, float(page_rect.height) - y)

                rect = fitz.Rect(x, y, x + w, y + h)
                page.add_redact_annot(rect, fill=(1, 1, 1))

        # Apply all redactions at end
        for i in range(len(doc)):
            doc[i].apply_redactions(images=fitz.PDF_REDACT_IMAGE_NONE)

        doc.save(str(paths.edited_pdf))
    finally:
        doc.close()

    return JsonResponse(
        {
            "ok": True,
            "download_url": f"/edit/{job_id}/download/",
        }
    )


@require_GET
def download_edited(request, job_id: str):
    paths = make_job_paths(job_id)
    if not paths.edited_pdf.exists():
        return HttpResponse("No edited PDF yet. Click Save in editor.", status=404)
    return FileResponse(open(paths.edited_pdf, "rb"), as_attachment=True, filename="edited.pdf")


@require_GET
def unlock_page(request):
    return render(request, "pdfkit/unlock.html")


@require_POST
def unlock_run(request):
    """
    Removes password ONLY when provided password successfully decrypts the PDF.
    """
    f = request.FILES.get("pdf")
    password = request.POST.get("password", "")

    if not f:
        return HttpResponse("No PDF uploaded", status=400)

    paths = create_job_dir()
    with open(paths.original_pdf, "wb") as out:
        for chunk in f.chunks():
            out.write(chunk)

    doc = fitz.open(str(paths.original_pdf))

    try:
        if doc.needs_pass:
            ok = doc.authenticate(password)
            if not ok:
                return HttpResponse("Wrong password (cannot unlock).", status=400)

        # Save unencrypted
        doc.save(str(paths.edited_pdf), encryption=fitz.PDF_ENCRYPT_NONE)
    finally:
        doc.close()

    return FileResponse(open(paths.edited_pdf, "rb"), as_attachment=True, filename="unlocked.pdf")


@require_GET
def images_to_pdf_page(request):
    return render(request, "pdfkit/images_to_pdf.html")

import os
from pathlib import Path
from dataclasses import dataclass

@dataclass
class JobPaths:
    job_dir: Path
    edited_pdf: Path

def create_job_dir():
    # Creates a unique folder for this specific conversion task
    base_dir = Path("media/jobs")
    base_dir.mkdir(parents=True, exist_ok=True)
    
    # In a real app, use a UUID or timestamp for the folder name
    import uuid
    unique_id = str(uuid.uuid4())
    job_dir = base_dir / unique_id
    job_dir.mkdir(exist_ok=True)
    
    return JobPaths(
        job_dir=job_dir,
        edited_pdf=job_dir / "output.pdf"
    )

@require_POST
def images_to_pdf_run(request):
    imgs = request.FILES.getlist("images")
    if not imgs:
        return HttpResponse("No images uploaded", status=400)

    paths = create_job_dir() 
    img_paths = []

    for i, f in enumerate(imgs):
        ext = (Path(f.name).suffix or ".jpg").lower()
        temp_img_path = paths.job_dir / f"img_{i:04d}{ext}"
        
        # --- COMPRESSION LOGIC START ---
        with Image.open(f) as img:
            # 1. Convert to RGB (required for JPEG saving)
            if img.mode != 'RGB':
                img = img.convert('RGB')
            
            # 2. Optional: Resize if the image is massive (saves TONS of space)
            # 2000px is more than enough for high-quality A4 printing
            img.thumbnail((2000, 2000), Image.Resampling.LANCZOS)
            
            # 3. Save with compression quality (75 is the sweet spot)
            img.save(temp_img_path, "JPEG", optimize=True, quality=75)
        # --- COMPRESSION LOGIC END ---

        img_paths.append(str(temp_img_path))

    # A4 Configuration (same as before)
    a4_size = (img2pdf.mm_to_pt(210), img2pdf.mm_to_pt(297))
    margin = img2pdf.mm_to_pt(10)
    
    layout_fun = img2pdf.get_layout_fun(
        pagesize=a4_size,
        border=(margin, margin),
        fit=img2pdf.FitMode.into
    )

    pdf_bytes = img2pdf.convert(img_paths, layout_fun=layout_fun)
    paths.edited_pdf.write_bytes(pdf_bytes)

    return FileResponse(open(paths.edited_pdf, "rb"), as_attachment=True, filename="compressed_images.pdf")

