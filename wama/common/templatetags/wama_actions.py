"""
Tags d'inclusion des ACTIONS DE CARD — l'héritage du mécanisme, côté gabarit.

Calqué sur `wama_catalog.refresh_button` : la card nomme son app, et reçoit le rendu que la
DÉCLARATION impose. C'est ce qui empêche la treizième card de recopier le bouton de la douzième.

Pourquoi seul ⬇ y figure : les cinq autres actions de card (⚙ ▶ ⧉ 🗑 ✏) sont des BOUTONS à
comportement, donc leur domicile commun est le JS (`queue-actions.js`, `wama-cycle-button.js`) et
le gabarit n'a qu'à poser une classe. ⬇ est un LIEN — il n'a rien à déléguer, et sa divergence
vivait donc entièrement dans le markup. Elle ne pouvait se résorber que là.
"""
from django import template

register = template.Library()


@register.inclusion_tag('common/_download_button.html')
def download_button(app, url, ready, available=None, title=None, empty_title=None, css_class=None,
                    html_id=None, label=None, split=True):
    """Rend le bouton ⬇ de l'app `app` selon `WAMA_APP_CONVENTIONS §6.3`.

    `url`       : URL de téléchargement SANS query (`{% url 'app:download' o.id %}`).
    `ready`     : y a-t-il un résultat ? (sinon → bouton désactivé, l'action reste VISIBLE).
    `available` : restriction au niveau de l'ITEM — un format déclaré que CET élément n'a pas
                  (ex. `json` de reader, qui suppose un `raw_result`) ne doit pas s'afficher.
                  `None` = tous les formats déclarés. Passer une liste VIDE n'aurait pas le même
                  sens (aucun format), d'où le défaut à `None` et non à `()`.

    La forme — lien simple ou split ▾ — n'est PAS un paramètre : elle se déduit de
    `export_formats` déclaré au catalogue. Une app ne peut donc pas choisir sa forme au gabarit,
    ce qui est exactement ce qui avait laissé deux apps rendre un `<button>`+JS contraire à §6.3.

    ⚠ `split` n'est pas une exception à ce principe (2026-08-30) : il ne dit pas « avec ou sans
    formats », il dit à quel NIVEAU on est. `split=False` est la forme d'une action de BARRE DE
    FILE, où il n'existe pas de « format par défaut » cliquable sans ouvrir le menu — la barre
    télécharge TOUT, ou rien. Les formats offerts restent, eux, ceux de la DÉCLARATION.
    `html_id` / `label` existent pour la même raison (le JS d'app cible le bouton de barre par
    son id, et une barre porte un libellé là où une card n'a qu'une icône).

    ⚠ Renommé le 2026-08-30 (ex-`bouton_telecharger`, params `pret`/`disponibles`/`titre`/
    `titre_vide`/`classe`) : un tag est lu dans 12 gabarits, donc une API — anglais obligatoire.
    """
    from wama.common.utils.export_formats import entries_for_app
    return {
        'url': url,
        'ready': bool(ready),
        'formats': entries_for_app(app, available),
        'title': title,
        'empty_title': empty_title,
        'css_class': css_class,
        'id': html_id,
        'label': label,
        'split': bool(split),
    }


def _result_reference_url(surface):
    """Route commune de la référence pour une surface ÉVALUABLE, None sinon."""
    from django.urls import reverse
    from wama.common.services.result_evaluation import evaluation_spec
    if evaluation_spec(surface) is None:
        return None
    return reverse('common:api_result_reference', args=[surface, 'element', 0])


def _result_import_url(surface):
    """Route commune du résultat existant pour une surface qui le REPREND, None sinon (pk 0)."""
    from django.urls import reverse
    from wama.common.services.result_evaluation import evaluation_spec
    spec = evaluation_spec(surface)
    if spec is None or spec.import_result is None:
        return None
    return reverse('common:api_result_import', args=[surface, 0])


def _nature_label(nature):
    """Libellé AFFICHÉ d'une nature de la médiathèque (`object3d` → « Objet 3D ») ; la clé telle
    quelle si la nature est inconnue, '' sans nature."""
    if not nature:
        return ''
    from wama.media_library.natures import ASSET_NATURES
    found = ASSET_NATURES.get(nature)
    return found.label if found else nature


def _category_label(category):
    """Libellé AFFICHÉ d'une catégorie média (`3d` → « Objets 3D ») ; '' pour `all`."""
    from wama.common.app_registry import MEDIA_CATEGORY_LABELS
    if not category or category == 'all':
        return ''
    return MEDIA_CATEGORY_LABELS.get(category, category)


def _result_reference_accept(surface):
    """Les extensions que l'app sait LIRE comme référence (sa déclaration), pour le sélecteur."""
    from wama.common.services.result_evaluation import evaluation_spec
    spec = evaluation_spec(surface)
    return ','.join(spec.reference_extensions) if spec and spec.reference_extensions else None


@register.simple_tag
def queue_dnd_attrs(app, domain=None):
    """Attributs de MANIPULATION DIRECTE à poser sur le conteneur de file (CARD_DESIGN §3bis).

    Usage, sur le `<div class="wama-queue-…">` de l'app :
        <div id="…" class="wama-queue-{{ card_layout }}" {% queue_dnd_attrs 'reader' %}>
    ou, pour une file scopée par domaine :
        <div … {% queue_dnd_attrs 'enhancer' 'audio' %}>

    POURQUOI DES ATTRIBUTS ET PAS `APP.urls`. Les 12 apps exposent déjà leurs URLs au JS, mais
    chacune sous SON global (`READER_APP`, `IMAGER_APP`…) : une brique commune ne peut pas les
    lire sans connaître un nom d'app par app — exactement la « liste de graphies d'apps écrite
    dans le substrat » que `queue-actions.js` documente comme le symptôme d'une brique manquante.
    Le DOM, lui, est déjà le véhicule commun des URLs d'action (`data-batch-<action>-url`) : on
    suit ce contrat plutôt que d'en inventer un second.

    UNE ROUTE ABSENTE N'ÉMET PAS SON ATTRIBUT — `{% url %}` en mode `as` ne lève pas. La brique
    JS désactive alors le geste correspondant, au lieu de POSTer dans le vide. Même contrat de
    non-collision que les boutons de lot : ce qui n'est pas déclaré n'existe pas.

    `data-wama-dnd` marque la file comme manipulable : c'est LUI que la brique cherche, jamais
    une classe de conteneur. Une file qui n'en veut pas (page de démo, file en lecture seule)
    n'a rien à désactiver.
    """
    from django.urls import NoReverseMatch, reverse
    from django.utils.html import format_html_join
    from wama.common.utils.app_modes import route_prefix

    p = route_prefix(app, domain) if domain else ''
    pfx = f'{p}_' if p else ''

    def _url(nom, avec_pk=False):
        try:
            return reverse(f'{app}:{pfx}{nom}', args=[0] if avec_pk else None)
        except NoReverseMatch:
            return None

    paires = [
        ('data-dnd-reorder-url',      _url('reorder')),
        ('data-dnd-reorder-queue-url', _url('reorder_queue')),
        ('data-dnd-move-url',         _url('move_to_batch', avec_pk=True)),
        ('data-dnd-remove-url',       _url('remove_from_batch', avec_pk=True)),
        # ⚠ `merge`, PAS `consolidate` — deux opérations distinctes (cf. le bloc du même nom
        # dans `queue_manipulation.py`). `consolidate` est l'import : cinq apps le redéfinissent
        # en version PAR NATURE, qui RANGE en plusieurs lots au lieu de refuser. Router le geste
        # de fusion dessus rendait « succès » après n'avoir rien fait de visible.
        ('data-dnd-merge-url',        _url('merge')),
        # Geste « Résultat de référence… » (port `reference_result`) : émis SEULEMENT pour une
        # surface qui a déclaré son évaluation — le menu de card n'offre pas un port que rien ne
        # lit. L'URL est celle d'un ÉLÉMENT au pk 0 ; la brique y substitue nature et pk.
        ('data-result-reference-url', _result_reference_url(app)),
        ('data-result-reference-accept', _result_reference_accept(app)),
        # « Résultat existant… » (port `work_result`) : seulement si l'app sait le reprendre.
        ('data-result-import-url', _result_import_url(app)),
    ]
    # « Programmer… » (calendrier, étape 3 — ROUTE §10.6 point 13) : seulement si la file a un
    # OUTIL de lancement dans `tool_api` — c'est lui que le distributeur appellera (dérivation
    # unique, partagée avec le fichier batch : `scheduled_actions.start_tool_for`).
    from wama.common.services.scheduled_actions import start_tool_for
    tool = start_tool_for(app, p)
    if tool:
        paires += [('data-schedule-url', reverse('common:schedule_create')),
                   ('data-schedule-tool', tool)]
    presents = [(k, v) for k, v in paires if v]
    if not presents:
        return ''
    presents.insert(0, ('data-wama-dnd', app))
    if domain:
        presents.append(('data-dnd-domain', domain))
    return format_html_join(' ', '{}="{}"', presents)


@register.simple_tag
def domain_route_prefix(app, domain=None):
    """Préfixe des routes de ce domaine, LU dans la déclaration (`app_modes.route_prefix`).

    Remplace le paramètre `batch_ns` que la card mère de lot recevait à la main (2026-08-23).
    La différence n'est pas cosmétique : `batch_ns='enhancer:audio_batch'` était un namespace
    d'app écrit dans un gabarit d'app — donc une rustine qui ne se propageait pas. Ici le
    gabarit ne connaît que SON nom et SON domaine ; c'est la déclaration qui sait le reste, et
    une future app à trois domaines n'aura rien à passer de plus.
    """
    if not domain:
        return ''
    from wama.common.utils.app_modes import route_prefix
    p = route_prefix(app, domain)
    return f'{p}_' if p else ''


@register.simple_tag
def live_input_declared(app):
    """L'app déclare-t-elle la capture EN DIRECT (`has_live_input`) ? — pour la card v3, qui
    affichait le bouton Speak sur le seul littéral `show_live` de la page (2026-09-28)."""
    from wama.common.app_registry import app_has_live_input
    return app_has_live_input(app)


@register.simple_tag
def input_slots(app, domain=None):
    """Les SLOT-ROWS de la card d'entrée v4 — une par PORT déclaré, avec ses modalités.

    Le gabarit ne reçoit plus des littéraux par app (`show_url`, `show_media_library`,
    `reference_accept`…) mais la LISTE de ce que l'app déclare : `studio_node_ports(app)`
    en est la seule source. Ajouter un port à une app lui donne son slot, sans toucher au
    gabarit — c'est la règle « métadonnée-driven » appliquée à la zone de preview
    (`CARD_DESIGN §11.11 B`).

    Ce que le tag DÉRIVE, et pourquoi chaque dérivation est légitime :
      - `accept`  : des `types` du port (jamais de l'app) — c'est ce qui donne enfin à la
                    médiathèque un filtre PAR RÔLE (exigence 5 du §11.8, aujourd'hui globale
                    à la card et donc parfois fausse) ;
      - `folder`  : seulement si le port est `multi` — importer un dossier dans un slot qui
                    n'accepte qu'un fichier n'a aucun sens ;
      - `url`     : sur tout port FICHIER (l'ingest distant est commun, `ensure_local_input`) ;
      - `live`    : la CAPACITÉ d'app `has_live_input` (`app_registry.app_has_live_input`,
                    2026-09-28) — déclarée au catalogue, lue ici ; plus de littéral `show_live`
                    passé par la page.

    Le port `prompt` est EXCLU : ce n'est pas un slot de la zone de preview, c'est la cellule
    primaire au-dessus (§11.9 C — le seul élément autorisé à grandir).
    """
    from wama.common.app_registry import (app_own_input_ports, app_ports_carried_elsewhere,
                                          studio_node_ports)

    # UN inventaire pour la card et le nœud du Studio (`studio_node_ports`), qui porte EN TÊTE les
    # ports que l'app consomme elle-même (le fichier de travail du synthesizer) ; moins les ports
    # qu'un RÉGLAGE porte (la voix de référence du synthesizer, choisie dans `voice_preset`).
    # `card_ports` ne sert plus qu'à leurs OBLIGATIONS (`known` ci-dessous). 2026-09-30.
    card_ports = app_own_input_ports(app)
    carried = app_ports_carried_elsewhere(app)
    ports = [p for p in ((studio_node_ports(app) or {}).get('inputs') or [])
             if p.get('id') not in carried]
    # Card d'un DOMAINE (imager image/vidéo, enhancer image-vidéo/audio — deux cards par page) :
    # seulement les ports dont le domaine accepte les natures (`ports_for_domain`, 2026-09-30).
    domain = domain or None
    if domain:
        from wama.common.app_registry import ports_for_domain
        ports = ports_for_domain(app, domain, ports)

    # ── L'OBLIGATION VIENT DES MODÈLES, pas du groupe (2026-09-11) ──────────────────────
    # `required` valait `group == 'travail'` : tout port de travail était donc annoncé
    # « requis ». Mesuré au navigateur sur la card v4 de l'imager, elle affichait « Image de
    # travail REQUIS » alors que `work_image` n'est exigé que par 2 de ses 12 modèles (les 10
    # autres génèrent depuis le seul prompt). C'est un mensonge d'interface : l'utilisateur
    # d'un modèle texte→image se serait cru bloqué faute d'image.
    # L'union sait la vérité (`app_input_ports` : requis = exigé par TOUS les modèles retenus),
    # et c'est ce que dit `matches_inputs` côté serveur. Repli sur l'ancien critère quand
    # l'union est vide (app sans moteur IA) — le comportement d'avant, exactement.
    # Les ports du RÉSULTAT (`app_result_ports`) portent leur propre obligation — jamais requis :
    # sans eux ici, le repli par groupe annoncerait « requis » le `work_result` (groupe travail).
    from wama.common.app_registry import app_input_ports, app_result_ports
    result_ports = app_result_ports(app)
    known = (app_input_ports(app, domain) or []) + result_ports + card_ports
    oblig = {p['id']: p['required'] for p in known}
    # « L'un OU l'autre » (2026-09-30, `app_input_ports`) : l'avatarizer exige une image OU un
    # objet 3D. Le PREMIER port du groupe (ordre des onglets) est celui que le geste nocturne
    # remplit (`ui_smoke._fill_required_ports`) — il en faut un, pas deux.
    alternatives = {p['id']: p.get('one_of') or [] for p in known}
    port_labels = {p['id']: p.get('label', p['id']) for p in known}
    # Le prompt n'est jamais un onglet : dans « requis · ou … » il se dit comme on le voit.
    port_labels['prompt'] = 'le texte saisi'
    seen_groups = set()
    textes = {p['id']: p.get('description', '') for p in known}
    # Un port du RÉSULTAT n'entre pas par l'upload mais par l'ÉVALUATION : ses formats sont
    # ceux qu'elle déclare savoir lire (`reference_extensions`), pas `input_extensions`.
    result_ids = {p['id'] for p in result_ports}

    from wama.common.app_registry import port_accept
    from wama.common.utils.app_modes import library_nature_for
    slots = []
    primary_seen = False
    for port in ports:
        if port.get('group') == 'prompt':
            continue
        types = port.get('types') or []
        # Ce que l'app DÉCLARE pour les natures du port — la liste que l'upload vérifie ; pour
        # un port du résultat, celle que l'évaluation lit.
        accept = ((port.get('id') in result_ids and _result_reference_accept(app))
                  or port_accept(app, types))
        travail = port.get('group') == 'travail'
        # IMPORT = UN SEUL GESTE (décision Fabien 05/09) : fichier(s) ET dossier(s), dépôt ET
        # clic — `drop` et `folder` ne sont plus deux modalités. Le sélecteur de dossier reste
        # une affordance DANS la tuile Importer (contrainte de l'<input> natif), sur les ports
        # `multi` seulement.
        mods = ['import', 'library', 'url']
        # Le PREMIER port de travail est le port PRINCIPAL : il porte les ids historiques de la
        # card (dropzone, input, dossier, URL, gabarit de lot) — ceux que lisent `WamaImport` et
        # les gestes nocturnes. Les ports de travail suivants (l'avatarizer : audio ET image)
        # reçoivent des ids dérivés de leur port (2026-09-29) : sans cela la v4 rendait N
        # dropzones au même id.
        primary = travail and not primary_seen
        primary_seen = primary_seen or primary
        others = alternatives.get(port.get('id')) or []
        one_of_group = frozenset(others + [port.get('id')]) if others else None
        one_of_first = bool(one_of_group) and one_of_group not in seen_groups
        if one_of_group:
            seen_groups.add(one_of_group)
        slots.append({
            'id': port.get('id'),
            'kind': 'file',
            'label': port.get('label') or port.get('id'),
            'group': port.get('group'),
            'accept': accept,
            'primary': primary,
            # `media_library_type` n'accepte qu'UNE valeur : un port multi-nature (converter)
            # ouvre la médiathèque non filtrée plutôt que sur une nature arbitraire.
            'library_type': types[0] if len(types) == 1 else 'all',
            # Son LIBELLÉ (« Objets 3D », pas la clé `3d`) — table déclarée avec les catégories.
            'library_type_label': _category_label(types[0] if len(types) == 1 else 'all'),
            # L'ONGLET d'ouverture de la médiathèque, quand l'app le déclare (`library_natures`).
            'library_prefer': library_nature_for(app, port.get('id')),
            # Son LIBELLÉ, celui de la nature (« Objet 3D », pas la clé `object3d`).
            'library_prefer_label': _nature_label(library_nature_for(app, port.get('id'))),
            'multi': bool(port.get('multi')),
            'required': oblig.get(port.get('id'), travail),
            # Requis « ou » ces autres ports (libellés, pour être affichés tels quels) — et le
            # premier du groupe, celui qu'un geste automatique remplit.
            'one_of': [port_labels.get(a, a) for a in others],
            'one_of_first': one_of_first,
            # Texte qui dit À QUOI sert cette entrée (demande Fabien 10/09) : deux onglets
            # « Image » ne se distinguent pas par leur type — il faut dire lequel sera ÉDITÉ et
            # lequel GUIDERA. Vide tant que le gabarit ne l'affiche pas : ajout additif.
            'description': textes.get(port.get('id'), '') or port.get('description', ''),
            'modalities': mods,
        })
    from wama.common.app_registry import app_has_live_input
    if app_has_live_input(app):
        # LE LIVE EST UN PORT, pas une modalité (décision Fabien 05/09, CARD_DESIGN §11.11 D) :
        # « en direct » est une SOURCE alternative au fichier de travail, pas une façon de le
        # fournir. Sa modalité unique ARME ; ▶ démarre (deux temps, §11.9 A).
        slots.append({
            'id': 'live', 'kind': 'live', 'label': 'En direct', 'group': 'live',
            'accept': '', 'library_type': 'all', 'multi': False, 'required': False,
            'description': "Capture en direct au lieu d'un fichier. Le clic ARME, ▶ démarre.",
            'modalities': ['arm'],
        })
    return slots


@register.simple_tag
def ports_have_group(ports, group):
    """Un des ports de la card appartient-il à ce groupe (`reference`, `travail`…) ? — pour qu'un
    gabarit décide sur la LISTE qu'il a reçue, sans reboucler dessus."""
    return any((p or {}).get('group') == group for p in (ports or []))


@register.simple_tag
def lot_slot(app):
    """L'onglet « Lot » de la card v4 — `None` si l'app ne déclare pas le lot (`has_batch`).

    Ce n'est PAS un port (décision de Fabien, 2026-09-29) : un port est une entrée d'un nœud
    Studio (`studio_node_ports`), qui passe dans les manifestes et les pipelines. Un fichier de
    lot n'est l'entrée d'aucun nœud : chacune de ses lignes remplit une card ENTIÈRE — fichier de
    travail, prompt, référence, sortie, réglages, programmation (`BATCH_FORMAT.md`). D'où un
    onglet de la card, rendu comme les ports, jamais déclaré parmi eux.

    Il donne à la règle 1 de BATCH_FORMAT (« l'intention déclarée prime ») son geste : posé
    ici, un fichier EST un lot ; posé sur le port de travail, c'est toujours sa STRUCTURE qui
    décide (règle 2 — `WamaImport` tente la détection, puis retombe sur le contenu). Et une app
    SANS port de travail (composer, synthesizer) garde son import de lot.
    """
    from wama.common.app_registry import APP_CATALOG
    from wama.common.utils.batch_parsers import SUPPORTED_BATCH_EXTENSIONS
    if not (APP_CATALOG.get(app) or {}).get('has_batch'):
        return None
    return {'accept': ','.join('.' + e for e in SUPPORTED_BATCH_EXTENSIONS),
            'formats': ' · '.join(e.upper() for e in SUPPORTED_BATCH_EXTENSIONS)}
