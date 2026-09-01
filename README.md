# Injest-Mail-to-md

Pipeline local et conteneurisé (Docker + GPU CUDA) qui transforme des e-mails
(`.eml` exportés depuis Thunderbird) et leurs pièces jointes (PDF, images) en
fichiers Markdown propres, prêts à être ingérés puis classés par Claude Code
dans un coffre Obsidian.

```
Thunderbird ──▶ SOURCE_DIR ──▶ [ Docker + CUDA ] ──▶ DEST_DIR (Inbox Obsidian) ──▶ LLM de classement
   .eml / PJ                    marker · Surya                 .md + frontmatter YAML
```

## Ce que fait le pipeline

| Entrée | Traitement | Sortie |
| --- | --- | --- |
| `.eml` | Décodage des en-têtes MIME, extraction Expéditeur / Date / Sujet / Destinataires, conversion du corps HTML (ou texte) en Markdown via `markdownify` | `DEST_DIR/AAAA-MM-JJ-sujet.md` avec frontmatter YAML |
| Pièces jointes du `.eml` | Extraction, conversion PDF/image, lien Obsidian `[[...]]` depuis la note du mail | `DEST_DIR/attachments/…md` |
| `.pdf` déposé directement | `marker-pdf` (Surya) sur GPU : layout, tableaux, OCR | `DEST_DIR/attachments/…md` |
| Images (`.png`, `.jpg`, `.tiff`…) | Enveloppe PDF puis marker ; repli OCR Tesseract | `DEST_DIR/attachments/…md` |

Chaque fichier traité est enregistré (empreinte SHA-256) dans un journal :
relancer le conteneur ne recrée pas les notes déjà produites.

## Prérequis

- Docker et Docker Compose v2
- Un GPU NVIDIA + pilote récent + [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html)
- Vérification rapide :
  ```bash
  docker run --rm --gpus all nvidia/cuda:12.1.0-base-ubuntu22.04 nvidia-smi
  ```

Sans GPU, le pipeline fonctionne quand même : mettez `TORCH_DEVICE=cpu` (plus lent).

## Installation

```bash
git clone <ce-dépôt>
cd Injest-Mail-to-md
cp .env.example .env
$EDITOR .env          # renseigner SOURCE_DIR et DEST_DIR
docker compose build  # ~10 min la première fois (PyTorch CUDA + marker)
```

## Utilisation

Passage unique (traite tout ce qui est présent, puis s'arrête) :

```bash
docker compose run --rm ingest-mail-to-md
```

Surveillance continue (le conteneur reste actif et traite les nouveaux fichiers) :

```bash
# dans .env : WATCH=true et RESTART_POLICY=unless-stopped
docker compose up -d
docker compose logs -f
```

Options ponctuelles en ligne de commande :

```bash
docker compose run --rm ingest-mail-to-md --reprocess      # retraiter tout
docker compose run --rm ingest-mail-to-md --no-marker      # PyMuPDF/Tesseract seuls
docker compose run --rm ingest-mail-to-md --device cpu     # forcer le CPU
docker compose run --rm ingest-mail-to-md --log-level DEBUG
```

> Le premier lancement télécharge les modèles Surya (~2 Go). Ils sont conservés
> dans le volume `ingest-models`, les démarrages suivants sont immédiats.

### Côté Thunderbird

Sélectionnez vos messages puis **Fichier ▸ Enregistrer sous ▸ Fichier** (`.eml`)
dans `SOURCE_DIR`. Les pièces jointes internes aux `.eml` sont extraites
automatiquement : inutile de les exporter séparément. Vous pouvez aussi déposer
directement des PDF ou des images dans `SOURCE_DIR`.

## Configuration (`.env`)

| Variable | Défaut | Rôle |
| --- | --- | --- |
| `SOURCE_DIR` | — | Dossier surveillé sur l'hôte (`.eml`, PDF, images) |
| `DEST_DIR` | — | Inbox du coffre Obsidian sur l'hôte |
| `TORCH_DEVICE` | `cuda` | `cuda` ou `cpu` |
| `WATCH` | `false` | Surveillance continue |
| `POLL_INTERVAL` | `30` | Intervalle de scrutation (s) en mode `WATCH` |
| `RESTART_POLICY` | `no` | `unless-stopped` pour un service permanent |
| `OCR_LANGS` | `fra+eng` | Langues Tesseract (fallback OCR) |
| `DELETE_AFTER` | `false` | Supprimer la source après conversion réussie |
| `REPROCESS` | `false` | Ignorer le journal et tout retraiter |
| `EXTRACT_ATTACHMENTS` | `true` | Convertir les PJ contenues dans les `.eml` |
| `ATTACHMENTS_SUBDIR` | `attachments` | Sous-dossier des notes de PJ |
| `MAX_FILE_MB` | `200` | Taille maximale d'un fichier traité |
| `LOG_LEVEL` | `INFO` | Verbosité |

## Exemple de note produite

```markdown
---
title: Confirmation de commande n°8821
type: email
from: no-reply@boutique.fr
from_name: Boutique
to:
- moi@example.org
date: '2025-08-26T09:12:00+02:00'
source_file: commande.eml
body_format: html
attachments:
- facture.pdf
tags:
- inbox
- email
ingested_at: '2025-08-26T10:02:11+00:00'
---

# Confirmation de commande n°8821

Votre commande **#8821** est confirmée.

## Pièces jointes

- `facture.pdf` → [[2025-08-26-confirmation-de-commande-n8821-pj-facture]]
```

## Étape suivante : le classement par LLM

Le pipeline s'arrête volontairement à l'Inbox. Le tri, le nettoyage éditorial et
le rangement thématique sont confiés à Claude Code lancé dans le coffre : le
prompt prêt à l'emploi est dans [`prompts/classement-obsidian.md`](prompts/classement-obsidian.md).
Le frontmatter généré ici (expéditeur, date, type, source) lui sert de matière
première.

## Architecture du code

```
processor.py              Entrypoint CLI (arguments, logs, diagnostic CUDA)
ingest_mail/
  config.py               Réglages issus des variables d'environnement
  eml.py                  Parsing .eml : en-têtes, corps HTML/texte, pièces jointes
  documents.py            PDF/images -> Markdown (marker GPU, repli PyMuPDF/Tesseract)
  frontmatter.py          Génération du frontmatter YAML
  state.py                Journal SHA-256 des fichiers déjà traités
  pipeline.py             Orchestration, nommage des notes, mode surveillance
  utils.py                Slugs, hachage, détection de type
tests/                    Tests unitaires (sans GPU ni modèles)
```

## Développement et tests

```bash
python -m pip install -r requirements.txt   # ou seulement les libs légères
python -m pytest tests -q
SOURCE_DIR=./data/in DEST_DIR=./data/out USE_MARKER=false python processor.py
```

Les tests n'ont besoin ni de GPU ni de modèles : la conversion de documents y est
remplacée par un stub, `USE_MARKER=false` suffit pour un essai local sur `.eml`.

## Dépannage

| Symptôme | Piste |
| --- | --- |
| `could not select device driver "nvidia"` | NVIDIA Container Toolkit absent ou non configuré |
| Log « CUDA demandé mais indisponible » | Le conteneur ne voit pas le GPU : vérifier `deploy.resources` et le pilote |
| `marker indisponible … repli PyMuPDF` | VRAM insuffisante ou modèles non téléchargés ; le pipeline continue en CPU |
| Notes non regénérées | Comportement normal (journal) : utiliser `--reprocess` |
| PDF scanné mal transcrit | Installer/étendre `OCR_LANGS`, ou augmenter la VRAM disponible pour marker |
