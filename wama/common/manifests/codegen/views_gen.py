"""
Gabarit `views.py` (marche A — le morceau annoncé au cadrage A0, écrit à la marche S2).

Contrat : le fichier généré DÉFINIT un callable pour CHAQUE route du urls.py généré
(facette processing : `endpoints` conventionnels + `extra_routes`) — sinon l'import du
module urls casse la jumelle entière. Deux régimes :

  • CONVENTIONNEL (implémentation réelle) : la vue est un idiome MESURÉ (cadrage A0 /
    pilote converter) paramétré par le manifeste — modèle d'item (processing.model_spec),
    modèle de batch et FK (DÉRIVÉS de la facette `data` : la FK de l'item vers *Batch),
    tâche Celery (processing.tasks), statuts, briques communes (begin_processing,
    stop_instance, duplicate_instance, apply_queue_sort_filter, fabrique
    make_queue_manipulation_views_direct, get_console_lines).
  • TROU DE GLU (stub 501) : politique d'app non conventionnelle (card_html — nom du
    partial inconnaissable ; batch_preview/create — parsing+consolidation ; consolidate ;
    toutes les extra_routes). La page BOOTE, la fonctionnalité manque VISIBLEMENT —
    c'est le détecteur (Playwright/diff), pas un échec silencieux.

Formes de file : v1 ne rend l'index/fabrique QUE pour la forme FK-DIRECTE (item.batch,
batch_row_index — converter). La forme à modèle de liaison (transcriber…) est un trou
déclaré de ce gabarit (raison explicite, jamais de fichier partiel faux).
"""
from __future__ import annotations


def _donnees(manifest: dict) -> dict:
    """Paramètres du gabarit dérivés du manifeste — (dict, jamais None) ; clé '_raison'
    posée si un préalable manque."""
    body = manifest.get('body') or {}
    proc = body.get('processing') or {}
    spec = (proc.get('model_spec') or {}).get('item') or {}
    data_models = {m['name']: m for m in (body.get('data') or {}).get('models') or []}

    item = spec.get('name')
    if not item:
        return {'_raison': 'processing.model_spec.item absent'}
    if item not in data_models:
        return {'_raison': f'facette data sans le modèle {item}'}

    d = {
        'app_id': manifest.get('key'),
        'item': item,
        'input_field': spec.get('input_field') or 'input_file',
        'endpoints': list(proc.get('endpoints') or []),
        'extras': [str(e.get('view', '')).split('.')[-1]
                   for e in (proc.get('extra_routes') or []) if e.get('view')],
        'tasks': [t.get('function') for t in (proc.get('tasks') or []) if t.get('function')],
        'statuses': list(proc.get('statuses') or ['PENDING', 'RUNNING', 'SUCCESS', 'FAILURE']),
        'params_fields': list(spec.get('params_fields') or []),
    }

    champs = {f['name']: f for f in data_models[item].get('fields') or []}
    d['champ_noms'] = set(champs)
    d['a_output'] = 'output_file' in champs
    d['name_field'] = ('input_filename' if 'input_filename' in champs
                       else 'input_name' if 'input_name' in champs else '')

    # Forme de file : FK de l'item vers un modèle *Batch de la MÊME app (facette data).
    d['batch'], d['batch_fk'], d['row_field'] = '', '', ''
    for nom, f in champs.items():
        to = ((f.get('kwargs') or {}).get('to') or {}).get('expr', '')
        cible = to.strip('\'"').split('.')[-1]
        for m_name in data_models:
            if cible.lower() == m_name.lower() and m_name.lower().endswith('batch'):
                d['batch'], d['batch_fk'] = m_name, nom
    if d['batch'] and 'batch_row_index' in champs:
        d['row_field'] = 'batch_row_index'
    d['batch_extra'] = ('media_type' if (d['batch'] and 'media_type' in champs
                        and 'media_type' in {f['name'] for f in
                                             data_models[d['batch']].get('fields') or []})
                        else '')
    return d


def render_views(manifest: dict) -> tuple:
    """(source, raison) — views.py complet, ou (None, raison). Jamais de fichier partiel."""
    from ..builtin.app import _GEN_MARK
    d = _donnees(manifest)
    if d.get('_raison'):
        return None, d['_raison']
    if not d['tasks']:
        return None, 'processing.tasks vide (aucune tâche à dispatcher)'
    if not (d['batch'] and d['row_field']):
        return None, ('forme de file NON directe (pas de FK item→Batch + batch_row_index) — '
                      'gabarit v1 = forme converter ; la forme à modèle de liaison est un '
                      'trou déclaré')

    app, item, batch = d['app_id'], d['item'], d['batch']
    fk, row, task = d['batch_fk'], d['row_field'], d['tasks'][0]
    mark = _GEN_MARK.format(app_id=app)
    stub_msg = f'[manifest-gen app:{app}] endpoint non généré (glu — marche B)'
    name_expr = (f'j.{d["name_field"]}' if d['name_field']
                 else f'(j.{d["input_field"]}.name if j.{d["input_field"]} else "")')

    def stub(nom, pk=False):
        arg = ', pk' if pk else ''
        return (f"def {nom}(request{arg}):\n"
                f"    \"\"\"TROU DE GLU {mark} — politique d'app non conventionnelle.\"\"\"\n"
                f"    return JsonResponse({{'error': {stub_msg!r}}}, status=501)")

    # ── Corps conventionnels (idiomes MESURÉS, paramétrés) ─────────────────────
    vues = {}
    # ENVELOPPEMENT DES ORPHELINS — convention commune, et non un détail (2026-08-22).
    # `batch_common.auto_wrap_orphans` la formule : « chaque orphelin → SON batch-of-1, la
    # règle depuis 2026-08-14 (10 apps) », et `build_batches_list` s'y adosse (« une card
    # isolée est déjà auto-enveloppée dans son propre batch »). L'app générée l'ignorait et
    # laissait des items HORS LOT : `apply_queue_sort_filter` lit alors `b['obj'].created_at`
    # sur un None et la file entière tombe en AttributeError — un seul item isolé suffisait.
    # Le contrat de la brique n'était pas trop strict, c'est la vue générée qui le violait.
    # ⚠ La brique commune suppose un modèle de LIAISON ; ici la FK est DIRECTE (comme
    # converter, seule app dans ce cas), d'où la boucle explicite plutôt qu'un appel — même
    # forme que `converter/views.py::_auto_wrap_orphans`. Trou consigné : `batch_common` n'a
    # pas de variante FK-directe, et le motif est désormais écrit à 4 endroits.
    vues['index'] = f'''class IndexView(View):
    def get(self, request):
        user = _user(request)
        _auto_wrap_orphans(user)
        jobs = {item}.objects.filter(user=user).order_by('{fk}_id', '{row}')
        grouped = {{}}
        for j in jobs:
            grouped.setdefault(j.{fk}_id or f'loose-{{j.id}}', []).append(j)
        batches_list = []
        for items in grouped.values():
            b = items[0].{fk}
            statuses = [normalize_status(j.status) for j in items]
            batches_list.append({{
                'obj': b, 'items': items,
                'is_group': bool(b) and (b.total if b else len(items)) > 1,
                'success_count': statuses.count('SUCCESS'),
                'running_count': statuses.count('RUNNING'),
                'failure_count': statuses.count('FAILURE'),
                'has_success': 'SUCCESS' in statuses,
                'eta_ids': ','.join(str(j.id) for j in items),
            }})
        batches_list, q_sort, q_filter = apply_queue_sort_filter(
            request, batches_list,
            name_of=lambda b: ({name_expr.replace('j.', 'b["items"][0].')} if b['items'] else ''))
        try:
            from .params import PARAMS_JSON
            params_json = json.dumps(PARAMS_JSON)
        except Exception:
            params_json = '[]'
        # TROU DE GLU {mark} — contexte SPÉCIFIQUE d'app (profils, formats…) non généré :
        # le gabarit ne fournit que le contexte CONVENTIONNEL de file.
        return render(request, '{app}/index.html', {{
            'batches_list': batches_list, 'queue_count': len(jobs),
            'q_sort': q_sort, 'q_filter': q_filter, 'params_json': params_json,
        }})'''

    vues['upload'] = f'''@require_POST
def upload(request):
    user = _user(request)
    f = request.FILES.get('file')
    if not f:
        return JsonResponse({{'error': 'Aucun fichier fourni'}}, status=400)
    kwargs = {{'user': user, '{d['input_field']}': f}}
    {f"kwargs['{d['name_field']}'] = f.name" if d['name_field'] else ''}
    item = {item}.objects.create(**kwargs)
    return JsonResponse({{'id': item.id, 'status': item.status}})'''

    # APERÇU DE LOT — conventionnel, plus un stub (2026-08-22). Le parsing d'un fichier de lot
    # n'a jamais été une « politique d'app » : `batch_media_list_preview_response` fait tout le
    # travail (parse, nom de fichier, avertissements, JSON {items, warnings, count}) et c'est
    # déjà ce qu'appelle l'app en place. Sans cette route, le front ne peut RIEN faire d'un
    # fichier de lot — et il ne peut pas non plus décider qu'un texte n'en est pas un, puisque
    # c'est le `count == 0` du serveur qui le lui dit (batch-import.js:140).
    vues['batch_preview'] = '''@require_POST
def batch_preview(request):
    """Aperçu d'un fichier de lot AVANT création — brique commune, zéro code d'app."""
    from wama.common.utils.batch_parsers import batch_media_list_preview_response
    return batch_media_list_preview_response(request)'''

    # CRÉATION DE LOT — conventionnelle, plus un stub (trou 22, 2026-08-22). L'aperçu marchait,
    # le bouton ne produisait rien : le dernier maillon bouchonné du chemin de lot. Rien de
    # neuf n'est écrit ici, tout existait —
    #   `parse_batch_file_from_request` (lecture du fichier, déjà utilisée par batch_preview),
    #   `copy_into_app_input` (copie sûre + chemin relatif MEDIA_ROOT),
    #   `group_into_batches_by_nature` (règle générale de regroupement, conventions §9).
    #
    # ⚠ UNE URL N'EST PAS TÉLÉCHARGÉE ICI. On enregistre la SOURCE et `ensure_local_input` la
    # résout en tête de tâche (idempotent, WAMA_INGEST). Deux raisons, pas une : la requête ne
    # part pas chercher N fichiers distants sous le nez de l'utilisateur (le converter, lui,
    # télécharge en eager et un lot de 30 URL y tient la requête ouverte), et le seul chemin de
    # téléchargement reste celui qui passe par la garde SSRF. Une app SANS ingest déclaré le dit
    # dans `warnings` plutôt que d'échouer en silence.
    # Fragments PRÉCALCULÉS (pas de f-string imbriquée : elle dépendrait de PEP 701 et se
    # relit mal — le gabarit doit rester lisible par qui n'écrit pas de générateur).
    nature_champ = d['batch_extra']          # 'media_type' si l'app la porte, sinon ''
    _nom = d['name_field']
    bc_nom_url = (f"""if nom:
                    obj.{_nom} = nom
                    obj.save(update_fields=['{_nom}'])""" if _nom else "pass")
    bc_nom_fichier = f"kwargs['{_nom}'] = _dest.name" if _nom else "pass"
    bc_nature = (f"str(getattr(o, '{nature_champ}', '') or '')" if nature_champ else "''")
    bc_nature_kw = (f", **{{'{nature_champ}': nature}}" if nature_champ else "")
    vues['batch_create'] = f'''@require_POST
def batch_create(request):
    """Crée N éléments depuis un fichier de lot, puis les regroupe — briques communes."""
    from pathlib import Path as _Path
    from django.conf import settings as _settings
    from wama.common.utils.batch_common import group_into_batches_by_nature
    from wama.common.utils.batch_parsers import parse_batch_file_from_request
    from wama.common.utils.media_paths import copy_into_app_input

    user = _user(request)
    try:
        lignes, avertissements = parse_batch_file_from_request(request)
    except ValueError as e:
        return JsonResponse({{'error': str(e)}}, status=400)
    if not lignes:
        return JsonResponse({{'error': 'Aucun élément valide trouvé dans le fichier'}}, status=400)

    # Clé 'source' (défaut 'source_url') — c'est celle que lit `ensure_local_input`
    # (source_ingest.py:77) et celle que porte le manifeste (`processing.ingest`).
    # On vérifie AUSSI que le champ existe : un modèle généré avant le 2026-08-22 peut
    # déclarer l'ingest sans porter le champ, et écrire dans un attribut fantôme
    # échouerait à la création avec un message illisible.
    ingest = getattr({item}, 'WAMA_INGEST', None) or {{}}
    champ_source = ingest.get('source') or ('source_url' if ingest else '')
    if champ_source and not any(f.name == champ_source for f in {item}._meta.get_fields()):
        champ_source = ''
    racine = _Path(_settings.MEDIA_ROOT).resolve()
    crees = []
    for ligne in lignes:
        src = (ligne.get('path') or '').strip()
        if not src:
            continue
        try:
            kwargs = {{'user': user}}
            if src.startswith(('http://', 'https://')):
                if not champ_source:
                    avertissements.append('URL non prise en charge (app sans ingest) : ' + src)
                    continue
                kwargs[champ_source] = src
                nom = (ligne.get('filename') or '').strip()
                obj = {item}.objects.create(**kwargs)
                {bc_nom_url}
            else:
                cand = _Path(src)
                absolu = (cand if cand.is_absolute() else (racine / src)).resolve()
                if not str(absolu).startswith(str(racine)) or not absolu.exists():
                    avertissements.append('Introuvable : ' + src)
                    continue
                _dest, rel = copy_into_app_input(absolu, '{app}', user.id, 'input')
                {bc_nom_fichier}
                obj = {item}.objects.create(**kwargs)
                obj.{d['input_field']}.name = rel
                obj.save(update_fields=['{d['input_field']}'])
            crees.append(obj)
        except Exception as e:
            avertissements.append(src + ' : ' + str(e))

    # TROU DE GLU {mark} — les champs DÉRIVÉS de l'entrée (converter : `media_type`, déduit du
    # nom par son `format_router`) ne sont pas renseignés : la déduction est propre à l'app, il
    # n'existe pas de détecteur COMMUN nom→type (`probe_media` travaille sur un fichier présent
    # et rend une fiche, pas une valeur de `choices`). Le `upload` généré a exactement le même
    # manque : on le laisse IDENTIQUE ici plutôt que de doter un seul des deux chemins — c'est
    # la divergence entre chemins qui a produit les trois derniers défauts de codegen.
    def _lier(lot, obj, idx):
        setattr(obj, '{fk}', lot)
        setattr(obj, '{row}', idx)
        obj.save(update_fields=['{fk}', '{row}'])

    lots = group_into_batches_by_nature(
        crees,
        nature_of=lambda o: {bc_nature},
        create_batch=lambda nature, total: {batch}.objects.create(
            user=user, total=total{bc_nature_kw}),
        link_item=_lier,
    )
    return JsonResponse({{'success': True, 'count': len(crees),
                         'batches': len(lots), 'warnings': avertissements}})'''

    vues['start'] = f'''@require_POST
def start(request, pk):
    user = _user(request)
    item, err = begin_processing({item}, pk, user=user,
                                 reset={{'progress': 0, 'error_message': ''}})
    if err:
        return JsonResponse({{'error': err}}, status=400)
    t = {task}.delay(item.id)
    item.task_id = t.id
    item.save(update_fields=['task_id'])
    return JsonResponse({{'id': item.id, 'status': item.status}})'''

    vues['stop'] = f'''@require_POST
def stop(request, pk):
    user = _user(request)
    item = get_object_or_404({item}, pk=pk, user=user)
    if item.status not in ('RUNNING', 'PENDING'):
        return JsonResponse({{'id': item.id, 'status': item.status}})
    new_status = stop_instance(item, error_field='error_message')
    return JsonResponse({{'id': item.id, 'status': new_status}})'''

    corps_status = f'''    data = {{'id': item.id, 'status': item.status, 'progress': item.progress,
            'error_message': item.error_message}}
    {"if item.output_file: data['output_url'] = item.output_file.url" if d['a_output'] else ''}
    return JsonResponse(data)'''
    vues['status'] = (f"def status(request, pk):\n    user = _user(request)\n"
                      f"    item = get_object_or_404({item}, pk=pk, user=user)\n{corps_status}")
    vues['progress'] = (f"def progress(request, pk):\n    user = _user(request)\n"
                        f"    item = get_object_or_404({item}, pk=pk, user=user)\n{corps_status}")

    vues['download'] = (f'''def download(request, pk):
    user = _user(request)
    item = get_object_or_404({item}, pk=pk, user=user)
    if not item.output_file:
        return JsonResponse({{'error': 'Aucun résultat'}}, status=404)
    return FileResponse(item.output_file.open('rb'), as_attachment=True,
                        filename=Path(item.output_file.name).name)'''
                        if d['a_output'] else stub('download', pk=True))

    vues['delete'] = f'''@require_POST
def delete(request, pk):
    user = _user(request)
    item = get_object_or_404({item}, pk=pk, user=user)
    for f in [{f"item.{d['input_field']}" + (", item.output_file" if d['a_output'] else "")}]:
        if f:
            safe_delete_file(f)
    b = item.{fk}
    item.delete()
    if b is not None and not b.items.exists():
        b.delete()
    return JsonResponse({{'deleted': True}})'''

    vues['duplicate'] = f'''@require_POST
def duplicate(request, pk):
    user = _user(request)
    item = get_object_or_404({item}, pk=pk, user=user)
    new = duplicate_instance(
        instance=item,
        reset_fields={{'status': 'PENDING', 'progress': 0, 'task_id': '', 'error_message': ''}},
        clear_fields={['output_file'] if d['a_output'] else []!r},
    )
    return JsonResponse({{'success': True, 'id': new.id}})'''

    vues['start_all'] = f'''@require_POST
def start_all(request):
    user = _user(request)
    started = []
    for item in {item}.objects.filter(user=user, status='PENDING'):
        item.status = 'RUNNING'
        item.save(update_fields=['status'])
        t = {task}.delay(item.id)
        item.task_id = t.id
        item.save(update_fields=['task_id'])
        started.append(item.id)
    return JsonResponse({{'started': started}})'''

    vues['clear_all'] = f'''@require_POST
def clear_all(request):
    user = _user(request)
    n = 0
    for item in {item}.objects.filter(user=user).exclude(status='RUNNING'):
        for f in [{f"item.{d['input_field']}" + (", item.output_file" if d['a_output'] else "")}]:
            if f:
                safe_delete_file(f)
        item.delete()
        n += 1
    {batch}.objects.filter(user=user, items__isnull=True).delete()
    return JsonResponse({{'cleared': n}})'''

    vues['download_all'] = (f'''def download_all(request):
    user = _user(request)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        for item in {item}.objects.filter(user=user, status='SUCCESS'):
            if item.output_file:
                z.writestr(Path(item.output_file.name).name, item.output_file.read())
    buf.seek(0)
    return FileResponse(buf, as_attachment=True, filename='{app}_outputs.zip')'''
                            if d['a_output'] else stub('download_all'))

    vues['global_progress'] = f'''def global_progress(request):
    user = _user(request)
    qs = {item}.objects.filter(user=user)
    running = list(qs.filter(status='RUNNING').values_list('progress', flat=True))
    return JsonResponse({{
        'running': len(running), 'pending': qs.filter(status='PENDING').count(),
        'percent': int(sum(running) / len(running)) if running else 0,
    }})'''

    vues['console'] = f'''def console_content(request):
    user = _user(request)
    return JsonResponse({{'lines': get_console_lines(user.id, app='{app}')}})'''

    vues['batch_start'] = f'''@require_POST
def batch_start(request, pk):
    user = _user(request)
    b = get_object_or_404({batch}, pk=pk, user=user)
    started = []
    for item in {item}.objects.filter({fk}=b, user=user, status='PENDING').order_by('{row}'):
        item.status = 'RUNNING'
        item.save(update_fields=['status'])
        t = {task}.delay(item.id)
        item.task_id = t.id
        item.save(update_fields=['task_id'])
        started.append(item.id)
    return JsonResponse({{'started': started}})'''

    maj = '\n'.join(f'''        if '{c}' in donnees:
            setattr(item, '{c}', donnees['{c}'])
            touches.append('{c}')''' for c in d['params_fields'])
    vues['batch_update'] = f'''@require_POST
def batch_update(request, pk):
    user = _user(request)
    b = get_object_or_404({batch}, pk=pk, user=user)
    try:
        donnees = json.loads(request.body) if request.body else dict(request.POST)
    except Exception:
        donnees = dict(request.POST)
    donnees = {{k: (v[0] if isinstance(v, list) else v) for k, v in donnees.items()}}
    updated = 0
    for item in {item}.objects.filter({fk}=b, user=user).exclude(status='RUNNING'):
        touches = []
{maj}
        if touches:
            item.save(update_fields=touches)
            updated += 1
    return JsonResponse({{'updated': updated}})'''

    vues['batch_delete'] = f'''@require_POST
def batch_delete(request, pk):
    user = _user(request)
    b = get_object_or_404({batch}, pk=pk, user=user)
    for item in {item}.objects.filter({fk}=b, user=user):
        for f in [{f"item.{d['input_field']}" + (", item.output_file" if d['a_output'] else "")}]:
            if f:
                safe_delete_file(f)
        item.delete()
    b.delete()
    return JsonResponse({{'deleted': True}})'''

    extra_kw = (f", {d['batch_extra']}=src.{d['batch_extra']}" if d['batch_extra'] else '')
    vues['batch_duplicate'] = f'''@require_POST
def batch_duplicate(request, pk):
    user = _user(request)
    src = get_object_or_404({batch}, pk=pk, user=user)
    new_b = {batch}.objects.create(user=user, total=0{extra_kw})
    idx = 0
    for item in {item}.objects.filter({fk}=src, user=user).order_by('{row}'):
        new = duplicate_instance(
            instance=item,
            reset_fields={{'status': 'PENDING', 'progress': 0, 'task_id': '', 'error_message': ''}},
            clear_fields={['output_file'] if d['a_output'] else []!r},
        )
        new.{fk} = new_b
        new.{row} = idx
        new.save(update_fields=['{fk}', '{row}'])
        idx += 1
    new_b.total = idx
    new_b.save(update_fields=['total'])
    return JsonResponse({{'success': True, 'id': new_b.id}})'''

    vues['batch_download'] = (f'''def batch_download(request, pk):
    user = _user(request)
    b = get_object_or_404({batch}, pk=pk, user=user)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w') as z:
        for item in {item}.objects.filter({fk}=b, user=user, status='SUCCESS'):
            if item.output_file:
                z.writestr(Path(item.output_file.name).name, item.output_file.read())
    buf.seek(0)
    return FileResponse(buf, as_attachment=True, filename=f'{app}_batch_{{b.id}}.zip')'''
                              if d['a_output'] else stub('batch_download', pk=True))

    vues['batch_template'] = f'''def batch_template(request):
    contenu = "# {app} — fichier batch : une ligne par média (chemin local ou URL)\\n"
    resp = HttpResponse(contenu, content_type='text/plain; charset=utf-8')
    resp['Content-Disposition'] = 'attachment; filename="{app}_batch_template.txt"'
    return resp'''

    fabrique = f'''# Fabrique COMMUNE de manipulation de file (forme FK-DIRECTE — dérivée de la facette data).
_qm = make_queue_manipulation_views_direct(
    work_model={item}, batch_model={batch},
    batch_fk='{fk}', row_field='{row}',
    get_user=_user,{f"""
    batch_extra=lambda w: {{'{d['batch_extra']}': w.{d['batch_extra']}}},""" if d['batch_extra'] else ''}
)
reorder           = _qm['reorder']
move_to_batch     = _qm['move_to_batch']
remove_from_batch = _qm['remove_from_batch']
# `consolidate` était BOUCHONNÉ en 501 alors que la fabrique ci-dessus le rend depuis
# toujours — quatre clés, trois reprises (2026-08-22). Rien à écrire : le regroupement de
# N dépôts en un lot était déjà là, dans le fichier même de l'app.
consolidate       = _qm['consolidate']'''

    # ── Assemblage : UNE définition par callable exigé (conventionnel ou stub) ──
    # `batch_preview` RETIRÉ de cet ensemble (2026-08-22) : sa route conventionnelle est
    # `batch/preview/` — SANS pk. Le stub était généré avec `(request, pk)` et Django levait
    # TypeError avant d'entrer dedans : 500 au lieu du 501 annoncé. Un bouchon dont toute la
    # raison d'être est d'échouer VISIBLEMENT se sabordait donc lui-même — le front recevait
    # une page d'erreur HTML au lieu de JSON (« Unexpected token '<' ») et le vrai manque
    # devenait indéchiffrable. Le second chemin d'assemblage (`extras`, plus bas) l'excluait
    # déjà correctement : les deux se contredisaient.
    stubs_pk = {'card_html'}
    couverts_fabrique = {'reorder', 'move_to_batch', 'remove_from_batch', 'consolidate'}
    ignores = {'about', 'help'}     # servis par common.views dans le urls généré
    blocs, deja = [], set()
    for ep in d['endpoints']:
        if ep in ignores or ep in couverts_fabrique or ep in deja:
            continue
        deja.add(ep)
        if ep in vues:
            blocs.append(vues[ep])
        else:
            blocs.append(stub(ep, pk=ep in stubs_pk or ep.rstrip('_') in
                              ('cancel', 'dismiss', 'update')))
    # ⚠ Cette boucle consulte `vues` AVANT de boucher (2026-08-22). Elle ne le faisait pas : une
    # route déclarée en `extra_routes` plutôt qu'en `endpoints` recevait un STUB 501 alors que
    # la fabrique savait la rendre. C'est ce qui gardait `batch_create` bouché — le corps était
    # à écrire, mais même écrit il n'aurait pas été émis pour une app qui le déclare en extra.
    # Deux chemins d'assemblage qui ne donnent pas la même app : le défaut exact déjà trouvé
    # sur `WAMA_INGEST` (models_gen) et sur le `pk` de `batch_preview` ci-dessus.
    for nom in d['extras']:
        if nom not in deja:
            deja.add(nom)
            if nom in vues:
                blocs.append(vues[nom])
                continue
            blocs.append(stub(nom, pk=True) if nom not in ('quick_convert', 'batch_preview',
                                                           'batch_create', 'consolidate',
                                                           'profile_list', 'profile_save')
                         else stub(nom))
    blocs.append(fabrique)

    tete = f'''"""
{mark} — views.py GÉNÉRÉ par le gabarit A (views_gen, marche S2).

CONVENTIONNEL paramétré par le manifeste (item={item}, batch={batch} FK '{fk}',
tâche {task}) ; les endpoints hors convention sont des STUBS 501 marqués TROU DE GLU
(marche B) — la page boote, la fonctionnalité manque VISIBLEMENT (détecteur).
"""
import io
import json
import zipfile
from pathlib import Path

from django.http import FileResponse, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views import View
from django.views.decorators.http import require_POST

from wama.accounts.views import get_or_create_anonymous_user
from wama.common.utils.console_utils import get_console_lines
from wama.common.utils.detail_registry import normalize_status
from wama.common.utils.process_control import begin_processing, stop_instance
from wama.common.utils.queue_duplication import duplicate_instance, safe_delete_file
from wama.common.utils.queue_manipulation import make_queue_manipulation_views_direct
from wama.common.utils.queue_view import apply_queue_sort_filter

from .models import {batch}, {item}
from .tasks import {task}


def _user(request):
    return request.user if request.user.is_authenticated else get_or_create_anonymous_user()


def _auto_wrap_orphans(user):
    """Chaque item HORS LOT devient son propre lot-de-1 — convention commune des 10 apps.

    Non décoratif : `apply_queue_sort_filter` lit `b['obj'].created_at`, et un item sans lot
    donne `obj = None` → la file entière tombe. La brique `batch_common.auto_wrap_orphans`
    porte cette règle, mais suppose un modèle de LIAISON ; la FK est ici DIRECTE, d'où la
    boucle (même forme que converter). Silencieux par item : un orphelin cassé ne doit pas
    empêcher la page de s'afficher.
    """
    orphelins = {item}.objects.filter(user=user, {fk}__isnull=True)
    for w in orphelins:
        try:
            b = {batch}.objects.create(user=user, total=1)
            setattr(w, '{fk}', b)
            setattr(w, '{row}', 0)
            w.save(update_fields=['{fk}', '{row}'])
        except Exception:
            pass

'''
    return tete + '\n\n\n'.join(blocs) + '\n', None
