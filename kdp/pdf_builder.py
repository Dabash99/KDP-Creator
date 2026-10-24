"""Build the interior PDF from processed page images."""
from __future__ import annotations

import logging
from pathlib import Path

import img2pdf
from PIL import Image, ImageDraw, ImageFont

from .postprocess import PAGE_W_PX, PAGE_H_PX

log = logging.getLogger("kdp")

# ── "This Book Belongs To" page ───────────────────────────────────────────────

_FONT_PATHS = [
    r"C:\Windows\Fonts\georgia.ttf",
    r"C:\Windows\Fonts\arial.ttf",
    r"C:\Windows\Fonts\calibri.ttf",
    r"C:\Windows\Fonts\times.ttf",
]


def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for fp in _FONT_PATHS:
        try:
            return ImageFont.truetype(fp, size)
        except (OSError, IOError):
            continue
    return ImageFont.load_default()


def _create_title_page(scratch_dir: Path) -> Path:
    img = Image.new("L", (PAGE_W_PX, PAGE_H_PX), 255)
    draw = ImageDraw.Draw(img)

    font_title = _load_font(130)
    font_sub   = _load_font(80)
    font_line  = _load_font(70)

    cx = PAGE_W_PX // 2
    y  = PAGE_H_PX // 4

    def centered_text(text: str, font: ImageFont.ImageFont | ImageFont.FreeTypeFont, y_pos: int) -> None:
        bbox = draw.textbbox((0, 0), text, font=font)
        tw   = bbox[2] - bbox[0]
        draw.text((cx - tw // 2, y_pos), text, fill=0, font=font)

    centered_text("This Book", font_title, y)
    centered_text("Belongs To", font_title, y + 160)

    # Decorative rule
    rule_y = y + 380
    draw.line([(250, rule_y), (PAGE_W_PX - 250, rule_y)], fill=0, width=4)

    # Name line
    name_y = rule_y + 60
    centered_text("Name:", font_sub, name_y)
    line_y = name_y + 110
    draw.line([(350, line_y), (PAGE_W_PX - 350, line_y)], fill=0, width=3)

    # Bottom decorative rule
    draw.line(
        [(250, PAGE_H_PX - 280), (PAGE_W_PX - 250, PAGE_H_PX - 280)],
        fill=0, width=4,
    )
    centered_text("Happy Colouring!", font_line, PAGE_H_PX - 220)

    out = scratch_dir / "_title_page.png"
    img.save(out, format="PNG")
    return out


def _create_blank_page(scratch_dir: Path) -> Path:
    out = scratch_dir / "_blank_page.png"
    if not out.exists():
        Image.new("L", (PAGE_W_PX, PAGE_H_PX), 255).save(out, format="PNG")
    return out


# ── Main PDF builder ──────────────────────────────────────────────────────────

# 8.5 × 11 in in PDF points (1 pt = 1/72 in)
_PT_W = 8.5 * 72
_PT_H = 11.0 * 72


def build_pdf(
    clean_dir: Path,
    output_path: Path,
    page_ideas_ordered: list[str],
) -> int:
    """
    Assemble the interior PDF.
    Layout:
      Page 1 (right-hand): "This Book Belongs To"
      Page 2:              blank
      For each drawing:    drawing page, blank page
    Returns total page count.
    """
    scratch = output_path.parent
    title_page = _create_title_page(scratch)
    blank_page = _create_blank_page(scratch)

    # Build ordered list of clean page paths
    drawing_pages: list[Path] = []
    for idea in page_ideas_ordered:
        # Clean pages are named 01_slug.png; match by prefix number
        num_str = idea.split("_")[0]  # e.g. "01"
        matches = sorted(clean_dir.glob(f"{num_str}_*.png"))
        if matches:
            drawing_pages.append(matches[0])
        else:
            log.warning("No clean page found for %s — inserting blank", idea)
            drawing_pages.append(blank_page)

    # Compose final page list
    pages: list[Path] = [title_page, blank_page]
    for dp in drawing_pages:
        pages.append(dp)
        pages.append(blank_page)

    total = len(pages)
    log.info("PDF pages: 2 (title+blank) + %d drawings × 2 = %d total", len(drawing_pages), total)

    layout = img2pdf.get_layout_fun((_PT_W, _PT_H))
    pdf_bytes = img2pdf.convert([str(p) for p in pages], layout_fun=layout)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(pdf_bytes)
    return total
