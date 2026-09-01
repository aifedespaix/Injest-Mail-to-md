"""Lecture des exports `.eml` : métadonnées, corps et pièces jointes."""

from __future__ import annotations

import email
import email.policy
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from email.header import decode_header, make_header
from email.message import EmailMessage
from email.utils import getaddresses, parsedate_to_datetime
from pathlib import Path
from typing import Iterable

from bs4 import BeautifulSoup
from markdownify import markdownify as html_to_markdown

LOGGER = logging.getLogger(__name__)

_BLANK_LINES = re.compile(r"\n{3,}")
_TRAILING_SPACES = re.compile(r"[ \t]+\n")
# Balises purement techniques : on les supprime avant la conversion Markdown.
_DROP_TAGS = ("script", "style", "head", "meta", "link", "noscript")


@dataclass(slots=True)
class Attachment:
    filename: str
    content_type: str
    payload: bytes

    @property
    def size(self) -> int:
        return len(self.payload)


@dataclass(slots=True)
class ParsedEmail:
    subject: str
    sender: str
    sender_name: str
    recipients: list[str]
    cc: list[str]
    date: datetime | None
    message_id: str
    body_markdown: str
    body_format: str
    attachments: list[Attachment] = field(default_factory=list)


def _decode(value: str | None) -> str:
    """Décode les en-têtes MIME encodés (=?utf-8?B?...?=) en texte lisible."""
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value))).strip()
    except Exception:  # en-tête malformé : on retombe sur la valeur brute
        return value.strip()


def _addresses(message: EmailMessage, header: str) -> list[str]:
    raw = message.get_all(header, [])
    if not raw:
        return []
    decoded = [_decode(item) for item in raw]
    return [addr for _, addr in getaddresses(decoded) if addr]


def _sender(message: EmailMessage) -> tuple[str, str]:
    raw = _decode(message.get("From"))
    pairs = getaddresses([raw]) if raw else []
    if not pairs:
        return raw, raw
    name, addr = pairs[0]
    return addr or raw, name or addr or raw


def _parse_date(message: EmailMessage) -> datetime | None:
    raw = message.get("Date")
    if not raw:
        return None
    try:
        return parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        LOGGER.debug("Date illisible: %r", raw)
        return None


def html_body_to_markdown(html: str) -> str:
    """Nettoie le HTML d'un mail puis le convertit en Markdown lisible."""
    soup = BeautifulSoup(html, "lxml")
    for tag_name in _DROP_TAGS:
        for tag in soup.find_all(tag_name):
            tag.decompose()
    for tag in soup.find_all(attrs={"style": True}):
        del tag["style"]
    markdown = html_to_markdown(
        str(soup),
        heading_style="ATX",
        bullets="-",
        strip=["span", "font"],
    )
    return normalize_markdown(markdown)


def normalize_markdown(text: str) -> str:
    cleaned = (text or "").replace("\r\n", "\n").replace("‌", "").replace("\xa0", " ")
    cleaned = _TRAILING_SPACES.sub("\n", cleaned)
    cleaned = _BLANK_LINES.sub("\n\n", cleaned)
    return cleaned.strip()


def _decode_payload(part: EmailMessage) -> str:
    payload = part.get_payload(decode=True) or b""
    charset = part.get_content_charset() or "utf-8"
    try:
        return payload.decode(charset, errors="replace")
    except LookupError:
        return payload.decode("utf-8", errors="replace")


def _iter_parts(message: EmailMessage) -> Iterable[EmailMessage]:
    if message.is_multipart():
        for part in message.walk():
            if not part.is_multipart():
                yield part
    else:
        yield message


def _extract_body(message: EmailMessage) -> tuple[str, str]:
    """Privilégie la partie HTML (plus riche), retombe sur le texte brut."""
    html_parts: list[str] = []
    text_parts: list[str] = []

    for part in _iter_parts(message):
        content_type = part.get_content_type()
        disposition = (part.get_content_disposition() or "").lower()
        if disposition == "attachment":
            continue
        if content_type == "text/html":
            html_parts.append(_decode_payload(part))
        elif content_type == "text/plain":
            text_parts.append(_decode_payload(part))

    if html_parts:
        return html_body_to_markdown("\n".join(html_parts)), "html"
    if text_parts:
        return normalize_markdown("\n".join(text_parts)), "text"
    return "", "empty"


def _extract_attachments(message: EmailMessage) -> list[Attachment]:
    attachments: list[Attachment] = []
    for index, part in enumerate(_iter_parts(message)):
        disposition = (part.get_content_disposition() or "").lower()
        filename = _decode(part.get_filename())
        if disposition != "attachment" and not filename:
            continue
        payload = part.get_payload(decode=True)
        if not payload:
            continue
        name = filename or f"piece-jointe-{index}"
        attachments.append(
            Attachment(filename=name, content_type=part.get_content_type(), payload=payload)
        )
    return attachments


def parse_eml(path: Path) -> ParsedEmail:
    """Parse un fichier `.eml` exporté depuis Thunderbird."""
    with path.open("rb") as handle:
        message = email.message_from_binary_file(handle, policy=email.policy.default)

    sender, sender_name = _sender(message)
    body, body_format = _extract_body(message)

    return ParsedEmail(
        subject=_decode(message.get("Subject")) or "Sans objet",
        sender=sender,
        sender_name=sender_name,
        recipients=_addresses(message, "To"),
        cc=_addresses(message, "Cc"),
        date=_parse_date(message),
        message_id=_decode(message.get("Message-ID")),
        body_markdown=body,
        body_format=body_format,
        attachments=_extract_attachments(message),
    )
