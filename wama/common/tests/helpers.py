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


def run_data_migration(function, field: str, rows: dict) -> dict:
    """Joue une fonction de migration de DONNÉES (`RunPython`) sur une table EN MÉMOIRE :
    `rows` = {pk: valeur du champ `field`}, modifié en place et rendu. Couvre ce qu'utilisent les
    migrations de préfixage en clés de catalogue (`exclude(<champ>__in / __contains)`,
    `filter(pk= / <champ>__startswith=)`, `values_list`, `update`) — sans base, donc sans dépendre
    de l'état du catalogue. Était écrite pour le seul `ai_model` de l'enhancer (2026-10-06) ;
    l'avatarizer (`animation_model`, 2026-10-07) en avait besoin sous un autre nom de champ."""
    from unittest import mock

    class _Rows:
        def __init__(self, pks):
            self.pks = list(pks)

        def _keep(self, test):
            return _Rows(pk for pk in self.pks if test(rows[pk]))

        def exclude(self, **lookup):
            (key, arg), = lookup.items()
            if key == f'{field}__in':
                return self._keep(lambda v: v not in arg)
            if key == f'{field}__contains':
                return self._keep(lambda v: arg not in v)
            raise AssertionError(f'lookup non couvert par la doublure : {key}')

        def filter(self, **lookup):
            (key, arg), = lookup.items()
            if key == 'pk':
                return _Rows([arg])
            if key == f'{field}__startswith':
                return self._keep(lambda v: v.startswith(arg))
            raise AssertionError(f'lookup non couvert par la doublure : {key}')

        def values_list(self, *fields):
            return [(pk, rows[pk]) for pk in self.pks]

        def update(self, **values):
            for pk in self.pks:
                rows[pk] = values[field]

    model = type('Model', (), {'objects': _Rows(rows)})
    function(mock.Mock(get_model=lambda app, name: model), None)
    return rows
