"""Parse a KDP coloring-book Markdown file into a structured KDPBook object.

Supports book files whose headings are in Arabic and/or English and whose
KDP form fields are written as a Markdown table (`| Field | Value |`).
Section matching is keyword based (case-insensitive substring of the heading).
"""
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


# ── Low-level helpers ─────────────────────────────────────────────────────────

_FENCE_RE = re.compile(r"```[^\n]*\n(.*?)```", re.DOTALL)
_FENCE_SPAN_RE = re.compile(r"```.*?```", re.DOTALL)
_HEADING_RE = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*$", re.MULTILINE)
_ARABIC_RE = re.compile(r"[؀-ۿ]")


def _code_block(text: str) -> Optional[str]:
    """Return content of the first fenced code block, or None."""
    m = _FENCE_RE.search(text)
    return m.group(1).strip() if m else None


def _headings(text: str) -> list[tuple[int, str, int, int]]:
    """All headings outside fenced code blocks as (level, title, start, end_of_line)."""
    spans = [(m.start(), m.end()) for m in _FENCE_SPAN_RE.finditer(text)]
    out: list[tuple[int, str, int, int]] = []
    for m in _HEADING_RE.finditer(text):
        if any(s <= m.start() < e for s, e in spans):
            continue
        out.append((len(m.group(1)), m.group(2).strip(), m.start(), m.end()))
    return out


def _section(
    text: str,
    *keywords: str,
    min_level: int = 1,
    max_level: int = 6,
) -> Optional[str]:
    """Body of the first heading whose title contains one of *keywords*.

    Keywords are tried in order (case-insensitive substring match, any language).
    The body runs until the next heading of the same or a higher level.
    Only headings with min_level <= level <= max_level are considered.
    """
    heads = _headings(text)
    for kw in keywords:
        kw_l = kw.lower()
        for i, (level, title, _start, end) in enumerate(heads):
            if not (min_level <= level <= max_level):
                continue
            if kw_l not in title.lower():
                continue
            stop = len(text)
            for lvl2, _t2, start2, _e2 in heads[i + 1:]:
                if lvl2 <= level:
                    stop = start2
                    break
            return text[end:stop]
    return None


def _field(text: str, *patterns: str) -> str:
    """Legacy `key: value` extractor, anchored to line starts."""
    for pat in patterns:
        safe = f"(?:{pat})"
        m = re.search(
            r"^[ \t]*[-*]?[ \t]*\*{0,2}" + safe + r"\*{0,2}[ \t]*[:\-][ \t]*(.+?)[ \t]*$",
            text,
            re.IGNORECASE | re.MULTILINE,
        )
        if m and m.group(1) is not None:
            return m.group(1).strip().strip("*").strip()
    return ""


def _inline(text: str, label: str) -> str:
    """Value of `Label: value` that may sit inside a line separated by `|`."""
    m = re.search(
        r"(?:^|[|\s\-*])" + re.escape(label) + r"[ \t]*:[ \t]*([^|\n]+)",
        text,
        re.IGNORECASE | re.MULTILINE,
    )
    return m.group(1).strip().strip("`*").strip() if m else ""


def _table_rows(text: str) -> dict[str, str]:
    """Parse Markdown table rows into {lowercase first cell: second+ cells}."""
    rows: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not (line.startswith("|") and line.endswith("|")):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 2:
            continue
        if all(re.fullmatch(r":?-{2,}:?", c) or c == "" for c in cells):
            continue  # separator row
        key = cells[0].strip("` *").lower()
        if key in ("الحقل", "field", "name", ""):
            continue  # header row
        rows[key] = " | ".join(cells[1:]).strip()
    return rows


def _clean_value(value: str) -> str:
    """Strip backticks/bold; treat placeholder notes as empty."""
    v = value.strip().strip("`").strip("*").strip()
    low = v.lower()
    if v.startswith("فاضي") or low in ("empty", "none", "n/a", "-"):
        return ""
    if v.startswith("حسب قرار"):  # "per the author's decision" -> not set (use --author)
        return ""
    return v


def _get(table: dict[str, str], text: str, keys: tuple[str, ...], legacy: tuple[str, ...]) -> str:
    """Look up a field in the table (key prefix match), else fall back to `key: value`."""
    for k in keys:
        k = k.lower()
        for tk, tv in table.items():
            if tk == k or tk.startswith(k):
                return _clean_value(tv)
    return _clean_value(_field(text, *legacy)) if legacy else ""


def _numbered_items(text: str) -> list[tuple[int, str]]:
    return [
        (int(n), t.strip())
        for n, t in re.findall(r"^[ \t]*(\d+)[.)][ \t]+(.+?)[ \t]*$", text, re.MULTILINE)
    ]


def _strip_ticks(s: str) -> str:
    return s.strip().strip("`").strip()


def _first_long_numbered_list(text: str, min_items: int = 10) -> list[tuple[int, str]]:
    """Fallback: first run of consecutive numbered items with at least min_items entries."""
    no_fences = _FENCE_SPAN_RE.sub("", text)
    run: list[tuple[int, str]] = []
    for line in no_fences.splitlines():
        m = re.match(r"^[ \t]*(\d+)[.)][ \t]+(.+?)[ \t]*$", line)
        if m:
            run.append((int(m.group(1)), m.group(2).strip()))
        elif line.strip() == "":
            continue
        else:
            if len(run) >= min_items:
                return run
            run = []
    return run if len(run) >= min_items else []


def _heading_titles(text: str) -> list[str]:
    return [("  " * (lvl - 1)) + "#" * lvl + " " + title for lvl, title, _s, _e in _headings(text)]


# ── Main parser ───────────────────────────────────────────────────────────────

def parse_book(md_path: Path) -> KDPBook:
    """Parse *md_path* and return a :class:`KDPBook`.  Raises ``ValueError`` on errors."""
    text = Path(md_path).read_text(encoding="utf-8")
    errors: list[str] = []

    # ── 1. Master style prompt ────────────────────────────────────────────────
    style_sec = _section(text, "master style prompt", "master style", "style prompt", "style guide")
    if style_sec is None:
        errors.append("Section not found: 'Master Style Prompt'")
        master_style = ""
    else:
        raw_code = _code_block(style_sec)
        if raw_code is None:
            errors.append("No fenced code block found inside 'Master Style Prompt'")
            master_style = style_sec.strip()
        else:
            # Drop the "Reply Ready" paragraph (API calls are stateless)
            master_style = re.sub(
                r"\n[ \t]*\n[ \t]*Reply\s*[\"“”']?Ready[\"“”']?.*$",
                "",
                raw_code,
                flags=re.IGNORECASE | re.DOTALL,
            ).strip()

    # ── 2. Page ideas ─────────────────────────────────────────────────────────
    ideas_sec = _section(
        text, "page ideas", "فكرة", "أفكار", "افكار", "ideas", "coloring pages", "page list"
    )
    raw_ideas = _numbered_items(ideas_sec) if ideas_sec is not None else []
    if not raw_ideas:
        raw_ideas = _first_long_numbered_list(text, 10)
    if not raw_ideas:
        errors.append("No page ideas found (looked for a heading with 'فكرة'/'أفكار'/'ideas' "
                      "containing a numbered list)")
    page_ideas = [PageIdea(number=n, idea=t) for n, t in raw_ideas]

    # ── 3. Cover prompts ──────────────────────────────────────────────────────
    cover_sec = _section(text, "غلاف", "cover", max_level=2)
    front_prompt = back_prompt = sample_prompt = ""
    if cover_sec is None:
        errors.append("Section not found: cover section (heading containing 'غلاف' or 'cover')")
    else:
        front_sec = _section(cover_sec, "front cover", "وش الغلاف", "front", min_level=3)
        back_sec = _section(cover_sec, "back cover", "ضهر الغلاف", "back", min_level=3)
        samp_sec = _section(cover_sec, "colored sample", "colour sample", "عينات", "sample",
                            min_level=3)

        def _prompt(sec: Optional[str]) -> str:
            return (_code_block(sec) or "") if sec else ""

        front_prompt = _prompt(front_sec)
        back_prompt = _prompt(back_sec)
        sample_prompt = _prompt(samp_sec)

        # Fallback: when sub-sections are absent, use ordered code blocks in the cover section
        if not (front_prompt and back_prompt and sample_prompt):
            all_blocks = [m.group(1).strip() for m in _FENCE_RE.finditer(cover_sec)]
            if not front_prompt and len(all_blocks) > 0:
                front_prompt = all_blocks[0]
            if not back_prompt and len(all_blocks) > 1:
                back_prompt = all_blocks[1]
            if not sample_prompt and len(all_blocks) > 2:
                sample_prompt = all_blocks[2]

        if not front_prompt:
            errors.append("Missing front cover prompt (sub-heading 'وش الغلاف'/'front' with a code block)")
        if not back_prompt:
            errors.append("Missing back cover prompt (sub-heading 'ضهر الغلاف'/'back' with a code block)")
        if not sample_prompt:
            errors.append("Missing colored-sample prompt (sub-heading 'عينات'/'sample' with a code block)")

    # ── 4. KDP form fields ────────────────────────────────────────────────────
    det = _section(
        text, "فورم", "paperback details", "kdp details", "kdp listing", "listing details",
        "book details", "publication details", max_level=2,
    )
    detail_text = det if det is not None else text
    table = _table_rows(detail_text)

    language = _get(table, detail_text, ("language",), (r"language",)) or "English"
    book_title = _get(table, detail_text, ("book title",), (r"book\s*title",))
    subtitle = _get(table, detail_text, ("subtitle",), (r"subtitle",))
    series = _get(table, detail_text, ("series",), (r"series",))
    edition = _get(table, detail_text, ("edition",), (r"edition\s*(?:number)?",))
    author = _get(table, detail_text, ("author",), (r"author",))
    contributors = _get(table, detail_text, ("contributor",), (r"contributors?",))
    pub_rights = _get(table, detail_text, ("publishing rights",), (r"publishing\s*rights?",))
    sexually_exp = _get(table, detail_text, ("sexually explicit",), (r"sexually\s*explicit",)) or "No"
    marketplace = _get(table, detail_text, ("primary marketplace",),
                       (r"primary\s*marketplace", r"marketplace"))
    low_content = _get(table, detail_text, ("low-content", "low content", "low_content"),
                       (r"low.?content|large.?print",))
    pub_date = _get(table, detail_text, ("publication date",), (r"publication\s*date",))
    release_date = _get(table, detail_text, ("release date",), (r"release\s*date",))

    # Reading age: "Min 1 / Max 3 (...)", "3-8", "3 to 8"
    age_raw = _get(table, detail_text, ("reading age",), (r"reading\s*age",))
    age_min = age_max = ""
    m_mm = re.search(r"min\D*(\d+).*?max\D*(\d+)", age_raw, re.IGNORECASE)
    m_rng = re.search(r"(\d+)\s*(?:-|–|—|to)\s*(\d+)", age_raw, re.IGNORECASE)
    if m_mm:
        age_min, age_max = m_mm.group(1), m_mm.group(2)
    elif m_rng:
        age_min, age_max = m_rng.group(1), m_rng.group(2)

    # Description: first code block inside a 'Description' sub-section
    desc_sec = _section(detail_text, "description", min_level=2)
    description = (_code_block(desc_sec) or desc_sec.strip()) if desc_sec else ""

    # Keywords: numbered list inside a 'Keywords' sub-section
    kw_sec = _section(detail_text, "keyword", min_level=2)
    keywords = [_strip_ticks(t) for _n, t in _numbered_items(kw_sec)] if kw_sec else []
    keywords = [k for k in keywords if k]

    # Categories: bullet (or numbered) list inside a 'Categories' sub-section
    cat_sec = _section(detail_text, "categor", "تصنيف", min_level=2)
    categories: list[str] = []
    if cat_sec:
        cats = re.findall(r"^[ \t]*[-•*][ \t]+(.+?)[ \t]*$", cat_sec, re.MULTILINE)
        if not cats:
            cats = [t for _n, t in _numbered_items(cat_sec)]
        for c in cats:
            c = _strip_ticks(c)
            if re.match(r"^\((?:اختياري|optional)", c, re.IGNORECASE):
                continue  # optional hint line, not a real category
            # drop trailing Arabic parenthetical notes, e.g. "(أو أقرب مسار)"
            c = re.sub(r"\s*\([^)]*\)\s*$", lambda mm: "" if _ARABIC_RE.search(mm.group(0)) else mm.group(0), c)
            c = c.strip()
            if c:
                categories.append(c)

    # ── Content / print settings (separate section; values may share one line) ──
    content_sec = _section(text, "paperback content", "إعدادات", "print settings", max_level=2) or ""
    search_in = content_sec if content_sec else detail_text
    paper = _inline(search_in, "Paper") or _field(detail_text, r"paper") or "White"
    interior = _inline(search_in, "Interior") or _field(detail_text, r"interior") or "Black & White Standard"
    trim = _inline(search_in, "Trim") or _field(detail_text, r"trim\s*(?:size)?") or "8.5 x 11 in"
    bleed = _inline(search_in, "Bleed") or _field(detail_text, r"bleed") or "No bleed"
    cover_finish = (_inline(search_in, "Cover finish") or _field(detail_text, r"cover\s*finish")
                    or "Matte")

    # ── Pricing ──────────────────────────────────────────────────────────────
    price_sec = _section(text, "التسعير", "pricing", "price", max_level=2) or ""
    pricing = ""
    pricing_notes = ""
    if price_sec.strip():
        pr = re.search(r"\d+(?:\.\d+)?\s*\$?\s*[–\-—]\s*\d+(?:\.\d+)?\s*\$?", price_sec)
        pricing = pr.group(0).strip() if pr else ""
        bullets = re.findall(r"^[ \t]*[-•*][ \t]+(.+?)[ \t]*$", price_sec, re.MULTILINE)
        pricing_notes = " ".join(bullets) if bullets else price_sec.strip()
    else:
        pricing = _field(detail_text, r"pric(?:e|ing)")
        pricing_notes = _field(detail_text, r"pricing\s*note")

    # ── 5. Collect errors ─────────────────────────────────────────────────────
    if not book_title:
        h1 = re.search(r"^#[ \t]+(.+?)[ \t]*$", text, re.MULTILINE)
        if h1:
            book_title = h1.group(1).strip()
        else:
            errors.append("Field not found: 'Book Title' (table row 'Book Title' in the KDP form section)")
    if not keywords:
        errors.append("No keywords found (numbered list under a 'Keywords' sub-heading)")

    if errors:
        found = "\n".join(f"    {h}" for h in _heading_titles(text)) or "    (none)"
        raise ValueError(
            "Could not fully parse the Markdown file. Issues found:\n"
            + "\n".join(f"  • {e}" for e in errors)
            + "\n  Headings found in the file:\n"
            + found
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
        reading_age_min=age_min,
        reading_age_max=age_max,
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


if __name__ == "__main__":  # quick manual check: python parser.py path\to\book.md
    import sys

    b = parse_book(Path(sys.argv[1]))
    print("Title:", b.book_title)
    print("Subtitle:", b.subtitle)
    print("Ideas:", len(b.page_ideas), "| Keywords:", len(b.keywords), "| Categories:", len(b.categories))
    print("Reading age:", b.reading_age_min, "-", b.reading_age_max)
    print("Covers:", bool(b.front_cover_prompt), bool(b.back_cover_prompt), bool(b.colored_sample_prompt))