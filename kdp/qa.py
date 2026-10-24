"""Automatic QA checks for generated coloring-book pages."""
from __future__ import annotations

from pathlib import Path
from typing import NamedTuple

import numpy as np
from PIL import Image

# ── Configurable thresholds ───────────────────────────────────────────────────

# Grayscale value boundaries
WHITE_THRESHOLD    = 230   # pixels >= this are considered "white"
DARK_THRESHOLD     = 60    # pixels <  this are "dark" (outlines)
MIDTONE_LOW        = 60    # midtone band: [MIDTONE_LOW, MIDTONE_HIGH]
MIDTONE_HIGH       = 200

# Percentage limits
DARK_MIN_PCT       = 2.0   # flag "too_empty"  if dark % < this
DARK_MAX_PCT       = 30.0  # flag "too_filled" if dark % > this
MIDTONE_MAX_PCT    = 20.0  # flag "grey"       if midtone % of non-white > this

# Edge proximity (fraction of page dimension)
EDGE_MARGIN_FRAC   = 0.04  # flag "cropped" if bbox within this fraction of any edge

# Background-noise detection
BG_BOX_FRAC        = 0.95  # bounding box is "full page" if bbox covers > this of area
BG_DENSITY_MAX     = 0.05  # flag "background" if bbox that large but density < this


class QAResult(NamedTuple):
    flags: list[str]       # list of flag names (empty = pass)
    dark_pct: float        # % of pixels that are dark
    midtone_pct: float     # % of non-white pixels that are midtone
    density: float         # dark / bbox_area

    @property
    def ok(self) -> bool:
        return len(self.flags) == 0


def check_image(path: Path) -> QAResult:
    """Run all QA checks on *path* and return a :class:`QAResult`."""
    img   = Image.open(path).convert("L")
    arr   = np.array(img, dtype=np.uint8)
    total = arr.size

    white_mask   = arr >= WHITE_THRESHOLD
    dark_mask    = arr < DARK_THRESHOLD
    midtone_mask = (arr >= MIDTONE_LOW) & (arr < MIDTONE_HIGH)
    non_white    = total - int(white_mask.sum())

    dark_pct    = 100.0 * dark_mask.sum() / total
    midtone_pct = (100.0 * midtone_mask.sum() / non_white) if non_white else 0.0

    flags: list[str] = []

    # 1. Grey / shading
    if midtone_pct > MIDTONE_MAX_PCT:
        flags.append("grey")

    # 2. Too empty / too filled
    if dark_pct < DARK_MIN_PCT:
        flags.append("too_empty")
    elif dark_pct > DARK_MAX_PCT:
        flags.append("too_filled")

    # 3. Bounding box too close to edge (cropped)
    non_white_coords = np.argwhere(~white_mask)  # shape (N, 2) rows [row, col]
    h, w = arr.shape
    density = 0.0
    if non_white_coords.size > 0:
        r_min, c_min = non_white_coords.min(axis=0)
        r_max, c_max = non_white_coords.max(axis=0)
        bbox_h = int(r_max - r_min)
        bbox_w = int(c_max - c_min)
        bbox_area = bbox_h * bbox_w if bbox_h > 0 and bbox_w > 0 else 1
        density = non_white_coords.shape[0] / bbox_area

        margin_h = EDGE_MARGIN_FRAC * h
        margin_w = EDGE_MARGIN_FRAC * w
        if r_min < margin_h or c_min < margin_w or r_max > h - margin_h or c_max > w - margin_w:
            flags.append("cropped")

        # 4. Background noise (large bbox + very low density)
        page_area  = h * w
        bbox_cover = bbox_area / page_area
        if bbox_cover > BG_BOX_FRAC and density < BG_DENSITY_MAX:
            flags.append("background")

    return QAResult(flags=flags, dark_pct=dark_pct, midtone_pct=midtone_pct, density=density)
