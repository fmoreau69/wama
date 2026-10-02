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
import time

from django import template
from django.contrib.staticfiles import finders
from django.templatetags.static import static

register = template.Library()

#: Chemin RÉSOLU de chaque statique — il ne change pas pendant la vie du processus. C'était le
#: coût dominant : `finders.find` parcourt les dossiers statiques de toutes les apps sur /mnt/d.
_PATH_CACHE = {}
#: {path: (mtime, instant de la lecture)}.
_MTIME_CACHE = {}
#: En DEBUG (le cas du serveur en service), le mtime se relit au-delà de ce délai : une modif de
#: JS/CSS reste visible au rechargement suivant, à quelques secondes près. Mesuré le 2026-10-02 :
#: SANS aucun cache en DEBUG, 51 statiques coûtaient 0,39 s sur les 0,53 s de l'accueil, 66 en
#: coûtaient 0,51 s au transcriber (find 3,1 ms + deux stat à 2 ms chacun, sur /mnt/d).
DEBUG_RECHECK_SECONDS = 5.0


def _mtime(path, debug):
    now = time.monotonic()
    hit = _MTIME_CACHE.get(path)
    if hit is not None and (not debug or now - hit[1] < DEBUG_RECHECK_SECONDS):
        return hit[0]
    if path not in _PATH_CACHE:
        _PATH_CACHE[path] = finders.find(path)
    abs_path = _PATH_CACHE[path]
    if not abs_path:
        return None
    try:
        mtime = int(os.stat(abs_path).st_mtime)        # UN stat (exists + getmtime en faisaient deux)
    except OSError:
        _PATH_CACHE.pop(path, None)                    # fichier déplacé : on le recherchera
        return None
    _MTIME_CACHE[path] = (mtime, now)
    return mtime


@register.simple_tag
def static_v(path):
    """URL statique + `?v=<mtime>` pour casser le cache navigateur au changement."""
    url = static(path)
    try:
        from django.conf import settings
        mtime = _mtime(path, bool(getattr(settings, 'DEBUG', False)))
        if mtime:
            sep = '&' if '?' in url else '?'
            url = f"{url}{sep}v={mtime}"
    except Exception:
        pass
    return url
