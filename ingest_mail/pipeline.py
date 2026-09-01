"""Orchestration : parcours de SOURCE_DIR, conversion, écriture des notes dans DEST_DIR."""

from __future__ import annotations

import logging
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .config import Settings
from .documents import ConversionResult, DocumentConverter
from .eml import ParsedEmail, parse_eml
from .frontmatter import build_note
from .state import ProcessedState
from .utils import (
    date_prefix,
    is_stable,
    is_supported,
    isoformat,
    kind_of,
    sha256_bytes,
    sha256_file,
    slugify,
    unique_path,
)

LOGGER = logging.getLogger(__name__)


@dataclass
class RunReport:
    emails: int = 0
    documents: int = 0
    attachments: int = 0
    skipped: int = 0
    failed: int = 0

    def summary(self) -> str:
        return (
            f"{self.emails} e-mail(s), {self.documents} document(s), "
            f"{self.attachments} pièce(s) jointe(s), {self.skipped} ignoré(s), {self.failed} en échec"
        )


class Pipeline:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.state = ProcessedState(settings.state_file)
        self.converter = DocumentConverter(
            device=settings.torch_device,
            use_marker=settings.use_marker,
            ocr_langs=settings.ocr_langs,
        )

    # --------------------------------------------------------------- découverte
    def discover(self) -> list[Path]:
        source = self.settings.source_dir
        if not source.exists():
            LOGGER.error("SOURCE_DIR introuvable : %s", source)
            return []
        files = [p for p in sorted(source.rglob("*")) if p.is_file() and is_supported(p)]
        # Les e-mails d'abord : leurs pièces jointes internes sont traitées dans la foulée.
        files.sort(key=lambda p: (kind_of(p) != "email", str(p)))
        return files

    # ------------------------------------------------------------------ écriture
    def _write_note(self, stem: str, metadata: dict, body: str, directory: Path) -> Path:
        directory.mkdir(parents=True, exist_ok=True)
        target = unique_path(directory, stem)
        target.write_text(build_note(metadata, body), encoding="utf-8")
        LOGGER.info("Note écrite : %s", target)
        return target

    # ------------------------------------------------------------------- e-mails
    def _email_note_body(self, parsed: ParsedEmail, attachment_notes: list[tuple[str, Path]]) -> str:
        sections: list[str] = [f"# {parsed.subject}", ""]
        body = parsed.body_markdown or "_(corps de message vide)_"
        sections.append(body)
        if attachment_notes:
            sections += ["", "## Pièces jointes", ""]
            for filename, note_path in attachment_notes:
                # Lien Obsidian vers la note générée pour la pièce jointe.
                sections.append(f"- `{filename}` → [[{note_path.stem}]]")
        return "\n".join(sections)

    def _process_email(self, path: Path, report: RunReport) -> None:
        parsed = parse_eml(path)
        stem = f"{date_prefix(parsed.date)}-{slugify(parsed.subject)}"

        attachment_notes: list[tuple[str, Path]] = []
        if self.settings.extract_attachments:
            attachment_notes = self._process_email_attachments(parsed, stem, report)

        metadata = {
            "title": parsed.subject,
            "type": "email",
            "from": parsed.sender,
            "from_name": parsed.sender_name,
            "to": parsed.recipients,
            "cc": parsed.cc,
            "date": isoformat(parsed.date),
            "message_id": parsed.message_id,
            "source_file": path.name,
            "body_format": parsed.body_format,
            "attachments": [attachment.filename for attachment in parsed.attachments],
            "tags": ["inbox", "email"],
            "ingested_at": datetime.now(timezone.utc).isoformat(),
        }
        self._write_note(stem, metadata, self._email_note_body(parsed, attachment_notes), self.settings.dest_dir)
        report.emails += 1

    def _process_email_attachments(
        self, parsed: ParsedEmail, email_stem: str, report: RunReport
    ) -> list[tuple[str, Path]]:
        """Convertit les PJ convertibles (PDF/images) contenues dans le `.eml`."""
        notes: list[tuple[str, Path]] = []
        convertible = [a for a in parsed.attachments if kind_of(Path(a.filename)) in {"pdf", "image"}]
        if not convertible:
            return notes

        with tempfile.TemporaryDirectory(prefix="ingest-att-") as tmpdir:
            workdir = Path(tmpdir)
            for attachment in convertible:
                digest = sha256_bytes(attachment.payload)
                known = self.state.get(digest)
                if known and not self.settings.reprocess:
                    notes.append((attachment.filename, Path(known["note"])))
                    report.skipped += 1
                    continue
                if attachment.size > self.settings.max_file_bytes:
                    LOGGER.warning("PJ ignorée (trop volumineuse) : %s", attachment.filename)
                    report.skipped += 1
                    continue

                extracted = workdir / Path(attachment.filename).name
                extracted.write_bytes(attachment.payload)
                note_path = self._convert_document(
                    extracted,
                    stem=f"{email_stem}-pj-{slugify(Path(attachment.filename).stem, max_length=40)}",
                    metadata_extra={
                        "parent_email": parsed.subject,
                        "from": parsed.sender,
                        "attachment_of": email_stem,
                    },
                    workdir=workdir,
                    report=report,
                )
                if note_path is not None:
                    self.state.remember(digest, attachment.filename, str(note_path))
                    notes.append((attachment.filename, note_path))
                    report.attachments += 1
        return notes

    # ----------------------------------------------------------------- documents
    def _convert_document(
        self,
        path: Path,
        stem: str,
        metadata_extra: dict,
        workdir: Path,
        report: RunReport,
    ) -> Path | None:
        result: ConversionResult = self.converter.convert(path, workdir=workdir)
        if not result.markdown:
            LOGGER.error("Aucun texte extrait de %s", path.name)
            report.failed += 1
            return None

        metadata = {
            "title": path.stem,
            "type": kind_of(path),
            "source_file": path.name,
            "converter": result.engine,
            "device": self.settings.torch_device,
            "pages": result.pages or None,
            "tags": ["inbox", "document"],
            "ingested_at": datetime.now(timezone.utc).isoformat(),
            **metadata_extra,
        }
        body = f"# {path.stem}\n\n{result.markdown}"
        return self._write_note(stem, metadata, body, self.settings.attachments_dir)

    def _process_standalone_document(self, path: Path, report: RunReport) -> None:
        stem = f"{date_prefix(datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc))}-{slugify(path.stem)}"
        with tempfile.TemporaryDirectory(prefix="ingest-doc-") as tmpdir:
            note = self._convert_document(
                path,
                stem=stem,
                metadata_extra={},
                workdir=Path(tmpdir),
                report=report,
            )
        if note is not None:
            report.documents += 1

    # ----------------------------------------------------------------- exécution
    def process_file(self, path: Path, report: RunReport) -> None:
        digest = sha256_file(path)
        if self.state.has(digest) and not self.settings.reprocess:
            LOGGER.debug("Déjà traité, ignoré : %s", path.name)
            report.skipped += 1
            return
        if path.stat().st_size > self.settings.max_file_bytes:
            LOGGER.warning("Fichier ignoré (> %s Mo) : %s", self.settings.max_file_mb, path.name)
            report.skipped += 1
            return

        kind = kind_of(path)
        try:
            if kind == "email":
                self._process_email(path, report)
            else:
                self._process_standalone_document(path, report)
        except Exception:
            LOGGER.exception("Échec du traitement de %s", path)
            report.failed += 1
            return

        self.state.remember(digest, str(path), str(self.settings.dest_dir))
        self.state.save()

        if self.settings.delete_after:
            path.unlink(missing_ok=True)
            LOGGER.info("Source supprimée : %s", path.name)

    def run_once(self) -> RunReport:
        report = RunReport()
        self.settings.dest_dir.mkdir(parents=True, exist_ok=True)
        files = self.discover()
        if not files:
            LOGGER.info("Aucun fichier à traiter dans %s", self.settings.source_dir)
            return report

        LOGGER.info("%d fichier(s) candidat(s).", len(files))
        for path in files:
            # En surveillance continue, on laisse au client mail le temps de finir
            # d'écrire le fichier avant de le lire.
            if self.settings.watch and not is_stable(path):
                LOGGER.info("Fichier en cours d'écriture, reporté : %s", path.name)
                continue
            self.process_file(path, report)

        self.state.save()
        LOGGER.info("Terminé : %s", report.summary())
        return report

    def watch(self) -> None:
        """Boucle de surveillance simple (polling), robuste aux montages réseau."""
        LOGGER.info(
            "Mode surveillance actif : %s toutes les %ss.",
            self.settings.source_dir,
            self.settings.poll_interval,
        )
        while True:
            try:
                self.run_once()
            except KeyboardInterrupt:
                raise
            except Exception:
                LOGGER.exception("Erreur pendant un cycle de traitement — poursuite.")
            time.sleep(self.settings.poll_interval)
