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
  • TROU DE GLU (stub 501) : politique d'app non conventionnelle (batch_preview/create —
    parsing+consolidation ; consolidate ; toutes les extra_routes). ⚠ `card_html` a quitté
    cette liste le 2026-08-29 : sa raison — « nom du partial inconnaissable » — datait d'avant
    `templates_gen`, qui émet ce partial. Une raison périmée ne se relit pas. La page BOOTE, la fonctionnalité manque VISIBLEMENT —
    c'est le détecteur (Playwright/diff), pas un échec silencieux.

⚠ Ce qui a QUITTÉ la liste des stubs le 2026-08-29 — et pourquoi ce n'étaient pas des
trous de glu : `cancel` et `update`/`update_job`. Le premier est le corps `stop` sous un
autre NOM (8 manifestes disent `stop`, le converter dit `cancel` — et le converter est
justement la seule app que ce gabarit sait générer entièrement) ; le second est
`batch_update` un cran plus bas, sur les MÊMES `params_fields`. Dans les deux cas le
gabarit savait déjà faire, et bouchait quand même.
*Un gabarit qui suppose un nom au lieu de le LIRE au manifeste rend une app qui boote et
ne marche pas* — et 501 sur ces deux-là, c'était le ⏹ qui POSTait dans le vide et le ⚙
sans URL d'enregistrement, donc trois boutons de card morts pour deux corps déjà écrits.

Formes de file : v1 ne rend l'index/fabrique QUE pour la forme FK-DIRECTE (item.batch,
batch_row_index — converter). La forme à modèle de liaison (transcriber…) est un trou
déclaré de ce gabarit (raison explicite, jamais de fichier partiel faux).
"""
from __future__ import annotations

from wama.common.app_registry import MEDIA_CATEGORIES
from wama.common.manifests.codegen.urls_gen import route_variants


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

    # VOCABULAIRE D'ENTRÉE de l'app — LU au manifeste, jamais supposé. Il est déclaré DEUX fois
    # et les deux déclarations sont d'accord sur 10/10 apps (mesuré le 2026-08-29) :
    #   • `body.ports.inputs[].types`   ← APP_CATALOG['<app>']['input_types'] (PORTS_FIELDS) ;
    #   • `body.modes.domains[].accepts` ← app_modes.APP_MODES (l'axe UX).
    # On lit les ports en premier (c'est la facette de TYPAGE) et les domaines en repli.
    #
    # ⚠ On ne retient que les ports qui portent des FICHIERS — `group` travail/référence — et
    # jamais le port `prompt`. Historique : `text` était un HOMONYME (texte brut vs fichier
    # texte) et ce bloc devait s'en protéger à la main. ✅ TRANCHÉ le 2026-08-30
    # (`ROUTE §S2bis.6bis`) : la saisie s'appelle `prompt` (jeton de RÔLE, hors
    # MEDIA_CATEGORIES), les fichiers texte sont des `document` — les filtres ci-dessous
    # tiennent désormais par construction, sans exception codée en dur.
    types = []
    for port in ((body.get('ports') or {}).get('inputs') or []):
        if (port.get('group') or 'travail') == 'prompt':
            continue
        for t in (port.get('types') or []):
            if t not in types and t in MEDIA_CATEGORIES:
                types.append(t)
    if not types:
        for dom in ((body.get('modes') or {}).get('domains') or []):
            for t in (dom.get('accepts') or []):
                # `prompt` (jeton de rôle, ex-homonyme `text` — tranché 30/08) n'est pas dans
                # MEDIA_CATEGORIES : le filtre l'écarte par construction, plus d'exception.
                if t not in types and t in MEDIA_CATEGORIES:
                    types.append(t)
    d['types_entree'] = tuple(sorted(types))
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
    # Symbole du schéma de params — LU au manifeste (`body.params.primary`), jamais supposé.
    # `PARAMS_JSON` reste le repli conventionnel, mais l'écrire en dur ferait de la 3ᵉ facette
    # devinée de ce fichier en deux jours (routes, signature de brique, et celle-ci).
    schema_symbole = (((manifest.get('body') or {}).get('params') or {}).get('primary')
                      or 'PARAMS_JSON')
    # Champs FICHIER de l'item — la brique commune prend (instance, NOM DE CHAMP) et non
    # l'objet FileField : `safe_delete_file(f)` levait un TypeError sur les trois vues de
    # suppression (delete, clear_all, batch_delete). Les 10 apps écrites à la main appellent
    # toutes à DEUX arguments — c'est le gabarit seul qui avait deviné la signature.
    # *Une signature de brique se lit ; devinée, elle rend une vue qui plante à l'usage,
    # pas à la génération — donc invisible à `check` comme aux tests de codegen.*
    champs_fichiers = [d['input_field']] + (['output_file'] if d['a_output'] else [])
    # Nom de fichier pour les propriétés d'ENTRÉE de la card (input_props_for) : le champ
    # nom déclaré, sinon le nom du FileField lui-même.
    nom_pour_props = (f"getattr(item, '{d['name_field']}', '') or ''" if d['name_field']
                      else f"(item.{d['input_field']}.name if item.{d['input_field']} else '')")
    name_expr = (f'j.{d["name_field"]}' if d['name_field']
                 else f'(j.{d["input_field"]}.name if j.{d["input_field"]} else "")')

    # ── NATURE DE L'ENTRÉE — dérivée, plus un trou (2026-08-29) ──────────────────
    # 4ᵉ occurrence du motif que ce fichier documente déjà deux fois (`accepts_url`, puis
    # `inspector`) : une facette DÉCLARÉE au manifeste et non projetée n'est pas un trou de
    # glu, c'est un manque de gabarit. Ici les DEUX pièces existaient — le détecteur commun
    # `category_of_path` et le vocabulaire `body.ports.inputs[].types` — et le gabarit ne
    # lisait ni l'un ni l'autre : il déclarait le trou et rouvrait un arbitrage.
    nature_champ = d['batch_extra']          # 'media_type' si l'app la porte, sinon ''
    types_entree = d['types_entree']
    bloc_nature = f'''

# Vocabulaire d'ENTRÉE de l'app — projection de `body.ports.inputs[].types` du manifeste
# (lui-même extrait d'APP_CATALOG['<app>']['input_types']). Écrit ici pour que la vue ne
# dépende pas du catalogue à l'exécution ; il se REGÉNÈRE avec la vue, donc il ne peut pas
# dériver de sa source.
_TYPES_ENTREE = {types_entree!r}


def _nature(nom):
    """Catégorie média d'un nom de fichier, CONTRAINTE au vocabulaire déclaré de l'app.

    Le détecteur est `app_registry.category_of_path` — la source UNIQUE du dépôt (celle dont
    `probe_media` se sert pour son aiguillage), pas un second détecteur écrit pour l'occasion.

    Hors vocabulaire → '' plutôt qu'une valeur approchée. Mesuré le 2026-08-29 : sur les 59
    extensions acceptées par le converter, le commun s'accorde 56 fois avec le détecteur de
    l'app ; les 3 écarts (.md, .markdown, .txt) tiennent à ce que le commun distingue 'text'
    de 'document' là où l'app ne déclare pas 'text'. L'appelant le SIGNALE : un champ vide et
    dit se répare, une valeur fausse et muette se propage.
    """
    from wama.common.app_registry import category_of_path
    cat = category_of_path(nom)
    return cat if cat in _TYPES_ENTREE else ''

''' if nature_champ else ''

    # ── Garde de PROPRIÉTÉ avant suppression physique (trou A5, audit 31/08) ──
    # Dérivée de la politique du converter réel (`_is_app_owned`) : on ne supprime un
    # fichier QUE s'il vit dans l'arbre média de L'APP. Un fichier seulement RÉFÉRENCÉ
    # (envoi Filemanager, galerie partagée) appartient à l'utilisateur — le supprimer avec
    # la card détruirait une donnée hors de la juridiction de l'app, et `safe_delete_file`
    # ne teste que les doubles références EN BASE, pas la propriété. Conservatrice par
    # construction : elle protège AUSSI la politique inverse (rattachement par référence,
    # avatarizer) — l'arbitrage de PLATEFORME reste ouvert (ROUTE §S2ter), cette garde n'en
    # préjuge pas : elle ne fait qu'interdire de détruire hors de chez soi.
    bloc_garde = f'''

def _fichier_de_l_app(item, champ):
    """Un fichier n'est supprimable avec sa card QUE s'il vit dans l'arbre de l'app
    (`{app}/<user_id>/…`) — politique du converter réel, garde muette sinon (le fichier
    reste, la card part)."""
    f = getattr(item, champ, None)
    nom = (getattr(f, 'name', '') or '').replace('\\\\', '/')
    return nom.startswith(f'{app}/{{item.user_id}}/')
'''
    up_nature = (f"""_avert = ''
    nature = _nature(f.name)
    if nature:
        kwargs['{nature_champ}'] = nature
    else:
        _avert = f.name + " : nature hors vocabulaire d'entrée de l'app\""""
                 if nature_champ else "_avert = ''")

    def stub(nom, pk=False):
        arg = ', pk' if pk else ''
        return (f"def {nom}(request{arg}):\n"
                f"    \"\"\"TROU DE GLU {mark} — politique d'app non conventionnelle.\"\"\"\n"
                f"    return JsonResponse({{'error': {stub_msg!r}}}, status=501)")

    # ── Découpage colonnes ↔ conteneur JSON du schéma (idiome params_storage) ──
    # Calculé AVANT les corps de vues : l'upload (cascade de réglages du dépôt), le
    # décorateur et update en dépendent tous trois.
    body = manifest.get('body') or {}
    _schemas = (body.get('params') or {}).get('schemas') or {}
    _schema_prim = _schemas.get((body.get('params') or {}).get('primary') or '') or []
    _noms_schema = [str(p.get('name')) for p in _schema_prim
                    if isinstance(p, dict) and p.get('name')]
    _champs_modeles = {m.get('name'): {f.get('name') for f in (m.get('fields') or [])}
                       for m in ((body.get('data') or {}).get('models') or [])
                       if isinstance(m, dict)}
    _champs_item = _champs_modeles.get(item) or set()
    hors_colonnes = [n for n in _noms_schema
                     if n not in _champs_item and n not in d['params_fields']]
    conteneur_options = 'options' if ('options' in _champs_item and hors_colonnes) else None
    colonnes_schema = [n for n in _noms_schema if n not in hors_colonnes and n != nature_champ]

    # ── Réglages du DÉPÔT — cascade de l'app réelle (converter/views.py::upload) ──
    # défauts APPLICABLES du schéma (show_if satisfait par la nature détectée — brique
    # `applicable_defaults`) ← derniers réglages persistés de l'utilisateur (brique
    # user_settings) ← POST non vide ; le POST re-persiste ses clés comme défauts du
    # prochain dépôt. C'est ce qui donne ses valeurs à un élément FRAIS : sans cette
    # cascade, la section RÉGLAGES de la card et le volet restaient VIDES jusqu'au premier
    # passage par la modale (constat Fabien 31/08 sur la jumelle). La nature détectée n'est
    # JAMAIS écrasée par la cascade (la détection prime — champ porteur, non sauvegardé).
    ligne_opts = (f"kwargs['{conteneur_options}'] = _extras" if conteneur_options
                  else "pass  # pas de conteneur JSON déclaré : extras non stockés")
    # FONCTION module-level PARTAGÉE upload/batch_create : la cascade ne vivait que dans
    # upload — les filles de LOT naissaient sans valeurs (chips vides, constat Fabien 31/08).
    bloc_reglages = '' if not _noms_schema else f'''

def _reglages_du_depot(user, nature, poste=None):
    """Cascade des réglages d'un élément NAISSANT (upload ET batch_create) : défauts
    APPLICABLES du schéma (show_if ⟂ nature détectée) ← user_settings persistés ← poste
    non vide, re-persisté. → (colonnes, extras) ; la nature n'est jamais écrasée."""
    try:
        from .params import {schema_symbole} as _sch
    except Exception:
        return {{}}, {{}}
    from wama.common.utils.param_schema import applicable_defaults, coerce_schema_values
    from wama.common.utils.user_settings import get_user_app_settings, save_user_app_settings
    noms = [n for n in {_noms_schema!r} if n != {nature_champ!r}]
    vals = applicable_defaults(_sch, {{{nature_champ!r}: nature}})
    vals.pop({nature_champ!r}, None)
    # ⚠ `defaults` définit AUSSI l'ensemble des clés LUES (contrat de la brique) — un {{}}
    # ici ne relirait jamais rien.
    vals.update({{k: v for k, v in get_user_app_settings(
                     user, '{app}', {{n: '' for n in noms}}).items()
                 if v not in (None, '')}})
    envoye = ({{k: poste.get(k) for k in noms if poste.get(k) not in (None, '')}}
              if poste is not None else {{}})
    vals.update(envoye)
    # ⚠ COERCER selon le schéma AVANT de poser (défaut VÉCU, 2026-09-01) : le POST et les
    # user_settings re-persistés portent des CHAÎNES ('false', '72'). Tant que la
    # destination était un JSON, elles passaient ; sur des colonnes TYPÉES, un
    # BooleanField refuse 'false' (ValidationError) — et batch_create avalait l'erreur en
    # warning : 2 POST « acceptés », 0 élément créé, vu à la batterie navigateur seulement.
    vals = coerce_schema_values(_sch, vals)
    cols, extras = {{}}, {{}}
    for k, v in vals.items():
        (cols if k in {colonnes_schema!r} else extras)[k] = v
    if envoye:
        save_user_app_settings(user, '{app}', envoye)
    return cols, extras
'''
    up_reglages = '' if not _noms_schema else f'''
    _cols, _extras = _reglages_du_depot(user, kwargs.get({nature_champ!r}, ''), request.POST)
    kwargs.update(_cols)
    if _extras:
        {ligne_opts}'''
    ligne_opts_bc = (f"kwargs['{conteneur_options}'] = _extras" if conteneur_options
                     else "pass  # pas de conteneur JSON déclaré")
    # Méta COMMUNES aux filles pour la card MÈRE (slot `meta_template` de _batch_card.html —
    # mécanisme du PARC : transcriber calcule ses common_* dans l'extra de
    # build_batches_list, « valeur si partagée par toutes les filles, sinon Mixte »).
    # Dérivation SCHÉMA-driven ici : mêmes chips que les filles (brique card_chips), retenus
    # quand TOUTES les filles s'accordent — la jumelle ne passait pas le slot, mère sans
    # réglages (constat Fabien 31/08 : « c'est déjà acté et en place, juste à câbler »).
    ligne_commun = '' if not _noms_schema else f'''
            try:
                from wama.common.utils.card_chips import common_chips_for_items as _ccfi
                from .params import {schema_symbole} as _sch_m
                _cc = _ccfi(items, _sch_m)   # items déjà _decorer-és : valeurs aplaties
            except Exception:
                _cc = {{}}'''
    cle_commun = ("'common_chips': _cc," if _noms_schema else "'common_chips': {},")
    # Défauts de FILE pour le volet (index) — même cascade, sans nature ni POST.
    ligne_defauts = (("_c, _e = _reglages_du_depot(user, '')\n"
                      "        panel_defaults = json.dumps({**_c, **_e})")
                     if _noms_schema else "panel_defaults = '{}'")
    bc_reglages = '' if not _noms_schema else f'''
                _cols, _extras = _reglages_du_depot(user, kwargs.get({nature_champ!r}, ''))
                kwargs.update(_cols)
                if _extras:
                    {ligne_opts_bc}'''

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
            grouped.setdefault(j.{fk}_id or f'loose-{{j.id}}', []).append(_decorer(j))
        batches_list = []
        for items in grouped.values():
            b = items[0].{fk}
            statuses = [normalize_status(j.status) for j in items]{ligne_commun}
            batches_list.append({{
                {cle_commun}
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
            from .params import {schema_symbole}
            params_json = json.dumps({schema_symbole})
        except Exception:
            params_json = '[]'
        # Défauts des prochains dépôts (paramètres de FILE) : la MÊME cascade que le dépôt
        # lui-même (défauts du schéma ← user_settings), sans nature ni POST — le volet les
        # montre hors sélection, WamaImport les POSTE (extraFields), la boucle est fermée.
        {ligne_defauts}
        # TROU DE GLU {mark} — contexte SPÉCIFIQUE d'app (profils, formats…) non généré :
        # le gabarit ne fournit que le contexte CONVENTIONNEL de file.
        return render(request, '{app}/index.html', {{
            'batches_list': batches_list, 'queue_count': len(jobs),
            'q_sort': q_sort, 'q_filter': q_filter, 'params_json': params_json,
            'panel_defaults': panel_defaults,
        }})'''

    vues['upload'] = f'''@require_POST
def upload(request):
    user = _user(request)
    f = request.FILES.get('file')
    if not f:
        return JsonResponse({{'error': 'Aucun fichier fourni'}}, status=400)
    kwargs = {{'user': user, '{d['input_field']}': f}}
    {f"kwargs['{d['name_field']}'] = f.name" if d['name_field'] else ''}
    {up_nature}{up_reglages}
    item = {item}.objects.create(**kwargs)
    return JsonResponse({{'id': item.id, 'status': item.status, 'warning': _avert}})'''

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
    _nom = d['name_field']
    bc_nom_url = (f"""if nom:
                    obj.{_nom} = nom
                    obj.save(update_fields=['{_nom}'])""" if _nom else "pass")
    bc_nom_fichier = f"kwargs['{_nom}'] = _dest.name" if _nom else "pass"
    bc_nature_url = (f"""nature = _nature(nom or src)
                if nature:
                    kwargs['{nature_champ}'] = nature
                else:
                    avertissements.append((nom or src) + ' : nature hors vocabulaire')"""
                     if nature_champ else "pass")
    bc_nature_fichier = (f"""nature = _nature(_dest.name)
                if nature:
                    kwargs['{nature_champ}'] = nature
                else:
                    avertissements.append(_dest.name + ' : nature hors vocabulaire')"""
                         if nature_champ else "pass")
    bc_nature = (f"str(getattr(o, '{nature_champ}', '') or '')" if nature_champ else "''")
    # ⚠ ÉMISE COMME FONCTION NOMMÉE, plus comme lambda inline (2026-09-04). Ce n'est pas du
    # style : elle a DEUX consommateurs — le groupement à l'import (`nature_of`) et la fusion
    # par glisser-déposer (`group_key` de la fabrique de manipulation). Une lambda inline ne
    # se partage pas, donc la jumelle générée serait née avec la règle appliquée d'un seul
    # côté : import refusant de mélanger les natures, drag&drop les mélangeant.
    # ⚠ NOM DISTINCT de `bloc_nature` (ligne ~161), qui porte `_TYPES_ENTREE` + `def _nature`.
    # Ma première graphie réutilisait ce nom et l'ÉCRASAIT : l'app générée perdait son
    # vocabulaire d'entrée et sa détection de nature, tout en gardant les appels `_nature(...)`
    # — donc un NameError à la première utilisation. Trois tests de `tests_codegen_lot` l'ont
    # dit tout de suite ; à l'œil, le diff n'avait l'air que d'un ajout.
    bloc_nature_de_lot = f'''def _nature_de_lot(o):
    """Nature de l'élément — ce qui peut cohabiter dans un lot.

    UNE déclaration, DEUX consommateurs : `group_into_batches_by_nature` (import groupé) et
    `group_key` de la fabrique de manipulation de file (fusion par drag&drop)."""
    return {bc_nature}'''
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
                {bc_nature_url}{bc_reglages}
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
                {bc_nature_fichier}{bc_reglages}
                obj = {item}.objects.create(**kwargs)
                obj.{d['input_field']}.name = rel
                obj.save(update_fields=['{d['input_field']}'])
            crees.append(obj)
        except Exception as e:
            avertissements.append(src + ' : ' + str(e))

    # La NATURE de l'entrée est renseignée plus haut, dans LES DEUX branches (URL et fichier),
    # par `_nature` — et `upload` la renseigne pareillement. Doter un seul des deux chemins est
    # ce qui a produit les trois derniers défauts de codegen ; le groupement ci-dessous en
    # dépend directement (`nature_of` lisait un champ que personne n'écrivait, donc UN lot
    # fourre-tout au lieu d'un lot par nature).
    def _lier(lot, obj, idx):
        setattr(obj, '{fk}', lot)
        setattr(obj, '{row}', idx)
        obj.save(update_fields=['{fk}', '{row}'])

    lots = group_into_batches_by_nature(
        crees,
        nature_of=_nature_de_lot,
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

    # ARRÊT — le CORPS est conventionnel, le NOM ne l'est pas : 8 apps déclarent `stop`,
    # le converter déclare `cancel` (mesuré sur les 9 manifestes le 2026-08-29). Le gabarit
    # ne connaissait que `stop` : la seule app qu'il sait générer entièrement recevait donc
    # un 501 sur son ⏹, et le bouton de cycle — brique commune, bien câblée — POSTait dans le
    # vide. ⚠ Même famille que le `pk` de `batch_preview` : un gabarit qui suppose le nom au
    # lieu de le LIRE au manifeste rend une app qui boote et ne marche pas.
    # Les orthographes admises viennent de `urls_gen.ROUTE_ALIASES` (propriétaire du
    # vocabulaire de routes) — les réécrire ici en ferait une seconde source de vérité.
    #
    # Le corps ci-dessous est l'idiome MESURÉ (describer, avatarizer, composer : garde
    # `not in ('RUNNING','PENDING')` puis `stop_instance` → FAILURE, card rouge + ↻).
    # DEUX apps s'en écartent — anonymizer et converter remettent en PENDING (et le converter
    # supprime en plus la ligne d'un quick-convert éphémère). Le gabarit rend la CONVENTION
    # sous le nom déclaré ; réconcilier ces deux politiques est un chantier de PORTAGE, pas
    # l'affaire du gabarit (même doctrine que `ROUTE_TABLE`). L'écart reste mesurable au diff.
    def corps_stop(nom):
        return f'''@require_POST
def {nom}(request, pk):
    user = _user(request)
    item = get_object_or_404({item}, pk=pk, user=user)
    if item.status not in ('RUNNING', 'PENDING'):
        return JsonResponse({{'id': item.id, 'status': item.status}})
    new_status = stop_instance(item, error_field='error_message')
    return JsonResponse({{'id': item.id, 'status': new_status}})'''

    for _nom in route_variants('stop'):
        vues[_nom] = corps_stop(_nom)

    # CARD RENDUE SERVEUR — conventionnelle, et elle ne l'a pas toujours paru. L'en-tête de
    # ce module la rangeait en trou de glu avec pour raison « nom du partial inconnaissable ».
    # Cette raison était vraie AVANT que `templates_gen` n'existe ; depuis, le partial est
    # émis par le MÊME gabarit, sous un nom que lui seul choisit (`_generic_card.html`).
    # ⚠ Troisième occurrence du même défaut, et la plus instructive : ici la facette n'était
    # pas « non lue » — la raison écrite était juste PÉRIMÉE, et personne ne relit une raison.
    # *Un trou justifié par une contrainte disparue survit à la contrainte.*
    # Mesuré le 2026-08-29 : 10 apps sur 10 définissent `card_html`, toutes de la même forme
    # (récupérer → décorer → rendre le partial de card). La décoration elle-même est une
    # BRIQUE COMMUNE (`card_chips.chips_by_section`) appliquée au schéma déjà déclaré au
    # manifeste (`params.primary`), donc rien ici n'est propre à l'app.
    # Point d'attache UNIQUE (leçon describer, recopiée telle quelle dans converter) : la même
    # décoration sert l'index ET card_html, sinon la card se vide à son premier rafraîchissement.
    # Idiome de STOCKAGE des réglages hors-colonnes — DÉRIVÉ de deux facettes (le cadrage A0
    # le listait « params_storage : à déclarer ») : les champs du SCHÉMA de params qui ne sont
    # PAS des colonnes du modèle item s'écrivent dans son conteneur JSON `options` s'il
    # existe. Mesuré sur le converter (le « déviant double ») : 3 colonnes + 17 champs de
    # schéma routés en JSON — sans cette voie, la modale générée s'affichait COMPLÈTE mais
    # n'ENREGISTRAIT que les 3 colonnes, et le volet PARAMÈTRES restait vide (constats Fabien
    # 31/08 ; le vide du volet vient aussi de `gear_data`, @property du modèle RÉEL = glu non
    # sérialisée par la facette data, absente du modèle jumeau — d'où l'aplatissement de
    # `_decorer` ci-dessous, qui porte les valeurs du conteneur sur l'instance).
    # ⚠ Glu RESTANTE nommée : le sous-split `cross_app_options` du converter réel (upscale/
    # denoise/audio_enhance) n'est pas dérivé — ces clés atterrissent dans `options`.
    # (Le découpage colonnes ↔ conteneur — _noms_schema/hors_colonnes/conteneur_options —
    # est calculé PLUS HAUT, avant l'upload : la cascade de réglages du dépôt en dépend aussi.)

    aplat = '' if not conteneur_options else f'''
    # Valeurs du conteneur JSON portées sur l'instance (transitoire) : la card émet ses
    # `data-param-*` par `item.<champ>`, le volet et la modale les relisent — mêmes valeurs
    # que ce que `update` écrit (idiome params_storage dérivé).
    try:
        _opts = dict(item.{conteneur_options} or {{}})
        for _k in {hors_colonnes!r}:
            setattr(item, _k, _opts.get(_k, ''))
    except Exception:
        pass'''
    decorateur = f'''def _decorer(item):
    """Chips de card GÉNÉRÉS du schéma (brique commune) — point d'attache unique index/card_html."""{aplat}
    # ⚠ L'aplatissement DOIT précéder les chips : ils lisent les valeurs SUR l'instance —
    # calculés avant, ils voyaient une instance vide (card sans Réglages, constat Fabien
    # 31/08 : les chips vivaient au volet mais pas sur la card).
    try:
        from wama.common.utils.card_chips import chips_by_section
        from .params import {schema_symbole}
        item.chips = chips_by_section(item, {schema_symbole})
    except Exception:
        item.chips = {{}}
    # `gear_data` : le VOLET lit les data-* du bouton ⚙ (pas les data-param-* de la card —
    # deux lecteurs, deux sources). Sur le modèle RÉEL c'est une @property (glu non
    # sérialisée) : la brique commune `card_gear` la reconstitue depuis le schéma + les
    # valeurs de l'instance (aplaties ci-dessus) — volet PARAMÈTRES vide sinon (Fabien 31/08).
    try:
        from wama.common.utils.card_gear import gear_data
        from .params import {schema_symbole} as _sch
        item.gear_data = gear_data(item, _sch)
    except Exception:
        item.gear_data = {{}}
    # Propriétés RÉELLES du fichier d'entrée (extension, poids) — sous-ligne de la section
    # ENTRÉE (brique commune extraite du pilote reader ; constat Fabien 31/08 : la card ne
    # montrait que la nature).
    try:
        from wama.common.utils.card_chips import input_props_for
        item.input_props = input_props_for(item, '{d['input_field']}', {nom_pour_props})
    except Exception:
        item.input_props = []
    return item'''

    vues['card_html'] = f'''def card_html(request, pk):
    """Card = partial serveur UNIQUE : le JS remplace la card par ce rendu."""
    user = _user(request)
    item = get_object_or_404({item}, pk=pk, user=user)
    return render(request, '{app}/_generic_card.html', {{'item': _decorer(item)}})'''

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
    for _champ in {champs_fichiers!r}:
        if _fichier_de_l_app(item, _champ):
            safe_delete_file(item, _champ)
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
        for _champ in {champs_fichiers!r}:
            if _fichier_de_l_app(item, _champ):
                safe_delete_file(item, _champ)
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

    # Contrat du COMPOSANT COMMUN (`wama-global-progress.js` lit total/done/overall_progress) —
    # l'émission précédente renvoyait {running, pending, percent} : la barre globale restait
    # MUETTE avec « 0 terminé » permanent, zéro erreur console (audit 31/08, trou A3 de la
    # cartographie). Même assiette que l'app réelle (converter/views.py::global_progress),
    # sans la lecture de cache par item (le squelette de tâche généré écrit item.progress).
    vues['global_progress'] = f'''def global_progress(request):
    user = _user(request)
    jobs = list({item}.objects.filter(user=user).values('status', 'progress'))
    total = len(jobs)
    done = sum(1 for j in jobs if j['status'] == 'SUCCESS')
    acc = sum(100 if j['status'] == 'SUCCESS' else (j['progress'] or 0) for j in jobs)
    return JsonResponse({{
        'total': total, 'done': done,
        'running': sum(1 for j in jobs if j['status'] == 'RUNNING'),
        'failed': sum(1 for j in jobs if j['status'] == 'FAILURE'),
        'overall_progress': int(acc / total) if total else 0,
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

    def maj_champs(ind):
        """Affectation des `params_fields` DÉCLARÉS (+ conteneur JSON dérivé), à l'indentation demandée."""
        p = ' ' * ind
        lignes = [f'''{p}if '{c}' in donnees:
{p}    setattr(item, '{c}', donnees['{c}'])
{p}    touches.append('{c}')''' for c in d['params_fields']]
        if conteneur_options:
            lignes.append(f'''{p}_extras = {{k: donnees[k] for k in {hors_colonnes!r} if k in donnees}}
{p}if _extras:
{p}    _opts = dict(item.{conteneur_options} or {{}})
{p}    _opts.update(_extras)
{p}    item.{conteneur_options} = _opts
{p}    touches.append('{conteneur_options}')''')
        return '\n'.join(lignes)

    lect_donnees = f'''    try:
        donnees = json.loads(request.body) if request.body else dict(request.POST)
    except Exception:
        donnees = dict(request.POST)
    donnees = {{k: (v[0] if isinstance(v, list) else v) for k, v in donnees.items()}}
    # ⚠ COERCER selon le schéma AVANT tout setattr (défaut VÉCU le 02/09, 2ᵉ site du même
    # piège que la cascade du dépôt) : le FormData d'une modale poste TOUTES ses valeurs,
    # VIDES comprises — appliquer '' sur une colonne Integer plante au save (int('') →
    # 500)... et SEULEMENT depuis un vrai navigateur : le client de test Django poste en
    # urlencoded, le défaut lui est invisible (même angle mort que _ids_de_la_requete).
    # `coerce_schema_values` type ('640'→640, 'true'→True) et FAIT DISPARAÎTRE les vides —
    # la sémantique voulue : un champ vide veut dire « ne pas toucher », jamais « effacer ».
    try:
        from .params import {schema_symbole} as _sch
        from wama.common.utils.param_schema import coerce_schema_values
        donnees = {{**{{k: v for k, v in donnees.items()}},
                   **coerce_schema_values(_sch, donnees)}}
        donnees = {{k: v for k, v in donnees.items()
                   if not (v == '' and k in {_noms_schema!r})}}
    except Exception:
        pass  # schéma indisponible : les données brutes restent (comportement d'avant)'''

    # ÉDITION D'UN ÉLÉMENT — l'idiome existait déjà, un cran plus haut (`batch_update`) : mêmes
    # `params_fields`, même lecture de corps, même garde RUNNING. Seul le niveau changeait, et
    # l'élément était bouché en 501. C'est ce 501 qui rendait le ⚙ des cards inerte : la brique
    # commune (`WamaQueueActions.onSettings` + `WamaParams.settingsModal`) n'avait pas d'URL
    # d'enregistrement à viser. *Un gabarit qui sait faire N n'a aucune raison de boucher 1.*
    # Deux noms pour une seule vue : le converter route `update/` vers `views.update_job`.
    def corps_update(nom):
        return f'''@require_POST
def {nom}(request, pk):
    user = _user(request)
    item = get_object_or_404({item}, pk=pk, user=user)
    if item.status == 'RUNNING':
        return JsonResponse({{'error': 'Impossible de modifier un élément en cours'}}, status=400)
{lect_donnees}
    touches = []
{maj_champs(4)}
    if touches:
        item.save(update_fields=touches)
    return JsonResponse({{'success': True, 'id': item.id, 'updated': touches}})'''

    for _nom in route_variants('update'):
        vues[_nom] = corps_update(_nom)

    maj = maj_champs(8)
    vues['batch_update'] = f'''@require_POST
def batch_update(request, pk):
    user = _user(request)
    b = get_object_or_404({batch}, pk=pk, user=user)
{lect_donnees}
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
        for _champ in {champs_fichiers!r}:
            if _fichier_de_l_app(item, _champ):
                safe_delete_file(item, _champ)
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

    # Gabarit de lot : par la BRIQUE COMMUNE, avec une LIGNE D'EXEMPLE déposable — un gabarit
    # fait de seuls commentaires n'est pas déposable (mesuré `converter_01.batch_import`,
    # 2026-08-30 : la détection structurelle n'y reconnaît rien). L'extension d'exemple est
    # DÉRIVÉE du vocabulaire d'entrée, jamais écrite au hasard.
    _EXEMPLES = {'image': '.jpg', 'video': '.mp4', 'audio': '.mp3',
                 'document': '.pdf', 'archive': '.zip', '3d': '.glb', 'dataset': '.csv'}
    ext_exemple = _EXEMPLES.get((d.get('types_entree') or ('video',))[0], '.mp4')
    vues['batch_template'] = f'''def batch_template(request):
    from wama.common.utils.batch_parsers import build_batch_template
    texte = build_batch_template(
        ['fichier'], {{'fichier': 'https://example.com/exemple{ext_exemple}'}},
        app_label='{app} (un chemin local ou une URL par ligne)')
    resp = HttpResponse(texte, content_type='text/plain; charset=utf-8')
    resp['Content-Disposition'] = 'attachment; filename="{app}_batch_template.txt"'
    return resp'''

    fabrique = f'''# Fabrique COMMUNE de manipulation de file (forme FK-DIRECTE — dérivée de la facette data).
_qm = make_queue_manipulation_views_direct(
    work_model={item}, batch_model={batch},
    batch_fk='{fk}', row_field='{row}',
    get_user=_user,{f"""
    batch_extra=lambda w: {{'{d['batch_extra']}': w.{d['batch_extra']}}},""" if d['batch_extra'] else ''}
    # JUMEAU du `nature_of` de l'import : la meme regle decide de ce qui peut cohabiter dans
    # un lot, qu'on y arrive par import groupe ou par glisser-deposer.
    group_key=_nature_de_lot,
)
reorder           = _qm['reorder']
reorder_queue     = _qm['reorder_queue']
# `merge` = fusion STRICTE (geste du drag&drop) — distincte de `consolidate`, qui range
# par nature a l'import. Voir le bloc « DEUX OPERATIONS, DEUX NOMS » de queue_manipulation.
merge             = _qm['merge']
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
    # `card_html` a quitté cet ensemble le 2026-08-29 : il a un corps conventionnel
    # (cf. plus haut). L'ensemble reste — d'autres routes à `pk` s'y ajouteront.
    stubs_pk = set()
    couverts_fabrique = {'reorder', 'reorder_queue', 'merge', 'move_to_batch',
                         'remove_from_batch', 'consolidate'}
    ignores = {'about', 'help'}     # servis par common.views dans le urls généré
    blocs, deja = [], set()
    for ep in d['endpoints']:
        if ep in ignores or ep in couverts_fabrique or ep in deja:
            continue
        deja.add(ep)
        if ep in vues:
            blocs.append(vues[ep])
        else:
            # `cancel`/`update` ont quitté cette liste d'arité le 2026-08-29 : ils ne sont plus
            # jamais bouchés (corps conventionnel émis sous le nom déclaré). Y laisser leur nom
            # aurait fait croire au lecteur suivant qu'ils sont encore des trous.
            blocs.append(stub(ep, pk=ep in stubs_pk or ep.rstrip('_') == 'dismiss'))
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
    blocs.insert(0, decorateur)
    # La nature AVANT la fabrique : c'est elle qui la consomme (`group_key`), et le module
    # généré est lu de haut en bas — `_nature_de_lot` doit exister au moment de l'appel.
    blocs.append(bloc_nature_de_lot)
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
{bloc_nature}{bloc_garde}{bloc_reglages}
'''
    return tete + '\n\n\n'.join(blocs) + '\n', None
