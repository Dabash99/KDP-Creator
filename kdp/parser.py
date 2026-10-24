"""Parse a KDP coloring-book Markdown file into a structured KDPBook object."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# ── Data classes ─────────────────────────────────────────────────────────────

@dataclass
class PageIdea:
    number: int
    idea: str

    @property
    def slug(self) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", self.idea.lower()).strip("-")
        return slug[:50]

    @property
    def filename(self) -> str:
        return f"{self.number:02d}_{self.slug}.png"


@dataclass
class KDPBook:
    # Style / content
    master_style_prompt: str
    page_ideas: list[PageIdea]

    # Cover prompts (exact text from MD, use as-is)
    front_cover_prompt: str
    back_cover_prompt: str
    colored_sample_prompt: str

    # KDP form fields
    language: str = "English"
    book_title: str = ""
    subtitle: str = ""
    series: str = ""
    edition_number: str = ""
    author: str = ""
    contributors: str = ""
    publishing_rights: str = ""
    sexually_explicit: str = "No"
    reading_age_min: str = ""
    reading_age_max: str = ""
    primary_marketplace: str = ""
    low_content_notes: str = ""
    publication_date: str = ""
    release_date: str = ""
    description: str = ""
    keywords: list[str] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)

    # Content / print settings
    paper: str = "White"
    interior: str = "Black & White Standard"
    trim: str = "8.5 x 11 in"
    bleed: str = "No bleed"
    cover_finish: str = "Matte"
    pricing: str = ""
    pricing_notes: str = ""


# ── Internal helpers ──────────────────────────────────────────────────────────

def _code_block(text: str) -> Optional[str]:
    """Return content of the first fenced code block, or None."""
    m = re.search(r"```[^\n]*\n(.*?)```", text, re.DOTALL)
    return m.group(1).strip() if m else None


def _heading_re(keyword: str) -> re.Pattern:
    """Regex that matches a heading line containing *keyword* (case-insensitive)."""
    return re.compile(
        r"^(#{1,6})\s.*" + re.escape(keyword) + r".*$",
        re.MULTILINE | re.IGNORECASE,
    )


def _section(text: str, *keywords: str) -> Optional[str]:
    """
    Return the text content of the first heading that contains any of *keywords*.
    Content runs until the next heading at the same or higher level (fewer/equal #).
    """
    for kw in keywords:
        m = _heading_re(kw).search(text)
        if not m:
            continue
        level = len(m.group(1))
        start = m.end()
        # Next heading at same or higher level
        next_h = re.compile(r"^#{1," + str(level) + r"}\s", re.MULTILINE)
        nm = next_h.search(text, start)
        return text[start : nm.start() if nm else len(text)]
    return None


def _field(text: str, *patterns: str) -> str:
    """Extract a key: value field from *text*, anchored to line starts to avoid
    matching words mid-sentence (e.g. 'bleed' inside a description HTML tag)."""
    for pat in patterns:
        # Wrap in (?:...) so that | inside *pat* doesn't split the surrounding prefix/suffix
        safe = f"(?:{pat})"
        m = re.search(
            r"^[ \t]*\*{0,2}" + safe + r"\*{0,2}[ \t]*[:\-][ \t]*(.+?)[ \t]*$",
            text,
            re.IGNORECASE | re.MULTILINE,
        )
        if m and m.group(1) is not None:
            return m.group(1).strip().strip("*").strip()
    return ""


# ── Main parser ───────────────────────────────────────────────────────────────

def parse_book(md_path: Path) -> KDPBook:
    """Parse *md_path* and return a :class:`KDPBook`.  Raises ``ValueError`` on errors."""
    text = md_path.read_text(encoding="utf-8")
    errors: list[str] = []

    # ── 1. Master style prompt ────────────────────────────────────────────────
    style_sec = _section(text, "master style prompt", "style prompt", "style guide")
    if style_sec is None:
        errors.append("Section not found: 'Master Style Prompt'")
        master_style = ""
    else:
        raw_code = _code_block(style_sec)
        if raw_code is None:
            errors.append("No fenced code block found inside 'Master Style Prompt'")
            master_style = style_sec.strip()
        else:
            # Drop the "Reply Ready" paragraph at the end (API calls are stateless)
            master_style = re.sub(
                r'\n\nReply\s*["“]?Ready["”]?.*$',
                "",
                raw_code,
                flags=re.IGNORECASE | re.DOTALL,
            ).strip()

    # ── 2. Page ideas ─────────────────────────────────────────────────────────
    ideas_sec = _section(text, "page ideas", "coloring pages", "page list", "pages")
    if ideas_sec is None:
        errors.append("Section not found: 'Page Ideas'")
        page_ideas: list[PageIdea] = []
    else:
        raw_ideas = re.findall(r"^\s*(\d+)[.)]\s+(.+)$", ideas_sec, re.MULTILINE)
        if not raw_ideas:
            errors.append("No numbered list found inside the page-ideas section")
            page_ideas = []
        else:
            page_ideas = [PageIdea(number=int(n), idea=t.strip()) for n, t in raw_ideas]

    # ── 3. Cover prompts ──────────────────────────────────────────────────────
    cover_sec = _section(text, "cover")
    if cover_sec is None:
        errors.append("Section not found: 'Cover'")
        front_prompt = back_prompt = sample_prompt = ""
    else:
        # Sub-sections
        front_sec = _section(cover_sec, "front cover", "front")
        back_sec  = _section(cover_sec, "back cover", "back")
        samp_sec  = _section(cover_sec, "colored sample", "colour sample", "sample")

        # Fallback: collect all code blocks in order
        all_blocks = re.findall(r"```[^\n]*\n(.*?)```", cover_sec, re.DOTALL)
        all_blocks = [b.strip() for b in all_blocks]

        def _cover_prompt(sec: Optional[str], fallback_idx: int) -> str:
            if sec:
                cb = _code_block(sec)
                if cb:
                    return cb
            return all_blocks[fallback_idx] if len(all_blocks) > fallback_idx else ""

        front_prompt  = _cover_prompt(front_sec, 0)
        back_prompt   = _cover_prompt(back_sec,  1)
        sample_prompt = _cover_prompt(samp_sec,  2)

        if not front_prompt:
            errors.append("Missing front cover prompt (no code block found)")
        if not back_prompt:
            errors.append("Missing back cover prompt (no code block found)")
        if not sample_prompt:
            errors.append("Missing colored-sample prompt (no code block found)")

    # ── 4. KDP form fields ────────────────────────────────────────────────────
    # Accept several possible heading names for the details section
    det = _section(text, "kdp details", "kdp listing", "listing details",
                   "book details", "publication details", "details", "kdp")
    detail_text = det if det else text  # fall back to full doc

    language        = _field(detail_text, r"language") or "English"
    book_title      = _field(detail_text, r"book\s*title")
    subtitle        = _field(detail_text, r"subtitle")
    series          = _field(detail_text, r"series")
    edition         = _field(detail_text, r"edition\s*(?:number)?")
    author          = _field(detail_text, r"author")
    contributors    = _field(detail_text, r"contributors?")
    pub_rights      = _field(detail_text, r"publishing\s*rights?", r"rights")
    sexually_exp    = _field(detail_text, r"sexually\s*explicit") or "No"
    marketplace     = _field(detail_text, r"primary\s*marketplace", r"marketplace")
    low_content     = _field(detail_text, r"low.?content|large.?print")
    pub_date        = _field(detail_text, r"publication\s*date")
    release_date    = _field(detail_text, r"release\s*date")
    pricing         = _field(detail_text, r"pric(?:e|ing)")
    pricing_notes   = _field(detail_text, r"pricing\s*note")

    # Reading age: "3-8", "min: 3  max: 8", etc.
    age_raw = _field(detail_text, r"reading\s*age")
    age_m   = re.search(r"(\d+)\s*[-–to]\s*(\d+)", age_raw)
    if age_m:
        age_min, age_max = age_m.group(1), age_m.group(2)
    else:
        age_min = _field(detail_text, r"reading\s*age\s*\(?min\)?", r"age\s*min")
        age_max = _field(detail_text, r"reading\s*age\s*\(?max\)?", r"age\s*max")

    # Description: prefer a code block inside a 'Description' sub-section
    desc_sec  = _section(detail_text, "description")
    if desc_sec:
        description = _code_block(desc_sec) or desc_sec.strip()
    else:
        # Grab first code block in the detail section
        cb = _code_block(detail_text)
        description = cb or ""

    # Keywords: numbered list inside a 'Keywords' sub-section
    kw_sec = _section(detail_text, "keywords?", "keyword")
    if kw_sec:
        kws = re.findall(r"^\s*\d+[.)]\s+(.+)$", kw_sec, re.MULTILINE)
        keywords = [k.strip() for k in kws if k.strip()]
    else:
        keywords = []

    # Categories: bullet list inside a 'Categories' sub-section
    cat_sec = _section(detail_text, "categor")
    if cat_sec:
        cats = re.findall(r"^\s*[-•*]\s+(.+)$", cat_sec, re.MULTILINE)
        if not cats:
            cats = re.findall(r"^\s*\d+[.)]\s+(.+)$", cat_sec, re.MULTILINE)
        categories = [c.strip() for c in cats if c.strip()]
    else:
        categories = []

    # Print settings
    paper         = _field(detail_text, r"paper") or "White"
    interior      = _field(detail_text, r"interior") or "Black & White Standard"
    trim          = _field(detail_text, r"trim\s*(?:size)?") or "8.5 x 11 in"
    bleed         = _field(detail_text, r"bleed") or "No bleed"
    cover_finish  = _field(detail_text, r"cover\s*finish") or "Matte"

    # ── 5. Collect errors ─────────────────────────────────────────────────────
    if not book_title:
        errors.append("Field not found: 'Book Title'")
    if not page_ideas:
        errors.append("No page ideas found — cannot continue")

    if errors:
        raise ValueError(
            "Could not fully parse the Markdown file. Issues found:\n"
            + "\n".join(f"  • {e}" for e in errors)
        )

    return KDPBook(
        master_style_prompt=master_style,
        page_ideas=page_ideas,
        front_cover_prompt=front_prompt,
        back_cover_prompt=back_prompt,
        colored_sample_prompt=sample_prompt,
        language=language,
        book_title=book_title,
        subtitle=subtitle,
        series=series,
        edition_number=edition,
        author=author,
        contributors=contributors,
        publishing_rights=pub_rights,
        sexually_explicit=sexually_exp,
        reading_age_min=str(age_min) if age_min else "",
        reading_age_max=str(age_max) if age_max else "",
        primary_marketplace=marketplace,
        low_content_notes=low_content,
        publication_date=pub_date,
        release_date=release_date,
        description=description,
        keywords=keywords,
        categories=categories,
        paper=paper,
        interior=interior,
        trim=trim,
        bleed=bleed,
        cover_finish=cover_finish,
        pricing=pricing,
        pricing_notes=pricing_notes,
    )
