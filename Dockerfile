# syntax=docker/dockerfile:1

# Image CUDA runtime : fournit les bibliothèques NVIDIA nécessaires à PyTorch.
FROM nvidia/cuda:12.1.0-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    # Modèles Surya/marker et HuggingFace mis en cache sur un volume nommé.
    HF_HOME=/models \
    TORCH_HOME=/models/torch \
    TORCH_DEVICE=cuda

# Dépendances système : Python, Poppler (PDF), Tesseract (OCR fr/en), libGL (OpenCV).
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3.10 \
        python3-pip \
        python3-dev \
        poppler-utils \
        tesseract-ocr \
        tesseract-ocr-fra \
        tesseract-ocr-eng \
        libgl1 \
        libglib2.0-0 \
        fonts-dejavu-core \
        ca-certificates \
        curl \
    && rm -rf /var/lib/apt/lists/* \
    && ln -sf /usr/bin/python3.10 /usr/local/bin/python \
    && ln -sf /usr/bin/python3.10 /usr/local/bin/python3

RUN python -m pip install --upgrade pip setuptools wheel

# PyTorch compilé pour CUDA 12.1, installé avant le reste pour que marker-pdf
# réutilise cette build au lieu de tirer la variante CPU par défaut.
RUN python -m pip install \
        --index-url https://download.pytorch.org/whl/cu121 \
        torch==2.4.1 torchvision==0.19.1

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN python -m pip install -r /app/requirements.txt

COPY processor.py /app/processor.py
COPY ingest_mail /app/ingest_mail

# Points de montage par défaut (redéfinis par docker-compose via le .env).
ENV SOURCE_DIR=/data/source \
    DEST_DIR=/data/dest \
    STATE_FILE=/data/state/processed.json
RUN mkdir -p /data/source /data/dest /data/state /models

ENTRYPOINT ["python", "/app/processor.py"]
