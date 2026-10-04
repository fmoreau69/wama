"""Doublures PARTAGÉES par les tests de plusieurs apps (ce module n'est pas un module de tests :
la découverte ne lit que `tests*.py`)."""
import os

#: La conversion en ligne que joue le process « Sortie » (`output_formats.apply_output_settings`)
#: — l'adresse à remplacer par `stand_in_conversion` dans un test qui ne convertit rien.
INLINE_CONVERSION = 'wama.converter.utils.inline_convert.apply_inline_conversion'


def stand_in_conversion(path, fmt, preset='balanced', **_kw):
    """Doublure du convertisseur : écrit la cible à côté de la source (son contenu, marqué du
    format — un test peut lire d'où vient un rendu), retire la source, rend la cible. Était
    recopiée dans six fichiers de tests (2026-10-04)."""
    target = os.path.splitext(path)[0] + '.' + fmt
    with open(path, 'rb') as src:
        content = src.read()
    with open(target, 'wb') as out:
        out.write(content + b'>' + fmt.encode())
    if target != path:
        os.remove(path)
    return target
