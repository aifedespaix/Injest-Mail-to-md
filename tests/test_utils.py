from pathlib import Path

from ingest_mail.utils import kind_of, is_supported, slugify, unique_path


def test_slugify_accents_et_ponctuation():
    assert slugify("Facture Août 2025 — n°42 !") == "facture-aout-2025-n42"


def test_slugify_vide_utilise_le_fallback():
    assert slugify("///") == "sans-titre"


def test_slugify_tronque():
    assert len(slugify("a" * 200, max_length=20)) == 20


def test_kind_of():
    assert kind_of(Path("m.eml")) == "email"
    assert kind_of(Path("f.PDF")) == "pdf"
    assert kind_of(Path("scan.JPG")) == "image"
    assert kind_of(Path("note.txt")) == "unknown"


def test_is_supported():
    assert is_supported(Path("a.pdf"))
    assert not is_supported(Path("a.docx"))


def test_unique_path_evite_les_collisions(tmp_path):
    (tmp_path / "note.md").write_text("x", encoding="utf-8")
    assert unique_path(tmp_path, "note").name == "note-1.md"
