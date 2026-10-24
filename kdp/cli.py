"""CLI argument parsing and full pipeline orchestration."""
from __future__ import annotations

import argparse
import logging
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import openai
from dotenv import load_dotenv

from .details_writer import validate, write_upload_details
from .generator import ImageGenerator
from .parser import KDPBook, PageIdea, parse_book
from .pdf_builder import build_pdf
from .postprocess import process_page
from .qa import check_image
from .utils import (
    load_manifest,
    sanitize_folder_name,
    save_manifest,
    setup_logger,
)

log = logging.getLogger("kdp")

# ── Argument parser ───────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="kdp_book_builder",
        description="Generate everything needed to upload a KDP coloring book to Amazon.",
    )
    p.add_argument("md_file", metavar="MD_FILE", help="Path to the book Markdown file")

    p.add_argument("--out",      default=r"D:\KPD",     help="Root output folder (default: D:\\KDP)")
    p.add_argument("--yes",      action="store_true",    help="Skip the Proceed? prompt")
    p.add_argument("--limit",    type=int, default=0,    metavar="N", help="Only generate first N pages")
    p.add_argument("--regen",    default="",             metavar="PAGES", help="Comma-separated page numbers to regenerate, e.g. 7,12,31")
    p.add_argument("--skip-cover",    action="store_true", help="Skip cover generation")
    p.add_argument("--skip-samples",  action="store_true", help="Skip colored-sample image generation")
    p.add_argument("--author",   default="",             help="Override author name in upload_details.txt")
    p.add_argument("--model",    default="gpt-image-1",  help="OpenAI image model (default: gpt-image-1)")
    p.add_argument("--quality",  default="medium",       choices=["low", "medium", "high"], help="Image quality")
    p.add_argument("--size",     default="1024x1536",    help="Image size (default: 1024x1536)")
    p.add_argument("--workers",  type=int, default=3,    help="Concurrent generation threads (default: 3)")
    p.add_argument("--threshold",type=int, default=140,  help="B&W threshold 0-255 (default: 140)")
    p.add_argument("--dry-run",  action="store_true",    help="Parse, validate, write upload_details — no API calls")
    p.add_argument("--only-pdf", action="store_true",    help="Rebuild PDF and upload_details from existing images")
    return p


# ── API key loading ───────────────────────────────────────────────────────────

def load_api_key(script_dir: Path) -> str:
    load_dotenv(script_dir / ".env")
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        sys.exit(
            "ERROR: OPENAI_API_KEY is not set.\n"
            "  Create a .env file next to kdp_book_builder.py with:\n"
            "    OPENAI_API_KEY=sk-...\n"
            "  or export the variable in your shell."
        )
    return key


# ── Directory setup ───────────────────────────────────────────────────────────

def setup_dirs(out_root: Path, book_title: str) -> dict[str, Path]:
    book_dir   = out_root / sanitize_folder_name(book_title)
    raw_dir    = book_dir / "pages_raw"
    clean_dir  = book_dir / "pages_clean"
    cover_dir  = book_dir / "cover"
    int_dir    = book_dir / "interior"

    for d in (book_dir, raw_dir, clean_dir, cover_dir, int_dir):
        d.mkdir(parents=True, exist_ok=True)

    return dict(
        book=book_dir, raw=raw_dir, clean=clean_dir,
        cover=cover_dir, interior=int_dir,
    )


# ── Single-page generation + QA loop ─────────────────────────────────────────

_MAX_QA_RETRIES = 3


def _generate_and_qa(
    idea: PageIdea,
    gen: ImageGenerator,
    raw_dir: Path,
    clean_dir: Path,
    manifest: dict,
    manifest_lock: threading.Lock,
    threshold: int,
    force: bool,
) -> tuple[str, str]:
    """
    Generate one page, run QA, retry up to _MAX_QA_RETRIES on failure.
    Returns (page_key, status).
    """
    key       = f"{idea.number:02d}"
    raw_path  = raw_dir / idea.filename
    clean_path = clean_dir / idea.filename

    # Resume: skip if already OK
    with manifest_lock:
        page_data = manifest["pages"].get(key, {})
    if not force and page_data.get("status") == "ok" and clean_path.exists():
        log.info("  Page %s/%s — already OK, skipping", key, idea.idea[:40])
        return key, "ok"

    style_prompt = page_data.get("style_prompt", "")
    full_prompt  = page_data.get("prompt", style_prompt + f"\n\nCreate the coloring page for: {idea.idea}")

    qa_flags: list[str] = []
    api_calls = 0

    for attempt in range(1 + _MAX_QA_RETRIES):
        log.info(
            "  Page %s %s%s ...",
            key,
            idea.idea[:45],
            f" (QA retry {attempt})" if attempt > 0 else "",
        )

        ok = gen.generate(
            prompt=full_prompt,
            dest=raw_path,
            qa_flags=qa_flags if attempt > 0 else None,
        )
        api_calls += 1

        if not ok:
            status = "failed"
            break

        result = check_image(raw_path)
        if result.ok:
            process_page(raw_path, clean_path, threshold)
            status = "ok"
            qa_flags = []
            break
        else:
            qa_flags = result.flags
            log.warning(
                "    QA flags on page %s (attempt %d): %s  dark=%.1f%%",
                key, attempt + 1, ", ".join(qa_flags), result.dark_pct,
            )
            if attempt == _MAX_QA_RETRIES:
                # Still process it but mark for review
                process_page(raw_path, clean_path, threshold)
                status = "needs_review"

    with manifest_lock:
        manifest["pages"][key] = {
            "idea":      idea.idea,
            "status":    status,
            "attempts":  attempt + 1,
            "qa_flags":  qa_flags,
            "raw_path":  raw_path.name,
            "clean_path": clean_path.name,
        }
        manifest["stats"]["api_calls"] = manifest["stats"].get("api_calls", 0) + api_calls

    return key, status


# ── Cover generation ──────────────────────────────────────────────────────────

def _generate_covers(
    gen: ImageGenerator,
    book: KDPBook,
    cover_dir: Path,
    raw_dir: Path,
    n_samples: int,
    manifest: dict,
    skip_samples: bool,
) -> None:
    for name, prompt in (("front", book.front_cover_prompt), ("back", book.back_cover_prompt)):
        dest = cover_dir / f"{name}.png"
        if manifest.get("covers", {}).get(name, {}).get("status") == "ok" and dest.exists():
            log.info("  Cover %s — already OK, skipping", name)
            continue
        log.info("  Generating %s cover ...", name)
        ok = gen.generate(prompt=prompt, dest=dest, max_attempts=3)
        manifest.setdefault("covers", {})[name] = {"status": "ok" if ok else "failed", "path": dest.name}
        if not ok:
            log.error("  Cover %s generation failed after 3 attempts", name)

    if not skip_samples and book.colored_sample_prompt:
        raw_pages = sorted(raw_dir.glob("*.png"))[:n_samples]
        for i, src in enumerate(raw_pages, 1):
            dest = cover_dir / f"colored_sample_{i:02d}.png"
            if dest.exists():
                continue
            log.info("  Generating colored sample %d/%d ...", i, n_samples)
            ok = gen.edit(source_path=src, prompt=book.colored_sample_prompt, dest=dest)
            if not ok:
                log.warning("  Colored sample %d skipped (edit endpoint not available)", i)
                break  # if one fails, all will — stop early


# ── QA report writer ──────────────────────────────────────────────────────────

def _write_qa_report(book_dir: Path, manifest: dict) -> None:
    lines = ["KDP Book Builder — QA Report", "=" * 50, ""]
    ok_count = flagged = needs_review = 0
    for key in sorted(manifest["pages"]):
        p = manifest["pages"][key]
        status = p.get("status", "unknown")
        flags  = p.get("qa_flags", [])
        line   = f"  Page {key} [{status:12s}]  {p.get('idea','')[:50]}"
        if flags:
            line += f"  flags: {', '.join(flags)}"
        lines.append(line)
        if status == "ok":
            ok_count += 1
        elif status == "needs_review":
            needs_review += 1
            flagged += 1
        else:
            flagged += 1

    lines.append("")
    lines.append(f"Pages OK:           {ok_count}")
    lines.append(f"Pages flagged/failed:{flagged}  (including {needs_review} needs-manual-review)")
    lines.append(f"API calls made:     {manifest['stats'].get('api_calls', 0)}")
    lines.append("")
    lines.append("COVER: Check cover spelling manually — OCR is not performed.")
    (book_dir / "qa_report.txt").write_text("\n".join(lines), encoding="utf-8")


# ── Main run ──────────────────────────────────────────────────────────────────

def run(argv: list[str] | None = None) -> None:
    args    = build_parser().parse_args(argv)
    md_path = Path(args.md_file).resolve()

    if not md_path.exists():
        sys.exit(f"ERROR: File not found: {md_path}")

    # ── Parse ──────────────────────────────────────────────────────────────
    print(f"\nParsing {md_path.name} ...")
    try:
        book = parse_book(md_path)
    except ValueError as exc:
        sys.exit(str(exc))

    # Page subset
    regen_set: set[int] = set()
    if args.regen:
        try:
            regen_set = {int(x.strip()) for x in args.regen.split(",")}
        except ValueError:
            sys.exit("ERROR: --regen must be comma-separated integers, e.g. 7,12,31")

    ideas = book.page_ideas
    if args.limit > 0:
        ideas = ideas[: args.limit]
    n = len(ideas)

    # ── Setup directories ─────────────────────────────────────────────────
    out_root = Path(args.out)
    dirs     = setup_dirs(out_root, book.book_title)
    book_dir = dirs["book"]
    log_path = book_dir / "run.log"
    setup_logger(log_path)

    # ── Validate ──────────────────────────────────────────────────────────
    script_dir = Path(__file__).parent.parent
    warnings   = validate(book, len(book.page_ideas), script_dir)
    if warnings:
        print("\n⚠  VALIDATION WARNINGS:")
        for w in warnings:
            print(f"   {w}")

    # ── Print plan ────────────────────────────────────────────────────────
    n_covers    = 0 if args.skip_cover else 2
    n_api_pages = n if not (args.dry_run or args.only_pdf) else 0
    n_samples   = 4 if not args.skip_samples else 0
    total_calls = n_api_pages + n_covers + n_samples

    print(f"\n{'='*60}")
    print(f"  Book:         {book.book_title}")
    if book.subtitle:
        print(f"  Subtitle:     {book.subtitle}")
    print(f"  Output:       {book_dir}")
    print(f"  Page ideas:   {n}  (total in file: {len(book.page_ideas)})")
    print(f"  Interior PDF: 2 + {n}×2 = {2 + 2*n} pages")
    print(f"  API calls:    ~{total_calls}  ({n} pages + {n_covers} covers + {n_samples} samples)")
    print(f"  Model:        {args.model}  size={args.size}  quality={args.quality}")
    print(f"  Mode:         {'DRY-RUN' if args.dry_run else 'ONLY-PDF' if args.only_pdf else 'FULL'}")
    print(f"{'='*60}\n")

    if args.dry_run or args.only_pdf:
        # Write upload_details with placeholder page count
        total_pages = 2 + 2 * n
        interior_pdf = dirs["interior"] / f"{sanitize_folder_name(book.book_title)}_interior.pdf"
        det_path = write_upload_details(
            book, book_dir, interior_pdf, total_pages, warnings, args.author
        )
        print(f"upload_details.txt written → {det_path}")
        if args.dry_run:
            print("\nDRY-RUN complete — no API calls made.")
            return
        # only_pdf falls through to PDF builder below

    if not (args.dry_run or args.only_pdf):
        if not args.yes:
            ans = input("Proceed? [y/N] ").strip().lower()
            if ans not in ("y", "yes"):
                sys.exit("Aborted.")

    # ── Load API key & create client ──────────────────────────────────────
    if not args.only_pdf:
        api_key = load_api_key(script_dir)
        client  = openai.OpenAI(api_key=api_key)
        gen     = ImageGenerator(client, model=args.model, size=args.size, quality=args.quality)

    manifest      = load_manifest(book_dir / "manifest.json")
    manifest_lock = threading.Lock()

    # ── B. Generate interior pages ────────────────────────────────────────
    if not args.only_pdf:
        print(f"\n[B] Generating {n} interior pages (workers={args.workers}) ...\n")

        futures = {}
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            for idea in ideas:
                force = idea.number in regen_set
                f = pool.submit(
                    _generate_and_qa,
                    idea, gen,
                    dirs["raw"], dirs["clean"],
                    manifest, manifest_lock,
                    args.threshold, force,
                )
                futures[f] = idea

            for done in as_completed(futures):
                idea = futures[done]
                try:
                    key, status = done.result()
                    icon = "✓" if status == "ok" else ("⚠" if status == "needs_review" else "✗")
                    print(f"  {icon} Page {key}: {status}")
                except Exception as exc:
                    log.error("Unexpected error on page %s: %s", idea.number, exc)

        save_manifest(book_dir / "manifest.json", manifest)

        # Abort PDF build if any page hard-failed (needs_review is OK — image exists)
        failed_pages = [
            k for k, p in manifest["pages"].items() if p.get("status") == "failed"
        ]
        if failed_pages:
            _write_qa_report(book_dir, manifest)
            print(f"\n✗ {len(failed_pages)} page(s) failed to generate: {', '.join(failed_pages)}")
            print("  Fix the error above and re-run — resume mode will skip successful pages.")
            sys.exit(1)

        # ── F. Covers ─────────────────────────────────────────────────────
        if not args.skip_cover:
            print("\n[F] Generating covers ...\n")
            _generate_covers(
                gen, book, dirs["cover"], dirs["raw"],
                n_samples=4, manifest=manifest, skip_samples=args.skip_samples,
            )
            save_manifest(book_dir / "manifest.json", manifest)

    # ── E. Build PDF ──────────────────────────────────────────────────────
    print("\n[E] Building interior PDF ...\n")
    sanitized_title  = sanitize_folder_name(book.book_title)
    interior_pdf     = dirs["interior"] / f"{sanitized_title}_interior.pdf"
    page_order       = [f"{idea.number:02d}_{idea.slug}.png" for idea in ideas]
    total_pages      = build_pdf(dirs["clean"], interior_pdf, page_order)
    print(f"  Interior PDF: {interior_pdf}")
    print(f"  Total pages:  {total_pages}  ({'even ✓' if total_pages % 2 == 0 else 'ODD ✗'})")

    # ── G. Write upload_details.txt ───────────────────────────────────────
    det_path = write_upload_details(
        book, book_dir, interior_pdf, total_pages, warnings, args.author
    )

    # ── QA report ─────────────────────────────────────────────────────────
    _write_qa_report(book_dir, manifest)

    # ── Final summary ──────────────────────────────────────────────────────
    stats      = manifest.get("stats", {})
    ok_count   = sum(1 for p in manifest["pages"].values() if p.get("status") == "ok")
    flagged    = sum(1 for p in manifest["pages"].values() if p.get("status") != "ok")
    api_calls  = stats.get("api_calls", 0)

    print("\n" + "=" * 60)
    print("  DONE")
    print(f"  Pages OK:      {ok_count}")
    print(f"  Pages flagged: {flagged}  (see qa_report.txt)")
    print(f"  API calls:     {api_calls}")
    print(f"  Output folder: {book_dir}")
    print(f"  Details file:  {det_path}")
    print("=" * 60 + "\n")
