"""Shared utilities: logging, manifest I/O, retry, filename sanitisation."""
from __future__ import annotations

import json
import logging
import re
import time
from functools import wraps
from pathlib import Path
from typing import Any, Callable, TypeVar

F = TypeVar("F", bound=Callable[..., Any])

# ── Filename helpers ────────────────────────────────────────────────────────

_WIN_BAD = re.compile(r'[<>:"/\\|?*]')
_MULTI_SPACE = re.compile(r"\s+")
_MULTI_UNDER = re.compile(r"_+")


def sanitize_folder_name(name: str, max_len: int = 80) -> str:
    name = _WIN_BAD.sub("", name)
    name = _MULTI_SPACE.sub(" ", name).strip(" .")
    return name[:max_len]


def sanitize_filename(name: str, max_len: int = 60) -> str:
    name = _WIN_BAD.sub("_", name)
    name = name.replace(" ", "_")
    name = _MULTI_UNDER.sub("_", name).strip("_").lower()
    return name[:max_len]


# ── Manifest (JSON) ─────────────────────────────────────────────────────────

def load_manifest(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {"pages": {}, "covers": {}, "stats": {"api_calls": 0}}


def save_manifest(path: Path, data: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


# ── Logging ─────────────────────────────────────────────────────────────────

def setup_logger(log_path: Path) -> logging.Logger:
    logger = logging.getLogger("kdp")
    logger.setLevel(logging.DEBUG)
    if logger.handlers:
        return logger

    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")

    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    fh = logging.FileHandler(log_path, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    return logger


# ── Retry with exponential back-off ─────────────────────────────────────────

_RETRYABLE = ("rate limit", "429", "500", "502", "503", "504", "timeout",
              "connection error", "read timed out", "server error")


def retry_with_backoff(max_attempts: int = 4, base_delay: float = 2.0) -> Callable[[F], F]:
    def decorator(func: F) -> F:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exc: Exception | None = None
            for attempt in range(max_attempts):
                try:
                    return func(*args, **kwargs)
                except Exception as exc:
                    last_exc = exc
                    low = str(exc).lower()
                    if any(t in low for t in _RETRYABLE) and attempt < max_attempts - 1:
                        delay = base_delay * (2 ** attempt)
                        log = logging.getLogger("kdp")
                        log.warning(
                            "API error attempt %d/%d: %s  — retrying in %.1fs",
                            attempt + 1, max_attempts, exc, delay,
                        )
                        time.sleep(delay)
                        continue
                    raise
            raise last_exc  # type: ignore[misc]
        return wrapper  # type: ignore[return-value]
    return decorator  # type: ignore[return-value]
