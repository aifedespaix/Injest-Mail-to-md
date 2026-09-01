"""Journal des fichiers déjà traités, pour rendre le pipeline idempotent."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

LOGGER = logging.getLogger(__name__)


class ProcessedState:
    """Index `sha256 -> note produite`, persisté en JSON sur le volume de données."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._entries: dict[str, dict[str, str]] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                self._entries = {k: v for k, v in raw.items() if isinstance(v, dict)}
        except (json.JSONDecodeError, OSError) as exc:
            LOGGER.warning("État illisible (%s) — repartir de zéro.", exc)
            self._entries = {}

    def has(self, digest: str) -> bool:
        return digest in self._entries

    def get(self, digest: str) -> dict[str, str] | None:
        return self._entries.get(digest)

    def remember(self, digest: str, source: str, note: str) -> None:
        self._entries[digest] = {
            "source": source,
            "note": note,
            "processed_at": datetime.now(timezone.utc).isoformat(),
        }

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(self._entries, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def __len__(self) -> int:
        return len(self._entries)
