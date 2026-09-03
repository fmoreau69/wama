"""
Poids d'un modèle rangés dans SON dossier — pour les libs qui n'acceptent pas `cache_dir=`.

LA RÈGLE (une seule, `ROADMAP §5b`) : **le modèle est routé explicitement vers son dossier,
l'environnement n'est JAMAIS touché.** Elle a deux idiomes, et le choix n'est pas une
préférence — il est imposé par la lib :

    la lib accepte `cache_dir=`   →  `from_pretrained(hf_id, cache_dir=<dossier>)`
                                     (transformers, diffusers, pyannote… : la majorité)
    la lib ne l'accepte pas       →  CE MODULE : on télécharge nous-mêmes DANS le dossier,
                                     et on donne à la lib un CHEMIN LOCAL.

⚠ Pourquoi ce module ne remplace PAS `cache_dir=` là où il existe : `from_pretrained` gère la
révision, la reprise de téléchargement, le mode hors-ligne et la disposition de cache HF
(blobs/refs/snapshots). Le remplacer partout, ce serait réimplémenter moins bien ce que la
lib fait déjà. *Une règle, deux idiomes.*

⚠ Ce module REMPLACE la bascule d'environnement (`hf_cache_scope`) partout où la lib accepte
un chemin — mesuré le 2026-09-03 : c'est le cas de kokoro (`KModel(config=…, model=…)`) et de
sam3 (`build_sam3_image_model(checkpoint_path=…, load_from_HF=False)`), les deux seuls
adopteurs de la bascule. Différence décisive : le scope restaure l'environnement, **jamais les
fichiers** — il laisse donc les sous-dépendances dans le dossier du modèle. Ici, rien ne sort
de sa place, parce que rien n'est détourné.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional, Sequence

logger = logging.getLogger(__name__)


def poids_locaux(hf_id: str, dossier: str | Path, *,
                 patterns: Optional[Sequence[str]] = None,
                 token: Optional[str] = None,
                 revision: Optional[str] = None) -> str:
    """Chemin LOCAL des poids de `hf_id`, garantis présents sous `dossier`.

    Args:
        hf_id    : dépôt HuggingFace (`bosonai/higgs-audio-v2-...`).
        dossier  : dossier de famille du modèle (`AI-models/models/speech/higgs`), celui-là
                   même qu'on passerait à `cache_dir=`.
        patterns : `allow_patterns` — ne tirer que ce dont on a besoin (un jeu cohérent,
                   jamais le dépôt entier ; même esprit que l'installeur).
        token    : jeton HF si le dépôt est privé/gated.
        revision : révision épinglée si on en veut une.

    Rend le chemin du snapshot. **Aucune variable d'environnement n'est touchée.**

    Hors-ligne d'abord : on tente une résolution PUREMENT locale, et on ne va au réseau que
    si les poids manquent. Sans cela, un modèle déjà présent ferait quand même un aller-retour
    HTTP à chaque chargement — et un incident réseau ferait échouer un chargement qui n'avait
    besoin de rien.
    """
    from huggingface_hub import snapshot_download

    dossier = str(dossier)
    Path(dossier).mkdir(parents=True, exist_ok=True)
    commun = dict(repo_id=hf_id, cache_dir=dossier, revision=revision)
    if patterns:
        commun['allow_patterns'] = list(patterns)

    try:
        return snapshot_download(local_files_only=True, **commun)
    except Exception:
        logger.info('[hf_weights] %s absent de %s — téléchargement', hf_id, dossier)
    return snapshot_download(token=token, **commun)
