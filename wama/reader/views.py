"""
Reader — OCR document views.
"""
import io
from wama.accounts.permissions import app_access
import os
import json
import logging
import tempfile

from django.shortcuts import render, get_object_or_404
from django.views import View
from django.http import JsonResponse, FileResponse, HttpResponse, HttpResponseBadRequest
from django.core.cache import cache
from django.views.decorators.http import require_POST
from django.db import transaction
from django.utils.http import content_disposition_header

import re

from .models import ReadingItem, BatchReadingItem, BatchReadingItemLink
from .tasks import read_document_task, _count_pdf_pages, _extract_natural_text
from wama.accounts.views import get_or_create_anonymous_user
from wama.common.utils.console_utils import get_console_lines
from wama.common.utils.input_match import input_labels as _input_labels, select_match_meta
from wama.common.utils.queue_duplication import duplicate_instance, release_card_files

logger = logging.getLogger(__name__)


def _compact_preview(text: str, max_chars: int = 400) -> str:
    """Strip markdown syntax and collapse whitespace for card compact preview."""
    if not text:
        return ''
    t = str(text)
    t = re.sub(r'^#{1,6}\s+', '', t, flags=re.MULTILINE)
    t = re.sub(r'\*{1,3}|_{1,3}', '', t)
    t = re.sub(r'^\s*[-*+]\s+', '', t, flags=re.MULTILINE)
    t = re.sub(r'\|', ' ', t)
    t = re.sub(r'`+', '', t)
    t = re.sub(r'\s+', ' ', t).strip()
    return t[:max_chars]


# `ACCEPTED_EXTENSIONS` (liste écrite ici, doublon de `OCR_INPUT_EXTENSIONS` du catalogue)
# retirée le 2026-09-26 : le dépôt lit la déclaration par `app_registry.accepts_file`.


def _get_user(request):
    if request.user.is_authenticated:
        return request.user
    return get_or_create_anonymous_user()


def _live_progress(item) -> int:
    """La progression vivante : le cache du reader est un dict `{'pct', 'msg'}`."""
    cached = cache.get(f'reader_progress_{item.id}')
    return cached.get('pct', item.progress) if cached else item.progress


def _progress_extra(item: ReadingItem) -> dict:
    """Les clés PROPRES d'une lecture que le JS du reader lit (card à jour, `upsertCard`)."""
    cached = cache.get(f'reader_progress_{item.id}')
    return {
        'filename': item.filename,
        'backend': item.backend,
        'mode': item.mode,
        'output_format': item.output_format,
        'language': item.language,
        'progress_msg': cached.get('msg', '') if cached else '',
        'page_count': item.page_count,
        'result_preview': _compact_preview(item.result_text) if item.result_text else '',
        'has_result': bool(item.result_text),
        'has_raw_result': bool(item.raw_result),
        'used_backend': item.used_backend,
        # Un optionnel DÉSACTIVÉ ne pèse plus sur la card (`ROUTE §10.6` règle 4.4) : le
        # lancement ne vide plus l'analyse, la décocher la tait.
        'analysis': item.analysis if item.generate_analysis else '',
        'created_at': item.created_at.isoformat(),
    }


def _item_to_dict(item: ReadingItem) -> dict:
    """La card à jour, rendue par les vues qui la créent ou la modifient (dépôt, duplication,
    réglages) — les mêmes clés que la vue de progression (`_pv`). L'ETA est celle du LANCEMENT :
    la somme des process qu'il jouerait (`process_runs.launch_eta`, 2026-10-13)."""
    eta = 0.0
    if item.status in ('PENDING', 'RUNNING'):
        try:
            from wama.common.services.process_runs import launch_eta
            eta = launch_eta(item) or 0.0
        except Exception:
            eta = 0.0
    return {'id': item.id, 'status': item.status, 'progress': _live_progress(item),
            'error_message': item.error_message, 'estimated_seconds': eta,
            **_progress_extra(item)}


def _wrap_reading_in_batch(reading):
    """Wrap a standalone ReadingItem in a new BatchReadingItem-of-1 (brique commune)."""
    from wama.common.utils.batch_common import wrap_in_batch
    return wrap_in_batch(reading, batch_model=BatchReadingItem,
                         item_model=BatchReadingItemLink, fk_name='reading')


def _auto_wrap_orphans(user):
    """Wrap any ReadingItem not yet in a batch into a batch-of-1 (brique commune)."""
    from wama.common.utils.batch_common import auto_wrap_orphans
    auto_wrap_orphans(user, work_model=ReadingItem, batch_model=BatchReadingItem,
                      item_model=BatchReadingItemLink, fk_name='reading')


def _chips(reading):
    """Chips de la section RÉGLAGES (card v3, CARD_DESIGN §11) : moteur EFFECTIF
    (used_backend) prioritaire sur le réglage — brique commune card_chips.

    ⚠ « X pages » n'est PLUS ici : c'est une propriété de l'ENTRÉE (mesurée sur le fichier),
    pas un réglage. La v2 les mélangeait sur une seule ligne ; la v3 sépare les sections,
    donc chaque donnée rejoint la sienne (→ _input_props)."""
    from wama.common.utils.card_chips import chips_by_section
    from wama.reader.params import PARAMS_JSON

    # Le groupement vient du SCHÉMA (section=…), pas d'un tri écrit ici : la vue ne décide pas
    # où va un chip, elle lit ce que le champ déclare (métadonnée-driven). `values=` (brique,
    # 31/08) remplace le proxy _View recopié reader/transcriber (nettoyage audit, P6) :
    # une fois le run fait, le chip moteur montre used_backend.
    return chips_by_section(reading, PARAMS_JSON,
                            values={'backend': reading.used_backend or reading.backend})


def _input_props(reading):
    """Sous-ligne « propriétés RÉELLES du média » de la section ENTRÉE (§11).

    Relevées sur le fichier déposé, jamais dérivées des réglages : type, poids, pagination.
    Équivalent reader du « mp3 · 44,1 kHz · stéréo · durée » de la maquette."""
    # ADOPTION de la brique commune (31/08) — extraite d'ICI même (pilote), le corps local
    # est retiré (dupliquer le pilote et la brique était la dérive garantie). L'axe propre
    # au reader (pages) s'INSÈRE en position 1 : l'ordre HISTORIQUE de la card est
    # ext · pages · poids — l'insertion « en tête » aurait changé l'affichage du pilote
    # (réserve levée à l'audit du 31/08 avant adoption).
    from wama.common.utils.card_chips import input_props_for
    props = input_props_for(reading, 'input_file', reading.filename or '')
    pages = getattr(reading, 'page_count', 0) or 0
    if pages:
        props.insert(1 if props else 0, f"{pages} page" + ('s' if pages > 1 else ''))
    return props


def _output_chips(reading):
    """Section SORTIE **temporelle** (§11) — prototype du futur hook commun `predicted_output()`.

    AVANT/PENDANT : chips « blueprint » (pointillés) dérivés des réglages — ce qui VA sortir.
    APRÈS         : chips solides = propriétés RÉELLES mesurées sur le résultat.
    En ÉCHEC, le template remplace la sortie par l'erreur (même piste) — rien à produire ici.

    Volontairement dans la vue reader et pas dans common/ : le §11 pose l'anatomie, mais la
    forme du hook ne sera figée qu'une fois vue en réel sur le pilote (démarche de la v2)."""
    if reading.status == 'SUCCESS' and reading.result_text:
        words = len(reading.result_text.split())
        chips = [{'label': f"{words:,} mots".replace(',', ' '),
                  'icon': 'fa-align-left', 'title': 'Mots extraits', 'variant': ''}]
        pages = getattr(reading, 'page_count', 0) or 0
        if pages:
            label = f"{pages} pages lues" if pages > 1 else "1 page lue"
            chips.append({'label': label, 'icon': 'fa-file-lines',
                          'title': 'Pages traitées', 'variant': ''})
        return chips

    # Pas encore produit → prévision, signalée comme telle (variant blueprint = pointillés).
    # Le format prévu n'est PLUS écrit ici : il vient des chips déclarés section="output" dans
    # le schéma (params.py), qu'on repasse simplement en blueprint. Ajouter un futur champ de
    # sortie au schéma suffira à le voir apparaître — aucune vue à modifier.
    blueprint = []
    for chip in (reading.chips or {}).get('output', []):
        blueprint.append(dict(chip, variant='blueprint',
                              title=(chip.get('title') or '') + ' (prévu)'))
    blueprint.append({'label': 'TXT · MD · PDF · DOCX', 'icon': 'fa-download',
                      'title': 'Formats téléchargeables après traitement',
                      'variant': 'blueprint', 'section': 'output'})
    return blueprint


def _decorate_card(reading):
    """Attache les 3 jeux de données des sections v3 à l'instance (Entrée · Réglages · Sortie).
    Point d'attache UNIQUE : appelé par IndexView ET par card_html — sinon la card rendue par
    l'endpoint diverge de celle du chargement (leçon describer)."""
    reading.chips = _chips(reading)
    reading.input_props = _input_props(reading)
    reading.output_chips = _output_chips(reading)
    return reading


def _decorate_with_processes(reading, preloaded=False):
    """Sections v3 (`_decorate_card`), puis les PROCESS de la card et son état MONTRÉ
    (`process_pipeline.decorate`, `ROUTE §10.6` 5.1) — moteur demandé « auto » compris : les
    process se montrent AVANT le premier lancement, c'est là que leurs cases à cocher servent."""
    from wama.common.services.process_pipeline import decorate
    _decorate_card(reading)
    decorate(reading, preloaded=preloaded)
    return reading


class IndexView(View):
    def get(self, request):
        user = _get_user(request)

        # Lazily wrap any orphan readings into a batch-of-1
        _auto_wrap_orphans(user)

        # Agrégats de file — brique COMMUNE (contrat toolbar/_batch_card) + enrichissements reader.
        from wama.common.utils.batch_common import build_batches_list

        def _extra(batch, items, readings):
            from wama.common.utils.card_chips import common_chips_for_items as _ccfi
            from wama.reader.params import PARAMS_JSON as _RD_PARAMS_JSON
            success_count = sum(1 for r in readings if r.status == 'SUCCESS')
            first = readings[0] if readings else None
            for r in readings:
                _decorate_card(r)     # sections card v3 (générées, CARD_DESIGN §11)
            return {
                'success_pct': int(success_count / batch.total * 100) if batch.total > 0 else 0,
                'first_backend': first.backend if first else '',
                'first_mode': first.mode if first else '',
                'first_language': first.language if first else '',
                # (l'ETA agrégée de la card mère, `eta_ids`, vient de `build_batches_list`)
                # Réglages COMMUNS aux filles (slot meta_template — porté le 31/08 ;
                # readings déjà décorées ci-dessus, attributs à jour).
                'common_chips': _ccfi(readings, _RD_PARAMS_JSON),
            }

        # Réconcilie les tâches RUNNING orphelines (worker mort/crash) — brique COMMUNE,
        # même câblage que transcriber : preuve positive de mort uniquement.
        try:
            from wama.common.utils.process_control import reconcile_orphaned_running
            running = list(ReadingItem.objects.filter(user=user, status='RUNNING'))
            reconcile_orphaned_running(running)
        except Exception:
            pass

        batches_list = build_batches_list(user, batch_model=BatchReadingItem,
                                          work_attr='reading', order_by='-id', extra=_extra)
        # Les PROCESS de chaque card (sections v3 déjà posées par `_extra`) — les lignes
        # d'exécution de la page lues en UNE requête (`decorate_cards`, 2026-10-13).
        from wama.common.services.process_pipeline import decorate_cards
        decorate_cards([link.reading for b in batches_list for link in b['items'] if link.reading])

        # Tri + filtrage de la file — brique COMMUNE (toolbar _queue_toolbar).
        from wama.common.utils.queue_view import apply_queue_sort_filter

        def _name(b):
            r = b['items'][0].reading if b['obj'].total == 1 and b['items'] and b['items'][0].reading else None
            return (r.filename or '').lower() if r else ''

        batches_list, q_sort, q_filter = apply_queue_sort_filter(request, batches_list, name_of=_name)

        queue_count = sum(len(b['items']) for b in batches_list)

        from wama.common.utils.param_schema import catalog_options
        from wama.reader.params import PARAMS, PARAMS_JSON
        return render(request, 'reader/index.html', {
            'batches_list': batches_list,
            'queue_count': queue_count,
            'q_sort': q_sort,
            'q_filter': q_filter,
            # Pré-rendu du select : LA lecture commune du domaine déclaré (clés de catalogue,
            # « auto » compris) — l'énumération du modèle a disparu avec la route F4b ⑤.
            'backend_choices': catalog_options(next(p for p in PARAMS if p.name == 'backend')),
            'mode_choices': ReadingItem.Mode.choices,
            'format_choices': ReadingItem.OutputFormat.choices,
            # Schéma params (source unique inspecteur + modale batch). Voir reader/params.py.
            'params_json': json.dumps(PARAMS_JSON),
            # Appariement entrée↔modèles (brique commune input_match) : clés catalogue =
            # valeurs du select ; 'auto' = auto_entry (brique).
            # Domaine du select lu sur sa DÉCLARATION (`backend.options_query` = `OCR_SPEC`) : clés
            # ENTIÈRES de toute source (GLM-OCR est servi par Ollama) + « auto » — brique commune
            # depuis le 2026-10-13.
            'input_match_meta': json.dumps(select_match_meta('reader', 'backend')),
            'input_labels': json.dumps(_input_labels()),
        })


def new_reading_settings(user, model=None, app='reader', post=None) -> dict:
    """Les colonnes de réglage d'une lecture NAISSANTE, par la cascade COMMUNE (défauts du
    schéma ← réglages de l'auteur ← ce que le dépôt poste, `user_settings.new_element_settings`,
    2026-10-18). Le dépôt de la card, le lot et l'import du gestionnaire de fichiers (« Envoyer
    vers », sans volet donc sans POST) passent ici ; `model`/`app` : une jumelle de bac à sable
    passe les siens. Le curseur rapide/qualité n'a pas de colonne : la brique l'écarte, et
    `quality_intent_of` le relit au lancement dans les réglages de l'auteur. Une langue postée
    VIDE (détection automatique voulue) retire la préférence au dépôt : le défaut, vide, joue."""
    from wama.common.utils.user_settings import new_element_settings
    from wama.reader.params import PARAMS_JSON, user_setting_key
    return new_element_settings(user, app, PARAMS_JSON, model or ReadingItem, post=post,
                                key=user_setting_key, empty_is_value=SETTINGS_EMPTY_IS_VALUE)


def _deposit_settings(user, post):
    """Les réglages d'un DÉPÔT (fichiers, lot) : ce que le volet poste est gardé comme
    préférences (`save_panel_settings`, curseur compris), puis la lecture naît par la cascade."""
    from wama.common.utils.user_settings import save_panel_settings
    from wama.reader.params import PARAMS_JSON, user_setting_key
    save_panel_settings(user, 'reader', PARAMS_JSON, post, key=user_setting_key)
    return new_reading_settings(user, post=post)


@require_POST
def upload(request):
    """Upload one or more files to the reading queue."""
    user = _get_user(request)
    # Fichiers TÉLÉVERSÉS et/ou DÉSIGNÉS (médiathèque, arbre) — brique `received_inputs` : une
    # désignation se POINTE au lieu d'être recopiée, avec le même état du volet.
    from wama.common.utils.media_paths import received_inputs
    files = received_inputs(request, user, 'reader', field='files')
    if not files:
        return JsonResponse({'error': files.refusal or 'Aucun fichier reçu'}, status=400)

    # Tous les réglages, ceux du pipeline compris, par la cascade COMMUNE d'un dépôt.
    reading = _deposit_settings(user, request.POST)

    from wama.common.app_registry import accepts_file
    items_created = []
    created = []
    for f in files:
        ext = os.path.splitext(f.name)[1].lower()
        if not accepts_file('reader', f.name):
            continue  # un fichier refusé ne crée rien ; si AUCUN ne passe, la vue le DIT

        item = ReadingItem.objects.create(
            user=user,
            input_file=f.value,
            original_filename=f.name,
            status='PENDING',
            **reading,
        )
        f.record(item, 'input_file')

        # Count PDF pages immediately (quick, synchronous)
        if ext == '.pdf':
            try:
                n = _count_pdf_pages(item.input_file.path)
                if n:
                    item.page_count = n
                    item.save(update_fields=['page_count'])
            except Exception:
                pass

        items_created.append(item)
        created.append(_item_to_dict(item))

    if not items_created:
        # Un refus se DIT : le 200 vide laissait la brique d'import sans rien afficher.
        return JsonResponse({'created': [], 'error': 'Aucun fichier au format pris en charge'},
                            status=400)

    if len(items_created) > 1:
        # Multiple files → one multi-item batch
        batch = BatchReadingItem.objects.create(user=user, total=len(items_created))
        for i, item in enumerate(items_created):
            BatchReadingItemLink.objects.create(batch=batch, reading=item, row_index=i)
        return JsonResponse({'created': created, 'batch_id': batch.id, 'multi': True})
    else:
        _wrap_reading_in_batch(items_created[0])
        return JsonResponse({'created': created})


@require_POST
@app_access('reader')
def stop(request, pk: int):
    """
    Stoppe l'OCR en cours (révoque la tâche Celery) → item relançable (bouton de cycle ↻).
    Brique commune : wama.common.utils.process_control.stop_instance.
    """
    user = _get_user(request)
    from wama.common.utils.scoping import editable_or_404
    item = editable_or_404(ReadingItem, user, pk=pk)
    if item.status not in ('RUNNING', 'PENDING'):
        return JsonResponse({'id': item.id, 'status': item.status})
    from wama.common.utils.process_control import stop_instance
    new_status = stop_instance(item, to_status='FAILURE')   # FAILURE = état terminal relançable côté Reader
    return JsonResponse({'id': item.id, 'status': new_status})


def _reset_for_relaunch(item):
    """Remise à zéro avant (re)lancement — appliquée SOUS le verrou anti-race.

    ⚠ Depuis le 2026-10-13 la card porte un PIPELINE (`function_specs.PIPELINE`) : un lancement
    ne rejoue que ce qui n'est plus à jour. Le résultat d'un process s'efface donc QUAND CE
    PROCESS EST REJOUÉ (sa glu le réécrit, `tasks.PROCESSES`), plus ici — sinon relancer la seule
    analyse effacerait le texte qu'elle analyse (la règle du transcriber et du describer)."""
    item.error_message = ''
    item.progress = 0


#: Ce qu'une card DUPLIQUÉE ne porte pas de son original : ses résultats, ceux de chaque process.
#: Une seule liste pour la duplication d'un élément et celle d'un lot (`make_batch_views`).
DUPLICATE_RESET = {'result_text': '', 'raw_result': '', 'used_backend': '', 'analysis': ''}


# ── Les SIX vues de lot : fabrique COMMUNE (`batch_views.make_batch_views`, portage 2026-09-23,
# 2ᵉ app réelle — ROUTE §11 #36). Spécificités du reader DÉCLARÉES en kwargs : remise à zéro
# sous verrou (`_reset_for_relaunch`), cache de progression `reader_progress_<id>` (un dict
# `{'pct': …}`, lu par `batch_status`, purgé à la suppression), `result_text`/`used_backend`
# vidés à la duplication, `language` vide = auto-détection (VALEUR, pas absence), gating
# `@app_access` sur le démarrage. `batch_download` vient AUSSI de la fabrique depuis le
# 2026-10-02 : le format se choisit au téléchargement (`export_binding='late'`), la fabrique lit
# les formats DÉCLARÉS au catalogue et le rendu ENREGISTRÉ (`build_reading_bytes`, `apps.py`) —
# la vue locale recopiait les deux en dur. Seule la souche de chaque entrée reste dite ici.
from wama.common.utils.batch_views import DEFAULT_RESET, make_batch_views
from wama.reader.params import PARAMS_JSON as _SCHEMA


def _output_stem(r):
    """Souche du nom d'une lecture RENDUE dans un ZIP de lot — règle commune de nommage
    (`compose_output_name`) sur le nom d'origine du fichier ; l'extension vient du rendu."""
    from wama.common.utils.output_naming import compose_output_name
    return os.path.splitext(compose_output_name(
        app='reader', source_name=r.filename or f'item_{r.id}', item_id=r.id))[0]


#: Réglages d'une lecture écrits par la modale ⚙, le volet et la modale de LOT (schéma `params.py`).
SETTINGS_FIELDS = ('backend', 'mode', 'output_format', 'language', 'llm_model',
                   'llm_temperature', 'llm_seed', 'llm_top_p', 'format_markdown',
                   'generate_analysis')
#: `language` vide EST une valeur (auto-détection) — lu par la route d'élément et par la fabrique.
SETTINGS_EMPTY_IS_VALUE = ('language',)


def _apply_reading_settings(item, data):
    """LES réglages d'une lecture, posés sans sauver — rend les champs touchés. La route d'un
    élément (`update_settings`) ET la fabrique des vues de lot passent ici : les deux listes de
    champs écrites à deux endroits avaient divergé (le lot ignorait `output_format`, pourtant
    affiché dans sa modale — trouvé par `tests_item_settings_contract`, 2026-10-02).
    L'écrivain COMMUN ignore une valeur hors des choix du modèle."""
    from wama.common.utils.batch_views import apply_item_settings
    if 'language' in data:
        data = {**data, 'language': str(data['language'] or '').strip()[:16]}
    return apply_item_settings(item, data, params_fields=SETTINGS_FIELDS)


_bv = make_batch_views(
    work_model=ReadingItem, batch_model=BatchReadingItem, get_user=_get_user,
    task=read_document_task,
    output_fields=(),
    schema=_SCHEMA, empty_is_value=SETTINGS_EMPTY_IS_VALUE,
    apply_settings=_apply_reading_settings,
    item_model=BatchReadingItemLink, fk_name='reading',
    reset_on_start=_reset_for_relaunch,
    reset_on_duplicate={**DEFAULT_RESET, **DUPLICATE_RESET},
    progress_of=lambda r: (cache.get(f'reader_progress_{r.id}') or {}).get('pct', r.progress),
    on_delete=lambda r: cache.delete(f'reader_progress_{r.id}'),
    output_name=_output_stem,
)
batch_start = app_access('reader')(_bv['batch_start'])
batch_update = _bv['batch_update']
batch_delete = _bv['batch_delete']
batch_duplicate = _bv['batch_duplicate']
batch_download = _bv['batch_download']
batch_status = _bv['batch_status']
batch_promote = _bv['batch_promote']
batch_realign = _bv['batch_realign']


@app_access('reader')
@require_POST   # un GET lançait la lecture (parcours des adresses, 2026-09-22)
def start(request, pk: int):
    """Start OCR processing for a single item — anti-race via la brique commune."""
    user = _get_user(request)
    from wama.common.utils.process_control import begin_processing
    item, err = begin_processing(ReadingItem, pk, user=user, reset=_reset_for_relaunch)
    if err == 'not_found':
        return JsonResponse({'error': 'Not found'}, status=404)
    if err == 'already_running':
        return JsonResponse({'error': 'Déjà en cours'}, status=409)

    task = read_document_task.delay(item.id)
    item.task_id = task.id
    item.save(update_fields=['task_id'])
    return JsonResponse({'ok': True, 'task_id': task.id})


from wama.common.utils.process_views import make_process_start_view  # noqa: E402

# ▶ d'UN process de la card (`ROUTE §10.6` 5.1) : fabrique COMMUNE — c'est aussi la mise en forme
# ou l'analyse « à la demande » sur un texte déjà lu.
start_process = app_access('reader')(make_process_start_view(
    work_model=ReadingItem, task_for=lambda r: read_document_task,
    get_user=_get_user, reset_on_start=_reset_for_relaunch))


def card_html(request, pk: int):
    """Card RENDUE serveur — source UNIQUE du markup v3 (partial _item_card.html ;
    CARD_DESIGN §3, update JS en place). `in_batch` : position dans la file, brique commune."""
    from wama.common.utils.batch_common import is_batch_child
    from wama.common.utils.scoping import visible_or_404  # lecture → partage F7
    item = visible_or_404(ReadingItem, _get_user(request), pk=pk)
    _decorate_with_processes(item)
    return render(request, 'reader/_item_card.html',
                  {'elem': item, 'in_batch': is_batch_child(item)})


# Les vues de PROGRESSION : fabrique COMMUNE (`progress_views.make_progress_views`, ROUTE §11 #37,
# 2026-10-03) — l'app n'y déclare que sa progression vivante (un dict au cache) et ses clés
# propres. Plus de triplet d'ETA de vue depuis le pipeline (2026-10-13) : la card s'estime à la
# SOMME de ses process, chacun déclarant le sien (`ProcessSpec.eta`, `tasks.*_eta`).
from wama.common.utils.progress_views import make_progress_views  # noqa: E402

_pv = make_progress_views(work_model=ReadingItem, app_id='reader',
                          progress_of=_live_progress, extra=_progress_extra)
progress, global_progress = _pv['progress'], _pv['global_progress']


def download(request, pk: int):
    """Download the OCR result. Supported formats: txt (default), md, pdf, docx, json."""
    from wama.common.utils.scoping import visible_or_404  # lecture → partage F7
    item = visible_or_404(ReadingItem, _get_user(request), pk=pk)

    fmt = request.GET.get('format', 'txt').lower()
    # SOUCHE par la BRIQUE COMMUNE (`compose_output_name`) — le reader composait
    # `{base}_ocr` a la main sur 8 sites. Le tag `ocr` est DECLARE (table des mots de
    # process), donc la convention que l'utilisateur connait est preservee ; s'ajoute
    # l'identifiant de card, qui rend le nom unique quand deux lectures du meme fichier
    # coexistent — et qui permet la comparaison entre modeles (demande Fabien 11/09).
    from wama.common.utils.output_naming import compose_output_name
    base = os.path.splitext(compose_output_name(
        app='reader', source_name=item.filename, item_id=item.pk))[0]

    # JSON format — serve raw backend output
    if fmt == 'json':
        if not item.raw_result:
            return HttpResponseBadRequest('Pas de données JSON disponibles')
        buffer = io.BytesIO(item.raw_result.encode('utf-8'))
        buffer.seek(0)
        return FileResponse(
            buffer,
            as_attachment=True,
            filename=f"{base}_raw.json",
            content_type='application/json; charset=utf-8',
        )

    if not item.result_text:
        return HttpResponseBadRequest('Pas encore de résultat')

    if fmt == 'pdf':
        try:
            from wama.common.utils.document_export import generate_reader_pdf
            pdf_bytes = generate_reader_pdf(item)
            response = HttpResponse(pdf_bytes, content_type='application/pdf')
            response['Content-Disposition'] = content_disposition_header(True, f"{base}.pdf")
            return response
        except ImportError as e:
            return HttpResponseBadRequest(str(e))
        except Exception as e:
            logger.error(f"[Reader] PDF generation failed: {e}")
            return HttpResponseBadRequest(f'Erreur PDF : {e}')

    if fmt == 'docx':
        try:
            from wama.common.utils.document_export import generate_reader_docx
            docx_bytes = generate_reader_docx(item)
            response = HttpResponse(
                docx_bytes,
                content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            )
            response['Content-Disposition'] = content_disposition_header(True, f"{base}.docx")
            return response
        except ImportError as e:
            return HttpResponseBadRequest(str(e))
        except Exception as e:
            logger.error(f"[Reader] DOCX generation failed: {e}")
            return HttpResponseBadRequest(f'Erreur DOCX : {e}')

    # txt / md (default)
    is_md = (fmt == 'md')
    ext = '.md' if is_md else '.txt'
    content_type = 'text/markdown' if is_md else 'text/plain'
    buffer = io.BytesIO(_extract_natural_text(item.result_text).encode('utf-8'))
    buffer.seek(0)
    return FileResponse(
        buffer,
        as_attachment=True,
        filename=f"{base}{ext}",
        content_type=f'{content_type}; charset=utf-8',
    )


@require_POST
def delete(request, pk: int):
    """Delete an item and its input file (if not shared). Also removes parent batch-of-1."""
    item = get_object_or_404(ReadingItem, pk=pk, user=_get_user(request))
    # Lot de l'élément, relevé AVANT la suppression — brique commune (`batch_common`).
    from wama.common.utils.batch_common import batch_snapshot, batch_state
    snapshot = batch_snapshot(item)
    release_card_files(item)
    cache.delete(f'reader_progress_{pk}')
    item.delete()  # signal batch_sync : recale total / supprime le batch vidé (+ son fichier batch)
    return JsonResponse({'deleted': pk, 'batch': batch_state(snapshot, ReadingItem)})


@require_POST
def duplicate(request, pk: int):
    """Duplicate an item, sharing the input file but resetting all results."""
    user = _get_user(request)
    from wama.common.utils.scoping import duplicable_or_404
    item = duplicable_or_404(ReadingItem, user, pk=pk)
    new_item = duplicate_instance(
        item,
        for_user=user,
        reset_fields={
            'status': 'PENDING',
            'progress': 0,
            'task_id': '',
            'error_message': '',
            **DUPLICATE_RESET,
        },
    )
    # 'duplicated' = contrat de la brique commune queue-actions.js (focus + reload)
    return JsonResponse({**_item_to_dict(new_item), 'duplicated': new_item.id})


@require_POST
@app_access('reader')
def start_all(request):
    """Start all PENDING items for the current user."""
    user = _get_user(request)
    from wama.common.utils.process_control import begin_processing
    items = ReadingItem.objects.filter(user=user, status='PENDING').order_by('-created_at')
    count = 0
    for item in items:
        item, err = begin_processing(ReadingItem, item.pk, user=user, reset=_reset_for_relaunch)
        if err:
            continue
        task = read_document_task.delay(item.id)
        item.task_id = task.id
        item.save(update_fields=['task_id'])
        count += 1
    return JsonResponse({'started': count})



# ⬇ « Télécharger tout » de la barre de file : le ZIP de la file que compte la barre globale,
# par la fabrique commune (`make_progress_views`, 2026-10-17 — REMOVAL_LEDGER R142).
download_all = _pv['download_all']


@require_POST
def clear_all(request):
    """Delete all items and batches for the current user."""
    user = _get_user(request)
    items = ReadingItem.objects.filter(user=user)
    for item in items:
        release_card_files(item)
        cache.delete(f'reader_progress_{item.id}')
    items.delete()
    # Clean up orphan batch containers and their files
    batches = BatchReadingItem.objects.filter(user=user)
    for batch in batches:
        release_card_files(batch)
    batches.delete()
    return JsonResponse({'ok': True})


@require_POST
def update_settings(request, pk: int):
    """Update per-item OCR settings (backend, mode, output_format, language)."""
    from wama.common.utils.scoping import editable_or_404
    item = editable_or_404(ReadingItem, _get_user(request), pk=pk)
    # JSON (inspecteur) OU FormData (modale ⚙ par le cycle commun `WamaParams.settingsModal`,
    # portage 2026-09-24) : le lecteur COMMUN des réglages postés, coercé au schéma — `language`
    # vide EST une valeur (auto-détection), comme pour la vue de lot, qui appelle la même fonction.
    from wama.common.utils.batch_views import read_settings_payload
    data = read_settings_payload(request, _SCHEMA, [p['name'] for p in _SCHEMA],
                                 empty_is_value=SETTINGS_EMPTY_IS_VALUE)
    touched = _apply_reading_settings(item, data)
    if touched:
        item.save(update_fields=touched)
    return JsonResponse(_item_to_dict(item))


@require_POST
def analyze(request, pk: int):
    """L'analyse LLM (résumé + points clés) d'un texte déjà lu — depuis le pipeline (2026-10-13),
    le process OPTIONNEL `analyze` : son interrupteur s'active et SON ▶ est joué (le texte lu et
    sa mise en forme restent en place)."""
    from wama.common.utils.scoping import editable_or_404
    item = editable_or_404(ReadingItem, _get_user(request), pk=pk)

    if not item.result_text:
        return JsonResponse({'error': 'Pas encore de texte extrait'}, status=400)

    if not item.generate_analysis:
        item.generate_analysis = True
        item.save(update_fields=['generate_analysis'])
    return start_process(request, pk, 'analyze')


def batch_template(request):
    """Download a batch file template (.txt)."""
    template_content = (
        "# WAMA Reader - Batch Import\n"
        "# Format : une URL ou chemin de fichier par ligne\n"
        "# Les lignes commençant par # sont des commentaires.\n"
        "# Formats supportés : PDF, JPG, PNG, TIFF, WebP\n"
        "\n"
        "https://example.com/document.pdf\n"
        "/media/uploads/scan.jpg\n"
    )
    response = HttpResponse(template_content, content_type='text/plain; charset=utf-8')
    response['Content-Disposition'] = 'attachment; filename="batch_reader_template.txt"'
    return response


@require_POST
def batch_preview(request):
    """Parse a batch file (one URL/path per line) and return the list for preview."""
    from wama.common.utils.batch_parsers import batch_media_list_preview_response
    return batch_media_list_preview_response(request)


@require_POST
def batch_create(request):
    """
    Parse batch file (URLs/paths), create BatchReadingItem + ReadingItem entries.
    Files are not downloaded yet — download happens when each task starts.
    """
    from wama.common.utils.batch_parsers import parse_batch_file_from_request

    user = _get_user(request)
    # Chaque fille naît par la cascade COMMUNE, comme un fichier déposé (2026-10-18) : elle lisait
    # quatre réglages dans le POST, avec leur défaut écrit ici, et pas ceux du pipeline.
    reading_settings = _deposit_settings(user, request.POST)

    try:
        items, warnings = parse_batch_file_from_request(request)
    except ValueError as e:
        return JsonResponse({'error': str(e)}, status=400)

    if not items:
        return JsonResponse({'error': 'Aucun élément valide trouvé dans le fichier'}, status=400)

    batch_file = request.FILES.get('batch_file')
    batch = BatchReadingItem.objects.create(
        user=user,
        total=len(items),
        batch_file=batch_file,
    )

    created_ids = []
    for i, item in enumerate(items):
        url_or_path = item['path']
        fname = url_or_path.split('/')[-1].split('\\')[-1] or url_or_path

        reading = ReadingItem.objects.create(
            **reading_settings,
            user=user,
            source_url=url_or_path,
            original_filename=fname,
            status='PENDING',
        )
        BatchReadingItemLink.objects.create(batch=batch, reading=reading, row_index=i)
        created_ids.append(reading.id)

    return JsonResponse({
        'batch_id': batch.id,
        'reading_ids': created_ids,
        'total': len(items),
        'warnings': warnings,
    })


def batch_list(request):
    """List the current user's batches with status counts."""
    user = _get_user(request)
    batches = BatchReadingItem.objects.filter(user=user).prefetch_related('items__reading')

    from wama.common.utils.batch_common import batch_elements
    data = []
    for batch in batches:
        counts = {'success': 0, 'running': 0, 'pending': 0, 'failure': 0}
        for r in batch_elements(batch, ReadingItem):     # lit le cache du prefetch, 0 requête
            k = r.status.lower()
            counts[k] = counts.get(k, 0) + 1

        total = batch.total
        if total > 0 and counts['success'] == total:
            status = 'SUCCESS'
        elif counts['running'] > 0:
            status = 'RUNNING'
        elif counts['pending'] == 0 and counts['running'] == 0 and counts['failure'] > 0:
            status = 'FAILURE'
        else:
            status = 'PENDING'

        data.append({
            'id': batch.id,
            'created_at': batch.created_at.strftime('%d/%m/%Y %H:%M'),
            'total': total,
            'status': status,
            'counts': counts,
        })

    return JsonResponse({'batches': data})


# Manipulation directe de la file (CARD_DESIGN §3bis) — vues GÉNÉRÉES par la brique commune.
from wama.common.utils.queue_manipulation import make_queue_manipulation_views

_qm = make_queue_manipulation_views(
    work_model=ReadingItem, batch_model=BatchReadingItem,
    item_model=BatchReadingItemLink, fk_name='reading', get_user=_get_user,
)
remove_from_batch = _qm['remove_from_batch']
reorder = _qm['reorder']
reorder_queue = _qm['reorder_queue']
merge = _qm['merge']
move_to_batch = _qm['move_to_batch']
consolidate = _qm['consolidate']


def build_reading_bytes(item, fmt):
    """Return (ext, bytes) for an OCR result in `fmt` (txt/md/pdf/docx/json), or None.

    Shared format builder for the batch ZIP dropdown (WAMA_APP_CONVENTIONS §9.10).
    """
    fmt = (fmt or 'txt').lower()
    if fmt == 'json':
        if not item.raw_result:
            return None
        return ('json', item.raw_result.encode('utf-8'))
    if not item.result_text:
        return None
    if fmt == 'pdf':
        try:
            from wama.common.utils.document_export import generate_reader_pdf
            return ('pdf', generate_reader_pdf(item))
        except Exception as e:
            logger.warning(f"[Reader] PDF skipped for {item.id}: {e}")
            return None
    if fmt == 'docx':
        try:
            from wama.common.utils.document_export import generate_reader_docx
            return ('docx', generate_reader_docx(item))
        except Exception as e:
            logger.warning(f"[Reader] DOCX skipped for {item.id}: {e}")
            return None
    ext = 'md' if fmt == 'md' else 'txt'
    return (ext, _extract_natural_text(item.result_text).encode('utf-8'))




def console_content(request):
    user = _get_user(request)
    lines = get_console_lines(user.id)
    return JsonResponse({'lines': lines})


