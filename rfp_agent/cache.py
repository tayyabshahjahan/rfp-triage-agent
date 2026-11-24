"""Small disk cache keyed by document bytes, model, and prompt version."""

from __future__ import annotations

import hashlib
from pathlib import Path

from .config import CACHE_DIR
from .schemas import FinalReport


def cache_key(file_bytes: bytes, model: str, prompt_version: str) -> str:
    digest = hashlib.sha256()
    digest.update(file_bytes)
    digest.update(model.encode())
    digest.update(prompt_version.encode())
    return digest.hexdigest()


def load_cached(key: str, cache_dir: Path = CACHE_DIR) -> FinalReport | None:
    path = cache_dir / f"{key}.json"
    if not path.exists():
        return None
    try:
        return FinalReport.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def save_cached(report: FinalReport, key: str, cache_dir: Path = CACHE_DIR) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"{key}.json"
    path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
