# KDP Book Builder

A Python 3.10+ command-line tool that reads **one Markdown file** describing a children's coloring book and produces every file needed to upload to Amazon KDP — in a single run.

---

## Features

- **Parse** a structured Markdown file: style prompt, page ideas, cover prompts, all KDP listing fields
- **Generate** interior pages with the OpenAI Images API (`gpt-image-1`), 3 workers in parallel
- **QA every image** automatically: flags grey/shading, too-empty, too-filled, cropped, background noise — and retries with corrective instructions
- **Post-process** to print-ready 2550×3300 px pure B&W PNGs (8.5×11 in @ 300 DPI)
- **Build the interior PDF** losslessly with a "This Book Belongs To" page + blank page behind every drawing
- **Generate covers** (front + back) and optional colored sample images via the image edit endpoint
- **Write `upload_details.txt`** — every KDP form field copy-paste ready, cover spine/dimension calculations, AI-disclosure reminder, pre-upload checklist
- **Resume** from where it left off (manifest.json tracks each page's status)
- **Validate** metadata: title length, keyword character counts, HTML tags, blacklisted brand names

---

## Quick Start

### 1. Clone & install

```bash
git clone https://github.com/Dabash99/KDP-Creator.git
cd KDP-Creator
pip install -r requirements.txt
```

### 2. Set your OpenAI API key

Create a `.env` file next to `kdp_book_builder.py`:

```
OPENAI_API_KEY=sk-...
```

The key is never printed or logged. `.gitignore` already excludes `.env`.

### 3. Run

```bash
# Dry run — parse + validate + write upload_details, no API calls
python kdp_book_builder.py "D:\path\to\book.md" --dry-run

# Test with first 2 pages only
python kdp_book_builder.py "D:\path\to\book.md" --limit 2 --yes --skip-samples

# Full run
python kdp_book_builder.py "D:\path\to\book.md" --yes
```

---

## Output Structure

```
D:\KDP\
  <Book Title>\
    pages_raw\          01_big-cute-puppy.png  ...   (raw API output)
    pages_clean\        01_big-cute-puppy.png  ...   (2550×3300, pure B&W)
    cover\              front.png  back.png  colored_sample_01.png ...
    interior\           <BookTitle>_interior.pdf
    upload_details.txt  copy-paste ready for every KDP form field
    qa_report.txt       per-page QA results
    manifest.json       run state — used for resume
    run.log             full log
```

---

## CLI Flags

| Flag | Default | Description |
|---|---|---|
| `--out PATH` | `D:\KDP` | Root output folder |
| `--yes` | — | Skip the Proceed? prompt |
| `--limit N` | 0 (all) | Only generate first N pages |
| `--regen 7,12` | — | Force-regenerate specific page numbers |
| `--skip-cover` | — | Skip cover generation |
| `--skip-samples` | — | Skip colored-sample generation |
| `--author "Name"` | from MD | Override author in upload_details.txt |
| `--model ID` | `gpt-image-1` | OpenAI image model |
| `--quality` | `medium` | `low` / `medium` / `high` |
| `--size` | `1024x1536` | Image size |
| `--workers N` | `3` | Concurrent generation threads |
| `--threshold N` | `140` | B&W threshold for post-processing (0–255) |
| `--dry-run` | — | Parse + validate + write details, **no API calls** |
| `--only-pdf` | — | Rebuild PDF from existing processed images |

---

## Markdown File Format

See [`tests/fixtures/sample_book.md`](tests/fixtures/sample_book.md) for a full working example.

Required sections (headings matched case-insensitively):

| Section | Content |
|---|---|
| `## Master Style Prompt` | Fenced code block with style instructions |
| `## Page Ideas` | Numbered list of page ideas |
| `## Cover` | Sub-sections with code blocks: Front Cover, Back Cover, Colored Sample |
| `## KDP Details` | Key–value fields + sub-sections: Description, Keywords, Categories |

---

## Tests

```bash
pytest tests/test_parser.py -v
```

47 tests covering the parser helpers, the full fixture file, and synthetic edge-case Markdown.

---

## Blacklist

Edit [`blacklist.txt`](blacklist.txt) to add brand or character names that should trigger a warning if found in the book's title, subtitle, description, or keywords.

---

## Requirements

- Python 3.10+
- Windows (paths use `pathlib`; fonts resolved from `C:\Windows\Fonts\`)
- OpenAI API key with Images access (`gpt-image-1`)

```
openai>=1.40.0
pillow>=10.0.0
numpy>=1.24.0
img2pdf>=0.5.1
python-dotenv>=1.0.0
```

---

## License

MIT
