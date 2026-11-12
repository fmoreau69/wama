"""
Reader — OCR document views.
"""
import io
import os
import json
import logging
import tempfile

from django.shortcuts import render
from django.views import View
from django.http import JsonResponse, FileResponse
from django.core.cache import cache
from django.views.decorators.http import require_POST
from django.db import transaction
from django.utils.http import content_disposition_header

from .models import ReadingItem, BatchReadingItem, BatchReadingItemLink
from .tasks import read_document_task, _count_pdf_pages, _extract_natural_text
from wama.accounts.views import get_or_create_anonymous_user
from wama.common.utils.console_utils import get_console_lines
from wama.common.utils.input_match import input_labels as _input_labels, select_match_meta

logger = logging.getLogger(__name__)


def _compact_preview(text: str, max_chars: int = 400) -> str:
    """L'extrait d'une lecture pour l'API : son texte sans la syntaxe Markdown, sur une ligne.
    La syntaxe se retire par LA règle commune (`document_export.strip_markdown`, 2026-10-29) — la
    copie qui vivait ici retirait chaque `_` et chaque `*`, et un `nom_de_fichier` lu par l'OCR
    sortait `nomdefichier`, le défaut corrigé le 28/10 dans la règle commune."""
    if not text:
        return ''
    from wama.common.utils.document_export import strip_markdown
    return ' '.join(strip_markdown(str(text)).split())[:max_chars]


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
    """La card à jour, rendue par le dépôt — les mêmes clés que la vue de progression (`_pv`) ; la
    duplication et les réglages viennent de la fabrique commune (`_iv`, 2026-11-01). L'ETA est celle du LANCEMENT :
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


def _shown_title(reading, batch_readings=None) -> str:
    """Le titre que la card AFFICHE (2026-11-08) : celui qu'elle a lu sur sa partition, sinon celui
    de son lot (`batch_identity.content_title` — une page sans titre prend celui d'une autre page du
    même lot), suivi du numéro de page lu. `batch_readings` : les cards du lot, déjà lues (la file) ;
    sinon lues ici (la card rendue seule)."""
    from wama.common.services.batch_identity import content_title
    title = reading.read_title
    # Seule une page lue comme partition hérite d'un titre (une card de texte ne paie aucune requête).
    if not title and reading.read_as_score:
        if batch_readings is None:
            from wama.common.utils.batch_common import batch_elements, batch_of
            batch = batch_of(reading)
            batch_readings = batch_elements(batch, ReadingItem) if batch else []
        title = content_title(batch_readings)
    if title and reading.score_page and getattr(reading.score_file, 'name', ''):
        title = f"{title} — p. {reading.score_page}"
    return title


def _decorate_card(reading, batch_readings=None):
    """Attache les 3 jeux de données des sections v3 à l'instance (Entrée · Réglages · Sortie).
    Point d'attache UNIQUE : appelé par IndexView ET par card_html — sinon la card rendue par
    l'endpoint diverge de celle du chargement (leçon describer)."""
    reading.chips = _chips(reading)
    reading.input_props = _input_props(reading)
    reading.output_chips = _output_chips(reading)
    reading.shown_title = _shown_title(reading, batch_readings)
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
                _decorate_card(r, readings)     # sections card v3 (générées, CARD_DESIGN §11)
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

        # Réconcilie les éléments RUNNING orphelins (worker mort/crash) — LA brique commune.
        from wama.common.utils.process_control import reconcile_queue_of
        reconcile_queue_of(ReadingItem, user)

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


def new_reading_settings(user, model=None, app='reader', post=None, inputs=None) -> dict:
    """Les colonnes de réglage d'une lecture NAISSANTE, par la cascade COMMUNE (défauts du
    schéma ← réglages de l'auteur ← ce que le dépôt poste, `user_settings.new_element_settings`,
    2026-10-18). Le dépôt de la card, le lot et l'import du gestionnaire de fichiers (« Envoyer
    vers », sans volet donc sans POST) passent ici ; `model`/`app` : une jumelle de bac à sable
    passe les siens. Le curseur rapide/qualité n'a pas de colonne : la brique l'écarte, et
    `quality_intent_of` le relit au lancement dans les réglages de l'auteur. Une langue postée
    VIDE (détection automatique voulue) retire la préférence au dépôt : le défaut, vide, joue."""
    from wama.common.utils.user_settings import new_element_settings
    from wama.reader.params import PARAMS_JSON
    return new_element_settings(user, app, PARAMS_JSON, model or ReadingItem, post=post,
                                inputs=inputs, empty_is_value=SETTINGS_EMPTY_IS_VALUE)


def _deposit_settings(user, post, inputs=None):
    """Les réglages d'un DÉPÔT (fichiers, lot) : ce que le volet poste est gardé comme
    préférences (`save_panel_settings`, curseur compris), puis la lecture naît par la cascade —
    `inputs` : le fichier reçu, sous son port, qui propose ses réglages (`inputs_by_port`)."""
    from wama.common.utils.user_settings import save_panel_settings
    from wama.reader.params import PARAMS_JSON
    save_panel_settings(user, 'reader', PARAMS_JSON, post)
    return new_reading_settings(user, post=post, inputs=inputs)


def _joined_pages(post, files):
    """Les fichiers reçus, où plusieurs IMAGES arrivées ensemble deviennent UN PDF de ces pages
    quand l'utilisateur l'a choisi AU DÉPÔT (la case « un seul document » de la brique d'import,
    `join_pages` — un choix du dépôt, pas un réglage d'élément) : une seule card lit alors le
    document entier (2026-11-10). Le PDF suit l'ordre du dépôt ; il est NEUF (ni téléversé ni
    désigné, il n'a pas de provenance à retenir). Un PDF, une seule image, la case décochée : rien
    ne change."""
    from contextlib import ExitStack

    from django.core.files.base import ContentFile

    from wama.common.app_registry import category_of_path
    from wama.common.utils.media_paths import ReceivedInput
    from wama.common.utils.param_schema import TRUTHY
    from wama.common.utils.pdf_pages import pages_to_pdf
    from wama.common.utils.work_dir import work_dir
    images = [f for f in files if category_of_path(f.name) == 'image']
    # Ce que poste la case « un seul document » de la brique d'import (`WamaImport`, `joinPages`),
    # lu par la règle d'un interrupteur du schéma.
    if len(images) < 2 or str(post.get('join_pages', '')).strip().lower() not in TRUTHY:
        return files
    with work_dir('reader_join') as folder, ExitStack() as stack:
        paths = [stack.enter_context(f.readable_path()) for f in images]
        stem = os.path.splitext(images[0].name)[0]
        target = pages_to_pdf(paths, str(folder / f'{stem}.pdf'))
        from pathlib import Path
        joined = ReceivedInput(f'{stem}.pdf', ContentFile(Path(target).read_bytes(), name=f'{stem}.pdf'))
    return [joined] + [f for f in files if f not in images]


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
    files = _joined_pages(request.POST, files)

    from wama.common.app_registry import accepts_file
    from wama.common.utils.user_settings import inputs_by_port
    items_created = []
    created = []
    for f in files:
        ext = os.path.splitext(f.name)[1].lower()
        if not accepts_file('reader', f.name):
            continue  # un fichier refusé ne crée rien ; si AUCUN ne passe, la vue le DIT

        # Chaque fichier PROPOSE ses réglages (`default_from`) ; sans proposition, ceux du dépôt.
        inputs = inputs_by_port('reader', f)
        item = ReadingItem.objects.create(
            user=user,
            input_file=f.value,
            original_filename=f.name,
            status='PENDING',
            **(new_reading_settings(user, post=request.POST, inputs=inputs) if inputs else reading),
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

    # Les fichiers arrivés ENSEMBLE se rangent par la brique commune (`consolidate_arrival` : un lot,
    # ou le lot d'un élément seul) — cette vue construisait le sien jusqu'au 2026-11-10, seule app
    # hors de la brique (inventaire des files, PROJECT_STATUS §PALIER 2026-11-10).
    from wama.common.utils.queue_manipulation import consolidate_arrival
    lots = consolidate_arrival(ReadingItem, [item.pk for item in items_created], user)
    if len(items_created) > 1:
        return JsonResponse({'created': created, 'batch_id': lots[0].id, 'multi': True})
    return JsonResponse({'created': created})


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
# vidés à la duplication, `language` vide = auto-détection (VALEUR, pas absence).
# `batch_download` vient AUSSI de la fabrique depuis le
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
# Les colonnes de réglage, DÉRIVÉES du schéma (2026-11-08, comme l'avatarizer) : la liste écrite à
# la main ici n'aurait pas suivi la case « Lire une partition » et son modèle. Le curseur
# (`quality_intent`) est un réglage d'app de l'utilisateur, pas une colonne : écarté.
SETTINGS_FIELDS = tuple(p['name'] for p in _SCHEMA
                        if p['name'] in {f.name for f in ReadingItem._meta.concrete_fields})
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
batch_start = _bv['batch_start']
batch_update = _bv['batch_update']
batch_delete = _bv['batch_delete']
batch_duplicate = _bv['batch_duplicate']
batch_download = _bv['batch_download']
batch_status = _bv['batch_status']
batch_promote = _bv['batch_promote']
batch_realign = _bv['batch_realign']


# ▶ de la card, ▶ et 🗑 de la file : fabrique COMMUNE (`item_views.make_item_views`, ROUTE §11
# #39, 2026-10-29) — la même déclaration que lit l'outil `start_reader` de l'assistant.
from wama.common.utils.item_views import make_item_views  # noqa: E402

_iv = make_item_views(work_model=ReadingItem, app_id='reader', task=read_document_task,
                      get_user=_get_user, reset_on_start=_reset_for_relaunch,
                      batch_model=BatchReadingItem)
start = _iv['start']
start_all = _iv['start_all']
clear_all = _iv['clear_all']
# ⏹ ⬇ 🗑 ⧉ ⚙ d'une card : la même fabrique (2026-11-01, ROUTE §11 #42 ④), qui les lit à la
# déclaration de `_bv` ci-dessus — `DUPLICATE_RESET`, cache purgé, rendu nommé par `_output_stem`,
# `_apply_reading_settings`. La copie d'une card a désormais sa place dans la file dès sa naissance
# (elle restait orpheline jusqu'au prochain affichage de la page).
stop = _iv['stop']
delete, duplicate = _iv['delete'], _iv['duplicate']
download, update_settings = _iv['download'], _iv['update_settings']


from wama.common.utils.process_views import make_process_start_view  # noqa: E402

# ▶ d'UN process de la card (`ROUTE §10.6` 5.1) : fabrique COMMUNE — c'est aussi la mise en forme
# ou l'analyse « à la demande » sur un texte déjà lu.
start_process = make_process_start_view(
    work_model=ReadingItem, task_for=lambda r: read_document_task,
    get_user=_get_user, reset_on_start=_reset_for_relaunch)


# Card RENDUE serveur — source UNIQUE du markup v3 (partial _item_card.html) : fabrique commune
# (`make_card_view`, 2026-11-02).
from wama.common.utils.item_views import make_card_view  # noqa: E402

card_html = make_card_view(work_model=ReadingItem, template='reader/_item_card.html',
                           decorate=lambda item: _decorate_with_processes(item))


# Les vues de PROGRESSION : fabrique COMMUNE (`progress_views.make_progress_views`, ROUTE §11 #37,
# 2026-10-03) — l'app n'y déclare que sa progression vivante (un dict au cache) et ses clés
# propres. Plus de triplet d'ETA de vue depuis le pipeline (2026-10-13) : la card s'estime à la
# SOMME de ses process, chacun déclarant le sien (`ProcessSpec.eta`, `tasks.*_eta`).
from wama.common.utils.progress_views import make_progress_views  # noqa: E402

_pv = make_progress_views(work_model=ReadingItem, app_id='reader',
                          progress_of=_live_progress, extra=_progress_extra)
progress, global_progress = _pv['progress'], _pv['global_progress']


# ⬇ « Télécharger tout » de la barre de file : le ZIP de la file que compte la barre globale,
# par la fabrique commune (`make_progress_views`, 2026-10-17 — REMOVAL_LEDGER R142).
download_all = _pv['download_all']


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
    """Gabarit de fichier batch, par la brique commune (`batch_template_response`) : une source
    par ligne, les formats que l'app DÉCLARE (la liste était recopiée ici, et plus courte).
    Écrit à la main jusqu'au 2026-11-02."""
    from wama.common.utils.batch_parsers import batch_template_response
    return batch_template_response(
        'reader', ['source'], {'source': 'https://example.com/document.pdf'},
        label='Reader (une URL ou un chemin de document ou d’image par ligne)')


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
    # La PARTITION lue (2026-11-08) : ses deux fichiers, tels qu'ils sont (l'ABC corrigée compris).
    if fmt in ('abc', 'musicxml'):
        field = item.score_file if fmt == 'abc' else item.score_musicxml
        if not getattr(field, 'name', ''):
            return None
        try:
            with field.open('rb') as handle:
                return (fmt, handle.read())
        except OSError:
            return None
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
    text = _extract_natural_text(item.result_text)
    if fmt == 'md':
        return ('md', text.encode('utf-8'))
    # TXT = du texte BRUT : la mise en forme Markdown en est retirée (décision de Fabien,
    # 2026-10-28 — « le choix du fichier de sortie définit de lui-même si on retire la mise en
    # forme ») ; elle y partait telle quelle (`#`, `**`, `|`).
    from wama.common.utils.document_export import strip_markdown
    return ('txt', strip_markdown(text).encode('utf-8'))


def reading_lot_formats(items):
    """Les formats en lesquels un lot du reader se combine en UN fichier : ceux du groupe PARTITION
    quand toutes ses cards sont des partitions (`holds_score`) — les pages d'une œuvre ; aucun pour
    un lot de textes, que le commun réunit (`export_formats._joined_texts`). Lus par leur groupe au
    vocabulaire commun, jamais recopiés."""
    from wama.common.utils.export_formats import SCORE, entries_for_app
    from wama.reader.function_specs import holds_score
    if not all(holds_score(item) for item in items):
        return []
    return [e['value'] for e in entries_for_app('reader') if e['group'] == SCORE]


def build_reading_lot_bytes(items, fmt):
    """Return (ext, bytes) for ONE score made of the pages of a lot (in lot order), or None.

    Les MusicXML LUS de chaque page, assemblés (`musicxml_score.merge_drum_pages` : la légende de
    batterie lue sur une page vaut pour toutes) ; l'ABC en est tirée, titrée par le titre lu sur les
    pages (`batch_identity.content_title`). ⚠ Une correction faite à la main sur l'ABC d'une page
    (« Éditer la partition ») n'y entre pas : l'aller-retour ABC → MusicXML garde les notes mais
    perd la légende (mesuré le 2026-11-10 : `abc2xml` nomme « Part 1 » chaque son de batterie)."""
    if fmt not in ('abc', 'musicxml'):
        return None
    from wama.common.services.batch_identity import content_title
    from wama.common.utils.musicxml_score import merge_drum_pages, musicxml_to_abc
    pages = []
    for item in items:
        field = item.score_musicxml
        if not getattr(field, 'name', ''):
            return None
        try:
            with field.open('rb') as handle:
                pages.append(handle.read().decode('utf-8', errors='replace'))
        except OSError:
            return None
    score = merge_drum_pages(pages)
    if fmt == 'musicxml':
        return ('musicxml', score.encode('utf-8'))
    return ('abc', musicxml_to_abc(score, title=content_title(items)).encode('utf-8'))


def console_content(request):
    user = _get_user(request)
    lines = get_console_lines(user.id)
    return JsonResponse({'lines': lines})


