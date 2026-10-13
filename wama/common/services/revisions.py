"""
Révisions d'un élément — la brique de la marche 8a (`WAMA_COLLABORATION.md §7.1`).

CE QU'ELLE FAIT : garde, DANS la card, l'historique des états qu'un élément a reçus. Chaque
résultat produit donne une révision numérotée (réglages, sorties et leur empreinte,
instruction) ; une révision que l'on PUBLIE devient une version.
CE QU'ELLE NE FAIT PAS (encore — marches suivantes, §7.1) : restaurer un état d'un geste,
afficher l'historique au volet droit.
GARDER LES FICHIERS (2026-10-13, reste 2 de §7.2) — pour une app qui le DÉCLARE
(`keep_outputs`, le Writer d'abord) : chaque révision copie ses fichiers de sortie dans la liste
de la card (`KeptOutputsMixin`), et les `keep` dernières révisions + les publiées gardent les leurs ;
au-delà le fichier part, la révision reste et le dit (`purged`). Une relance réécrit toujours au
même chemin : c'est la COPIE qui ne s'écrase plus.

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


def text_fingerprint(value) -> str:
    """Empreinte d'une sortie qui est un TEXTE (pas un fichier) — celle des révisions, et celle
    qu'un process déclare pour périmer son aval (`output_fingerprint`, `task_skeleton`)."""
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
                refs.append({'field': field.name, 'path': '', 'sha256': text_fingerprint(value)})
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
                    revision = ItemRevision.objects.create(number=last + 1, **target, **values)
            except IntegrityError:
                continue
            keep_files(app_id, item, revision)
            return revision
        logger.warning("[revisions] numéro introuvable pour %s", target)
        return None
    except Exception as exc:
        logger.debug("[revisions] révision non enregistrée (%s: %s)", type(exc).__name__, exc)
        return None


# ── Fichiers gardés (reste 2 de §7.2) ───────────────────────────────────────────────────

#: Le champ de la card qui porte les fichiers gardés (`common.models.KeptOutputsMixin`).
KEPT_FIELD = 'kept_outputs'
#: V3 tranché par Fabien le 2026-10-13 : les 20 dernières révisions + les publiées.
KEEP_DEFAULT = 20
#: Sous-dossier, à côté du fichier vivant, où vivent ses copies de révision.
KEPT_FOLDER = 'revisions'

#: `{app: nombre de révisions dont les fichiers se gardent}` — rempli par `keep_outputs`, appelé
#: depuis le `ready()` de l'app qui le déclare (`processing.revisions` du manifeste) : ce module
#: ne nomme aucune app.
_KEEPING = {}


def keep_outputs(app_id: str, keep: int = KEEP_DEFAULT) -> None:
    """Déclare que `app_id` GARDE les fichiers de ses `keep` dernières révisions (+ les publiées).
    Son modèle d'élément hérite `KeptOutputsMixin` et déclare `kept_outputs` à la rétention."""
    _KEEPING[app_id] = max(1, int(keep))


def kept_count(app_id: str) -> int:
    """Combien de révisions gardent leurs fichiers pour `app_id` — 0 : l'app n'en garde pas."""
    return _KEEPING.get(app_id, 0)


def kept_path(path: str, number: int) -> str:
    """Où vit la copie de `path` pour la révision `number` : à côté de lui, dans `revisions/`,
    numérotée — `…/drafts/7_draft.md` → `…/drafts/revisions/7_draft.r3.md`."""
    import posixpath
    folder, name = posixpath.split(str(path).replace('\\', '/'))
    stem, ext = posixpath.splitext(name)
    return posixpath.join(folder, KEPT_FOLDER, f'{stem}.r{number}{ext}')


def _kept_entries(item) -> list:
    """La liste gardée telle qu'elle est EN BASE (l'instance de l'appelant peut être plus vieille
    qu'un enregistrement concurrent)."""
    value = (type(item).objects.filter(pk=item.pk).values_list(KEPT_FIELD, flat=True).first())
    return list(value or [])


def keep_files(app_id: str, item, revision) -> list:
    """Copie les fichiers de sortie de `revision` dans la liste gardée de `item`, puis applique la
    rétention (`prune_kept`). Rend les entrées ajoutées. Rien pour une app qui ne garde pas, une
    sortie texte (sa valeur est en base, pas dans un fichier) ou un fichier absent. Best-effort :
    ne lève jamais — une copie manquée laisse la révision désigner le fichier vivant, comme avant."""
    if not kept_count(app_id) or not hasattr(item, KEPT_FIELD):
        return []
    try:
        import os
        import shutil

        from django.conf import settings
        added = []
        for ref in revision.outputs or []:
            path = ref.get('path') or ''
            source = os.path.join(settings.MEDIA_ROOT, path) if path else ''
            if not source or not os.path.isfile(source):
                continue
            rel = kept_path(path, revision.number)
            target = os.path.join(settings.MEDIA_ROOT, rel)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            partial = target + '.part'
            shutil.copyfile(source, partial)
            os.replace(partial, target)
            added.append({'path': rel, 'field': ref.get('field') or '',
                          'revision': revision.number, 'sha256': ref.get('sha256') or ''})
        if added:
            entries = _kept_entries(item) + added
            type(item).objects.filter(pk=item.pk).update(**{KEPT_FIELD: entries})
            setattr(item, KEPT_FIELD, entries)
            prune_kept(app_id, item)
        return added
    except Exception as exc:
        logger.warning("[revisions] fichiers de la révision %s non gardés (%s: %s)",
                       getattr(revision, 'number', '?'), type(exc).__name__, exc)
        return []


def prune_kept(app_id: str, item) -> list:
    """La rétention V3 : seuls les fichiers des `kept_count` dernières révisions et des révisions
    PUBLIÉES restent. Au-delà, le fichier part — s'il vit chez l'app de la card et que rien d'autre
    ne le désigne, les deux règles de `safe_delete_file` — et la révision le dit (`purged` sur sa
    référence, §7.1 « fichier purgé ») ; elle-même n'est jamais effacée. Rend les chemins retirés."""
    keep = kept_count(app_id)
    if not keep:
        return []
    import os

    from django.conf import settings

    from wama.common.utils.file_references import is_referenced_elsewhere
    from wama.common.utils.queue_duplication import owns_file
    revisions = revisions_of(app_id, item)
    kept = set(revisions.values_list('number', flat=True)[:keep])
    kept |= set(revisions.filter(published_at__isnull=False).values_list('number', flat=True))
    entries = _kept_entries(item)
    stay, gone = [], []
    for entry in entries:
        (stay if entry.get('revision') in kept else gone).append(entry)
    if not gone:
        return []
    type(item).objects.filter(pk=item.pk).update(**{KEPT_FIELD: stay})
    setattr(item, KEPT_FIELD, stay)
    removed = []
    for entry in gone:
        rel = entry.get('path') or ''
        if rel and owns_file(item, rel) and not is_referenced_elsewhere(
                rel, label=item._meta.label, pk=item.pk, field=KEPT_FIELD):
            try:
                os.remove(os.path.join(settings.MEDIA_ROOT, rel))
                removed.append(rel)
            except OSError:
                pass
    by_number = {}
    for entry in gone:
        by_number.setdefault(entry.get('revision'), set()).add(entry.get('field'))
    for revision in revisions.filter(number__in=list(by_number)):
        fields = by_number[revision.number]
        revision.outputs = [dict(ref, purged=True) if ref.get('field') in fields else ref
                            for ref in revision.outputs or []]
        revision.save(update_fields=['outputs'])
    return removed


def kept_file(app_id: str, item, number: int, field: str) -> str:
    """Le fichier GARDÉ du champ `field` à la révision `number` (chemin relatif à MEDIA_ROOT), ''
    s'il n'y en a pas (révision sans ce champ, fichier purgé, app qui ne garde pas)."""
    for entry in list(getattr(item, KEPT_FIELD, None) or []):
        if entry.get('revision') == number and entry.get('field') == field:
            return entry.get('path') or ''
    return ''


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
                if value in (None, '') or text_fingerprint(value) != recorded:
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
