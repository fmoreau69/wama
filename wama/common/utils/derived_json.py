"""UN FAIT DÉRIVÉ d'un média, rangé en JSON — le cycle écrit UNE fois.

Les pics fins de l'onde (`waveform`, 2026-10-21) ont posé le cycle : un fichier DÉRIVÉ au dossier
caché de l'utilisateur (`video_compat.derived_rel`), à jour tant qu'il est plus récent que
l'original, fabriqué par une tâche commune UNE fois par version du fichier (chemin, taille, date),
balayé quand l'original part ; « en file » et « échec » se lisent d'une marque de cache par
version, jamais d'un champ de card. Les pistes automatiques d'un média (`media_marks`, les plans
d'une vidéo, `ROUTE §10.7.14 ⑲`) sont de la même nature : ce module porte le cycle, chacun y
déclare son suffixe, sa tâche et ce qu'il range.

Rien ici ne calcule : qui déclare un fait dérivé garde SON calcul et appelle `store`.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Optional


def absolute(rel: str) -> str:
    from django.conf import settings
    return os.path.join(settings.MEDIA_ROOT, rel)


def version_of(rel: str) -> Optional[str]:
    """`chemin:taille:date` du média (une version), ou None s'il n'existe pas."""
    try:
        stat = os.stat(absolute(rel))
    except OSError:
        return None
    return f'{rel}:{stat.st_size}:{int(stat.st_mtime)}'


@dataclass(frozen=True)
class DerivedJson:
    """Un fait dérivé DÉCLARÉ : `name` (le préfixe de ses marques de cache), `suffix` (celui de son
    fichier — l'un de ceux que le balayage reconnaît, `video_compat.DERIVED_SUFFIXES` ou sa
    famille à clé `keyed_suffix`), `task` (`module:attribut` de
    la tâche Celery qui le fabrique, appelée avec le chemin du média puis `task_args`), `required`
    (la clé sans laquelle le fichier rangé ne vaut rien).

    Une version mise en file ne l'est plus pendant `queued_ttl` ; un échec se dit pendant
    `failed_ttl`, puis la page suivante retente (un échec se retente à l'ouverture d'une page, pas
    pendant qu'elle interroge)."""
    name: str
    suffix: str
    task: str
    task_args: tuple = ()
    required: str = ''
    queued_ttl: int = 30 * 86400
    failed_ttl: int = 3600

    def rel(self, rel: str) -> str:
        """Le chemin (relatif à MEDIA_ROOT) du fichier dérivé d'un média — pure."""
        from .video_compat import derived_rel
        return derived_rel(rel, self.suffix)

    def fresh(self, rel: str) -> Optional[dict]:
        """Ce qui est rangé et À JOUR pour ce média, ou None (absent, illisible, ou plus ancien
        que l'original : il a été remplacé depuis)."""
        path = absolute(self.rel(rel))
        try:
            if os.path.getmtime(path) < os.path.getmtime(absolute(rel)):
                return None
            with open(path, encoding='utf-8') as source:
                return json.load(source)
        except (OSError, ValueError):
            return None

    def state(self, rel: str, *, schedule: bool = True, retry_failed: bool = False) -> dict:
        """L'état du fait dérivé d'un média : `{'status': 'ready', 'data': …}`, ou `{'status':
        'pending' | 'failed' | 'none'}`. `schedule` met le calcul en file s'il n'y est pas ;
        `retry_failed` le relance après un échec (une page qui s'OUVRE). Ne lève jamais."""
        rel = str(rel or '').replace('\\', '/')
        data = self.fresh(rel) if rel else None
        if data and (not self.required or data.get(self.required)):
            return {'status': 'ready', 'data': data}
        version = version_of(rel) if rel else None
        if version is None:
            return {'status': 'none'}
        try:
            from django.core.cache import cache
            if cache.get(f'{self.name}_failed:{version}'):
                if not retry_failed:
                    return {'status': 'failed'}
                cache.delete_many([f'{self.name}_failed:{version}', f'{self.name}:{version}'])
            if schedule and self.schedule(rel):
                return {'status': 'pending'}
            return {'status': 'pending' if cache.get(f'{self.name}:{version}') else 'none'}
        except Exception:
            return {'status': 'none'}

    def schedule(self, rel: str) -> bool:
        """Met le calcul en file, UNE fois par version du fichier. Rend True si une tâche part. Ne
        lève jamais : une page ne casse pas pour un fait dérivé."""
        version = version_of(rel)
        if version is None:
            return False
        try:
            from django.core.cache import cache
            from django.db import transaction

            from wama.common.catalog.function_catalog import resolve_impl
            task = resolve_impl(self.task)
            if not cache.add(f'{self.name}:{version}', 1, self.queued_ttl):
                return False
            transaction.on_commit(lambda: task.delay(rel, *self.task_args))
            return True
        except Exception:
            return False

    def hold(self, rel: str) -> None:
        """Marque la version d'un média « en file » SANS rien lancer : un témoin de scénario
        s'ouvre « en cours », comme une page dont la tâche n'a pas encore tourné."""
        version = version_of(rel)
        if version is not None:
            from django.core.cache import cache
            cache.add(f'{self.name}:{version}', 1, self.queued_ttl)

    def store(self, rel: str, data: Optional[dict]) -> bool:
        """Range ce qui a été calculé pour ce média — par un fichier voisin qui ne remplace le
        précédent qu'une fois complet. Sans rien à ranger (`data` vide), l'échec se MARQUE pour
        cette version (`state` le dira). Rend True si le fichier est écrit."""
        if not data:
            version = version_of(rel)
            if version is not None:
                from django.core.cache import cache
                cache.set(f'{self.name}_failed:{version}', 1, self.failed_ttl)
            return False
        target = absolute(self.rel(rel))
        os.makedirs(os.path.dirname(target), exist_ok=True)
        partial = target + '.part'
        with open(partial, 'w', encoding='utf-8') as out:
            json.dump(data, out)
        os.replace(partial, target)
        return True
