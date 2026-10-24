"""Tests for parser.parse_book against the real book-01 Markdown file."""
from pathlib import Path

import pytest

from kdp.parser import parse_book

MD = Path(__file__).parents[2] / "books" / "book-01-toddler-animals.md"


@pytest.mark.skipif(not MD.exists(), reason="real book file not found")
def test_real_file():
    b = parse_book(MD)

    assert b.book_title == "My First Toddler Coloring Book Ages 1-3"
    assert b.subtitle == "50 Big and Simple Animals with Thick Bold Lines for Little Hands"

    assert len(b.page_ideas) == 50
    assert b.page_ideas[0].number == 1 and b.page_ideas[0].idea == "big cute puppy sitting"
    assert b.page_ideas[-1].number == 50 and b.page_ideas[-1].idea == "big dog with a bone"
    assert b.page_ideas[47].filename == "48_big-baby-duck-in-a-puddle.png"

    assert len(b.keywords) == 7
    assert b.keywords[0] == "toddler coloring book ages 1-3"
    assert all(len(k) <= 50 and "`" not in k for k in b.keywords)

    assert b.master_style_prompt.startswith("You are my illustrator")
    assert "Reply" not in b.master_style_prompt and "Ready" not in b.master_style_prompt
    assert b.master_style_prompt.endswith("franchise.")

    assert b.front_cover_prompt.startswith("Create a bright, cheerful, colorful front cover")
    assert '"MY FIRST"' in b.front_cover_prompt and "50 BIG & SIMPLE ANIMALS" in b.front_cover_prompt
    assert b.back_cover_prompt.startswith("Create a back cover")
    assert "barcode" in b.back_cover_prompt
    assert b.colored_sample_prompt.startswith("Create a colorful version")

    assert (b.reading_age_min, b.reading_age_max) == ("1", "3")
    assert b.language == "English"
    assert b.primary_marketplace == "Amazon.com"
    assert b.sexually_explicit == "No"
    assert b.series == "" and b.edition_number == "" and b.contributors == ""
    assert b.author == "Ahmed Dabash"
    assert b.publishing_rights.startswith("I own the copyright")

    assert b.description.startswith("<b>A big, simple, and happy coloring book")
    assert 0 < len(b.description) <= 4000

    assert b.categories == [
        "Children's Books > Activities, Crafts & Games > Coloring Books",
        "Children's Books > Animals",
    ]

    assert (b.paper, b.interior, b.trim, b.bleed, b.cover_finish) == (
        "White", "Black & White", "8.5 x 11 in", "No Bleed", "Matte",
    )
    assert b.pricing.replace(" ", "") == "6.99$–7.99$"


def test_missing_sections_report_headings(tmp_path):
    bad = tmp_path / "bad.md"
    bad.write_text("# Something\n\n## Random\n\ntext\n", encoding="utf-8")
    try:
        parse_book(bad)
    except ValueError as e:
        msg = str(e)
        assert "Headings found in the file" in msg and "Random" in msg
    else:
        raise AssertionError("expected ValueError")


if __name__ == "__main__":
    import tempfile

    test_real_file()
    with tempfile.TemporaryDirectory() as d:
        test_missing_sections_report_headings(Path(d))
    print("All parser tests passed")
