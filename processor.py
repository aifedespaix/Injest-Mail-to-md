#!/usr/bin/env python3
"""Point d'entrée du conteneur : convertit e-mails et pièces jointes en Markdown.

Usage :
    python processor.py                 # un passage, puis sortie
    python processor.py --watch         # surveillance continue de SOURCE_DIR
    python processor.py --reprocess     # ignore le journal et retraite tout
"""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import replace

from ingest_mail.config import Settings, load_settings
from ingest_mail.pipeline import Pipeline


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stdout,
    )
    # Les modèles de marker sont bavards au chargement.
    logging.getLogger("PIL").setLevel(logging.WARNING)
    logging.getLogger("transformers").setLevel(logging.ERROR)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="E-mails et pièces jointes -> Markdown Obsidian")
    parser.add_argument("--watch", action="store_true", help="surveiller SOURCE_DIR en continu")
    parser.add_argument("--once", action="store_true", help="forcer un passage unique (ignore WATCH)")
    parser.add_argument("--reprocess", action="store_true", help="retraiter les fichiers déjà connus")
    parser.add_argument("--no-marker", action="store_true", help="désactiver marker (PyMuPDF/Tesseract seuls)")
    parser.add_argument("--device", help="forcer le device torch (cuda, cpu)")
    parser.add_argument("--log-level", help="DEBUG, INFO, WARNING, ERROR")
    return parser.parse_args(argv)


def build_settings(args: argparse.Namespace) -> Settings:
    settings = load_settings()
    overrides: dict = {}
    if args.reprocess:
        overrides["reprocess"] = True
    if args.no_marker:
        overrides["use_marker"] = False
    if args.device:
        overrides["torch_device"] = args.device
    if args.log_level:
        overrides["log_level"] = args.log_level.upper()
    if args.watch:
        overrides["watch"] = True
    if args.once:
        overrides["watch"] = False
    return replace(settings, **overrides) if overrides else settings


def log_environment(settings: Settings) -> None:
    logger = logging.getLogger("processor")
    logger.info("Source : %s", settings.source_dir)
    logger.info("Destination : %s", settings.dest_dir)
    logger.info("Device demandé : %s (marker=%s)", settings.torch_device, settings.use_marker)
    try:
        import torch

        available = torch.cuda.is_available()
        logger.info(
            "CUDA disponible : %s%s",
            available,
            f" ({torch.cuda.get_device_name(0)})" if available else "",
        )
        if settings.torch_device.startswith("cuda") and not available:
            logger.warning("CUDA demandé mais indisponible — bascule CPU (plus lent).")
    except ImportError:
        logger.warning("PyTorch absent : conversion en mode fallback CPU.")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    settings = build_settings(args)
    configure_logging(settings.log_level)
    log_environment(settings)

    import os

    os.environ["TORCH_DEVICE"] = settings.torch_device

    pipeline = Pipeline(settings)
    if settings.watch:
        try:
            pipeline.watch()
        except KeyboardInterrupt:
            logging.getLogger("processor").info("Arrêt demandé.")
        return 0

    report = pipeline.run_once()
    return 1 if report.failed and not (report.emails or report.documents or report.attachments) else 0


if __name__ == "__main__":
    raise SystemExit(main())
