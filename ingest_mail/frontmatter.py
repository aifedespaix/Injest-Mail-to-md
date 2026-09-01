"""Génération du frontmatter YAML consommé par Obsidian / Claude Code."""

from __future__ import annotations

from typing import Any, Mapping

import yaml


def _clean(value: Any) -> Any:
    if isinstance(value, str):
        return value.replace("\r\n", "\n").strip()
    if isinstance(value, (list, tuple)):
        return [_clean(item) for item in value if item not in (None, "")]
    return value


def dump_frontmatter(metadata: Mapping[str, Any]) -> str:
    """Sérialise les métadonnées en bloc `---` YAML (ordre d'insertion préservé)."""
    payload = {key: _clean(value) for key, value in metadata.items() if value not in (None, "", [], {})}
    body = yaml.safe_dump(
        payload,
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
        width=1000,
    ).strip()
    return f"---\n{body}\n---\n"


def build_note(metadata: Mapping[str, Any], body: str) -> str:
    """Assemble une note Markdown complète : frontmatter + corps normalisé."""
    normalized = (body or "").replace("\r\n", "\n").strip()
    return f"{dump_frontmatter(metadata)}\n{normalized}\n"
