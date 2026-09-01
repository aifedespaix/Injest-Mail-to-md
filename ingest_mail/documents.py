"""Conversion PDF / images -> Markdown.

Stratégie :
1. `marker-pdf` (Surya) sur GPU quand il est disponible : layout, tableaux, OCR.
2. Repli PyMuPDF (texte natif) puis Tesseract (OCR) si marker est absent ou échoue.
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass
from pathlib import Path

from .eml import normalize_markdown
from .utils import IMAGE_SUFFIXES

LOGGER = logging.getLogger(__name__)

# En dessous de ce volume de texte, un PDF est considéré comme scanné -> OCR.
_MIN_NATIVE_TEXT_CHARS = 40


@dataclass(slots=True)
class ConversionResult:
    markdown: str
    engine: str
    pages: int = 0


class DocumentConverter:
    """Convertit un PDF ou une image en Markdown, avec chargement paresseux des modèles."""

    def __init__(self, device: str = "cuda", use_marker: bool = True, ocr_langs: str = "fra+eng") -> None:
        self.device = device
        self.use_marker = use_marker
        self.ocr_langs = ocr_langs
        self._marker_converter = None
        self._marker_unavailable = False

    # ------------------------------------------------------------------ marker
    def _get_marker(self):
        """Instancie le convertisseur marker une seule fois (chargement des modèles coûteux)."""
        if self._marker_converter is not None or self._marker_unavailable:
            return self._marker_converter
        if not self.use_marker:
            self._marker_unavailable = True
            return None
        try:
            from marker.converters.pdf import PdfConverter
            from marker.models import create_model_dict

            LOGGER.info("Chargement des modèles marker/Surya sur %s…", self.device)
            self._marker_converter = PdfConverter(artifact_dict=create_model_dict())
            LOGGER.info("Modèles marker prêts.")
        except Exception as exc:  # dépendance absente, VRAM insuffisante, etc.
            LOGGER.warning("marker indisponible (%s) — repli PyMuPDF/Tesseract.", exc)
            self._marker_unavailable = True
        return self._marker_converter

    def _convert_with_marker(self, pdf_path: Path) -> ConversionResult | None:
        converter = self._get_marker()
        if converter is None:
            return None
        try:
            from marker.output import text_from_rendered

            rendered = converter(str(pdf_path))
            text, _, _images = text_from_rendered(rendered)
            markdown = normalize_markdown(text)
            if markdown:
                return ConversionResult(markdown=markdown, engine="marker")
            LOGGER.warning("marker n'a produit aucun texte pour %s.", pdf_path.name)
        except Exception as exc:
            LOGGER.warning("Échec marker sur %s (%s) — repli.", pdf_path.name, exc)
        return None

    # ---------------------------------------------------------------- fallbacks
    def _convert_with_pymupdf(self, pdf_path: Path) -> ConversionResult | None:
        try:
            import fitz  # PyMuPDF
        except ImportError:
            LOGGER.error("PyMuPDF absent : impossible de convertir %s.", pdf_path.name)
            return None

        chunks: list[str] = []
        page_count = 0
        try:
            with fitz.open(pdf_path) as document:
                page_count = document.page_count
                for index, page in enumerate(document, start=1):
                    text = page.get_text("text").strip()
                    if len(text) < _MIN_NATIVE_TEXT_CHARS:
                        text = self._ocr_pixmap(page) or text
                    if text:
                        chunks.append(f"## Page {index}\n\n{text}")
        except Exception as exc:
            LOGGER.error("Échec PyMuPDF sur %s : %s", pdf_path.name, exc)
            return None

        markdown = normalize_markdown("\n\n".join(chunks))
        if not markdown:
            return None
        return ConversionResult(markdown=markdown, engine="pymupdf", pages=page_count)

    def _ocr_pixmap(self, page) -> str:
        """OCR d'une page PDF rendue en image (200 dpi ≈ bon compromis qualité/temps)."""
        try:
            import pytesseract
            from PIL import Image

            pixmap = page.get_pixmap(dpi=200)
            image = Image.open(io.BytesIO(pixmap.tobytes("png")))
            return pytesseract.image_to_string(image, lang=self.ocr_langs).strip()
        except Exception as exc:
            LOGGER.debug("OCR page impossible : %s", exc)
            return ""

    def _image_to_pdf(self, image_path: Path, target: Path) -> Path | None:
        """marker consomme du PDF : on enveloppe l'image avant de la lui passer."""
        try:
            from PIL import Image

            with Image.open(image_path) as image:
                image.convert("RGB").save(target, "PDF", resolution=200.0)
            return target
        except Exception as exc:
            LOGGER.warning("Conversion image->PDF impossible pour %s : %s", image_path.name, exc)
            return None

    def _ocr_image(self, image_path: Path) -> ConversionResult | None:
        try:
            import pytesseract
            from PIL import Image

            with Image.open(image_path) as image:
                text = pytesseract.image_to_string(image, lang=self.ocr_langs)
        except Exception as exc:
            LOGGER.error("OCR impossible sur %s : %s", image_path.name, exc)
            return None

        markdown = normalize_markdown(text)
        if not markdown:
            return None
        return ConversionResult(markdown=markdown, engine="tesseract", pages=1)

    # ------------------------------------------------------------------- public
    def convert(self, path: Path, workdir: Path | None = None) -> ConversionResult:
        """Convertit un fichier en Markdown ; renvoie un résultat vide plutôt qu'une exception."""
        suffix = path.suffix.lower()

        if suffix in IMAGE_SUFFIXES:
            scratch = (workdir or path.parent) / f"{path.stem}.marker.pdf"
            pdf_path = self._image_to_pdf(path, scratch)
            try:
                if pdf_path is not None:
                    result = self._convert_with_marker(pdf_path)
                    if result is not None:
                        return result
            finally:
                if pdf_path is not None and pdf_path.exists():
                    pdf_path.unlink(missing_ok=True)
            return self._ocr_image(path) or ConversionResult(markdown="", engine="none")

        result = self._convert_with_marker(path)
        if result is not None:
            return result
        return self._convert_with_pymupdf(path) or ConversionResult(markdown="", engine="none")
