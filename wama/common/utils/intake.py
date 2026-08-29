"""
intake — « Que peut faire WAMA de ce fichier ? » : l'index inverse type → capacités (COMMUN).

Généralisation serveur du menu « Envoyer vers » du filemanager, pour l'assistant
(`WAMA_LLM.md §Intake universel` — plan amendé par l'instance portage et confronté au réel
le 2026-08-29). PURE COMPOSITION de déclarations existantes, aucun vocabulaire nouveau :

  • la cible n'est jamais « une app » à plat mais « quel PORT de quelle app »
    (`studio_node_ports` — groupe `travail`/`reference`) : composer par `input_types`/
    `input_extensions` est FAUX à 100 % sur .txt/.md/.csv (l'homonyme `text` y désigne le
    PROMPT, et les extensions de composer/imager/synthesizer sont des formats de LOT) ;
  • un fichier texte sans port n'est pas « aucune cible » : c'est le déclencheur des
    détecteurs de LOT (`batch_parsers`) et de la question à poser à l'utilisateur ;
  • les jumelles bac à sable sont exclues (`non_sandbox_apps` — `converter_01` remonte
    dans les trois voies sinon, mesuré) ;
  • les MONDES se déclarent ici par sonde (`register_intake_probe`, appelé depuis leur
    `apps.py` — même sens que `lecteurs_data` au registre des registres) : ce module ne
    cite JAMAIS un monde en dur (doctrine des mondes, CLAUDE.md) ;
  • PAS de couche modèles : il n'existe AUCUNE correspondance déclarée entre catégorie de
    fichier et ids d'`INPUT_TYPES` — l'inventer ici créerait le vocabulaire parallèle que
    le plan interdit. Le rétrécissement par modèle reste dans l'app, au lancement
    (`INPUT_MODEL_MATCHING.md`).
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

#: Sondes déclarées par les mondes : clé → fn(path) -> dict | None (None = pas concerné).
#: Chaque sonde est fail-safe à l'appel : une panne d'un monde ne casse pas l'intake.
INTAKE_PROBES: dict = {}

#: Octets lus au plus pour les sniffs de contenu (lot, manifeste) — l'intake reste léger.
_SNIFF_MAX_BYTES = 256_000


def register_intake_probe(key: str, fn) -> None:
    """Un monde déclare sa sonde d'intake (appelé depuis son `apps.py:ready()`)."""
    INTAKE_PROBES[key] = fn


def _ports_for_category(category: str) -> list:
    """Tous les ports FICHIER (travail/référence) des apps réelles qui acceptent cette nature."""
    from wama.common.app_registry import APP_CATALOG, studio_node_ports
    from wama.common.sandbox import non_sandbox_apps

    cibles = []
    for app_id in sorted(non_sandbox_apps(APP_CATALOG)):
        ports = studio_node_ports(app_id) or {}
        for port in ports.get('inputs', []):
            if port.get('group') == 'prompt':
                continue  # le port prompt n'est pas un port de FICHIER
            if category in (port.get('types') or []):
                cibles.append({
                    'app': app_id,
                    'port': port.get('id'),
                    'group': port.get('group'),
                    'label': port.get('label', ''),
                })
    return cibles


def _sniff_batch(path: Path) -> dict | None:
    """Le fichier ressemble-t-il à un LOT ? (formats de `BATCH_FORMAT.md`, détecteurs communs)."""
    from wama.common.utils.batch_parsers import (
        SUPPORTED_BATCH_EXTENSIONS,
        extract_batch_file_text,
        is_csv_header_batch,
        is_structured_batch_text,
        is_unified_batch_text,
    )

    ext = path.suffix.lstrip('.').lower()
    if ext not in [e.lstrip('.') for e in SUPPORTED_BATCH_EXTENSIONS]:
        return None
    try:
        text = extract_batch_file_text(str(path))[:_SNIFF_MAX_BYTES]
    except Exception:
        logger.debug('[intake] extraction batch impossible : %s', path, exc_info=True)
        return None

    forme = None
    if is_unified_batch_text(text):
        forme = 'unified'
    elif is_csv_header_batch(text):
        forme = 'csv_header'
    elif is_structured_batch_text(text):
        forme = 'structured'
    return {'looks_like_batch': forme is not None, 'format': forme}


def _sniff_manifest(path: Path) -> dict | None:
    """Le fichier est-il un manifeste WAMA (JSON, `kind` parmi les kinds enregistrés) ?"""
    if path.suffix.lower() != '.json':
        return None
    try:
        with open(path, 'r', encoding='utf-8') as fh:
            data = json.loads(fh.read(_SNIFF_MAX_BYTES))
    except Exception:
        return None
    kind = (data or {}).get('kind') if isinstance(data, dict) else None
    if not kind:
        return None
    from wama.common.manifests import MANIFEST_KINDS
    if kind not in MANIFEST_KINDS:
        return {'kind': kind, 'registered': False}
    # ⚠ La PORTE d'ingestion n'existe pas encore (`ingest()` sans appelant, mesuré 29/08) :
    # l'intake SAIT le reconnaître, il ne sait pas encore le faire entrer.
    return {'kind': kind, 'registered': True, 'ingestable': False}


def _asset_types_for(path: Path, category: str) -> list:
    """Rôles médiathèque candidats : catégorie compatible ET extension admise par le rôle."""
    from wama.media_library.models import ALLOWED_EXTENSIONS, ASSET_TYPE_CATEGORY

    ext = path.suffix.lstrip('.').lower()
    return sorted(
        at for at, cat in ASSET_TYPE_CATEGORY.items()
        if cat == category and ext in (ALLOWED_EXTENSIONS.get(at) or [])
    )


def capabilities_for_path(path) -> dict:
    """
    Chemin de fichier → cibles typées AVEC leur rôle, composées des déclarations.

    Retour :
      {'category', 'ports': [{'app','port','group','label'}], 'batch': {...}|None,
       'manifest': {...}|None, 'asset_types': [...], 'probes': {monde: {...}}}

    Ne touche PAS au contenu média (pas de ffprobe ici — `probe_media` reste disponible
    pour un examen profond) ; lit au plus quelques centaines de Ko pour les sniffs texte.
    """
    from wama.common.app_registry import category_of_path

    p = Path(path)
    category = category_of_path(str(p))

    result = {
        'category': category,
        'ports': _ports_for_category(category),
        'batch': _sniff_batch(p) if p.exists() else None,
        'manifest': _sniff_manifest(p) if p.exists() else None,
        'asset_types': _asset_types_for(p, category),
        'probes': {},
    }

    for key, fn in INTAKE_PROBES.items():
        try:
            hit = fn(str(p))
        except Exception:
            logger.debug('[intake] sonde %s en échec sur %s', key, p, exc_info=True)
            hit = None
        if hit:
            result['probes'][key] = hit

    return result
