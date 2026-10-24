"""Write upload_details.txt and run KDP metadata validation."""
from __future__ import annotations

import re
from pathlib import Path

from .parser import KDPBook

# ── KDP-allowed HTML tags in description ─────────────────────────────────────
_ALLOWED_TAGS = {"b", "i", "u", "br", "p", "ul", "ol", "li", "h4", "h5", "h6"}
_TAG_RE       = re.compile(r"</?([a-zA-Z0-9]+)[^>]*>")

# White paper, B&W:  spine = pages × 0.002252 in
_SPINE_PER_PAGE_IN = 0.002252
_BLEED_EXTRA_IN    = 0.25   # KDP adds 0.125 in each side
_COVER_H_IN        = 11.0 + _BLEED_EXTRA_IN
_SINGLE_W_IN       = 8.5
_DPI               = 300


# ── Validation ────────────────────────────────────────────────────────────────

def _load_blacklist(script_dir: Path) -> list[str]:
    bl_path = script_dir / "blacklist.txt"
    if not bl_path.exists():
        return []
    lines = bl_path.read_text(encoding="utf-8").splitlines()
    return [l.strip().lower() for l in lines if l.strip() and not l.startswith("#")]


def validate(book: KDPBook, n_ideas: int, script_dir: Path) -> list[str]:
    """Return a list of warning strings (empty = all clear)."""
    warnings: list[str] = []
    blacklist = _load_blacklist(script_dir)

    # Title colon
    if ":" in book.book_title:
        warnings.append(
            f"Title contains a colon — KDP rejects colons in the title field: '{book.book_title}'"
        )

    # Title + Subtitle length
    combined = book.book_title + (" " + book.subtitle if book.subtitle else "")
    if len(combined) > 200:
        warnings.append(
            f"Title + Subtitle is {len(combined)} chars (KDP limit 200)"
        )

    # Keywords
    if len(book.keywords) > 7:
        warnings.append(
            f"Too many keywords: {len(book.keywords)} (KDP allows exactly 7)"
        )
    for i, kw in enumerate(book.keywords, 1):
        if len(kw) > 50:
            warnings.append(f"Keyword {i} is {len(kw)} chars (limit 50): '{kw}'")

    # Description length
    if len(book.description) > 4000:
        warnings.append(
            f"Description is {len(book.description)} chars (KDP limit 4000)"
        )

    # Description tags
    bad_tags = set()
    for m in _TAG_RE.finditer(book.description):
        tag = m.group(1).lower()
        if tag not in _ALLOWED_TAGS:
            bad_tags.add(tag)
    if bad_tags:
        warnings.append(
            f"Description uses unsupported HTML tags: {', '.join(sorted(bad_tags))}"
        )

    # Blacklist check — title, subtitle, description, keywords
    def _check_text(label: str, text: str) -> None:
        low = text.lower()
        hits = [b for b in blacklist if b in low]
        if hits:
            warnings.append(
                f"'{label}' may contain a restricted brand/character name: {hits}"
            )

    _check_text("Title",    book.book_title)
    _check_text("Subtitle", book.subtitle)
    _check_text("Description", book.description)
    for i, kw in enumerate(book.keywords, 1):
        _check_text(f"Keyword {i}", kw)

    # Page count in title/subtitle vs actual.
    # Strip age-range tokens first (e.g. "Ages 1-3", "1-3") so they are never
    # mistaken for a page count.
    title_sub = book.book_title + " " + book.subtitle
    title_for_count = re.sub(r'\bages?\s+\d+\s*[-–]\s*\d+\b', '', title_sub, flags=re.IGNORECASE)
    title_for_count = re.sub(r'\b\d+\s*[-–]\s*\d+\b', '', title_for_count)
    m = re.search(r"\b(\d+)\b", title_for_count)
    if m:
        promised = int(m.group(1))
        if promised != n_ideas:
            warnings.append(
                f"Title/Subtitle promises {promised} pages but the file has {n_ideas} page ideas"
            )

    return warnings


# ── Cover dimension calculator ────────────────────────────────────────────────

def cover_dimensions(total_pages: int) -> dict:
    spine_in    = total_pages * _SPINE_PER_PAGE_IN
    full_w_in   = 2 * _SINGLE_W_IN + spine_in + _BLEED_EXTRA_IN
    full_h_in   = _COVER_H_IN
    full_w_px   = round(full_w_in * _DPI)
    full_h_px   = round(full_h_in * _DPI)
    spine_px    = round(spine_in * _DPI)
    return dict(
        spine_in=spine_in, full_w_in=full_w_in, full_h_in=full_h_in,
        full_w_px=full_w_px, full_h_px=full_h_px, spine_px=spine_px,
    )


# ── Writer ────────────────────────────────────────────────────────────────────

def write_upload_details(
    book: KDPBook,
    book_dir: Path,
    interior_pdf: Path,
    total_pages: int,
    warnings: list[str],
    author_override: str = "",
) -> Path:
    out_path = book_dir / "upload_details.txt"
    dims = cover_dimensions(total_pages)

    author = author_override if author_override else (book.author or "AUTHOR: <fill in before upload>")

    lines: list[str] = []

    def h(title: str) -> None:
        lines.append("")
        lines.append("=" * 70)
        lines.append(f"  {title.upper()}")
        lines.append("=" * 70)

    def field(label: str, value: str) -> None:
        lines.append(f"{label:<28} {value}")

    # ── Warnings at the top ───────────────────────────────────────────────────
    if warnings:
        lines.append("!! WARNINGS — fix before uploading !!")
        for w in warnings:
            lines.append(f"  ⚠  {w}")
        lines.append("")

    # ── Paperback Details ────────────────────────────────────────────────────
    h("Paperback Details")
    field("Language:",            book.language or "English")
    field("Book Title:",          book.book_title)
    field("Subtitle:",            book.subtitle)
    field("Series:",              book.series)
    field("Edition Number:",      book.edition_number)
    field("Author:",              author)
    field("Contributors:",        book.contributors)
    field("Publishing Rights:",   book.publishing_rights or "I own the copyright and I hold the necessary publishing rights.")
    field("Sexually Explicit:",   book.sexually_explicit or "No")
    field("Reading Age (min):",   book.reading_age_min)
    field("Reading Age (max):",   book.reading_age_max)
    field("Primary Marketplace:", book.primary_marketplace or "Amazon.com")
    field("Low-content/Notes:",   book.low_content_notes)
    field("Publication Date:",    book.publication_date)
    field("Release Date:",        book.release_date)

    h("Description (paste HTML into KDP rich-text box)")
    lines.append(book.description)

    h("Keywords (7 entries, one per line)")
    for i, kw in enumerate(book.keywords, 1):
        lines.append(f"  {i}. {kw}  [{len(kw)} chars]")
    if len(book.keywords) < 7:
        for i in range(len(book.keywords) + 1, 8):
            lines.append(f"  {i}. <fill in>")

    h("Categories (verify names in the KDP category picker)")
    for cat in book.categories:
        lines.append(f"  • {cat}")
    if not book.categories:
        lines.append("  <no categories parsed — fill in manually>")

    # ── Paperback Content ────────────────────────────────────────────────────
    h("Paperback Content")
    field("Print ISBN:",   "Free KDP ISBN (assign at upload)")
    field("Paper:",        book.paper or "White")
    field("Interior:",     book.interior or "Black & White Standard")
    field("Trim size:",    book.trim or "8.5 x 11 in")
    field("Bleed:",        book.bleed or "No bleed")
    field("Cover finish:", book.cover_finish or "Matte")
    lines.append("")
    field("Interior page count:", str(total_pages))
    field("Interior PDF to upload:", str(interior_pdf))
    field("Cover file to upload:",  str(book_dir / "cover" / "front.png")
                                    + "  (OR the Canva wrap-around cover you build below)")

    # ── Cover dimensions ─────────────────────────────────────────────────────
    h("Cover Wrap Dimensions — ESTIMATE — confirm with KDP Cover Calculator")
    lines.append("  https://kdp.amazon.com/cover-calculator")
    lines.append("")
    field("Interior pages:",              str(total_pages))
    field("Paper type:",                  "White (0.002252 in/page)")
    field("Spine width:",                 f"{dims['spine_in']:.4f} in  ({dims['spine_px']} px @ 300 dpi)")
    field("Full cover width:",            f"{dims['full_w_in']:.4f} in  ({dims['full_w_px']} px @ 300 dpi)")
    field("Full cover height:",           f"{dims['full_h_in']:.4f} in  ({dims['full_h_px']} px @ 300 dpi)")
    lines.append("  (includes 0.125 in bleed on every side)")

    # ── Rights & Pricing ─────────────────────────────────────────────────────
    h("Rights & Pricing")
    field("Territories:", "All territories (worldwide rights)")
    field("Pricing suggestion:", book.pricing)
    if book.pricing_notes:
        lines.append(f"  Note: {book.pricing_notes}")
    lines.append("  KDP calculates royalties automatically based on your list price.")

    # ── AI disclosure ─────────────────────────────────────────────────────────
    h("AI-Generated Content Disclosure (KDP Question)")
    lines.append("  KDP will ask: 'Does this book contain AI-generated content?'")
    lines.append("  Answer: YES — the interior illustrations are AI-generated.")
    lines.append("  You (the publisher) reviewed, edited, and arranged the content.")

    # ── Pre-upload checklist ──────────────────────────────────────────────────
    h("Pre-Upload Checklist")
    checklist = [
        "No famous characters, brand names, or copyrighted content in any image",
        "Cover spelling proofread (title, subtitle, author name)",
        "Title and Subtitle on cover EXACTLY match KDP title/subtitle fields above",
        "Interior PDF previewed page by page in KDP Previewer",
        "All 7 keywords filled in (each ≤ 50 chars)",
        "Description is under 4 000 chars",
        f"Page count is even: {total_pages} ({'✓ even' if total_pages % 2 == 0 else '✗ odd — check build'})",
        "Categories confirmed in KDP category picker",
        "Pricing set for all target marketplaces",
    ]
    for item in checklist:
        lines.append(f"  [ ] {item}")

    out_path.write_text("\n".join(lines), encoding="utf-8")
    return out_path
