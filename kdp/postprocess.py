"""Post-process raw generated pages into print-ready B&W PNGs."""
from __future__ import annotations

from pathlib import Path

from PIL import Image

# ── Output dimensions (8.5 × 11 in @ 300 DPI) ────────────────────────────────
PAGE_W_PX    = 2550   # 8.5 in × 300 dpi
PAGE_H_PX    = 3300   # 11.0 in × 300 dpi
MARGIN_PX    = 150    # 0.5 in × 300 dpi — safe margin on every side
DRAW_W       = PAGE_W_PX - 2 * MARGIN_PX   # 2250
DRAW_H       = PAGE_H_PX - 2 * MARGIN_PX   # 3000

# Default B&W threshold (0–255); pixels >= threshold become white
DEFAULT_THRESHOLD = 140


def process_page(
    raw_path: Path,
    dest_path: Path,
    threshold: int = DEFAULT_THRESHOLD,
) -> Path:
    """
    Convert *raw_path* into a print-ready PNG at *dest_path*:
      1. Grayscale
      2. Lanczos-scale to fit inside the drawing area with margins
      3. Paste centred on a white 2550×3300 canvas
      4. Threshold to pure black/white
    """
    img = Image.open(raw_path).convert("L")

    # Scale to fit drawing area preserving aspect ratio
    img.thumbnail((DRAW_W, DRAW_H), Image.LANCZOS)

    # Paste onto white canvas, centred
    canvas = Image.new("L", (PAGE_W_PX, PAGE_H_PX), 255)
    paste_x = (PAGE_W_PX - img.width)  // 2
    paste_y = (PAGE_H_PX - img.height) // 2
    canvas.paste(img, (paste_x, paste_y))

    # Hard threshold → pure black/white
    canvas = canvas.point(lambda p: 255 if p >= threshold else 0, "L")

    dest_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(dest_path, format="PNG", optimize=False)
    return dest_path
