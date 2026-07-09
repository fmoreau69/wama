"""
Cache-busting statique centralisé pour WAMA.

`{% static_v 'app/js/foo.js' %}` = comme `{% static %}`, mais ajoute `?v=<mtime>`
(date de modification du fichier) à l'URL. Le navigateur re-télécharge le fichier
DÈS qu'il change, sans le mettre en cache périmé — et le garde en cache tant qu'il
ne change pas.

À utiliser dans TOUTES les apps pour leurs JS/CSS statiques (remplace `{% static %}`).
Sans ça, une modif de JS/CSS n'arrive pas au navigateur (il sert la version cachée),
ce qui donne l'impression que « le changement ne fait rien ».
"""
import os

from django import template
from django.contrib.staticfiles import finders
from django.templatetags.static import static

register = template.Library()

# Petit cache mtime en mémoire (process) pour éviter un os.stat par rendu. En DEBUG
# on ignore le cache pour refléter les modifs immédiatement.
_MTIME_CACHE = {}


@register.simple_tag
def static_v(path):
    """URL statique + `?v=<mtime>` pour casser le cache navigateur au changement."""
    url = static(path)
    try:
        from django.conf import settings
        debug = bool(getattr(settings, 'DEBUG', False))
        mtime = None if debug else _MTIME_CACHE.get(path)
        if mtime is None:
            abs_path = finders.find(path)
            if abs_path and os.path.exists(abs_path):
                mtime = int(os.path.getmtime(abs_path))
                if not debug:
                    _MTIME_CACHE[path] = mtime
        if mtime:
            sep = '&' if '?' in url else '?'
            url = f"{url}{sep}v={mtime}"
    except Exception:
        pass
    return url
