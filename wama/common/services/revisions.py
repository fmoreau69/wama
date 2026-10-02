"""
Révisions d'un élément — la brique de la marche 8a (`WAMA_COLLABORATION.md §7.1`).

CE QU'ELLE FAIT : garde, DANS la card, l'historique des états qu'un élément a reçus. Chaque
résultat produit donne une révision numérotée (réglages, sorties et leur empreinte,
instruction) ; une révision que l'on PUBLIE devient une version.
CE QU'ELLE NE FAIT PAS (encore — marches suivantes, §7.1) : restaurer un état, rendre les
sorties immuables (une relance réécrit encore au même chemin), purger selon une rétention,
afficher l'historique au volet droit.

AUCUNE APP N'ÉCRIT SA RÈGLE ICI. Ce qu'on garde d'un élément se DÉRIVE :
  - ses réglages, de son schéma de paramètres (`schema_for_app`, params de contexte `item`) —
    même règle de lecture que `card_gear.gear_data` : la colonne homonyme, sinon le conteneur
    JSON `options` de l'idiome params_storage (`views_gen`) ;
  - ses fichiers, de ses `FileField`.
La capture est posée UNE fois, dans le squelette de tâche commun (`task_skeleton`), à côté du
signal `produit` de `RunOutcome` auquel la révision se rattache.

RÈGLE D'INTÉGRATION — best-effort ABSOLU pour l'écriture, comme `run_outcome.record` : une
révision manquée est une trace perdue ; une exception levée ici ferait échouer une tâche qui a
réussi.
"""
from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)

#: Nom du conteneur JSON des réglages hors colonnes (idiome params_storage, `views_gen`).
OPTIONS_CONTAINER = 'options'


def json_safe(value):
    """Une valeur de réglage telle qu'un JSONField la gardera (Decimal, date… → chaîne ; un
    champ fichier → son chemin). Publique depuis le 2026-10-02 : la photo des réglages d'un
    process (`process_runs.snapshot`) écrit ses valeurs par la même règle que la révision."""
    from django.core.serializers.json import DjangoJSONEncoder
    try:
        return json.loads(json.dumps(value, cls=DjangoJSONEncoder))
    except (TypeError, ValueError):
        return str(value)


def _concrete_field_names(model) -> set:
    return {f.name for f in model._meta.get_fields() if getattr(f, 'concrete', False)}


def settings_snapshot(app_id: str, item) -> dict:
    """Réglages de `item` à cet instant, dérivés du schéma de son app. `{}` sans schéma."""
    from wama.common.utils.param_schema import _pget, schema_for_app

    columns = _concrete_field_names(type(item))
    container = {}
    if OPTIONS_CONTAINER in columns:
        container = getattr(item, OPTIONS_CONTAINER, None) or {}
        if not isinstance(container, dict):
            container = {}
    snapshot = {}
    for param in schema_for_app(app_id):
        if 'item' not in (_pget(param, 'contexts') or ()):
            continue
        name = _pget(param, 'name')
        if not name:
            continue
        if name in columns:
            snapshot[name] = json_safe(getattr(item, name, None))
        elif name in container:
            snapshot[name] = json_safe(container[name])
    return snapshot


def _text_fingerprint(value) -> str:
    import hashlib
    return hashlib.sha256(str(value).encode('utf-8')).hexdigest()


def output_references(item, fields=None) -> list:
    """`[{field, path, sha256}]` des SORTIES de `item`.

    `fields` = les champs que le traitement vient d'écrire (clés `fields` du retour de la glu,
    que le squelette connaît) : eux seuls sont des sorties. Un FileField y est référencé par son
    chemin, un champ texte par l'empreinte de sa valeur (`path` vide). Sans `fields`, repli :
    tous les FileField non vides — ce qui compte aussi les ENTRÉES (mesuré le 2026-10-01 : la
    1ʳᵉ révision du Writer portait son document de référence comme sortie, et pas le document
    produit, qui vit dans `result_text`)."""
    from django.db.models import FileField

    from wama.common.utils.provenance import sha256_of

    by_name = {f.name: f for f in type(item)._meta.get_fields() if getattr(f, 'concrete', False)}
    refs = []
    for field in (by_name.values() if fields is None else
                  [by_name[n] for n in fields if n in by_name]):
        if not isinstance(field, FileField):
            value = getattr(item, field.name, None)
            if fields is not None and value not in (None, ''):
                refs.append({'field': field.name, 'path': '', 'sha256': _text_fingerprint(value)})
            continue
        value = getattr(item, field.name, None)
        name = getattr(value, 'name', '') or ''
        if not name:
            continue
        try:
            full_path = value.path
        except Exception:        # stockage sans chemin local : on garde la référence seule
            full_path = None
        refs.append({'field': field.name, 'path': name,
                     'sha256': sha256_of(full_path) if full_path else ''})
    return refs


def _target(app_id: str, item) -> dict:
    return {'app': app_id or '', 'object_type': type(item).__name__,
            'object_id': getattr(item, 'pk', None) or 0}


def record_revision(app_id: str, item, *, origin: str = 'process', user=None, outcome=None,
                    model_keys=None, instruction: str = '', output_fields=None):
    """Donne à `item` sa révision suivante. Rend la ligne créée, ou None si rien n'a pu
    être écrit (best-effort : ne lève jamais). `output_fields` : cf. `output_references`."""
    try:
        from django.db import IntegrityError, transaction
        from django.db.models import Max

        from wama.common.models import ItemRevision

        target = _target(app_id, item)
        values = dict(
            origin=origin,
            user=user if user is not None else getattr(item, 'user', None),
            outcome=outcome,
            model_keys=[str(k) for k in (model_keys or []) if k],
            instruction=instruction or '',
            settings=settings_snapshot(app_id, item),
            outputs=output_references(item, output_fields),
        )
        # Deux résultats simultanés sur le même élément sont rares mais possibles (relance
        # pendant un traitement) : la contrainte d'unicité tranche, on reprend le numéro suivant.
        for _attempt in range(3):
            last = (ItemRevision.objects.filter(**target)
                    .aggregate(n=Max('number'))['n']) or 0
            try:
                with transaction.atomic():
                    return ItemRevision.objects.create(number=last + 1, **target, **values)
            except IntegrityError:
                continue
        logger.warning("[revisions] numéro introuvable pour %s", target)
        return None
    except Exception as exc:
        logger.debug("[revisions] révision non enregistrée (%s: %s)", type(exc).__name__, exc)
        return None


# ── Lecture ────────────────────────────────────────────────────────────────────────────

def revisions_of(app_id: str, item):
    """Toutes les révisions de `item`, la plus récente d'abord."""
    from wama.common.models import ItemRevision
    return ItemRevision.objects.filter(**_target(app_id, item)).order_by('-number')


def current_revision(app_id: str, item):
    """La dernière révision de `item`, ou None s'il n'a encore rien produit."""
    return revisions_of(app_id, item).first()


def published_revision(app_id: str, item):
    """La dernière révision PUBLIÉE — la version qu'un hébergement montre. None si aucune."""
    return (revisions_of(app_id, item).filter(published_at__isnull=False)
            .order_by('-published_at', '-number').first())


def get_revision(app_id: str, item, number: int):
    """La révision `number` de `item`. Lève `LookupError` si elle n'existe pas."""
    revision = revisions_of(app_id, item).filter(number=number).first()
    if revision is None:
        raise LookupError(f"{app_id}:{type(item).__name__}#{getattr(item, 'pk', None)} "
                          f"n'a pas de révision {number}")
    return revision


def outputs_changed_since(revision, item=None) -> list:
    """Les champs dont le fichier a changé (ou disparu) depuis `revision` — ce qui rend
    l'historique HONNÊTE tant que les sorties ne sont pas immuables. Un fichier sans
    empreinte enregistrée n'est pas jugé ; une sortie TEXTE (`path` vide) ne l'est qu'avec
    l'élément sous la main (`item`), sa valeur vivant en base."""
    from django.core.files.storage import default_storage

    from wama.common.utils.provenance import sha256_of

    changed = []
    for ref in revision.outputs or []:
        recorded = ref.get('sha256') or ''
        if not recorded:
            continue
        path = ref.get('path') or ''
        if not path:
            if item is not None:
                value = getattr(item, ref.get('field') or '', None)
                if value in (None, '') or _text_fingerprint(value) != recorded:
                    changed.append(ref.get('field'))
            continue
        try:
            current = sha256_of(default_storage.path(path)) if path else ''
        except Exception:
            current = ''
        if current != recorded:
            changed.append(ref.get('field') or path)
    return changed


# ── Publication ────────────────────────────────────────────────────────────────────────

def publish(app_id: str, item, number: int, *, user, note: str = ''):
    """Publie la révision `number` : elle devient une VERSION. Republier la même révision
    met à jour sa note et sa date. Les droits sont vérifiés par l'appelant (la vue), comme
    pour le partage : seul le propriétaire publie (`WAMA_COLLABORATION §3.6`)."""
    from django.utils import timezone

    revision = get_revision(app_id, item, number)
    revision.published_at = timezone.now()
    revision.published_by = user
    revision.publish_note = note or ''
    revision.save(update_fields=['published_at', 'published_by', 'publish_note'])
    return revision


def unpublish(app_id: str, item, number: int):
    """Retire la révision `number` des versions publiées (elle reste dans l'historique)."""
    revision = get_revision(app_id, item, number)
    revision.published_at = None
    revision.published_by = None
    revision.save(update_fields=['published_at', 'published_by'])
    return revision
