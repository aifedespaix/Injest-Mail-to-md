"""Petites fonctions utilitaires partagées (nommage, hachage, dates)."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

_SLUG_STRIP = re.compile(r"[^a-zA-Z0-9]+")
_MULTI_DASH = re.compile(r"-{2,}")

DOCUMENT_SUFFIXES = {".pdf"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp", ".gif"}
EMAIL_SUFFIXES = {".eml"}
SUPPORTED_SUFFIXES = DOCUMENT_SUFFIXES | IMAGE_SUFFIXES | EMAIL_SUFFIXES


def slugify(value: str, max_length: int = 80, fallback: str = "sans-titre") -> str:
    """Transforme un texte quelconque en identifiant de fichier sûr et lisible."""
    normalized = unicodedata.normalize("NFKD", value or "")
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
    slug = _SLUG_STRIP.sub("-", ascii_only).strip("-").lower()
    slug = _MULTI_DASH.sub("-", slug)
    if len(slug) > max_length:
        slug = slug[:max_length].rstrip("-")
    return slug or fallback


def sha256_file(path: Path, chunk_size: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def unique_path(directory: Path, stem: str, suffix: str = ".md") -> Path:
    """Renvoie un chemin libre dans `directory`, en suffixant -1, -2… si besoin."""
    candidate = directory / f"{stem}{suffix}"
    index = 1
    while candidate.exists():
        candidate = directory / f"{stem}-{index}{suffix}"
        index += 1
    return candidate


def isoformat(dt: datetime | None) -> str:
    if dt is None:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def date_prefix(dt: datetime | None) -> str:
    return (dt or datetime.now(timezone.utc)).strftime("%Y-%m-%d")


def is_supported(path: Path) -> bool:
    return path.suffix.lower() in SUPPORTED_SUFFIXES


def kind_of(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in EMAIL_SUFFIXES:
        return "email"
    if suffix in DOCUMENT_SUFFIXES:
        return "pdf"
    if suffix in IMAGE_SUFFIXES:
        return "image"
    return "unknown"


def is_stable(path: Path, min_age_seconds: float = 2.0) -> bool:
    """Évite de lire un fichier encore en cours d'écriture par le client mail."""
    try:
        stat = path.stat()
    except OSError:
        return False
    age = datetime.now(timezone.utc).timestamp() - stat.st_mtime
    return age >= min_age_seconds and stat.st_size > 0
