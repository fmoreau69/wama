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
    ]
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
def input_slots(app, live=False):
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
      - `live`    : passé par l'appelant, pas dérivé. Le drapeau DÉCLARATIF qui remplacera le
                    littéral `show_live` s'ajoutera avec sa déclaration — « jamais une
                    déclaration sans consommateur » vaut aussi dans l'autre sens : pas de
                    lecteur qui invente sa clé.

    Le port `prompt` est EXCLU : ce n'est pas un slot de la zone de preview, c'est la cellule
    primaire au-dessus (§11.9 C — le seul élément autorisé à grandir).
    """
    from wama.common.app_registry import studio_node_ports

    ports = (studio_node_ports(app) or {}).get('inputs') or []
    mimes = {'image': 'image/*', 'video': 'video/*', 'audio': 'audio/*'}
    slots = []
    for port in ports:
        if port.get('group') == 'prompt':
            continue
        types = port.get('types') or []
        accept = ','.join(mimes[t] for t in types if t in mimes) or '*/*'
        travail = port.get('group') == 'travail'
        mods = ['drop', 'library', 'url']
        if port.get('multi'):
            mods.append('folder')
        if travail and live:
            mods.append('live')
        slots.append({
            'id': port.get('id'),
            'label': port.get('label') or port.get('id'),
            'group': port.get('group'),
            'accept': accept,
            # `media_library_type` n'accepte qu'UNE valeur : un port multi-nature (converter)
            # ouvre la médiathèque non filtrée plutôt que sur une nature arbitraire.
            'library_type': types[0] if len(types) == 1 else 'all',
            'multi': bool(port.get('multi')),
            'required': travail,
            'modalities': mods,
        })
    return slots
