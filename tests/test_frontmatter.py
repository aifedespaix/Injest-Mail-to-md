import yaml

from ingest_mail.frontmatter import build_note, dump_frontmatter


def test_dump_ignore_les_valeurs_vides():
    out = dump_frontmatter({"title": "Test", "cc": [], "message_id": None})
    assert "cc" not in out and "message_id" not in out
    assert yaml.safe_load(out.strip("-\n")) == {"title": "Test"}


def test_dump_preserve_unicode_et_ordre():
    out = dump_frontmatter({"title": "Facture Été", "type": "email"})
    assert "Été" in out
    assert out.index("title") < out.index("type")


def test_build_note_structure():
    note = build_note({"title": "Sujet"}, "  Corps  ")
    assert note.startswith("---\n")
    assert note.count("---") >= 2
    assert note.rstrip().endswith("Corps")
