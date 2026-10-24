"""Unit tests for kdp.parser — run with: pytest tests/test_parser.py -v"""
from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from kdp.parser import KDPBook, PageIdea, _code_block, _field, _section, parse_book

FIXTURE = Path(__file__).parent / "fixtures" / "sample_book.md"


# ── Helper: build a minimal valid MD string ───────────────────────────────────

def _minimal_md(
    *,
    style: str = "Draw a cute animal.\n\nReply \"Ready\"",
    ideas: str = "1. Puppy\n2. Kitten",
    front: str = "Front cover prompt.",
    back:  str = "Back cover prompt.",
    sample: str = "Sample prompt.",
    title: str = "My Book",
    subtitle: str = "A Subtitle",
    author: str = "Jane Doe",
    keywords: str = "1. keyword one\n2. keyword two",
    description: str = "<p>Hello</p>",
    reading_age: str = "3-8",
) -> str:
    # Build line by line so multi-line interpolated values don't break heading indentation.
    # textwrap.dedent is NOT used because it de-indents based on the minimum indentation,
    # which breaks when an interpolated value contains zero-indented lines.
    parts = [
        "## Master Style Prompt",
        f"```\n{style}\n```",
        "## Page Ideas",
        ideas,
        "## Cover",
        "### Front Cover",
        f"```\n{front}\n```",
        "### Back Cover",
        f"```\n{back}\n```",
        "### Colored Sample",
        f"```\n{sample}\n```",
        "## KDP Details",
        f"**Book Title:** {title}",
        f"**Subtitle:** {subtitle}",
        f"**Author:** {author}",
        f"**Reading Age:** {reading_age}",
        "### Description",
        f"```\n{description}\n```",
        "### Keywords",
        keywords,
    ]
    return "\n".join(parts) + "\n"


# ── Internal helper tests ──────────────────────────────────────────────────────

class TestCodeBlock:
    def test_extracts_content(self):
        text = "some text\n```\nhello world\n```\nmore"
        assert _code_block(text) == "hello world"

    def test_with_language_tag(self):
        text = "```python\nprint('hi')\n```"
        assert _code_block(text) == "print('hi')"

    def test_returns_none_when_absent(self):
        assert _code_block("no code block here") is None

    def test_strips_whitespace(self):
        assert _code_block("```\n  hello  \n```") == "hello"


class TestSection:
    def test_finds_section_case_insensitive(self):
        text = "# Master Style Prompt\ncontent here\n# Next Section\n"
        result = _section(text, "master style prompt")
        assert result is not None
        assert "content here" in result

    def test_returns_none_for_missing_section(self):
        assert _section("# Only This\ncontent", "missing section") is None

    def test_stops_at_next_same_level_heading(self):
        text = "## Section A\nA content\n## Section B\nB content"
        result = _section(text, "section a")
        assert result is not None
        assert "A content" in result
        assert "B content" not in result

    def test_accepts_emoji_in_heading(self):
        text = "## 🎨 Master Style Prompt\nstyle text here\n"
        result = _section(text, "master style prompt")
        assert result is not None
        assert "style text here" in result

    def test_accepts_numbered_heading(self):
        text = "## 1. Page Ideas\n1. Puppy\n2. Kitten\n"
        result = _section(text, "page ideas")
        assert result is not None


class TestField:
    def test_plain_field(self):
        assert _field("Book Title: My Amazing Book\n", r"book\s*title") == "My Amazing Book"

    def test_bold_field(self):
        assert _field("**Author:** Jane Doe\n", r"author") == "Jane Doe"

    def test_case_insensitive(self):
        assert _field("LANGUAGE: English\n", r"language") == "English"

    def test_missing_returns_empty(self):
        assert _field("no match here", r"missing_field") == ""


# ── PageIdea tests ────────────────────────────────────────────────────────────

class TestPageIdea:
    def test_slug_replaces_non_alphanum(self):
        p = PageIdea(number=1, idea="Big cute puppy!")
        assert p.slug == "big-cute-puppy"

    def test_filename_format(self):
        p = PageIdea(number=3, idea="Baby elephant")
        assert p.filename == "03_baby-elephant.png"

    def test_filename_zero_pads(self):
        p = PageIdea(number=1, idea="x")
        assert p.filename.startswith("01_")


# ── Full parse on fixture ─────────────────────────────────────────────────────

@pytest.mark.skipif(not FIXTURE.exists(), reason="fixture file missing")
class TestParseFixture:
    @pytest.fixture(scope="class")
    @classmethod
    def book(cls) -> KDPBook:
        return parse_book(FIXTURE)

    def test_returns_kdpbook(self, book):
        assert isinstance(book, KDPBook)

    def test_book_title(self, book):
        assert book.book_title == "50 Adorable Animals Coloring Book"

    def test_subtitle(self, book):
        assert "Kids" in book.subtitle

    def test_author(self, book):
        assert book.author == "Alex Jordan"

    def test_page_ideas_count(self, book):
        assert len(book.page_ideas) == 10

    def test_page_ideas_ordered(self, book):
        assert book.page_ideas[0].number == 1
        assert book.page_ideas[-1].number == 10

    def test_first_idea_text(self, book):
        assert "puppy" in book.page_ideas[0].idea.lower()

    def test_style_prompt_no_ready(self, book):
        assert "Ready" not in book.master_style_prompt

    def test_style_prompt_has_content(self, book):
        assert len(book.master_style_prompt) > 100

    def test_front_cover_prompt(self, book):
        assert len(book.front_cover_prompt) > 20

    def test_back_cover_prompt(self, book):
        assert len(book.back_cover_prompt) > 20

    def test_sample_prompt(self, book):
        assert len(book.colored_sample_prompt) > 10

    def test_keywords_count(self, book):
        assert len(book.keywords) == 7

    def test_keywords_are_strings(self, book):
        for kw in book.keywords:
            assert isinstance(kw, str)
            assert len(kw) > 0

    def test_description_has_html(self, book):
        assert "<p>" in book.description

    def test_reading_age_min(self, book):
        assert book.reading_age_min == "3"

    def test_reading_age_max(self, book):
        assert book.reading_age_max == "8"

    def test_categories(self, book):
        assert len(book.categories) >= 1

    def test_trim(self, book):
        assert "8.5" in book.trim

    def test_pricing(self, book):
        assert book.pricing  # non-empty

    def test_language(self, book):
        assert book.language.lower() == "english"


# ── Full parse on minimal synthetic MD ───────────────────────────────────────

class TestParseMinimal:
    def _parse(self, md: str) -> KDPBook:
        import tempfile, os
        with tempfile.NamedTemporaryFile(mode="w", suffix=".md", delete=False, encoding="utf-8") as f:
            f.write(md)
            tmp = Path(f.name)
        try:
            return parse_book(tmp)
        finally:
            os.unlink(tmp)

    def test_basic_parse(self):
        book = self._parse(_minimal_md())
        assert book.book_title == "My Book"
        assert book.author == "Jane Doe"

    def test_page_ideas_parsed(self):
        book = self._parse(_minimal_md())
        assert len(book.page_ideas) == 2
        assert book.page_ideas[0].idea == "Puppy"

    def test_style_strips_reply_ready(self):
        book = self._parse(_minimal_md(style='Style text.\n\nReply "Ready" if you understand.'))
        assert "Ready" not in book.master_style_prompt
        assert "Style text." in book.master_style_prompt

    def test_style_strips_reply_ready_unicode_quotes(self):
        book = self._parse(_minimal_md(style='Style.\n\nReply “Ready” when done.'))
        assert "Ready" not in book.master_style_prompt

    def test_reading_age_dash(self):
        book = self._parse(_minimal_md(reading_age="4-10"))
        assert book.reading_age_min == "4"
        assert book.reading_age_max == "10"

    def test_reading_age_en_dash(self):
        book = self._parse(_minimal_md(reading_age="3–8"))
        assert book.reading_age_min == "3"
        assert book.reading_age_max == "8"

    def test_missing_title_raises(self):
        md = _minimal_md().replace("**Book Title:** My Book", "")
        with pytest.raises(ValueError, match="Book Title"):
            self._parse(md)

    def test_missing_style_section_raises(self):
        md = _minimal_md().replace("## Master Style Prompt", "## Unrelated")
        with pytest.raises(ValueError):
            self._parse(md)

    def test_missing_ideas_raises(self):
        md = _minimal_md(ideas="No numbered list here")
        with pytest.raises(ValueError):
            self._parse(md)

    def test_cover_fallback_to_code_blocks(self):
        """If cover sub-sections are absent, parser falls back to ordered code blocks."""
        parts = [
            "## Master Style Prompt",
            "```\nStyle.\n```",
            "## Page Ideas",
            "1. Puppy",
            "## Cover",
            "```\nfront prompt\n```",
            "```\nback prompt\n```",
            "```\nsample prompt\n```",
            "## KDP Details",
            "**Book Title:** My Book",
            "**Author:** J",
            "**Reading Age:** 3-8",
            "### Description",
            "```\n<p>Hi</p>\n```",
            "### Keywords",
            "1. kw one",
        ]
        md = "\n".join(parts) + "\n"
        book = self._parse(md)
        assert book.front_cover_prompt == "front prompt"
        assert book.back_cover_prompt  == "back prompt"
        assert book.colored_sample_prompt == "sample prompt"
