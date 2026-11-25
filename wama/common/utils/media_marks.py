"""LES PISTES AUTOMATIQUES D'UN MÉDIA — ce qui se segmente tout seul, rangé une fois par fichier.

`WAMA_APP_GENERATION_ROUTE.md §10.7.14 ⑲` (marche ③fonc, 2026-11-25) : un PRODUCTEUR analyse un
média et en remplit une piste de marques — les plans d'une vidéo aujourd'hui ; les parties d'un
morceau (intro, couplet, refrain), les silences d'un audio, demain, par la même porte. Le producteur
reste propre à son monde et à son app (`§10.7.3 ⑨`) : elle DÉCLARE sa fonction au catalogue et
l'inscrit ici (`register_producer`). Ce module ne connaît aucun producteur ; il porte ce qui est
commun à tous :

  • le RANGEMENT — un fichier dérivé du média, une fois par version du fichier, fabriqué par une
    tâche commune, balayé avec son original : le cycle des pics fins de l'onde (`derived_json`) ;
  • la LECTURE — les pistes d'un fichier dites sur place (`media_tracks`) et lues par le lecteur
    commun des marques (`catalog/marks.read_tracks`), sous ses noms : le pendant, pour un média,
    des pistes d'un fichier de données (`wama_data.frames.referential_tracks`) ;
  • les RÉGLAGES — ceux que la fonction déclarée porte (`FunctionSpec.call_params` : types,
    bornes, refus nommés), gardés avec ce qu'ils ont produit.

La piste appartient au FICHIER, pas à une card : deux cards qui emploient la même vidéo lisent les
mêmes plans, et chacune les coupera à sa façon (la coupe est une piste dérivée portée par l'entrée
de la card, `§10.7.14 ⑱`). Rien ici ne modifie le média.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Dict, List, Optional, Tuple

from ..catalog.marks import InvalidTracks, Track, extent, read_tracks, validate
from .derived_json import DerivedJson

#: La forme rangée (`v`), pour qu'un changement de forme ne se lise jamais comme une piste.
STORED_VERSION = 1


@dataclass(frozen=True)
class Producer:
    """Un producteur DÉCLARÉ par l'app dont c'est le métier.

      • `track` — ce que la piste dit d'elle-même (clé, libellé, famille, attributs, couleur,
        gestes, édition), SANS source : ses lignes sont celles du fichier dérivé ;
      • `natures` — les natures média qu'il sait analyser (`app_registry.category_of_path`) ;
      • `detect` — `'module:fonction'`, lue à la première analyse : `f(chemin absolu, **réglages)`
        rend les lignes (`start`, `end` ou `time`, et les attributs que la piste déclare) ;
      • `function` — la clé de sa fonction au catalogue commun : ses réglages s'y déclarent.
    """
    track: Track
    natures: Tuple[str, ...]
    detect: str
    function: str = ''

    @property
    def key(self) -> str:
        return self.track.key

    @property
    def derived(self) -> DerivedJson:
        from .video_compat import keyed_suffix
        return DerivedJson(f'media_marks_{self.key}', keyed_suffix(self.key),
                           'wama.common.tasks:make_media_marks_task', task_args=(self.key,),
                           required='marks')


_PRODUCERS: Dict[str, Producer] = {}


def _rows_of(producer: Producer):
    """La source de la piste d'un producteur : ce qui est rangé et à jour pour le média qu'on lui
    passe (son chemin relatif) — rien tant que l'analyse n'a pas tourné."""
    def rows(rel) -> List[dict]:
        return list((producer.derived.fresh(str(rel)) or {}).get('marks') or [])
    return rows


def register_producer(producer: Producer) -> Producer:
    """Inscrit un producteur (dans le `ready()` de son app, par son module déclarant). Une seconde
    inscription de la même clé la remplace ; une déclaration incohérente est REFUSÉE ici."""
    from wama.common.app_registry import MEDIA_CATEGORIES
    problems = []
    if producer.track.source or producer.track.within or producer.track.runs_of:
        problems.append("la piste d'un producteur ne dit pas de source : ses lignes sont celles "
                        "du fichier dérivé")
    else:
        problems += validate([replace(producer.track, source=_rows_of(producer))])
    unknown = [n for n in producer.natures if n not in MEDIA_CATEGORIES]
    if unknown or not producer.natures:
        problems.append(f"nature(s) {', '.join(unknown) or 'absente(s)'} hors des natures média")
    if ':' not in producer.detect:
        problems.append("`detect` se nomme par 'module:fonction'")
    if not producer.key.isidentifier():
        problems.append("sa clé nomme son fichier dérivé : un identifiant est attendu")
    if problems:
        raise InvalidTracks(f"producteur « {producer.key} » : " + ' ; '.join(problems))
    _PRODUCERS[producer.key] = producer
    return producer


def producers() -> Dict[str, Producer]:
    """Tous les producteurs inscrits, par clé. Un producteur s'inscrit depuis le module DÉCLARANT
    de son app, avec sa fonction : le catalogue des fonctions les charge (`load_all`, idempotent) —
    ce module ne nomme aucune app."""
    from wama.common.catalog.function_catalog import load_all
    load_all()
    return dict(_PRODUCERS)


def producers_for(rel: str) -> List[Producer]:
    """Les producteurs qui savent analyser ce média, d'après sa nature — dans l'ordre inscrit."""
    from wama.common.app_registry import category_of_path
    nature = category_of_path(str(rel or ''))
    return [p for p in producers().values() if nature in p.natures]


def media_tracks(rel: str) -> Tuple[Track, ...]:
    """Les pistes automatiques d'un média (chemin relatif à MEDIA_ROOT), dites sur place — à
    passer avec lui au lecteur commun (`marks.read_tracks(rel, media_tracks(rel))`, `outline`,
    `read_span`). Une piste dont l'analyse n'a pas tourné est là, vide : `marks_state` dit où en
    est son analyse."""
    return tuple(replace(p.track, source=_rows_of(p)) for p in producers_for(rel))


def read_media_tracks(rel: str) -> Dict[str, List[dict]]:
    """Les marques des pistes automatiques d'un média, par le lecteur COMMUN et sous ses noms."""
    return read_tracks(rel, media_tracks(rel))


def marks_state(rel: str, *, schedule: bool = True, retry_failed: bool = False) -> Dict[str, dict]:
    """Où en est l'analyse de chaque piste automatique de ce média : `{clé: {'status': 'ready',
    'count', 'start', 'end', 'params'} | {'status': 'pending' | 'failed' | 'none'}}`. `schedule`
    met en file celles qui n'y sont pas (une page ou l'assistant qui DEMANDE la piste) ;
    `retry_failed` relance un échec. Ne lève jamais."""
    out = {}
    for producer in producers_for(rel):
        state = producer.derived.state(rel, schedule=schedule, retry_failed=retry_failed)
        if state['status'] == 'ready':
            data = state['data']
            state = {'status': 'ready', **extent(data.get('marks') or []),
                     'params': data.get('params') or {}}
        out[producer.key] = state
    return out


def _checked_params(producer: Producer, params: Optional[dict]) -> dict:
    """Les réglages d'une analyse, par LA porte de la fonction déclarée (types, bornes, refus
    nommés) ; sans fonction au catalogue, tels quels."""
    from wama.common.catalog import function_catalog as fc
    spec = fc.get(producer.function) if producer.function else None
    return spec.call_params(params or {}) if spec is not None else dict(params or {})


def make_media_marks(rel: str, key: str, params: Optional[dict] = None) -> bool:
    """Analyse un média et range sa piste `key` — idempotent : ce qui est rangé et à jour reste,
    sauf si `params` demande d'autres réglages que ceux qui l'ont produit (l'analyse est alors
    refaite, et REMPLACE : une piste, un jeu de réglages). Rend True si la piste est prête. Un
    échec se marque (`marks_state` le dit) ; un producteur inconnu ou un réglage refusé lève
    `ValueError`."""
    import logging

    from wama.common.catalog.function_catalog import resolve_impl

    from .derived_json import absolute, version_of
    producer = producers().get(key)
    if producer is None:
        raise ValueError(f"producteur de marques inconnu : « {key} » "
                         f"({', '.join(sorted(_PRODUCERS)) or 'aucun inscrit'})")
    rel = str(rel or '').replace('\\', '/')
    if producer not in producers_for(rel):
        raise ValueError(f"« {key} » n'analyse pas ce média ({', '.join(producer.natures)})")
    wanted = _checked_params(producer, params)
    derived = producer.derived
    stored = derived.fresh(rel)
    if stored and stored.get('v') == STORED_VERSION and (
            params is None or wanted == (stored.get('params') or {})):
        return True
    if version_of(rel) is None:
        return False
    try:
        rows = list(resolve_impl(producer.detect)(absolute(rel), **wanted) or [])
    except Exception as error:
        logging.getLogger(__name__).warning('[marques] %s de %s en échec : %s', key, rel, error)
        rows = []
    return derived.store(rel, {'v': STORED_VERSION, 'producer': key, 'params': wanted,
                               'marks': rows} if rows else None)


def summary(rel: str, key: str) -> str:
    """Une phrase sur la piste rangée d'un média (« Plans — 12 sur 0:34 ») — ce qu'un lancement
    rend à qui l'a demandé (un nœud du Studio, une console). La durée couverte se dit par le
    formateur commun, sur l'axe du temps seulement."""
    producer = producers().get(key)
    found = extent(read_media_tracks(rel).get(key) or []) if producer else {'count': 0}
    if not producer or not found['count']:
        return f"{producer.track.label if producer else key} — aucune marque"
    covered = ''
    if producer.track.axis == 'time' and found.get('end') is not None:
        from .durations import format_duration
        covered = format_duration(found['end'] - found['start'])
    return f"{producer.track.label} — {found['count']}" + (f" sur {covered}" if covered else '')
