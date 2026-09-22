"""
WAMA Common — Les VUES DE LOT : fabrique commune (`make_batch_views`).

Le modèle de lot (`BatchMixin`, `register_batch_sync`), la file (`build_batches_list`,
`_queue_entry.html`) et la MANIPULATION de la file (`make_queue_manipulation_views` :
réordonner, déplacer, sortir, fusionner) étaient communs et adoptés 10/10. Les six ACTIONS de
lot, elles, restaient écrites à la main dans chaque app — même forme à chaque fois — :
`batch_start`, `batch_update`, `batch_delete`, `batch_duplicate`, `batch_download`,
`batch_status`. Mesuré le 2026-09-22 (question de Fabien : « le fonctionnement batch est
commun et porté ? ») : 60 lectures de lot recopiées sous cinq graphies, dont des lectures NON
ordonnées là où l'ordre compte. La fabrique manquante était déjà écrite, dans le générateur
d'apps (`codegen/views_gen.py`, corps conventionnels paramétrés par le manifeste) : elle est
EXTRAITE ici (`ROUTE §11 #36`), le générateur la consomme, les apps la rallient au fil des
portages (critère de grille `batch_views_common`).

Prérequis de convention — les mêmes que la fabrique de file :
  - batch.items      : related_name des membres (éléments en FK directe, ou lignes de liaison) ;
  - élément.status / progress / task_id / error_message / user ;
  - signaux `register_batch_sync` branchés (le lot VIDÉ est purgé par le signal — la vue ne
    supprime JAMAIS le lot par l'instance qu'elle tient : après le dernier `item.delete()`, elle
    n'a plus d'id ; mesuré sur converter_01 le 22/09).

Usage (views.py de l'app) :
    from wama.common.utils.batch_views import make_batch_views
    _bv = make_batch_views(work_model=Description, batch_model=BatchDescription, get_user=get_user,
                           task=describe_content, file_fields=('input_file', 'result_file'),
                           output_fields=('result_file',), params_fields=(...), schema=PARAMS_JSON,
                           item_model=BatchDescriptionItem, fk_name='description')
    batch_start, batch_delete = _bv['batch_start'], _bv['batch_delete'] …

Les deux formes de rattachement du dépôt sont servies par les briques de `batch_common`
(`batch_elements` pour lire, `attach_to_batch` pour rattacher) : la fabrique ne connaît la
forme que par ses kwargs (`item_model`/`fk_name` pour la liaison ; `batch_attr`/`row_field` pour
la FK directe).
"""
import io
import json
import zipfile
from pathlib import Path

from django.http import FileResponse, JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_GET, require_POST

from wama.common.utils.batch_common import attach_to_batch, batch_elements
from wama.common.utils.process_control import begin_processing
from wama.common.utils.queue_duplication import duplicate_instance, safe_delete_file

#: Remise à zéro d'un élément relancé / dupliqué — l'idiome des 10 apps.
DEFAULT_RESET = {'status': 'PENDING', 'progress': 0, 'task_id': '', 'error_message': ''}


def read_settings_payload(request, schema=None, schema_names=()):
    """Les RÉGLAGES postés à une vue d'édition — JSON ou formulaire, coercés selon le schéma.

    ⚠ `request.body` n'est lu QUE sur un POST JSON : sur un `FormData`, le middleware CSRF a déjà
    consommé le flux et `request.body` lève `RawPostDataException` (leçon de `ids_from_request`).
    ⚠ COERCER selon le schéma AVANT tout `setattr` (défaut vécu le 02/09) : le FormData d'une
    modale poste TOUTES ses valeurs, VIDES comprises — `''` sur une colonne Integer plante au
    save. `coerce_schema_values` type ('640'→640, 'true'→True) ; un champ du schéma laissé VIDE
    veut dire « ne pas toucher », jamais « effacer » — il est retiré.
    """
    if (request.content_type or '').startswith('application/json'):
        try:
            data = json.loads(request.body or '{}') or {}
        except (ValueError, TypeError):
            data = {}
    else:
        data = dict(request.POST)
    data = {k: (v[0] if isinstance(v, list) else v) for k, v in data.items()}
    if schema:
        try:
            from wama.common.utils.param_schema import coerce_schema_values
            data = {**data, **coerce_schema_values(schema, data)}
        except Exception:
            pass    # schéma inexploitable : les données brutes restent (comportement d'avant)
    names = set(schema_names or ())
    return {k: v for k, v in data.items() if not (v == '' and k in names)}


def apply_item_settings(item, data, *, params_fields=(), options_field=None, extra_names=()):
    """Pose sur `item` les réglages présents dans `data` — colonnes déclarées (`params_fields`)
    et, s'il existe, le conteneur JSON `options_field` pour les champs de schéma HORS colonnes
    (`extra_names`, idiome `params_storage`). Rend la liste des champs touchés (pour
    `save(update_fields=…)`) ; rien n'est sauvé ici."""
    touched = []
    for name in params_fields:
        if name in data:
            setattr(item, name, data[name])
            touched.append(name)
    if options_field:
        extras = {k: data[k] for k in extra_names if k in data}
        if extras:
            current = dict(getattr(item, options_field, None) or {})
            current.update(extras)
            setattr(item, options_field, current)
            touched.append(options_field)
    return touched


def _revoke_quietly(item):
    """Révoque la tâche Celery d'un élément qu'on va supprimer (sans la tuer : `terminate=False`,
    l'idiome mesuré des `batch_delete` d'app). Broker absent → on supprime quand même."""
    task_id = getattr(item, 'task_id', '') or ''
    if not task_id:
        return
    try:
        from celery import current_app
        current_app.control.revoke(task_id, terminate=False)
    except Exception:
        pass


def make_batch_views(*, work_model, batch_model, get_user, task=None,
                     file_fields=(), output_fields=(), output_field='output_file',
                     params_fields=(), schema=None, options_field=None, extra_names=(),
                     item_model=None, fk_name=None, batch_attr='batch',
                     row_field='batch_row_index', items_related='items',
                     batch_extra=None, reset_on_start=None, reset_on_duplicate=None,
                     zip_name=None, progress_of=None, item_label=None, on_delete=None):
    """Retourne les six vues de lot : {'batch_start', 'batch_update', 'batch_delete',
    'batch_duplicate', 'batch_download', 'batch_status'} (vues Django, `pk` = id du lot).

    Args:
        task            : tâche Celery de l'élément (`.delay(id)`) — sans elle, `batch_start` répond 400.
        file_fields     : champs FICHIER de l'élément (entrée en tête) — supprimés avec lui par
                          `safe_delete_file` (propriété + partage jugés par la brique).
        output_fields   : champs fichier de SORTIE — vidés à la duplication.
        output_field    : champ servi par `batch_download` (absent du modèle → 404 JSON).
        params_fields / schema / options_field / extra_names : cf. `apply_item_settings`.
        item_model, fk_name          : forme à LIAISON (`BatchXItem`, FK vers l'élément).
        batch_attr, row_field        : forme à FK DIRECTE (l'élément porte le lot et sa ligne).
        items_related   : related_name des membres sur le lot (défaut `items`).
        batch_extra     : dict|callable(lot source)->dict — champs du lot créé à la duplication
                          (converter : `media_type`, imager : `domain`).
        reset_on_start  : dict OU callable(élément) appliqué SOUS le verrou de `begin_processing`
                          (describer : `_reset_for_relaunch`) ; défaut `DEFAULT_RESET` sans
                          `status`/`task_id` — `begin_processing` pose RUNNING lui-même.
        reset_on_duplicate : dict de remise à zéro de la copie (défaut `DEFAULT_RESET`).
        progress_of     : callable(élément)->int — d'où lire la progression pour `batch_status`
                          (describer/transcriber : le cache `<app>_progress_<id>`) ; défaut `progress`.
        item_label      : callable(élément)->str — le `filename` de chaque ligne de `batch_status`
                          (idiome mesuré : describer/transcriber) ; défaut `input_filename`/`filename`.
        on_delete       : callable(élément) appelé AVANT `item.delete()` dans `batch_delete`
                          (describer : purge du cache de progression). La révocation de la tâche
                          Celery est faite par la fabrique (`terminate=False`, idiome mesuré).
    """
    schema_names = tuple(p.get('name') for p in (schema or []) if isinstance(p, dict) and p.get('name'))
    if reset_on_start is None:
        start_reset = {k: v for k, v in DEFAULT_RESET.items() if k not in ('status', 'task_id')}
    else:
        start_reset = reset_on_start if callable(reset_on_start) else dict(reset_on_start)
    dup_reset = dict(reset_on_duplicate) if reset_on_duplicate is not None else dict(DEFAULT_RESET)
    link_kwargs = ({'item_model': item_model, 'fk_name': fk_name} if item_model is not None
                   else {'batch_attr': batch_attr, 'row_field': row_field})

    def _progress(item):
        if progress_of is not None:
            try:
                return int(progress_of(item) or 0)
            except Exception:
                pass
        return int(getattr(item, 'progress', 0) or 0)

    def _label(item):
        if item_label is not None:
            return item_label(item)
        for name in ('input_filename', 'filename', 'name', 'title'):
            value = getattr(item, name, None)
            if value:
                return str(value)
        return ''

    def _batch(request, pk):
        return get_object_or_404(batch_model, pk=pk, user=get_user(request))

    @require_POST
    def batch_start(request, pk):
        user = get_user(request)
        b = _batch(request, pk)
        if task is None:
            return JsonResponse({'error': 'aucune tâche déclarée pour ce lot'}, status=400)
        started = []
        for item in batch_elements(b, work_model):
            if getattr(item, 'status', '') != 'PENDING':
                continue
            locked, err = begin_processing(work_model, item.pk, user=user, reset=start_reset)
            if err:
                continue
            t = task.delay(locked.id)
            locked.task_id = t.id
            locked.save(update_fields=['task_id'])
            started.append(locked.id)
        return JsonResponse({'started': started, 'count': len(started)})

    @require_POST
    def batch_update(request, pk):
        b = _batch(request, pk)
        data = read_settings_payload(request, schema, schema_names)
        updated = 0
        for item in batch_elements(b, work_model):
            if getattr(item, 'status', '') == 'RUNNING':
                continue
            touched = apply_item_settings(item, data, params_fields=params_fields,
                                          options_field=options_field, extra_names=extra_names)
            if touched:
                item.save(update_fields=touched)
                updated += 1
        return JsonResponse({'updated': updated})

    @require_POST
    def batch_delete(request, pk):
        b = _batch(request, pk)
        for item in batch_elements(b, work_model):
            _revoke_quietly(item)
            if on_delete is not None:
                on_delete(item)
            for field in file_fields:
                safe_delete_file(item, field)
            item.delete()
        # Le lot VIDÉ est purgé par le signal ; ne reste qu'un lot qui n'avait AUCUN élément —
        # par requête, jamais par l'instance (son id est parti avec le dernier élément).
        batch_model.objects.filter(pk=b.pk, **{f'{items_related}__isnull': True}).delete()
        return JsonResponse({'deleted': True, 'batch_id': pk})

    @require_POST
    def batch_duplicate(request, pk):
        user = get_user(request)
        src = _batch(request, pk)
        kw = {'user': user, 'total': 0}
        if batch_extra:
            kw.update(batch_extra(src) if callable(batch_extra) else dict(batch_extra))
        new_b = batch_model.objects.create(**kw)
        idx = 0
        for item in batch_elements(src, work_model):
            new = duplicate_instance(instance=item, reset_fields=dup_reset,
                                     clear_fields=list(output_fields))
            attach_to_batch(new, new_b, idx, **link_kwargs)
            idx += 1
        new_b.total = idx
        new_b.save(update_fields=['total'])
        return JsonResponse({'success': True, 'id': new_b.id, 'batch_id': new_b.id})

    @require_GET
    def batch_download(request, pk):
        b = _batch(request, pk)
        if not any(f.name == output_field for f in work_model._meta.get_fields()):
            return JsonResponse({'error': 'aucune sortie fichier pour ce lot'}, status=404)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, 'w') as z:
            for item in batch_elements(b, work_model):
                out = getattr(item, output_field, None)
                if getattr(item, 'status', '') == 'SUCCESS' and out:
                    z.writestr(Path(out.name).name, out.read())
        buf.seek(0)
        name = zip_name or f"{batch_model._meta.app_label}_batch_{b.id}.zip"
        return FileResponse(buf, as_attachment=True, filename=name)

    @require_GET
    def batch_status(request, pk):
        """État d'un lot — la FORME est celle MESURÉE sur les cinq apps qui l'exposent
        (describer, transcriber, reader, enhancer, synthesizer) : `counts` en minuscules
        {success, running, pending, failure}, `items` [{id, filename, status, progress, error}],
        `status` global (SUCCESS si tout a réussi ; RUNNING si un tourne ; FAILURE si plus rien
        n'attend et qu'un a échoué ; PENDING sinon)."""
        b = _batch(request, pk)
        items = batch_elements(b, work_model)
        counts = {'success': 0, 'running': 0, 'pending': 0, 'failure': 0}
        rows = []
        for i in items:
            status = getattr(i, 'status', '') or ''
            key = status.lower()
            counts[key] = counts.get(key, 0) + 1
            rows.append({'id': i.id, 'filename': _label(i), 'status': status,
                         'progress': _progress(i),
                         'error': (getattr(i, 'error_message', '') or None)
                                  if status == 'FAILURE' else None})
        total = b.total or len(items)
        if total and counts['success'] == total:
            overall = 'SUCCESS'
        elif counts['running']:
            overall = 'RUNNING'
        elif counts['failure'] and not counts['pending'] and not counts['running']:
            overall = 'FAILURE'
        else:
            overall = 'PENDING'
        return JsonResponse({'batch_id': pk, 'status': overall, 'total': total,
                             'counts': counts, 'items': rows})

    return {
        'batch_start': batch_start,
        'batch_update': batch_update,
        'batch_delete': batch_delete,
        'batch_duplicate': batch_duplicate,
        'batch_download': batch_download,
        'batch_status': batch_status,
    }
