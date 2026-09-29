"""
PROPOSITIONS de manifestes — le geste de validation qui manquait entre un rôle LLM et l'ingest.

La machine à états est écrite depuis août (`WAMA_MANIFEST_ARCHITECTURE §4`) : un manifeste
produit par « extract() ou LLM skill » entre en SANDBOX (`visibility='private'`), est VÉRIFIÉ
(diff), puis PROMU. Le magasin (`Manifest`) et `ingest()`/`promote()` existaient — sans aucun
appelant en production (mesuré le 2026-09-29). Les rôles `wama-dev-ai` déposaient leur
manifeste dans `outputs/`, d'où seul un terminal pouvait le projeter (`write_back(apply=True)`).
Ce module RELIE ce qui existait ; il n'ajoute ni état ni kind.

  propose()  → le manifeste d'un rôle entre au magasin, en bac à sable (jamais projeté) ;
  plan()     → ce que l'application FERAIT : champs comblés, divergences, dry-run du write-back ;
  apply()    → superposition, write-back RÉEL, promotion, export au corpus ;
  reject()   → la proposition sort du magasin, rien n'est défait (rien n'avait été fait).

⚠⚠ LA SUPERPOSITION NE COMBLE QUE DES VIDES (mesuré avant d'écrire une ligne). Projeter tel quel
le manifeste brut d'un LLM EFFAÇAIT des valeurs curées : `_CHAMPS_PROJETES` (kind `model`) rend
'' pour une clé absente, donc un manifeste qui ne dit rien de la licence la remettait à vide. La
proposition complète donc l'EXTRACTION courante — la règle que `provenance.set_identity` applique
déjà aux faits de la carte. Une valeur proposée qui CONTREDIT une valeur établie n'est pas
appliquée : elle est montrée dans le plan (`divergences`), et c'est l'humain qui tranche en
corrigeant la source.

`reject()` ne passe PAS par `un_ingest` : celui-ci appelle `un_write_back`, qui VIDE les champs
projetés du registre — sur une proposition jamais appliquée, il effacerait ce qu'elle n'a pas
écrit.
"""
from __future__ import annotations

import copy
import logging

from django.db import transaction

logger = logging.getLogger(__name__)

#: Visibilité d'une proposition APPLIQUÉE : elle rejoint le commun (le corpus est public).
PROMOTED_VISIBILITY = 'public'

_EMPTY = (None, '', [], {})


def _is_empty(value) -> bool:
    return value in _EMPTY


def fill_empty(current, proposed, path=''):
    """Superpose `proposed` sur `current` en ne comblant que les VIDES — récursif sur les dicts.

    Rend `(fusion, comblés, divergences)` : `comblés` = chemins écrits, `divergences` =
    `{chemin, current, proposed}` là où les deux portent une valeur différente (non appliquée).
    Une liste n'est jamais fusionnée élément par élément : elle est une valeur (des composants
    se remplacent en bloc ou pas du tout — un demi-jeu de composants serait pire que l'ancien).
    """
    if not isinstance(current, dict) or not isinstance(proposed, dict):
        if _is_empty(current) and not _is_empty(proposed):
            return copy.deepcopy(proposed), [path], []
        if not _is_empty(proposed) and current != proposed:
            return current, [], [{'path': path, 'current': current, 'proposed': proposed}]
        return current, [], []
    merged, filled, diverged = dict(current), [], []
    for key, value in proposed.items():
        sub = f'{path}.{key}' if path else key
        m, f, d = fill_empty(current.get(key), value, sub)
        merged[key] = m
        filled += f
        diverged += d
    return merged, filled, diverged


def propose(manifest: dict, *, origin: str = '', user=None):
    """Dépose un manifeste PROPOSÉ au magasin, en bac à sable. Rien n'est projeté.

    `origin` : d'où vient la proposition (rôle, fichier d'`outputs/`) — gardé dans `source`.
    Un manifeste invalide est stocké AVEC ses erreurs (`strict=False`) : le plan les montrera,
    plutôt que de laisser la proposition mourir dans un fichier.
    """
    from .ingest import ingest
    proposal = dict(manifest)
    proposal['visibility'] = 'private'
    proposal['source'] = {'type': 'proposal', 'ref': origin or 'inconnue'}
    return ingest(proposal, user=user, strict=False)


def pending(kind: str = None):
    """Propositions en attente (bac à sable), plus récentes d'abord."""
    from ..models import Manifest
    qs = Manifest.objects.filter(visibility='private')
    if kind:
        qs = qs.filter(manifest_kind=kind)
    return qs.order_by('-updated_at')


def _merged(obj) -> tuple:
    """(manifeste superposé, comblés, divergences) — la proposition sur l'extraction courante."""
    from .ingest import extract
    proposal = obj.as_manifest()
    try:
        current = extract(obj.manifest_kind, obj.key)
    except Exception:
        current = None
    if not current:
        # Rien à préserver (l'objet n'existe pas encore au registre) : la proposition entière.
        return proposal, ['body'], []
    body, filled, diverged = fill_empty(current.get('body') or {}, proposal.get('body') or {},
                                        'body')
    merged = {**current, 'body': body}
    return merged, filled, diverged


def plan(obj) -> dict:
    """Ce que `apply()` FERAIT — sans rien écrire. `write_back` est le dry-run du kind."""
    from .ingest import validate, write_back
    merged, filled, diverged = _merged(obj)
    errors = list(validate(merged) or [])
    try:
        projection = write_back(merged, apply=False) if not errors else None
    except Exception as e:
        projection, errors = None, errors + [f"write-back impossible : {type(e).__name__}: {e}"]
    return {'kind': obj.manifest_kind, 'key': obj.key, 'origin': (obj.source or {}).get('ref'),
            'filled': filled, 'divergences': diverged, 'errors': errors,
            'projection': projection}


@transaction.atomic
def apply(obj, user=None) -> dict:
    """Applique une proposition : superposition, write-back RÉEL, promotion, export au corpus.

    Refuse — sans rien écrire — un manifeste superposé invalide, ou une projection qui signale
    sa cible absente (un modèle se DÉCOUVRE, il ne se crée pas depuis un manifeste)."""
    from .ingest import promote, validate, write_back
    merged, filled, diverged = _merged(obj)
    errors = list(validate(merged) or [])
    if errors:
        return {'applied': False, 'errors': errors}
    projection = write_back(merged, apply=True)
    if isinstance(projection, dict) and (projection.get('absent') or projection.get('erreur')):
        transaction.set_rollback(True)
        return {'applied': False, 'errors': [projection.get('erreur') or 'cible absente']}
    obj.body = merged.get('body') or {}
    obj.errors = []
    if user is not None:
        obj.owner = user
    obj.save(update_fields=['body', 'errors', 'owner', 'updated_at'])
    promote(obj, PROMOTED_VISIBILITY)
    corpus = None
    try:
        from django.core.management import call_command
        call_command('manifest_export', obj.key, kind=obj.manifest_kind, verbosity=0)
        corpus = 'écrit'
    except Exception as e:                       # le corpus est un miroir : il se rattrape
        corpus = f"échec : {type(e).__name__}: {e}"
        logger.warning("[proposals] export au corpus impossible pour %s : %s", obj.key, e)
    return {'applied': True, 'filled': filled, 'divergences': diverged,
            'projection': projection, 'corpus': corpus}


def reject(obj) -> bool:
    """Retire une proposition du magasin. N'appelle PAS `un_ingest` (cf. docstring du module)."""
    if not obj.is_sandbox:
        return False
    obj.delete()
    return True
