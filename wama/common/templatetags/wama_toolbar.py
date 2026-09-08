"""Templatetags de la barre d'outils commune — expose le REGISTRE au gabarit.

Le gabarit ne connaît ni les clés ni l'ordre : il demande les outils d'un profil et les rend.
C'est ce qui permet d'ajouter un outil à toutes les files depuis `common/toolbar.py` seul.
"""
from django import template

from wama.common.toolbar import enveloppe_du_profil, outils_du_profil

register = template.Library()


@register.simple_tag
def toolbar_outils(profil, pole):
    """Les outils du profil pour CE pôle, dans l'ordre déclaré.

    Deux appels (un par pôle) plutôt qu'un filtrage dans le gabarit : les deux pôles ont des
    enrobages différents, donc deux boucles de toute façon — et un `{% if o.pole == … %}` dans
    la boucle laisserait des enrobages vides pour les outils de l'autre pôle.
    """
    return [o for o in outils_du_profil(profil) if o.pole == pole]


@register.simple_tag
def toolbar_enveloppe(profil):
    return enveloppe_du_profil(profil)
