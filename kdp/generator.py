"""OpenAI Images API wrapper: generate and edit images."""
from __future__ import annotations

import base64
import logging
import urllib.request
from pathlib import Path
from typing import Optional

import openai

from .utils import retry_with_backoff

log = logging.getLogger("kdp")

# ── Corrective suffixes appended on QA failures ───────────────────────────────

_QA_CORRECTIONS: dict[str, str] = {
    "grey":       "Use only pure black outlines on a plain white background — no grey shading, no fills.",
    "too_empty":  "Add much more detail: more outlines, patterns, and elements to fill the page richly.",
    "too_filled": "Use thinner outlines with open areas so children can colour it in — no solid fills.",
    "cropped":    "The whole illustration must fit inside the page with wide white margins on every side.",
    "background": "Plain white background only — no textures, gradients, or patterns behind the drawing.",
}


def _save_image(item, dest: Path) -> None:
    """Save one image response item — prefers b64_json, falls back to url."""
    if getattr(item, "b64_json", None):
        dest.write_bytes(base64.b64decode(item.b64_json))
    elif getattr(item, "url", None):
        with urllib.request.urlopen(item.url) as r:
            dest.write_bytes(r.read())
    else:
        raise RuntimeError("API response has neither b64_json nor url")


# ── Image generation ──────────────────────────────────────────────────────────

class ImageGenerator:
    def __init__(
        self,
        client: openai.OpenAI,
        model: str = "gpt-image-1",
        size: str = "1024x1536",
        quality: str = "medium",
    ) -> None:
        self.client  = client
        self.model   = model
        self.size    = size
        self.quality = quality

    # Decorated versions are created in generate() / edit() to allow
    # per-call max_attempts without re-wrapping the class method.

    def generate(
        self,
        prompt: str,
        dest: Path,
        qa_flags: Optional[list[str]] = None,
        attempt: int = 0,
        max_attempts: int = 4,
    ) -> bool:
        """
        Generate one image into *dest*.
        On QA retries, qa_flags corrections are appended to the prompt.
        Returns True on success.
        """
        full_prompt = prompt
        if qa_flags:
            corrections = "  ".join(
                _QA_CORRECTIONS[f] for f in qa_flags if f in _QA_CORRECTIONS
            )
            if corrections:
                full_prompt = prompt + "\n\nIMPORTANT CORRECTIONS: " + corrections

        @retry_with_backoff(max_attempts=max_attempts)
        def _call() -> None:
            resp = self.client.images.generate(
                model=self.model,
                prompt=full_prompt,
                size=self.size,
                quality=self.quality,
                n=1,
            )
            _save_image(resp.data[0], dest)

        try:
            _call()
            log.debug("Generated %s", dest.name)
            return True
        except Exception as exc:
            log.error("generate failed for %s: %s", dest.name, exc)
            return False

    def edit(
        self,
        source_path: Path,
        prompt: str,
        dest: Path,
        max_attempts: int = 3,
    ) -> bool:
        """
        Edit *source_path* with *prompt*, save result to *dest*.
        Returns True on success, False if the model/API doesn't support edits.
        """
        @retry_with_backoff(max_attempts=max_attempts)
        def _call() -> None:
            with open(source_path, "rb") as img_file:
                resp = self.client.images.edit(
                    model=self.model,
                    image=img_file,
                    prompt=prompt,
                    size=self.size,
                    quality=self.quality,
                    n=1,
                )
            _save_image(resp.data[0], dest)

        try:
            _call()
            log.debug("Edited %s -> %s", source_path.name, dest.name)
            return True
        except openai.BadRequestError as exc:
            log.warning("Image edit not available for model %s: %s", self.model, exc)
            return False
        except Exception as exc:
            log.error("edit failed for %s: %s", dest.name, exc)
            return False
