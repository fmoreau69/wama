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
