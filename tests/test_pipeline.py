from dataclasses import replace
from email.message import EmailMessage
from pathlib import Path

import pytest

from ingest_mail.config import Settings
from ingest_mail.documents import ConversionResult
from ingest_mail.pipeline import Pipeline


@pytest.fixture()
def settings(tmp_path) -> Settings:
    return Settings(
        source_dir=tmp_path / "source",
        dest_dir=tmp_path / "dest",
        state_file=tmp_path / "state" / "processed.json",
        attachments_subdir="attachments",
        torch_device="cpu",
        use_marker=False,
        ocr_langs="eng",
        watch=False,
        poll_interval=1,
        delete_after=False,
        reprocess=False,
        max_file_mb=10,
        extract_attachments=True,
        log_level="INFO",
    )


def _make_eml(directory: Path, subject: str = "Rapport mensuel", attachment=None) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = "a@example.org"
    message["To"] = "b@example.org"
    message["Date"] = "Mon, 01 Sep 2025 10:30:00 +0200"
    message.set_content("Bonjour")
    if attachment:
        message.add_attachment(attachment[1], maintype="application", subtype="pdf", filename=attachment[0])
    path = directory / f"{subject}.eml"
    path.write_bytes(bytes(message))
    return path


def test_run_once_produit_une_note_datee(settings):
    _make_eml(settings.source_dir)
    report = Pipeline(settings).run_once()

    notes = list(settings.dest_dir.glob("*.md"))
    assert report.emails == 1 and len(notes) == 1
    assert notes[0].name == "2025-09-01-rapport-mensuel.md"
    content = notes[0].read_text(encoding="utf-8")
    assert content.startswith("---\n") and "from: a@example.org" in content
    assert "Bonjour" in content


def test_run_once_est_idempotent(settings):
    _make_eml(settings.source_dir)
    Pipeline(settings).run_once()
    second = Pipeline(settings).run_once()

    assert second.emails == 0 and second.skipped == 1
    assert len(list(settings.dest_dir.glob("*.md"))) == 1


def test_reprocess_force_une_nouvelle_note(settings):
    _make_eml(settings.source_dir)
    Pipeline(settings).run_once()
    Pipeline(replace(settings, reprocess=True)).run_once()

    assert len(list(settings.dest_dir.glob("*.md"))) == 2


def test_piece_jointe_convertie_et_liee(settings, monkeypatch):
    _make_eml(settings.source_dir, attachment=("facture.pdf", b"%PDF-1.4 contenu"))
    monkeypatch.setattr(
        "ingest_mail.documents.DocumentConverter.convert",
        lambda self, path, workdir=None: ConversionResult(markdown="Total : 42 €", engine="stub", pages=1),
    )
    report = Pipeline(settings).run_once()

    attachment_notes = list(settings.attachments_dir.glob("*.md"))
    assert report.attachments == 1 and len(attachment_notes) == 1
    assert "Total : 42 €" in attachment_notes[0].read_text(encoding="utf-8")
    email_note = next(settings.dest_dir.glob("*.md")).read_text(encoding="utf-8")
    assert f"[[{attachment_notes[0].stem}]]" in email_note


def test_delete_after_supprime_la_source(settings):
    path = _make_eml(settings.source_dir)
    Pipeline(replace(settings, delete_after=True)).run_once()
    assert not path.exists()


def test_document_seul_utilise_le_convertisseur(settings, monkeypatch):
    settings.source_dir.mkdir(parents=True, exist_ok=True)
    (settings.source_dir / "scan.pdf").write_bytes(b"%PDF-1.4 x")
    monkeypatch.setattr(
        "ingest_mail.documents.DocumentConverter.convert",
        lambda self, path, workdir=None: ConversionResult(markdown="Texte OCR", engine="stub", pages=2),
    )
    report = Pipeline(settings).run_once()

    notes = list(settings.attachments_dir.glob("*.md"))
    assert report.documents == 1 and len(notes) == 1
    assert "pages: 2" in notes[0].read_text(encoding="utf-8")


def test_echec_de_conversion_est_comptabilise(settings, monkeypatch):
    settings.source_dir.mkdir(parents=True, exist_ok=True)
    (settings.source_dir / "vide.pdf").write_bytes(b"%PDF-1.4")
    monkeypatch.setattr(
        "ingest_mail.documents.DocumentConverter.convert",
        lambda self, path, workdir=None: ConversionResult(markdown="", engine="none"),
    )
    report = Pipeline(settings).run_once()
    assert report.failed == 1 and report.documents == 0
