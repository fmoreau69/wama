"""Gabarits du gestionnaire de fichiers — expose au client ce que le SERVEUR sait recevoir.

Le sous-menu « Envoyer vers… » se construit chez le client à partir de `WAMA_APP_CATALOG`
(déclaration d'app : libellé, icône, extensions acceptées). Ce catalogue dit ce qu'une app
ACCEPTE, jamais si le gestionnaire de fichiers sait la REMPLIR — deux choses distinctes, et
l'écart entre elles produisait un menu menteur (mesuré le 2026-08-28 : trois apps offertes puis
refusées par `api_import_to_app`). Le registre `IMPORTERS` tranche la seconde question ; ce tag
le publie pour que le menu soit bâti sur les DEUX.
"""
import json

from django import template
from django.utils.safestring import mark_safe

register = template.Library()


@register.simple_tag(takes_context=True)
def filemanager_importers_json(context):
    """La liste JSON des apps que le gestionnaire de fichiers sait remplir.

    Le contexte fournit l'utilisateur : les JUMELLES de bac à sable (importeur DÉRIVÉ de leur
    source, cf. `importer_for`) ne sont proposées qu'à qui peut ouvrir leur page (dev-only).
    """
    try:
        from wama.filemanager.views import receivable_apps
        request = context.get('request')
        apps = receivable_apps(getattr(request, 'user', None))
    except Exception:
        # Repli SÛR = liste VIDE, donc aucun envoi proposé. Le contraire (« tout proposer »)
        # rétablirait exactement le défaut qu'on ferme : mieux vaut un menu absent qu'un
        # menu qui promet ce que le serveur refusera.
        apps = []
    return mark_safe(json.dumps(apps))
