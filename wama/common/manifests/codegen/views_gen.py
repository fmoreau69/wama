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

Formes de file — LES DEUX sont rendues depuis le 2026-09-22 (trou #30 de la ROUTE) :
  • FK DIRECTE (converter) : l'item porte `batch` + `batch_row_index` — dérivée de la facette
    `data` ;
  • modèle de LIAISON (9 apps sur 10) : `BatchXItem(batch FK, <item> OneToOne, row_index)` —
    LUE au manifeste, `processing.model_spec.batch` (`link_name`, `link_item_field`,
    `link_batch_field`, `link_batch_related`), jamais devinée sur un nom de classe.
Les vues de lot lisent le lot par la BRIQUE (`batch_common.batch_elements`, ordre des lignes
garanti, les deux formes) et y rattachent par la brique (`attach_to_batch`) : le fichier généré
ne porte de sa forme que les kwargs déclarés, passés aux fabriques. Un seul corps par vue.
Jusqu'au 22/09 la seconde forme était un « trou déclaré » : `describer_01`, `composer_01` et
`imager_01` gardaient leurs vues COPIÉES et ne suivaient plus le commun.
"""
from __future__ import annotations

from wama.common.app_registry import MEDIA_CATEGORIES
from wama.common.manifests.codegen.urls_gen import ROUTE_ALIASES, alias_fits, route_variants


def card_entry(body: dict, fields=None) -> dict:
    """La FORME D'ENTRÉE de la card d'une app générée — `app_registry.entry_form` lu sur la facette
    `ports` du manifeste, où l'obligation de chaque port voyage avec lui (2026-10-19, décision de
    Fabien « par port »). Partagée par la vue (`upload`) et le gabarit (`templates_gen`) pour
    qu'ils ne divergent jamais ; égale à celle que la card rend à l'exécution (`input_slots`), qui
    applique la même fonction aux mêmes ports.

    {'drop_creates' : un dépôt sur le port de travail principal CRÉE l'élément ;
     'adds'         : la card a son bouton « Ajouter à la file » — consigne et/ou fichiers JOINTS
                      (forme ATTACHE : imager, composer, avatarizer ; forme MIXTE : synthesizer,
                      Translator, où la consigne seule et le fichier seul suffisent chacun) ;
     'prompt_field' : le champ où la consigne se pose — sa cible de prompt, sinon son port
                      (`prompt_port_field`) ; '' si la card ne la porte pas}.
    `fields` : les colonnes de l'élément, pour ne rendre qu'un champ qui existe (None = ne pas
    vérifier).

    ⚠ Remplace `prompt_entry` (2026-10-01 → 10-19), qui décidait « attache = une consigne et AUCUN
    port de travail » faute d'obligation au manifeste : imager et avatarizer restaient hors de la
    dérivation, et la forme MIXTE n'existait pas (la page du Translator n'avait NI saisie NI zone
    instantanée — `ROADMAP §10.B`)."""
    from wama.common.app_registry import entry_form
    form = entry_form((body.get('ports') or {}).get('inputs') or [])
    return {'drop_creates': form['drop_creates'],
            'adds': bool(form['prompt']) or (bool(form['work']) and not form['drop_creates']),
            'prompt_field': prompt_port_field(body, fields) if form['prompt'] else ''}


def prompt_port_field(body: dict, fields=None) -> str:
    """Le champ où la SAISIE de la card se pose : sa cible de prompt, sinon le PORT de consigne
    lui-même, sinon `prompt` — '' si aucune n'est une colonne (`fields`, None = ne pas vérifier).

    Le PORT de consigne nomme son champ, comme tout port (2026-10-16) : translate_01 déclarait son
    texte à traduire en port `text` du groupe prompt, SANS cible de prompt — à juste titre, le
    pipeline de prompts traduirait ou enrichirait le texte avant la traduction. Faute de cible et de
    colonne `prompt`, le champ restait vide : rien de ce qu'on tapait n'était gardé. Partagé par
    l'ajout à la file (`card_entry`) et le résultat instantané (`instant`)."""
    exists = (lambda n: True) if fields is None else (lambda n: n in fields)
    targets = (body.get('prompts') or {}).get('targets') or []
    ports = [p['id'] for p in ((body.get('ports') or {}).get('inputs') or [])
             if p.get('group') == 'prompt' and p.get('id')]
    return next((t['field'] for t in targets if t.get('field') and exists(t['field'])),
                next((p for p in ports if exists(p)), 'prompt' if exists('prompt') else ''))


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

    from wama.common.models import job_status_values

    d = {
        'app_id': manifest.get('key'),
        'item': item,
        'input_field': spec.get('input_field') or 'input_file',
        'endpoints': list(proc.get('endpoints') or []),
        'tasks': [t.get('function') for t in (proc.get('tasks') or []) if t.get('function')],
        # Repli : le vocabulaire COMMUN (cette ligne en portait une copie figée à 4 états).
        'statuses': list(proc.get('statuses') or job_status_values()),
        'params_fields': list(spec.get('params_fields') or []),
    }

    # Routes hors convention : le NOM du callable, et s'il s'agit d'une vue de CLASSE
    # (`views.ProcessView.as_view()`). Jusqu'au 2026-09-22 le dernier segment de l'expression
    # était pris tel quel — `as_view()` — et le bouchon émis `def as_view()(request…)` ne
    # compilait pas : la seule app à vues de classe (anonymizer) tombait à la première ligne.
    # Un nom qui n'est pas un identifiant n'est pas un callable à définir : on l'écarte.
    d['extras'], d['extra_classes'] = [], set()
    # View name → declared pattern: an item-route alias gets the conventional `(request, pk)`
    # body only if its pattern takes `<int:pk>` (`urls_gen.alias_fits`, 2026-09-24).
    d['view_patterns'] = {}
    # View name → declared ROUTE name. They differ when an app aligned its route on the
    # convention and kept its view: the imager's `settings/<int:pk>/` is named `update_settings`
    # and served by `generation_settings` (2026-09-29). Keyed by view name only, the item-edit
    # body was emitted under the route name and the view the urls call stayed a 501 stub.
    d['view_routes'] = {}
    for e in (proc.get('extra_routes') or []):
        expr = str(e.get('view') or '')
        if not expr:
            continue
        is_cbv = expr.endswith('.as_view()')
        base = expr[:-len('.as_view()')] if is_cbv else expr
        nom = base.split('.')[-1]
        if not nom.isidentifier():
            continue
        d['view_patterns'][nom] = str(e.get('pattern') or '')
        d['view_routes'][nom] = str(e.get('name') or '')
        d['extras'].append(nom)
        if is_cbv:
            d['extra_classes'].add(nom)

    champs = {f['name']: f for f in data_models[item].get('fields') or []}
    d['champ_noms'] = set(champs)
    # FORME D'ENTRÉE — déduite de l'obligation des PORTS déclarés (`card_entry`, 2026-10-19 ; la
    # règle du 2026-10-01 ne voyait qu'« une consigne sans port de travail »). Quand la card a son
    # bouton « Ajouter à la file » (formes ATTACHE et MIXTE), l'ajout reçoit consigne et fichiers
    # par la vue ci-dessous ; sinon le dépôt crée. Le générateur ne connaissait d'abord que la forme
    # « le dépôt crée » : la 1ʳᵉ app consigne-d'abord née de zéro (le Writer) n'avait aucun moyen
    # d'ajouter un élément (relevé par Fabien).
    d['entry'] = card_entry(body, champs)
    # Ports FICHIER SECONDAIRES (2026-10-05, le Writer : `reference_layout` à côté de
    # `reference_document`) — chacun posté sous le nom de son PORT, comme au composer
    # (`addToQueue(ports: 'card')`). Le port principal se reçoit sous le sien, `file` en repli
    # (le nom d'une dépose `WamaImport`). Seul un port qui EST une colonne est reçu.
    d['secondary_ports'] = [
        p['id'] for p in ((body.get('ports') or {}).get('inputs') or [])
        if p.get('id') and p.get('group') in ('travail', 'reference')
        and p['id'] != d['input_field'] and p['id'] in champs]
    d['a_output'] = 'output_file' in champs
    d['file_fields'] = [n for n, f in champs.items()
                        if str(f.get('class', '')).rsplit('.', 1)[-1] in ('FileField', 'ImageField')]
    d['name_field'] = ('input_filename' if 'input_filename' in champs
                       else 'input_name' if 'input_name' in champs else '')
    # RÉSULTAT servi au téléchargement — la DÉCLARATION (`processing.backend_result`, lue au
    # `RESULT` du paquet backends) que `tasks_gen` lit déjà pour PERSISTER (2026-09-24). Le
    # gabarit ne connaissait que `output_file` : describer (`{'kind': 'text', 'field':
    # 'result_text'}`) finissait en SUCCESS derrière un téléchargement 501, vu au geste
    # `describer_01.processing`. Fichier → sa colonne ; texte → une pièce jointe `.txt`.
    _res = proc.get('backend_result') or {}
    _res_field = _res.get('field') or ''
    d['out_file'] = ('output_file' if d['a_output']
                     else _res_field if (_res.get('kind') or 'file') == 'file'
                     and _res_field in d['file_fields'] else '')
    d['out_text'] = (_res_field if not d['out_file'] and _res.get('kind') == 'text'
                     and _res_field in champs else '')

    # Forme de file — la DÉCLARATION d'abord, la dérivation ensuite (2026-09-22).
    #   • LIAISON : `processing.model_spec.batch` la déclare (`link_name`, `link_item_field`,
    #     `link_batch_field`, `link_batch_related`) — 9 apps sur 10. On exige que le lot ET la
    #     liaison soient dans la facette `data` et que la liaison porte `row_index` (la
    #     colonne qu'ordonnent `wrap_in_batch`/`build_batches_list`) ;
    #   • FK DIRECTE : l'item porte lui-même sa FK vers un modèle *Batch de la même app +
    #     `batch_row_index` (converter) — dérivée de la facette `data`.
    # `batch_fk` ne se pose QUE sur la forme directe : `apps_gen` s'en sert pour brancher
    # `register_batch_sync(<Item>, direct_fk=True)`, la liaison passant par `batch_link_model`.
    d['batch'], d['batch_fk'], d['row_field'] = '', '', ''
    d['form'], d['link'], d['link_fk'], d['link_batch'], d['items_related'] = '', '', '', 'batch', 'items'
    batch_spec = (proc.get('model_spec') or {}).get('batch') or {}
    link_name = batch_spec.get('link_name') or ''
    link_fields = {f['name'] for f in (data_models.get(link_name) or {}).get('fields') or []}
    if (link_name and batch_spec.get('name') in data_models and link_name in data_models
            and 'row_index' in link_fields):
        d['form'] = 'link'
        d['batch'] = batch_spec['name']
        d['link'] = link_name
        d['link_fk'] = batch_spec.get('link_item_field') or item.lower()
        d['link_batch'] = batch_spec.get('link_batch_field') or 'batch'
        d['items_related'] = batch_spec.get('link_batch_related') or 'items'
        d['row_field'] = 'row_index'
    else:
        for nom, f in champs.items():
            to = ((f.get('kwargs') or {}).get('to') or {}).get('expr', '')
            cible = to.strip('\'"').split('.')[-1]
            for m_name in data_models:
                if cible.lower() == m_name.lower() and m_name.lower().endswith('batch'):
                    d['batch'], d['batch_fk'] = m_name, nom
        if d['batch'] and 'batch_row_index' in champs:
            d['row_field'] = 'batch_row_index'
            d['form'] = 'direct'
    # Colonne de NATURE de l'élément — la DÉCLARATION d'abord (`processing.backend_nature_field`,
    # lue au `NATURE_FIELD` du paquet backends), `media_type` en repli. C'est la MÊME règle que
    # `tasks_gen` (2026-09-24) : les deux gabarits la devinaient chacun, et divergeaient —
    # describer déclare `detected_type`, la tâche générée le lisait, la vue générée ne
    # connaissait que `media_type` et ne l'écrivait donc jamais (« nature '' sans backend »).
    # ⚠ Deux colonnes distinctes : l'ÉLÉMENT porte sa nature (`nature_field`), le LOT ne la
    # porte que s'il a la même colonne (`batch_extra`) — describer : oui / non.
    _declared = proc.get('backend_nature_field') or ''
    d['nature_field'] = (_declared if _declared in champs
                         else 'media_type' if 'media_type' in champs else '')
    d['batch_extra'] = (d['nature_field'] if (d['batch'] and d['nature_field'] and d['nature_field'] in
                        {f['name'] for f in data_models[d['batch']].get('fields') or []})
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
    if not (d['form'] and d['batch'] and d['row_field']):
        return None, ('forme de file inconnue : ni liaison déclarée '
                      '(processing.model_spec.batch avec link_name + row_index) ni FK directe '
                      'item→Batch + batch_row_index')

    app, item, batch = d['app_id'], d['item'], d['batch']
    fk, row, task = d['batch_fk'], d['row_field'], d['tasks'][0]
    is_link, link, link_fk = d['form'] == 'link', d['link'], d['link_fk']
    link_batch, items_related = d['link_batch'], d['items_related']
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
    # TOUS les champs FICHIER de l'item, LUS à la facette `data` (classe `FileField`/`ImageField`),
    # l'entrée déclarée en tête. Jusqu'au 2026-09-22 le gabarit n'en connaissait que deux noms
    # (`input_field` + `output_file`) : sur `describer_01` le `result_file` et sur `composer_01`
    # l'`audio_output` restaient sur le disque après suppression — vu par le contrat GÉNÉRIQUE
    # `tests_queue_delete_contract` dès que leurs vues ont été générées. Les sorties = les
    # champs fichier qui ne sont pas l'entrée (c'est ce que « Dupliquer » vide).
    # ⚠ Depuis le 2026-10-02 le RETRAIT n'émet plus cette liste : les vues générées appellent
    # `release_card_files(item)`, qui lit ce que la card porte (ses champs fichier, ses listes de
    # chemins déclarées) — la liste ne sert plus qu'à dériver les SORTIES.
    champs_fichiers = [d['input_field']] + [n for n in d['file_fields'] if n != d['input_field']]
    # Les PORTS d'entrée sont des ENTRÉES, pas des sorties : une copie les garde (2026-10-05 — le
    # port `reference_layout` du Writer, une colonne du même nom, aurait été vidé à la duplication).
    ports_entree = {p.get('id') for p in
                    (((manifest.get('body') or {}).get('ports') or {}).get('inputs') or [])}
    champs_sortie = [n for n in champs_fichiers
                     if n != d['input_field'] and n not in ports_entree]
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
    nature_champ = d['nature_field']         # colonne de nature de l'ÉLÉMENT, sinon ''
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


def _nature_url(url):
    """Nature d'une URL AVANT son téléchargement — la table commune de `url_ingest.url_nature`
    (plateforme média, extension), contrainte au même vocabulaire ; '' si elle ne la connaît
    pas. Sans elle, une URL YouTube (`watch?v=…`) était classée par son « extension »."""
    from wama.common.utils.url_ingest import url_nature
    cat = url_nature(url)
    return cat if cat in _TYPES_ENTREE else ''

''' if nature_champ else ''

    # ── Suppression physique : la PROPRIÉTÉ et le PARTAGE sont jugés par la brique ──
    # `safe_delete_file` porte elle-même les deux règles depuis le 2026-09-22 (`owns_file` +
    # `is_shared_elsewhere`, pour tout le parc). Le gabarit émettait une garde de propriété
    # `_fichier_de_l_app` (trou A5, audit 31/08, dérivée du converter réel) : REDONDANTE depuis,
    # et retirée le jour même sur décision de Fabien — une règle ne vit qu'à un endroit, et
    # une garde générée qui doublait la brique aurait dérivé à la première évolution de celle-ci
    # (elle l'avait déjà fait : l'ANCIEN domicile `<app>/{item.user_id}/` y a survécu au
    # déménagement des médias). Les vues de suppression appellent la brique seule.
    up_nature = (f"""_avert = ''
    nature = _nature(f.name)
    if nature:
        kwargs['{nature_champ}'] = nature
    else:
        _avert = f.name + " : nature hors vocabulaire d'entrée de l'app\""""
                 if nature_champ else "_avert = ''")

    def stub(nom, pk=False):
        # ⚠ Signature OUVERTE (`*args, **kwargs`) depuis le 2026-09-22 : un bouchon n'a rien à
        # lire, et deviner ses arguments d'après son nom a raté DEUX fois — `batch_preview` le
        # 22/08 (cf. l'assemblage plus bas), puis `profile_delete`, dont la route passe un `pk`
        # que le bouchon ne prenait pas : `TypeError` → 500 au lieu du 501 annoncé. Trouvé par le
        # parcours générique des adresses (`common/tests/tests_endpoints.py`). `pk` reste accepté par
        # compatibilité des appelants de cette fonction, et n'a plus d'effet.
        return (f"def {nom}(request, *args, **kwargs):\n"
                f"    \"\"\"TROU DE GLU {mark} — politique d'app non conventionnelle.\"\"\"\n"
                f"    return JsonResponse({{'error': {stub_msg!r}}}, status=501)")

    def stub_class(nom):
        # Vue de CLASSE hors convention (`views.X.as_view()` dans l'URLconf) : le bouchon doit
        # être une classe à `as_view`, sinon le urls généré ne s'importe pas.
        return (f"class {nom}(View):\n"
                f"    \"\"\"TROU DE GLU {mark} — vue de classe non conventionnelle.\"\"\"\n"
                f"    def dispatch(self, request, *args, **kwargs):\n"
                f"        return JsonResponse({{'error': {stub_msg!r}}}, status=501)")

    # ── Découpage colonnes ↔ conteneur JSON du schéma (idiome params_storage) ──
    # Ne décide ici que de ce qui s'ÉMET (l'aplatissement du conteneur dans `_decorer`) : les
    # listes de noms, elles, sont LUES à l'exécution par le module généré (`_SETTING_NAMES`…).
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

    # ── Réglages d'un élément NAISSANT — la cascade COMMUNE (2026-10-18) ──
    # L'élément naît COMPLET (`ROADMAP §23.2quater`) par `user_settings.new_element_settings` :
    # défauts du schéma applicables à la nature détectée ← préférences du volet de l'auteur ←
    # ce qui est posté, coercés par le schéma. Ce gabarit en émettait jusque-là sa propre copie
    # (`_reglages_du_depot`, recopiée du converter réel le 31/08), avec les noms de réglages figés
    # à la génération — le reste n°4 du `PROJECT_STATUS §CLÔTURE 2026-09-27`. La nature détectée
    # n'est jamais écrasée (la détection prime). Un DÉPÔT garde aussi ce qu'il poste comme
    # mémoire du volet (`save_panel_settings`) : le geste du transcriber (`_deposit_settings`).
    contexte_nature = f"{{{nature_champ!r}: nature}}" if nature_champ else 'None'
    retrait_nature = f"\n    values.pop({nature_champ!r}, None)" if nature_champ else ''
    bloc_reglages = '' if not _noms_schema else f'''

def _element_settings(user, nature='', post=None):
    """Les réglages d'un élément NAISSANT (dépôt, lot, résultat instantané) — la cascade COMMUNE
    `user_settings.new_element_settings` ; la nature détectée n'est jamais écrasée."""
    from wama.common.utils.user_settings import new_element_settings
    values = new_element_settings(user, '{app}', _SCHEMA, {item}, post=post,
                                  context={contexte_nature}, options_field=_OPTIONS_FIELD){retrait_nature}
    return values


def _deposit_settings(user, nature, post):
    """Un DÉPÔT : ce qu'il poste devient la mémoire du volet (`save_panel_settings`), puis
    l'élément naît par la cascade commune."""
    from wama.common.utils.user_settings import save_panel_settings
    save_panel_settings(user, '{app}', _SCHEMA, post)
    return _element_settings(user, nature, post)
'''
    # Une app sans champ de nature n'a rien à lire (`kwargs.get('', '')` s'émettait).
    arg_nature = f"kwargs.get({nature_champ!r}, '')" if nature_champ else "''"
    up_reglages = '' if not _noms_schema else f'''
    kwargs.update(_deposit_settings(user, {arg_nature}, request.POST))'''
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
    # Défauts de FILE pour le volet (index) : les réglages du volet de l'auteur, par NOM de
    # param — la brique commune `read_panel_settings`, celle des routes JSON du volet.
    ligne_defauts = (("from wama.common.utils.user_settings import read_panel_settings\n"
                      f"        panel_defaults = json.dumps(read_panel_settings(user, '{app}', _SCHEMA))")
                     if _noms_schema else "panel_defaults = '{}'")
    bc_reglages = '' if not _noms_schema else f'''
                kwargs.update(_element_settings(user, {arg_nature}))'''

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
    # FORME À LIAISON : la file est construite par la brique commune `build_batches_list`
    # (contrat de la toolbar, 9 apps réelles) — les entrées sont les LIAISONS, l'élément
    # voyage sous `elem` (alias posé par la brique) et se décore là. Le `extra` rend les
    # réglages communs que la card MÈRE lit ; son ETA agrégée (`eta_ids`) vient de la brique
    # (2026-10-16). La forme DIRECTE, qui construit ses lignes elle-même, la pose encore.
    index_link = f'''class IndexView(View):
    def get(self, request):
        user = _user(request)
        _auto_wrap_orphans(user)

        def _extra(b, liens, items):
            for e in items:
                _decorer(e){ligne_commun}
            return {{{cle_commun}}}

        batches_list = build_batches_list(user, batch_model={batch}, work_attr='{link_fk}',
                                          items_related='{items_related}', order_by='-id',
                                          extra=_extra)
        queue_count = sum(len(b['items']) for b in batches_list)
        batches_list, q_sort, q_filter = apply_queue_sort_filter(
            request, batches_list,
            name_of=lambda b: ({name_expr.replace('j.', 'b["items"][0].elem.')}
                               if b['items'] and b['items'][0].elem else ''))
        try:'''
    index_direct = f'''class IndexView(View):
    def get(self, request):
        user = _user(request)
        _auto_wrap_orphans(user)
        # Cards REÇUES aussi (2026-10-02) : `listable_by` = `visible_to`, sauf le compte anonyme.
        from wama.common.utils.scoping import listable_by
        jobs = listable_by({item}.objects.all(), user).order_by('{fk}_id', '{row}')
        grouped = {{}}
        for j in jobs:
            grouped.setdefault(j.{fk}_id or f'loose-{{j.id}}', []).append(_decorer(j))
        # RANGEMENT du destinataire (2026-10-02) : une entrée reçue qu'il a retirée de sa file
        # n'y figure plus ; les autres portent « reçue de … » et SON ordre (`reception`).
        from wama.common.services.reception import entry_arrangement, lines_for
        _lines = lines_for(user, {batch}, {item})
        batches_list = []
        for items in grouped.values():
            b = items[0].{fk}
            _arr = entry_arrangement(user, b or items[0], _lines)
            if _arr is None:
                continue
            if b and b.user_id != user.pk:
                # Lot REÇU : compté sur ce qu'il voit, en mémoire (`build_batches_list`, 2026-10-07).
                b.total = len(items)
            statuses = [normalize_status(j.status) for j in items]{ligne_commun}
            batches_list.append({{
                **_arr,
                {cle_commun}
                'obj': b, 'items': items,
                'is_group': bool(b) and (b.total if b else len(items)) > 1,
                'success_count': statuses.count('SUCCESS'),
                'running_count': statuses.count('RUNNING'),
                'failure_count': statuses.count('FAILURE'),
                'has_success': 'SUCCESS' in statuses,
                'eta_ids': ','.join(str(j.id) for j in items),
            }})
        # IDENTITÉ de chaque lot (titre, ce qui varie) — la pose commune à toutes les files.
        from wama.common.utils.batch_common import attach_identities
        attach_identities(batches_list)
        queue_count = len(jobs)
        batches_list, q_sort, q_filter = apply_queue_sort_filter(
            request, batches_list,
            name_of=lambda b: ({name_expr.replace('j.', 'b["items"][0].')} if b['items'] else ''))
        try:'''
    # `index` existe AUSSI comme FONCTION : l'imager route `path('', views.index)` (pas de
    # classe) — sans l'alias, le urls généré ne s'importait pas (`AttributeError: no attribute
    # 'index'`, page en 404, mesuré sur imager_01 le 22/09). Une ligne, pour toutes les apps.
    vues['index'] = (index_link if is_link else index_direct) + f'''
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
            'batches_list': batches_list, 'queue_count': queue_count,
            'q_sort': q_sort, 'q_filter': q_filter, 'params_json': params_json,
            'panel_defaults': panel_defaults,
        }})


index = IndexView.as_view()   # la même vue sous forme de FONCTION (route `views.index`)'''

    # Le dépôt ENVELOPPE à la création sur la forme à liaison (idiome des 9 apps réelles :
    # `wrap_in_batch` après `create`) ; la forme directe laisse `_auto_wrap_orphans` le faire
    # au chargement de la page (idiome converter).
    up_wrap = (f"\n    wrap_in_batch(item, batch_model={batch}, item_model={link}, fk_name='{link_fk}')"
               if is_link else '')
    vues['upload'] = f'''@require_POST
def upload(request):
    user = _user(request)
    f = request.FILES.get('file')
    if not f:
        return JsonResponse({{'error': 'Aucun fichier fourni'}}, status=400)
    kwargs = {{'user': user, '{d['input_field']}': f}}
    {f"kwargs['{d['name_field']}'] = f.name" if d['name_field'] else ''}
    {up_nature}{up_reglages}
    item = {item}.objects.create(**kwargs){up_wrap}
    return JsonResponse({{'id': item.id, 'status': item.status, 'warning': _avert}})'''
    if d['entry']['adds']:
        # Formes ATTACHE et MIXTE : la consigne et les réglages arrivent par la cascade (POST >
        # défauts), le fichier est FACULTATIF et peut être DÉSIGNÉ (médiathèque) — brique
        # `received_inputs`, celle des vues de création du composer et de l'avatarizer. La même vue
        # reçoit le DÉPÔT d'une card mixte (le fichier seul, posté sous `file`). Rien n'est lancé :
        # on ajoute, on règle, puis ▶ (CARD_DESIGN §11.11, règle des deux temps).
        p_field = d['entry']['prompt_field']
        vide = (f"not str(kwargs.get('{p_field}') or '').strip()" if p_field else 'True')
        # URL d'un port (`WamaApp.addToQueue` la poste sous `source_url` quand l'élément peut la
        # garder — même condition qu'au gabarit) : téléchargée dès la création (`source_ingest`).
        has_url = 'source_url' in d['champ_noms']
        ligne_url = ("\n    _url = (request.POST.get('source_url') or '').strip()"
                     "\n    if f is None and _url:\n        kwargs['source_url'] = _url"
                     if has_url else '')
        if has_url:
            vide += " and not kwargs.get('source_url')"
        # Ports secondaires : reçus par la MÊME brique, chacun sous son nom de port ; leur
        # provenance s'enregistre comme celle du principal. Un port secondaire ne suffit pas à
        # créer l'élément (une référence de forme n'est pas une consigne).
        sec = d['secondary_ports']
        secondary_lines = (f"\n    _others = []"
                     f"\n    for _port in {tuple(sec)!r}:"
                     f"\n        _r = received_inputs(request, user, '{app}', field=_port)"
                     f"\n        if _r:"
                     f"\n            kwargs[_port] = _r[0].value"
                     f"\n            _others.append((_port, _r[0]))"
                     f"\n        elif _r.refusal and not _avert:"
                     f"\n            _avert = _r.refusal"
                     if sec else '')
        record_sec = ("\n    for _port, _r in _others:\n        _r.record(item, _port)"
                      if sec else '')
        # La CONSIGNE vient de la card seule : passée par la cascade, une consigne vide
        # retomberait sur la DERNIÈRE consigne enregistrée, et chaque ajout l'enregistrerait
        # comme défaut du suivant. Elle sort du POST donné à la cascade et se pose après.
        # ⚠ `_poste` n'existe QUE s'il y a une consigne à retirer (2026-10-16) : la substitution
        # était faite pour toute app, la définition seulement avec `p_field` — une app SANS champ
        # de consigne (translate_01 : on dépose un texte, pas une consigne) levait `NameError:
        # name '_poste' is not defined` à chaque ajout, en 500.
        att_reglages = up_reglages
        if p_field:
            att_reglages = (f"\n    _poste = request.POST.copy()\n    _poste.pop('{p_field}', None)"
                            + up_reglages.replace('request.POST', '_poste')
                            + f"\n    kwargs['{p_field}'] = (request.POST.get('{p_field}') or '').strip()")
        vues['upload'] = f'''@require_POST
def upload(request):
    """Ajout à la file depuis la card d'entrée : consigne + fichier facultatif (téléversé ou
    désigné). Forme d'entrée déduite de l'obligation des ports du manifeste (`card_entry`)."""
    from wama.common.utils.media_paths import received_inputs
    user = _user(request)
    # Chaque port est posté sous SON nom (`addToQueue(ports: 'card')`) ; `file` reste le nom
    # d'une dépose (`WamaImport`), accepté en repli pour le port principal.
    received = received_inputs(request, user, '{app}', field='{d['input_field']}')
    if not received and not received.refusal:
        received = received_inputs(request, user, '{app}', field='file')
    kwargs = {{'user': user}}
    f = received[0] if received else None
    if f is not None:
        kwargs['{d['input_field']}'] = f.value
        {f"kwargs['{d['name_field']}'] = f.name" if d['name_field'] else ''}
    if f is not None:
        {up_nature.replace(chr(10) + '    ', chr(10) + '        ')}
    else:
        _avert = received.refusal{secondary_lines}{att_reglages}{ligne_url}
    if f is None and {vide}:
        return JsonResponse({{'error': received.refusal or 'Rien à ajouter : écrivez une consigne '
                                       'ou joignez un fichier.'}}, status=400)
    item = {item}.objects.create(**kwargs){up_wrap}
    if f is not None:
        f.record(item, '{d['input_field']}')   # provenance d'un fichier DÉSIGNÉ{record_sec}
    return JsonResponse({{'id': item.id, 'status': item.status, 'warning': _avert}})'''

    # RÉSULTAT INSTANTANÉ (2026-10-16, le Translator « à la DeepL » — capacité `instant_preview`,
    # `CARD_DESIGN §11.11 D bis`). La card l'appelle PENDANT la frappe : la glu de l'app
    # (`tasks.instant_result`) joue sur un élément NON enregistré — rien en file, rien en base.
    # Le texte vient de la card, les réglages de la MÊME cascade que l'ajout (la saisie retirée du
    # POST, comme pour une consigne). Sans champ de saisie, pas de corps : le bouchon 501 le dit.
    input_field = prompt_port_field(manifest.get('body') or {}, set(d['champ_noms']))
    if input_field:
        instant_settings = ''
        if _noms_schema:
            # La cascade SANS mémoire : la frappe n'écrit rien en base, préférences comprises —
            # c'est l'ajout à la file (le dépôt) qui les retient.
            instant_settings = ("\n    _posted = request.POST.copy()\n    _posted.pop('instant_text', None)"
                                "\n    kwargs.update(_element_settings(user, '', _posted))")
        vues['instant'] = f'''@require_POST
def instant(request):
    """Résultat INSTANTANÉ de la saisie (capacité `instant_preview`) : `tasks.instant_result`
    joué sur un élément NON enregistré — rien en file, rien en base. La card poste sa saisie sous
    `instant_text` (contrat de `wama-instant.js`) ; elle se pose ici dans le champ de l'app."""
    user = _user(request)
    text = (request.POST.get('instant_text') or '').strip()
    if not text:
        return JsonResponse({{'text': ''}})
    kwargs = {{'user': user}}{instant_settings}
    kwargs['{input_field}'] = text   # APRÈS les réglages : la saisie n'est jamais écrasée
    from .tasks import instant_result
    try:
        return JsonResponse({{'text': instant_result({item}(**kwargs))}})
    except NotImplementedError as exc:
        return JsonResponse({{'error': str(exc)}}, status=501)
    except Exception as exc:  # le modèle indisponible se DIT dans la zone, jamais un 500 muet
        return JsonResponse({{'error': f'Résultat indisponible : {{exc}}'}}, status=502)'''

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
    #   `consolidate_arrival` (le regroupement à l'arrivée déclaré par la fabrique, un lot par
    #   nature — conventions §9 ; 2026-10-16, il était recopié ici).
    #
    # ⚠ UNE URL N'EST PAS TÉLÉCHARGÉE ICI. On enregistre la SOURCE ; le récepteur commun
    # (`source_ingest`, 2026-10-13) la télécharge dès la création, HORS de la requête, et
    # `ensure_local_input` rattrape en tête de tâche (idempotent, WAMA_INGEST). Deux raisons : la requête ne
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
    bc_nature_url = (f"""nature = _nature_url(src) or _nature(nom or src)
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
    # style : elle servait DEUX consommateurs — le groupement à l'import (`nature_of`) et la
    # fusion par glisser-déposer (`group_key` de la fabrique de manipulation) — et une lambda
    # inline ne se partage pas : import refusant de mélanger les natures, drag&drop les
    # mélangeant. Depuis le 2026-10-16 l'import passe lui-même par la fabrique
    # (`consolidate_arrival`) : un seul consommateur, `group_key`, pour les deux gestes.
    # ⚠ NOM DISTINCT de `bloc_nature` (ligne ~161), qui porte `_TYPES_ENTREE` + `def _nature`.
    # Ma première graphie réutilisait ce nom et l'ÉCRASAIT : l'app générée perdait son
    # vocabulaire d'entrée et sa détection de nature, tout en gardant les appels `_nature(...)`
    # — donc un NameError à la première utilisation. Trois tests de `tests_codegen_lot` l'ont
    # dit tout de suite ; à l'œil, le diff n'avait l'air que d'un ajout.
    bloc_nature_de_lot = f'''def _nature_de_lot(o):
    """Nature de l'élément — ce qui peut cohabiter dans un lot.

    UNE déclaration, lue par la fabrique de manipulation de file (`group_key`) pour ses DEUX
    gestes : le regroupement à l'arrivée et la fusion par drag&drop."""
    return {bc_nature}'''
    # Émis sous CHAQUE orthographe admise (`urls_gen.ROUTE_ALIASES` : composer dit
    # `import_batch`) — même doctrine que `stop`/`cancel` : le corps est la convention, le nom
    # est lu au manifeste. L'assemblage plus bas ne retient que le nom déclaré par l'app.
    for _nom_bc in route_variants('batch_create'):
        vues[_nom_bc] = f'''@require_POST
def {_nom_bc}(request):
    """Crée N éléments depuis un fichier de lot, puis les regroupe — briques communes."""
    from pathlib import Path as _Path
    from django.conf import settings as _settings
    from wama.common.utils.batch_parsers import parse_batch_file_from_request
    from wama.common.utils.media_paths import OutsideMediaRoot, copy_into_app_input, resolve_under_media_root

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
                try:
                    absolu, _rel_src = resolve_under_media_root(src)
                except (OutsideMediaRoot, FileNotFoundError):
                    avertissements.append('Introuvable : ' + src)
                    continue
                _dest, rel = copy_into_app_input(absolu, '{app}', user.id, 'input')
                {bc_nom_fichier}
                {bc_nature_fichier}{bc_reglages}
                obj = {item}.objects.create(**kwargs)
                obj.{d['input_field']}.name = rel
                obj.save(update_fields=['{d['input_field']}'])
                # Provenance : la copie se souvient de sa source (brique commune, 2026-09-23 —
                # le lot généré était le dernier site de copie sans trace, D20/D21).
                from wama.common.utils.provenance import kind_of, record_origin
                record_origin(rel, kind=kind_of(_rel_src), ref=_rel_src, source_path=str(absolu))
            crees.append(obj)
        except Exception as e:
            avertissements.append(src + ' : ' + str(e))

    # La NATURE de l'entrée est renseignée plus haut, dans LES DEUX branches (URL et fichier),
    # par `_nature` — et `upload` la renseigne pareillement. Doter un seul des deux chemins est
    # ce qui a produit les trois derniers défauts de codegen ; le groupement ci-dessous en
    # dépend directement (`nature_of` lisait un champ que personne n'écrivait, donc UN lot
    # fourre-tout au lieu d'un lot par nature). Le regroupement est celui de la FABRIQUE
    # déclarée plus bas (`group_key`, `batch_extra`) : `consolidate_arrival`, commun aux apps.
    from wama.common.utils.queue_manipulation import consolidate_arrival
    lots = consolidate_arrival({item}, [o.id for o in crees], user)
    return JsonResponse({{'success': True, 'count': len(crees),
                         'batches': len(lots), 'warnings': avertissements}})'''

    # ▶ d'UN process (P5, `ROUTE §10.6` 5.1) — app à PLUSIEURS process seulement (le pipeline se
    # lit par la CLÉ, `pipeline_decl`) : la fabrique COMMUNE `make_process_start_view`, comme les
    # six apps réelles. Seules les sorties DÉCLARÉES du process lancé sont remplacées
    # (`reset_outputs`) ; la sortie d'un amont reste — c'est ce qu'un lancement borné reprend.
    from wama.common.manifests.codegen.pipeline_decl import declared_pipeline, process_specs
    _pipeline, _ = declared_pipeline(app)
    if _pipeline and len(process_specs(_pipeline)) >= 2:
        vues['start_process'] = f'''def _reset_for_process(item, process):
    """Remise à zéro d'un ▶ borné, sous le verrou (`begin_processing`)."""
    from .function_specs import PIPELINE
    PIPELINE.reset_outputs(item, (process,))
    item.progress = 0
    item.error_message = ''


start_process = make_process_start_view(
    work_model={item}, task_for=lambda _item: {task}, get_user=_user,
    reset_for_process=_reset_for_process)'''

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
    from wama.common.utils.scoping import editable_or_404
    item = editable_or_404({item}, user, pk=pk)   # le sien, ou en collaboration (E1)
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
    # (`conteneur_options` est décidé PLUS HAUT ; les noms aplatis sont ceux que le module
    # généré lit au schéma, `_SETTINGS_OUTSIDE`.)

    aplat = '' if not conteneur_options else f'''
    # Valeurs du conteneur JSON portées sur l'instance (transitoire) : la card émet ses
    # `data-param-*` par `item.<champ>`, le volet et la modale les relisent — mêmes valeurs
    # que ce que `update` écrit (idiome params_storage dérivé).
    try:
        _opts = dict(item.{conteneur_options} or {{}})
        for _k in _SETTINGS_OUTSIDE:
            setattr(item, _k, _opts.get(_k, ''))
    except Exception:
        pass'''
    # Nom du fichier de RÉSULTAT — la card générée l'affiche (`elem.output_filename`). Sur le
    # modèle réel c'est une @property (converter, describer) : glu non sérialisée, perdue par
    # le `models` généré — la card rendait une sortie SANS NOM, en silence (juge des membres
    # perdus, `converter_02`, 2026-10-07). Dérivé du champ que le manifeste déclare servir.
    out_file = d['out_file']
    output_name_line = '' if not out_file else f'''
    _set_unless_property(item, 'output_filename',
                         Path(item.{out_file}.name).name if item.{out_file} else '')'''
    decorateur = f'''def _set_unless_property(item, name, value):
    """Pose une valeur DÉCORATIVE sur l'instance — sauf si le modèle la calcule déjà.

    Les substitutions se font UNE À UNE : des vues GÉNÉRÉES peuvent servir un `models.py`
    encore COPIÉ, dont `gear_data` est une @property sans setter (glu de l'app réelle).
    Mesuré le 2026-09-22 sur `describer_01` : `item.gear_data = …` levait AttributeError au
    premier rendu de card, page vide 200, page habitée 500. La propriété du modèle réel
    rend déjà ce que la brique reconstituerait : on la laisse parler.
    """
    attr = getattr(type(item), name, None)
    if isinstance(attr, property) and attr.fset is None:
        return
    setattr(item, name, value)


def _decorer(item):
    """Chips de card GÉNÉRÉS du schéma (brique commune) — point d'attache unique index/card_html."""{aplat}
    # ⚠ L'aplatissement DOIT précéder les chips : ils lisent les valeurs SUR l'instance —
    # calculés avant, ils voyaient une instance vide (card sans Réglages, constat Fabien
    # 31/08 : les chips vivaient au volet mais pas sur la card).
    try:
        from wama.common.utils.card_chips import chips_by_section
        from .params import {schema_symbole}
        _set_unless_property(item, 'chips', chips_by_section(item, {schema_symbole}))
    except Exception:
        _set_unless_property(item, 'chips', {{}})
    # `gear_data` : le VOLET lit les data-* du bouton ⚙ (pas les data-param-* de la card —
    # deux lecteurs, deux sources). Sur le modèle RÉEL c'est une @property (glu non
    # sérialisée) : la brique commune `card_gear` la reconstitue depuis le schéma + les
    # valeurs de l'instance (aplaties ci-dessus) — volet PARAMÈTRES vide sinon (Fabien 31/08).
    try:
        from wama.common.utils.card_gear import gear_data
        from .params import {schema_symbole} as _sch
        _set_unless_property(item, 'gear_data', gear_data(item, _sch))
    except Exception:
        _set_unless_property(item, 'gear_data', {{}})
    # Propriétés RÉELLES du fichier d'entrée (extension, poids) — sous-ligne de la section
    # ENTRÉE (brique commune extraite du pilote reader ; constat Fabien 31/08 : la card ne
    # montrait que la nature).
    try:
        from wama.common.utils.card_chips import input_props_for
        _set_unless_property(item, 'input_props',
                             input_props_for(item, '{d['input_field']}', {nom_pour_props}))
    except Exception:
        _set_unless_property(item, 'input_props', []){output_name_line}
    # Alias NORMALISÉ `elem` (2026-09-09) : `common/_queue_entry.html` atteint l'élément
    # métier par `item.elem` — alias que `build_batches_list` pose sur chaque LIAISON. Pour la
    # card SEULE (`card_html`) comme pour la forme directe, liaison et élément COÏNCIDENT :
    # l'alias pointe sur l'item lui-même. Posé dans `_decorer`, point d'attache UNIQUE des
    # deux chemins de rendu (index et card_html).
    _set_unless_property(item, 'elem', item)
    # PIPELINE de la card (P5, 5.2) : lignes de process + état MONTRÉ, par la brique commune —
    # rien sans pipeline déclaré (la card lit alors `status`, la bande ne se rend pas).
    try:
        from wama.common.services.process_pipeline import decorate as _decorate_pipeline
        _decorate_pipeline(item)
    except Exception:
        pass
    return item'''

    vues['card_html'] = f'''def card_html(request, pk):
    """Card = partial serveur UNIQUE : le JS remplace la card par ce rendu."""
    user = _user(request)
    from wama.common.utils.scoping import visible_or_404
    item = visible_or_404({item}, user, pk=pk)   # LECTURE : le sien OU reçu
    # Clé `elem` (2026-09-09) — jumeau PAR CHAÎNE du renommage de `_generic_card.html` :
    # rendre ce partial avec l'ancienne clé sortirait une card complète et TOTALEMENT VIDE,
    # sans lever quoi que ce soit.
    # `in_batch` (2026-09-15) : position dans la file — brique commune.
    from wama.common.utils.batch_common import is_batch_child
    return render(request, '{app}/_generic_card.html',
                  {{'elem': _decorer(item), 'in_batch': is_batch_child(item)}})'''

    # PROGRESSION d'une card et de la file : la fabrique COMMUNE (`progress_views`, ROUTE §11 #37,
    # 2026-10-03), construite en tête du module (`_pv`, après `_user`) — ces vues n'en sont que
    # des noms. Lecture par `visible_or_404` (le sien OU reçu), progression vivante du cache que
    # publie le squelette de tâche, formule et vocabulaire du contrat de la barre commune.
    vues['status'] = "status = _pv['progress']"
    vues['progress'] = "progress = _pv['progress']"

    out_file, out_text = d['out_file'], d['out_text']
    # Nom d'une sortie TEXTE : brique commune `compose_output_name` (souche de l'entrée + tag
    # d'app + identifiant de card) — la règle du describer réel, pas un nom inventé ici.
    text_name = ("compose_output_name(app='{app}', ext='.txt', item_id=item.pk,\n"
                 "                              source_name=(Path(item.input_file.name).name\n"
                 "                                           if getattr(item, 'input_file', None) else ''))"
                 ).format(app=app)
    if out_file:
        vues['download'] = f'''def download(request, pk):
    user = _user(request)
    from wama.common.utils.scoping import visible_or_404
    item = visible_or_404({item}, user, pk=pk)   # LECTURE
    if not item.{out_file}:
        return JsonResponse({{'error': 'Aucun résultat'}}, status=404)
    return FileResponse(item.{out_file}.open('rb'), as_attachment=True,
                        filename=Path(item.{out_file}.name).name)'''
    elif out_text:
        vues['download'] = f'''def download(request, pk):
    """Résultat TEXTE déclaré (`processing.backend_result`) servi en pièce jointe `.txt`."""
    from django.utils.http import content_disposition_header
    from wama.common.utils.output_naming import compose_output_name
    user = _user(request)
    from wama.common.utils.scoping import visible_or_404
    item = visible_or_404({item}, user, pk=pk)   # LECTURE
    text = getattr(item, '{out_text}', '') or ''
    if item.status != 'SUCCESS' or not text:
        return JsonResponse({{'error': 'Aucun résultat'}}, status=404)
    name = {text_name}
    resp = HttpResponse(text, content_type='text/plain; charset=utf-8')
    resp['Content-Disposition'] = content_disposition_header(True, name)
    return resp'''
    else:
        vues['download'] = stub('download', pk=True)

    vues['delete'] = f'''@require_POST
def delete(request, pk):
    user = _user(request)
    item = get_object_or_404({item}, pk=pk, user=user)
    # Lot de l'élément, relevé AVANT la suppression — brique commune (`batch_common`). La
    # réponse dit ce que devient le lot ; `queue-actions.js` met la file à jour sans
    # rechargement de la page (2026-09-15).
    from wama.common.utils.batch_common import batch_snapshot, batch_state
    snapshot = batch_snapshot(item)
    release_card_files(item)   # tout ce que la card porte ; propriété + partage jugés par la brique
    item.delete()
    # ⚠ NE PAS supprimer le lot vidé ici (retiré le 2026-09-09). C'était une REDUPLICATION du
    # mécanisme commun `batch_sync` — `register_batch_sync(<Item>, direct_fk=True)` est branché
    # en `post_delete` par l'AppConfig générée, et `sync_batch_total` supprime déjà le lot
    # devenu vide (`common/utils/batch_sync.py:34`). Et c'est la duplication qui CASSAIT : le
    # signal supprime le lot AVANT le retour ici, l'instance gardée en mémoire n'a donc plus de
    # clé primaire, et `b.items.exists()` lève `ValueError: instance needs to have a primary key
    # value before this relationship can be used` → **500 sur un simple 🗑 de card**.
    # Mesuré le 2026-09-09 sur `converter_01` (`converter_01.duplicate_delete` rouge, doublon
    # toujours présent après clic). L'app RÉELLE de référence ne fait rien de tel non plus :
    # `converter/views.py::delete` se contente de `job.delete()` et laisse le signal faire.
    return JsonResponse({{'deleted': True, 'batch': batch_state(snapshot, {item})}})'''

    vues['duplicate'] = f'''@require_POST
def duplicate(request, pk):
    user = _user(request)
    from wama.common.utils.scoping import duplicable_or_404
    item = duplicable_or_404({item}, user, pk=pk)   # le sien OU reçu : la copie est à soi
    new = duplicate_instance(
        instance=item,
        for_user=user,
        reset_fields={{'status': 'PENDING', 'progress': 0, 'task_id': '', 'error_message': ''}},
        clear_fields={champs_sortie!r},
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
        release_card_files(item)
        item.delete()
        n += 1
    {batch}.objects.filter(user=user, {items_related}__isnull=True).delete()
    return JsonResponse({{'cleared': n}})'''

    if out_file or out_text:
        # Le ZIP de FILE par la fabrique (2026-10-17) : la file que compte `_pv`, les entrées
        # écrites comme celles du lot (déclarées à `make_batch_views`, `bv_output` plus bas).
        vues['download_all'] = "download_all = _pv['download_all']"
    else:
        vues['download_all'] = stub('download_all')

    # Contrat du COMPOSANT COMMUN (`wama-global-progress.js`) : rendu par la fabrique (`_pv`).
    vues['global_progress'] = "global_progress = _pv['global_progress']"

    vues['console'] = f'''def console_content(request):
    user = _user(request)
    return JsonResponse({{'lines': get_console_lines(user.id, app='{app}')}})'''

    # ÉDITION D'UN ÉLÉMENT — même lecture de corps et même affectation que les vues de LOT :
    # les deux passent par la brique `batch_views` (`read_settings_payload` coerce selon le
    # schéma et retire les vides ; `apply_item_settings` pose colonnes déclarées + conteneur
    # JSON des hors-colonnes, idiome `params_storage`). Jusqu'au 22/09 ces deux idiomes étaient
    # ÉMIS ici (une vingtaine de lignes par vue) ; la fabrique de lot les a absorbés.
    # Deux noms pour une seule vue : le converter route `update/` vers `views.update_job`.
    def corps_update(nom):
        return f'''@require_POST
def {nom}(request, pk):
    user = _user(request)
    from wama.common.utils.scoping import editable_or_404
    item = editable_or_404({item}, user, pk=pk)   # le sien, ou en collaboration (E1)
    if item.status == 'RUNNING':
        return JsonResponse({{'error': 'Impossible de modifier un élément en cours'}}, status=400)
    donnees = read_settings_payload(request, _SCHEMA, _SETTING_NAMES)
    touches = apply_item_settings(item, donnees, params_fields=_SETTING_COLUMNS,
                                  options_field=_OPTIONS_FIELD, extra_names=_SETTINGS_OUTSIDE)
    if touches:
        item.save(update_fields=touches)
    return JsonResponse({{'success': True, 'id': item.id, 'updated': touches}})'''

    for _nom in route_variants('update'):
        if alias_fits('update', _nom, d['view_patterns']):
            vues[_nom] = corps_update(_nom)
    # … and under the VIEW name when the route carries a conventional name the view does not.
    for _view, _route in d['view_routes'].items():
        if (_view not in vues and _route in route_variants('update')
                and '<int:pk>' in d['view_patterns'].get(_view, '')):
            vues[_view] = corps_update(_view)

    # Les SIX vues de lot viennent de la FABRIQUE COMMUNE `make_batch_views` (bloc `fabrique`
    # ci-dessous) — extraite de ce gabarit le 2026-09-22 (ROUTE §11 #36) : ce fichier n'émet plus
    # leurs corps. `batch_download` répond 404 JSON quand l'élément n'a pas de `output_file`.

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

    batch_extra_kw = (f"""
    batch_extra=lambda w: {{'{d['batch_extra']}': w.{d['batch_extra']}}},""" if d['batch_extra'] else '')
    # Fabrique des VUES DE LOT — les kwargs de forme sont ceux de `attach_to_batch` ; le reste
    # est LU au manifeste (champs fichier de la facette data, params déclarés, schéma).
    form_kwargs = (f"item_model={link}, fk_name='{link_fk}'" if is_link
                   else f"batch_attr='{fk}', row_field='{row}'")
    # Sortie servie par le ZIP de lot — le MÊME résultat déclaré que `download` (défaut de la
    # brique : `output_file`, rien à émettre).
    bv_output = (f"\n    output_text='{out_text}'," if out_text
                 else f"\n    output_field='{out_file}'," if out_file and out_file != 'output_file'
                 else '')
    bv_extra = (f"""
    batch_extra=lambda lot: {{'{d['batch_extra']}': lot.{d['batch_extra']}}},""" if d['batch_extra'] else '')
    fabrique_lot = f'''

# Fabrique COMMUNE des VUES DE LOT (`batch_views`, 2026-09-22) : les six actions de lot,
# paramétrées par le manifeste — champs de SORTIE de la facette data, réglages déclarés, schéma.
_bv = make_batch_views(
    work_model={item}, batch_model={batch}, get_user=_user, task={task},
    output_fields={champs_sortie!r},
    params_fields=_SETTING_COLUMNS, schema=_SCHEMA,
    options_field=_OPTIONS_FIELD, extra_names=_SETTINGS_OUTSIDE,
    {form_kwargs}, items_related='{items_related}',{bv_extra}{bv_output}
)
batch_start     = _bv['batch_start']
batch_update    = _bv['batch_update']
batch_delete    = _bv['batch_delete']
batch_duplicate = _bv['batch_duplicate']
batch_download  = _bv['batch_download']
batch_status    = _bv['batch_status']
batch_promote   = _bv['batch_promote']
batch_realign   = _bv['batch_realign']'''
    fabrique_link = f'''# Fabrique COMMUNE de manipulation de file (forme à LIAISON — lue au manifeste,
# `processing.model_spec.batch`) : la meme brique que les 9 apps reelles.
_qm = make_queue_manipulation_views(
    work_model={item}, batch_model={batch},
    item_model={link}, fk_name='{link_fk}',
    get_user=_user,{batch_extra_kw}
    # La meme regle decide de ce qui peut cohabiter dans un lot, qu'on y arrive par import
    # groupe (`consolidate_arrival`) ou par glisser-deposer.
    group_key=_nature_de_lot,
)'''
    fabrique_direct = f'''# Fabrique COMMUNE de manipulation de file (forme FK-DIRECTE — dérivée de la facette data).
_qm = make_queue_manipulation_views_direct(
    work_model={item}, batch_model={batch},
    batch_fk='{fk}', row_field='{row}',
    get_user=_user,{batch_extra_kw}
    # La meme regle decide de ce qui peut cohabiter dans un lot, qu'on y arrive par import
    # groupe (`consolidate_arrival`) ou par glisser-deposer.
    group_key=_nature_de_lot,
)'''
    fabrique = (fabrique_link if is_link else fabrique_direct) + fabrique_lot + f'''
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

    # ── Chaque corps conventionnel existe AUSSI sous ses orthographes déclarées ──
    # `urls_gen.ROUTE_ALIASES` est le propriétaire du vocabulaire : un alias qui y entre est
    # servi ici sans qu'un gabarit ait à le connaître (stop/cancel et update/update_job avaient
    # chacun leur boucle ; `upload/generate` du composer a montré le 22/09 qu'il en faudrait une
    # par alias — donc une règle générale). Le premier `def <canon>(` du corps prend le nom
    # déclaré ; une classe (index) n'a pas d'alias.
    for _canon, _alts in ROUTE_ALIASES.items():
        if _canon in vues:
            for _alt in _alts:
                if _alt not in vues and alias_fits(_canon, _alt, d['view_patterns']):
                    vues[_alt] = vues[_canon].replace(f'def {_canon}(', f'def {_alt}(', 1)

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
                         'remove_from_batch', 'consolidate',
                         'batch_start', 'batch_update', 'batch_delete', 'batch_duplicate',
                         'batch_download', 'batch_status', 'batch_promote', 'batch_realign'}
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
            if nom in couverts_fabrique:
                # `batch_status` (describer, enhancer…) est déclaré en EXTRA : la fabrique le rend,
                # un bouchon en plus ferait deux définitions (mesuré le 22/09 sur describer).
                continue
            if nom in vues:
                blocs.append(vues[nom])
                continue
            if nom in d['extra_classes']:
                # `IndexView` est DÉJÀ la classe conventionnelle émise par `vues['index']`
                # (l'anonymizer route son `upload` sur elle) : la redéfinir écraserait la file.
                if nom != 'IndexView':
                    blocs.append(stub_class(nom))
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

    # ── Ce que le fichier généré sait de sa forme de file ──
    # Les kwargs de forme sont passés aux FABRIQUES (manipulation de file, vues de lot), qui
    # rattachent par `attach_to_batch` — les corps de vues sont IDENTIQUES d'une forme à
    # l'autre. Une forme = un endroit. La lecture d'un lot passe par `batch_elements(b,
    # <Item>)` (brique, ordre des lignes garanti) — un helper généré `_batch_elements` a vécu
    # quelques heures le 22/09 : c'était un chemin parallèle.
    # `_link_to_batch` n'est plus émis qu'en forme DIRECTE, pour sa boucle d'orphelins : en
    # forme à liaison, son dernier appelant était `batch_create`, qui délègue son regroupement
    # à la fabrique depuis le 2026-10-16 (`consolidate_arrival`).
    if is_link:
        helpers_forme = f'''

def _auto_wrap_orphans(user):
    """Chaque item HORS LOT devient son propre lot-de-1 — brique COMMUNE, stratégie par
    défaut (orphelin → batch-of-1, règle des 10 apps depuis le 2026-08-14)."""
    auto_wrap_orphans(user, work_model={item}, batch_model={batch},
                      item_model={link}, fk_name='{link_fk}')
'''
        imports_forme = f'''from wama.common.utils.batch_common import (auto_wrap_orphans, batch_elements,
                                            build_batches_list, wrap_in_batch)
from wama.common.utils.queue_manipulation import make_queue_manipulation_views'''
        import_models = f'from .models import {batch}, {link}, {item}'
        forme_doc = f"liaison {link} (FK '{link_fk}' → item, '{link_batch}' → lot)"
    else:
        helpers_forme = f'''

def _link_to_batch(lot, obj, idx):
    """Rattache un élément à un lot — brique commune, forme à FK DIRECTE (idiome converter)."""
    return attach_to_batch(obj, lot, idx, batch_attr='{fk}', row_field='{row}')


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
            _link_to_batch(b, w, 0)
        except Exception:
            pass
'''
        imports_forme = f'''from wama.common.utils.batch_common import attach_to_batch, batch_elements
from wama.common.utils.queue_manipulation import make_queue_manipulation_views_direct'''
        import_models = f'from .models import {batch}, {item}'
        forme_doc = f"FK directe '{fk}'"

    # La sortie FICHIER d'une card, ajoutée au suivi de la card (`output_url`, ce que lit le
    # rafraîchissement généré) — la seule clé propre d'une app conventionnelle.
    pv_extra = (",\n                          extra=lambda item: ({'output_url': item.output_file.url}"
                " if item.output_file else {})" if d['a_output'] else '')
    tete = f'''"""
{mark} — views.py GÉNÉRÉ par le gabarit A (views_gen, marche S2).

CONVENTIONNEL paramétré par le manifeste (item={item}, batch={batch}, forme de file :
{forme_doc}, tâche {task}) ; les endpoints hors convention sont des STUBS 501 marqués
TROU DE GLU (marche B) — la page boote, la fonctionnalité manque VISIBLEMENT (détecteur).
"""
import json
from pathlib import Path

from django.http import FileResponse, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views import View
from django.views.decorators.http import require_POST

from wama.accounts.views import get_or_create_anonymous_user
from wama.common.utils.console_utils import get_console_lines
from wama.common.utils.detail_registry import normalize_status
from wama.common.utils.process_control import begin_processing, stop_instance
from wama.common.utils.batch_views import apply_item_settings, make_batch_views, read_settings_payload
from wama.common.utils.progress_views import make_progress_views
from wama.common.utils.queue_duplication import duplicate_instance, release_card_files
{imports_forme}
{'from wama.common.utils.process_views import make_process_start_view' + chr(10) if 'start_process' in vues else ''}from wama.common.utils.queue_view import apply_queue_sort_filter

{import_models}
from .tasks import {task}

# Schéma de réglages de l'app — LU au manifeste (`params.primary`) ; absent → aucun réglage.
try:
    from .params import {schema_symbole} as _SCHEMA
except Exception:
    _SCHEMA = []

# Les noms de réglages LUS au schéma, et les COLONNES de l'élément parmi eux LUES au modèle —
# jamais une liste figée à la génération (`check_redundancy` les relevait dans huit jumelles :
# elles dérivaient au premier réglage ajouté à la source). Un réglage du schéma sans colonne va
# au conteneur JSON `options` quand le modèle en porte un (idiome `params_storage`).
_SETTING_NAMES = [p['name'] for p in _SCHEMA if p.get('name')]
_ITEM_COLUMNS = {{f.name for f in {item}._meta.concrete_fields}}
_SETTING_COLUMNS = [n for n in _SETTING_NAMES if n in _ITEM_COLUMNS]
_SETTINGS_OUTSIDE = [n for n in _SETTING_NAMES if n not in _ITEM_COLUMNS]
_OPTIONS_FIELD = 'options' if _SETTINGS_OUTSIDE and 'options' in _ITEM_COLUMNS else None


def _user(request):
    return request.user if request.user.is_authenticated else get_or_create_anonymous_user()


# Les vues de PROGRESSION (une card, la file) : fabrique COMMUNE (`progress_views`, ROUTE §11 #37).
_pv = make_progress_views(work_model={item}, app_id='{app}'{pv_extra})
{helpers_forme}{bloc_nature}{bloc_reglages}
'''
    return tete + '\n\n\n'.join(blocs) + '\n', None
