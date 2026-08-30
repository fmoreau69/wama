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
