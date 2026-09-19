"""L'ANATOMIE d'un modèle composé — ses composants, DÉRIVÉS de ce qui est sur le disque.

POURQUOI CETTE BRIQUE (2026-09-20, demande de Fabien : « il faut que ce soit fonctionnel sans
passer par Claude, a minima avec un petit LLM local »)
======================================================================================
Le poids PAR COMPOSANT (`model_installer.components_for_spec`) et les deux empreintes de la
décision A (somme = plein GPU, plus gros composant = déchargement) ont besoin de savoir QUELS
fichiers comptent. Cette réponse était écrite À LA MAIN : 28 déclarations posées le 19/09 dans
les `model_config` des apps. Or pour un pipeline diffusers elle est ENTIÈREMENT DÉRIVABLE, et la
découverte ouvrait déjà le fichier qui la porte — `model_registry._overlay_engines_derived_from_disk`
lit `model_index.json` pour n'y prendre que `_class_name`, à trois lignes de la liste des rôles.

*Une déclaration manuelle qu'une mesure peut produire est une dette, pas une information.*

CE QUE LA DÉRIVATION MESURE, ET NE DEVINE PAS
=============================================
Relevé le 2026-09-20 sur les pipelines installés du parc, et chaque règle vient d'un cas :
  * un rôle est une clé de `model_index.json` dont la valeur est une paire `[lib, classe]` —
    `boundary_ratio`, `expand_timesteps`, `add_watermarker` sont des RÉGLAGES, pas des
    composants, et FastWan porte `transformer_2: [None, None]`, une place VIDE ;
  * un rôle ne compte que s'il a VRAIMENT des poids dans son sous-dossier : `scheduler`,
    `tokenizer`, `feature_extractor` n'en ont aucun. On ne les écarte donc pas par une liste de
    noms qu'il faudrait tenir à jour — on regarde le disque ;
  * `safety_checker` est DÉCLARÉ par le `model_index.json` de SD 1.5 et n'a AUCUN poids installé :
    une liste de noms l'aurait gardé, la mesure l'écarte ;
  * le motif vient des VRAIS noms de fichiers, jamais d'une convention supposée. Mesuré : SDXL
    n'a sur ce disque que ses variantes `.fp16` (`unet/diffusion_pytorch_model.fp16.safetensors`)
    — une déclaration écrite depuis la carte HF (la pleine précision) désigne donc des fichiers
    ABSENTS de l'installation, et pèse 9,56 Go là où la machine charge 4,78.
    *Le dépôt dit ce qu'on PEUT tirer, le snapshot dit ce qu'on a TIRÉ.*

⚠ CE QU'ELLE NE FAIT PAS : deviner un pipeline sans `model_index.json` (un modèle monobloc n'a
pas d'anatomie à décrire), lire les précisions (un nom de fichier n'est pas une preuve de dtype —
c'est `prospector.precision_of_files` qui ouvre les en-têtes), ni ÉCRASER une anatomie déclarée :
une déclaration à la main reste l'autorité, parce qu'elle seule peut trancher ce que les fichiers
ne disent pas (deux jeux de shards concurrents sous le même nom, cas `genmo/mochi-1-preview`).
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

#: `nom-00002-of-00005.safetensors` → le tronc `nom` et son extension. Un jeu de shards se
#: désigne par UN motif, pas par N noms.
_SHARD_RE = re.compile(r'^(?P<base>.+?)-\d{4,6}-of-\d{4,6}(?P<ext>\.[A-Za-z0-9]+)$')


def _is_component_entry(value) -> bool:
    """Cette entrée de `model_index.json` décrit-elle un COMPOSANT ?

    Une paire `[librairie, classe]` en décrit un. Un réglage (`True`, `None`, un nombre) et une
    place vide (`[None, None]`, cas `transformer_2` de FastWan) n'en décrivent aucun. On ne liste
    pas les rôles à exclure : c'est la forme de la valeur, puis la PRÉSENCE DE POIDS, qui tranche.
    """
    return (isinstance(value, (list, tuple)) and len(value) == 2
            and all(isinstance(x, str) and x for x in value))


def _weight_exts() -> tuple:
    """Extensions de POIDS — lues chez `prospector`, jamais recopiées.

    Elles vivent là-bas avec la dérivation qui les emploie, et une seconde liste divergerait :
    `.onnx` y a été ajouté le 2026-09-19 parce que son absence faisait peser ZÉRO un modèle dont
    l'ONNX EST le modèle.
    """
    try:
        from wama.model_manager.services.prospector import _WEIGHT_EXTS
        return _WEIGHT_EXTS
    except Exception:                                   # hors Django / import partiel
        return ('.safetensors', '.bin', '.pt', '.pth', '.gguf', '.onnx')


def pattern_for_files(role: str, filenames) -> str | None:
    """Motif glob désignant les poids de `role`, DÉRIVÉ de ses vrais fichiers — None si aucun.

    Un fichier unique donne son nom EXACT — donc la variante réellement installée (`.fp16` si
    c'est elle qui est là). Un jeu de shards donne `role/<tronc>-*<extension>`. Si plusieurs jeux
    coexistent, on retient le plus COMPLET (à égalité, le premier par ordre alphabétique :
    arbitrage stable) et on le SIGNALE au journal, parce que ce cas mérite une déclaration à la
    main — c'est celui de `genmo/mochi-1-preview`, dont seul l'`index.json` dit quel jeu charger.
    """
    names = sorted(filenames or [])
    if not names:
        return None
    sets: dict[tuple, list] = {}
    for name in names:
        m = _SHARD_RE.match(name)
        key = (m.group('base'), m.group('ext')) if m else (name, '')
        sets.setdefault(key, []).append(name)
    if len(sets) > 1:
        logger.info("[anatomie] %s : %d jeux de poids concurrents (%s) — le plus complet est "
                    "retenu ; une déclaration à la main tranche mieux", role, len(sets),
                    ', '.join(sorted(f"{b}{e or ''}" for b, e in sets)))
    (base, ext), members = max(sets.items(), key=lambda kv: (len(kv[1]), -ord(kv[0][0][0])))
    if len(members) == 1 and not ext:
        return f"{role}/{members[0]}"
    return f"{role}/{base}-*{ext}"


def components_from_snapshot(root) -> list:
    """`[{'role', 'pattern'}]` d'un pipeline diffusers INSTALLÉ, ou `[]`.

    `root` : un dossier de snapshot, ou un dossier `models--…` dont on prend la révision — celui
    que la découverte tient déjà (`extra_info['path']`, ou l'index `installed_snapshots()` pour une
    ligne d'app, qui n'en porte pas). Aucun réseau, aucun chargement, aucun poids ouvert.

    `[]` n'est PAS un échec : c'est la réponse pour un modèle monobloc (pas de `model_index.json`),
    pour un dossier illisible, et pour un pipeline dont aucun composant ne porte de poids.
    L'appelant ne doit donc rien écrire dans ce cas — surtout pas un `{}` qui effacerait une
    anatomie connue.
    """
    try:
        base_dir = Path(root)
        revisions = sorted(base_dir.glob('snapshots/*')) or ([base_dir] if base_dir.is_dir() else [])
    except (OSError, TypeError) as e:
        logger.debug('[anatomie] racine illisible (%s) : %s', root, e)
        return []
    exts = _weight_exts()
    for revision in revisions:
        index = revision / 'model_index.json'
        if not index.is_file():
            continue
        try:
            declared = json.loads(index.read_text(encoding='utf-8'))
        except (OSError, ValueError) as e:
            logger.debug('[anatomie] %s illisible : %s', index, e)
            return []
        parts = []
        for role, value in sorted(declared.items()):
            if role.startswith('_') or not _is_component_entry(value):
                continue
            folder = revision / role
            if not folder.is_dir():
                continue
            try:
                weights = [p.name for p in folder.iterdir()
                           if p.is_file() and p.suffix.lower() in exts]
            except OSError:                              # lien que cet OS ne sait pas suivre
                continue
            pattern = pattern_for_files(role, weights)
            if pattern:
                parts.append({'role': role, 'pattern': pattern})
        return parts
    return []


def model_composition(engine: str, components) -> dict:
    """`composition` au schéma de `manifests.builtin.model` — le CONSTRUCTEUR partagé.

    Écrit le 2026-09-20 après un relevé qui n'a trouvé AUCUN constructeur commun : le validateur
    et la projection vivaient dans `manifests/builtin/model.py`, mais chaque app avait son propre
    assembleur (`imager._pipeline_composition`, `composer._audiocraft_composition`) ou ses dicts
    littéraux (synthesizer, transcriber, neuf endroits du registre). Une forme assemblée à dix
    endroits finit par diverger d'un champ.

    ⚠ NOMMÉE `model_composition` ET NON `pipeline_composition` (question de Fabien, le jour même) :
    « pipeline » désigne DÉJÀ trois choses dans ce dépôt — le PROCESS WAMA (kind de manifeste
    `pipeline`, nœuds + liens, `ROUTE §10.6`), la CLASSE diffusers d'un modèle composé
    (`model_index.json._class_name`, rangée en `extra_info['pipeline_class']`), et la clé
    `'pipeline': 'sdxl'` des configs imager qui nomme une famille de chargeur. Une composition
    n'est PAS un process : c'est l'anatomie INTERNE d'un modèle que l'utilisateur choisit d'un
    seul geste. Ajouter un quatrième sens au mot aurait coûté plus que le nom ne rapporte.
    """
    if components:
        return {'components': [dict(c) for c in components],
                'runtime': {'engine': engine}}
    return {'runtime': {'engine': engine}} if engine else {}
