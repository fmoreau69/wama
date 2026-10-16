"""
Tag d'inclusion `{% refresh_button "cle" %}` — l'héritage du mécanisme, côté gabarit.

Une page catalogue nomme la CLÉ de son registre et reçoit le bon rendu : un bouton si le registre
s'actualise, une mention « toujours à jour » s'il est DÉRIVÉ. C'est ce qui empêche la huitième page
de recopier le bouton de la septième — et surtout ce qui empêche de coller un bouton menteur sur
une page qui recalcule déjà à chaque affichage.
"""
from django import template

from ..registries import (CELERY, DERIVED, EXECUTIONS, NATURES, REGISTRIES, execution_of,
                          is_authorized, synchronize)

register = template.Library()


@register.simple_tag(takes_context=True)
def page_heading(context, title='', icon=''):
    """`{label, icon}` de la page servie : ceux de son ENTRÉE DE MENU (`account_page_of`, lue par
    la route de la requête) — l'en-tête commun et le titre de l'onglet les lisent, aucun gabarit ne
    les recopie (2026-10-16). Un titre ou une icône PASSÉ explicitement l'emporte : une page hors
    menu (la lecture d'un doc, titrée par le doc lu) dit le sien. '' quand rien ne le déclare —
    `tests_catalog_heading` exige qu'aucune page catalogue n'en soit là."""
    from ..app_registry import account_page_of
    match = getattr(context.get('request'), 'resolver_match', None)
    page = account_page_of(getattr(match, 'view_name', '') or '') or {}
    return {'label': title or page.get('label', ''), 'icon': icon or page.get('icon', '')}


@register.inclusion_tag('common/_catalog_refresh.html', takes_context=True)
def refresh_button(context, key, reload_page=True):
    """Rend le contrôle d'actualisation du registre `key`.

    `reload_page` : la page se recharge après succès. Vrai par défaut — la plupart des catalogues
    rendent leur contenu côté serveur, donc un compte-rendu sans rechargement laisserait des
    chiffres périmés à l'écran, ce qui est pire que pas de bouton.
    """
    registry = REGISTRIES.get(key)
    if registry is None:
        # On le DIT au lieu de rendre du vide : une clé fautive doit se voir à l'écran, sinon le
        # bouton manquant passe pour une décision.
        return {'error': f"registre « {key} » inconnu", 'registry': None}
    # ⚠ Point de RESYNCHRONISATION entre processus. Gunicorn tourne à 4 workers : un registre en
    # mémoire actualisé dans l'un laisse les trois autres périmés, et l'utilisateur verrait son
    # total changer d'un rechargement à l'autre. Une lecture Redis ici suffit à l'éviter, et le
    # rechargement n'a lieu que si quelqu'un a réellement actualisé.
    synchronize(key)

    user = getattr(context.get('request'), 'user', None)
    execution = execution_of(registry)
    return {
        'error': '',
        'registry': registry,
        'key': key,
        'derived': registry.nature == DERIVED,
        'nature_label': NATURES.get(registry.nature, ''),
        'execution_label': EXECUTIONS.get(execution, ''),
        'in_background': execution == CELERY,
        'allowed': is_authorized(registry, user),
        'reload_page': '1' if reload_page else '0',
    }
