"""
PROPOSITIONS de manifestes — le geste de validation qui manquait entre un rôle LLM et l'ingest.

La machine à états est écrite depuis août (`WAMA_MANIFEST_ARCHITECTURE §4`) : un manifeste
produit par « extract() ou LLM skill » entre en SANDBOX (`visibility='private'`), est VÉRIFIÉ
(diff), puis PROMU. Le magasin (`Manifest`) et `ingest()`/`promote()` existaient — sans aucun
appelant en production (mesuré le 2026-09-29). Les rôles `wama-dev-ai` déposaient leur
manifeste dans `outputs/`, d'où seul un terminal pouvait le projeter (`write_back(apply=True)`).
Ce module RELIE ce qui existait ; il n'ajoute ni état ni kind.

  propose()  → le manifeste d'un rôle entre au magasin, en bac à sable (jamais projeté), avec
               sa DEMANDE de promotion ;
  plan()     → ce que l'application FERAIT : champs comblés, divergences, dry-run du write-back ;
  apply()    → superposition, write-back RÉEL, promotion AU SYSTÈME, export au corpus ;
  reject()   → la demande est close, rien n'est défait (rien n'avait été fait) ; la proposition
               d'un rôle, qui n'est à personne, sort du magasin.

PRIVÉ N'EST PAS « EN ATTENTE » (2026-10-18, `ROADMAP §29` étape 2). La file listait tout manifeste
privé : le modèle privé d'un utilisateur y serait tombé. Elle lit désormais la DEMANDE
(`Manifest.promotion_requested_at`), et valider rend l'élément au SYSTÈME (`ingest.promote`) au
lieu de le donner à l'admin qui valide.

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
    from django.utils import timezone

    from .ingest import ingest
    proposal = dict(manifest)
    proposal['visibility'] = 'private'
    proposal['source'] = {'type': 'proposal', 'ref': origin or 'inconnue'}
    obj = ingest(proposal, user=user, strict=False)
    obj.promotion_requested_at = timezone.now()
    obj.save(update_fields=['promotion_requested_at'])
    return obj


def pending(kind: str = None):
    """Promotions DEMANDÉES et non tranchées, plus récentes d'abord — pas tout ce qui est privé."""
    from ..models import Manifest
    qs = Manifest.objects.filter(promotion_requested_at__isnull=False)
    if kind:
        qs = qs.filter(manifest_kind=kind)
    return qs.order_by('-updated_at')


def _merged(obj) -> tuple:
    """(manifeste superposé, comblés, divergences) — la proposition sur l'extraction courante."""
    return _superposed(obj.as_manifest(), obj.manifest_kind, obj.key)


def _superposed(proposal: dict, kind: str, key: str) -> tuple:
    from .ingest import extract
    try:
        current = extract(kind, key)
    except Exception:
        current = None
    if not current:
        # Rien à préserver (l'objet n'existe pas encore au registre) : la proposition entière.
        return proposal, ['body'], []
    body, filled, diverged = fill_empty(current.get('body') or {}, proposal.get('body') or {},
                                        'body')
    merged = {**current, 'body': body}
    return merged, filled, diverged


def _errors(merged) -> list:
    """Ce qui interdit d'appliquer : la FORME (`validate`), puis ce que seul le réel peut dire
    (`ManifestKind.confront`, joué ici seulement — une forme fausse ne vaut pas un appel réseau).
    UNE liste pour le plan et pour l'application : « Valider » refuse exactement ce que le plan
    montre (2026-11-06, l'anatomie d'ACE-Step qui oubliait son encodeur de texte)."""
    from .ingest import validate
    from .kinds import get_kind
    errors = list(validate(merged) or [])
    confront = getattr(get_kind(merged.get('manifest_kind') or ''), 'confront', None)
    if not errors and confront:
        errors += list(confront(merged) or [])
    return errors


def judge(manifest: dict) -> list:
    """Ce que « Valider » refuserait de ce manifeste s'il était proposé MAINTENANT — la même
    superposition et la même liste que `plan`/`apply`, sans rien déposer.

    Pour le rôle qui l'écrit (2026-11-07, ACE-Step par l'assistant) : le rôle `model` ne jugeait
    que la FORME et se disait « VALIDE » d'une anatomie que « Valider » refusait, sans pouvoir se
    reprendre — la chaîne s'arrêtait dans la file, au jugement d'un humain sur un défaut mécanique."""
    merged, _, _ = _superposed(manifest, manifest.get('manifest_kind') or '',
                               manifest.get('key') or '')
    return _errors(merged)


def plan(obj) -> dict:
    """Ce que `apply()` FERAIT — sans rien écrire. `write_back` est le dry-run du kind."""
    from .ingest import write_back
    merged, filled, diverged = _merged(obj)
    errors = _errors(merged)
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
    from .ingest import promote, write_back
    merged, filled, diverged = _merged(obj)
    errors = _errors(merged)
    if errors:
        return {'applied': False, 'errors': errors}
    projection = write_back(merged, apply=True)
    # `error` : le refus de la garde des pertes (`ingest.write_back`, 2026-11-08) — la proposition
    # effacerait un fait que le registre a pris depuis qu'elle a été écrite.
    if isinstance(projection, dict) and (projection.get('absent') or projection.get('erreur')
                                         or projection.get('error')):
        transaction.set_rollback(True)
        return {'applied': False, 'errors': [projection.get('erreur') or projection.get('error')
                                             or 'cible absente'],
                **({'losses': projection['losses']} if projection.get('losses') else {})}
    obj.body = merged.get('body') or {}
    obj.errors = []
    obj.save(update_fields=['body', 'errors', 'updated_at'])
    promote(obj, by=user)
    corpus = None
    try:
        from .corpus import follow
        corpus = follow(obj.key, kind=obj.manifest_kind)
    except Exception as e:                       # le corpus est un miroir : il se rattrape
        corpus = f"échec : {type(e).__name__}: {e}"
        logger.warning("[proposals] export au corpus impossible pour %s : %s", obj.key, e)
    return {'applied': True, 'filled': filled, 'divergences': diverged,
            'projection': projection, 'corpus': corpus}


def reject(obj) -> bool:
    """Close une demande de promotion. N'appelle PAS `un_ingest` (cf. docstring du module).

    La proposition d'un RÔLE n'est à personne : elle sort du magasin. Le manifeste d'un AUTEUR
    reste le sien, privé comme avant sa demande."""
    if not obj.is_pending:
        return False
    if obj.is_system:
        obj.delete()
        return True
    obj.promotion_requested_at = None
    obj.save(update_fields=['promotion_requested_at', 'updated_at'])
    return True
