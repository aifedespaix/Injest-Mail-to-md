from email.message import EmailMessage
from pathlib import Path


from ingest_mail.eml import html_body_to_markdown, normalize_markdown, parse_eml


def _write_eml(tmp_path: Path, *, html: str | None = None, text: str | None = None,
               attachment: tuple[str, bytes] | None = None) -> Path:
    message = EmailMessage()
    message["Subject"] = "=?utf-8?B?RmFjdHVyZSDDiXTDqQ==?="  # "Facture Été"
    message["From"] = "Jean Dupont <jean@example.org>"
    message["To"] = "moi@example.org"
    message["Cc"] = "copie@example.org"
    message["Date"] = "Mon, 01 Sep 2025 10:30:00 +0200"
    message["Message-ID"] = "<abc123@example.org>"
    message.set_content(text or "Corps texte brut")
    if html:
        message.add_alternative(html, subtype="html")
    if attachment:
        name, payload = attachment
        message.add_attachment(payload, maintype="application", subtype="pdf", filename=name)

    path = tmp_path / "mail.eml"
    path.write_bytes(bytes(message))
    return path


def test_parse_metadonnees(tmp_path):
    parsed = parse_eml(_write_eml(tmp_path))
    assert parsed.subject == "Facture Été"
    assert parsed.sender == "jean@example.org"
    assert parsed.sender_name == "Jean Dupont"
    assert parsed.recipients == ["moi@example.org"]
    assert parsed.cc == ["copie@example.org"]
    assert parsed.date is not None and parsed.date.year == 2025
    assert parsed.message_id == "<abc123@example.org>"


def test_corps_html_prioritaire_sur_texte(tmp_path):
    path = _write_eml(tmp_path, html="<html><body><h1>Titre</h1><p>Bonjour</p></body></html>")
    parsed = parse_eml(path)
    assert parsed.body_format == "html"
    assert "# Titre" in parsed.body_markdown
    assert "Bonjour" in parsed.body_markdown


def test_corps_texte_quand_pas_de_html(tmp_path):
    parsed = parse_eml(_write_eml(tmp_path, text="Ligne unique"))
    assert parsed.body_format == "text"
    assert parsed.body_markdown == "Ligne unique"


def test_pieces_jointes_extraites(tmp_path):
    parsed = parse_eml(_write_eml(tmp_path, attachment=("facture.pdf", b"%PDF-1.4 fake")))
    assert [a.filename for a in parsed.attachments] == ["facture.pdf"]
    assert parsed.attachments[0].payload.startswith(b"%PDF")


def test_html_vers_markdown_supprime_script_et_style():
    md = html_body_to_markdown("<style>p{color:red}</style><script>alert(1)</script><p>Texte</p>")
    assert "alert" not in md and "color" not in md
    assert "Texte" in md


def test_normalize_markdown_compacte_les_lignes_vides():
    assert normalize_markdown("a\n\n\n\n\nb   \n") == "a\n\nb"
