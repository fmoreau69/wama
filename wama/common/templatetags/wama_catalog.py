"""
Tag d'inclusion `{% bouton_actualiser "cle" %}` — l'héritage du mécanisme, côté gabarit.

Une page catalogue nomme la CLÉ de son registre et reçoit le bon rendu : un bouton si le registre
s'actualise, une mention « toujours à jour » s'il est DÉRIVÉ. C'est ce qui empêche la huitième page
de recopier le bouton de la septième — et surtout ce qui empêche de coller un bouton menteur sur
une page qui recalcule déjà à chaque affichage.
"""
from django import template

from ..registries import DERIVE, NATURES, REGISTRES, autorise

register = template.Library()


@register.inclusion_tag('common/_catalog_refresh.html', takes_context=True)
def bouton_actualiser(context, cle, recharger=True):
    """Rend le contrôle d'actualisation du registre `cle`.

    `recharger` : la page se recharge après succès. Vrai par défaut — la plupart des catalogues
    rendent leur contenu côté serveur, donc un compte-rendu sans rechargement laisserait des
    chiffres périmés à l'écran, ce qui est pire que pas de bouton.
    """
    registre = REGISTRES.get(cle)
    if registre is None:
        # On le DIT au lieu de rendre du vide : une clé fautive doit se voir à l'écran, sinon le
        # bouton manquant passe pour une décision.
        return {'erreur': f"registre « {cle} » inconnu", 'registre': None}
    user = getattr(context.get('request'), 'user', None)
    return {
        'erreur': '',
        'registre': registre,
        'cle': cle,
        'derive': registre.nature == DERIVE,
        'nature_label': NATURES.get(registre.nature, ''),
        'peut': autorise(registre, user),
        'recharger': '1' if recharger else '0',
    }
