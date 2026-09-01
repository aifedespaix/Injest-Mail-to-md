"""Configuration du pipeline, entièrement pilotée par variables d'environnement."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_path(name: str, default: str) -> Path:
    return Path(os.getenv(name, default)).expanduser()


@dataclass(frozen=True)
class Settings:
    """Paramètres d'exécution résolus une seule fois au démarrage."""

    source_dir: Path = field(default_factory=lambda: _env_path("SOURCE_DIR", "/data/source"))
    dest_dir: Path = field(default_factory=lambda: _env_path("DEST_DIR", "/data/dest"))
    state_file: Path = field(default_factory=lambda: _env_path("STATE_FILE", "/data/state/processed.json"))

    # Sous-dossier de DEST_DIR où atterrissent les pièces jointes converties.
    attachments_subdir: str = field(default_factory=lambda: os.getenv("ATTACHMENTS_SUBDIR", "attachments"))

    # cuda | cpu — propagé à marker/Surya via TORCH_DEVICE.
    torch_device: str = field(default_factory=lambda: os.getenv("TORCH_DEVICE", "cuda"))
    use_marker: bool = field(default_factory=lambda: _env_bool("USE_MARKER", True))
    ocr_langs: str = field(default_factory=lambda: os.getenv("OCR_LANGS", "fra+eng"))

    # Boucle de surveillance : le conteneur reste actif et traite les nouveaux fichiers.
    watch: bool = field(default_factory=lambda: _env_bool("WATCH", False))
    poll_interval: int = field(default_factory=lambda: _env_int("POLL_INTERVAL", 30))

    # Nettoyage / limites.
    delete_after: bool = field(default_factory=lambda: _env_bool("DELETE_AFTER", False))
    reprocess: bool = field(default_factory=lambda: _env_bool("REPROCESS", False))
    max_file_mb: int = field(default_factory=lambda: _env_int("MAX_FILE_MB", 200))
    extract_attachments: bool = field(default_factory=lambda: _env_bool("EXTRACT_ATTACHMENTS", True))

    log_level: str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO").upper())

    @property
    def attachments_dir(self) -> Path:
        return self.dest_dir / self.attachments_subdir if self.attachments_subdir else self.dest_dir

    @property
    def max_file_bytes(self) -> int:
        return self.max_file_mb * 1024 * 1024


def load_settings() -> Settings:
    """Construit les réglages et s'assure que TORCH_DEVICE est visible par marker."""
    settings = Settings()
    os.environ.setdefault("TORCH_DEVICE", settings.torch_device)
    return settings
