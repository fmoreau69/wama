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

Un producteur est une RÈGLE (ffmpeg, processeur : lancée dès qu'on regarde le fichier) ou un MODÈLE
(`§10.7.14 ㉑`) : une passe remplit alors plusieurs pistes (`analysis`), tourne sur la file de son
app (`task`), seulement quand on la demande (`on_demand`) — et ce qu'un process de card a déjà
calculé sur ce fichier s'y DÉPOSE (`deposit`) au lieu d'être jeté.
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

    Et ce qu'un producteur À MODÈLE déclare en plus (`§10.7.14 ㉑`, 2026-11-25 — la structure d'un
    morceau) :
      • `analysis` — le nom d'une ANALYSE qui remplit plusieurs pistes d'UNE passe (un modèle
        décode d'un coup les parties, les mesures, la tonalité) : les producteurs qui la nomment
        partagent `detect`, qui rend alors `{clé de piste: lignes}`, et une seule mise en file ;
        une piste qu'elle laisse vide est prête et vide (un morceau sans accord décodé) ;
      • `task` — `'module:tâche'` Celery quand l'analyse ne tourne pas sur la file commune (CPU) :
        celle de son app, qui amène son modèle par la route et le décharge ; appelée comme la
        tâche commune, `(chemin du média, clé)` ;
      • `on_demand` — l'analyse ne part que si SA piste est demandée (`marks_state(asked=…)`, le
        process d'une card), jamais parce qu'on liste les pistes du fichier : une règle ne coûte
        rien, un modèle occupe la carte graphique.
    """
    track: Track
    natures: Tuple[str, ...]
    detect: str
    function: str = ''
    analysis: str = ''
    task: str = ''
    on_demand: bool = False

    @property
    def key(self) -> str:
        return self.track.key

    @property
    def derived(self) -> DerivedJson:
        from .video_compat import keyed_suffix
        # Un fichier par PISTE (la lecture ne change pas), une marque « en file » par ANALYSE :
        # demander ses quatre pistes ne lance qu'une passe.
        return DerivedJson(f'media_marks_{self.analysis or self.key}', keyed_suffix(self.key),
                           self.task or 'wama.common.tasks:make_media_marks_task',
                           task_args=(self.key,), required='v' if self.analysis else 'marks')


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
    if producer.task and ':' not in producer.task:
        problems.append("`task` se nomme par 'module:tâche'")
    if producer.analysis and not producer.analysis.isidentifier():
        problems.append("son analyse nomme sa marque de file : un identifiant est attendu")
    shared = [p for p in _PRODUCERS.values()
              if producer.analysis and p.analysis == producer.analysis and p.key != producer.key]
    if any((p.detect, p.task, p.natures, p.function, p.on_demand) !=
           (producer.detect, producer.task, producer.natures, producer.function,
            producer.on_demand) for p in shared):
        problems.append(f"l'analyse « {producer.analysis} » est UNE passe : mêmes `detect`, "
                        "`task`, natures, fonction et `on_demand` pour toutes ses pistes")
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


def media_rel(path) -> str:
    """Le chemin RELATIF à MEDIA_ROOT d'un média donné absolu ou relatif — par LA garde de
    confinement (`media_paths.resolve_under_media_root`) : '' pour un chemin qui en sort. Toute
    porte qui reçoit un chemin (la fonction d'un nœud du Studio, la tâche d'une app, le dépôt d'un
    process) passe par ici : rien n'est analysé ni rangé hors des médias."""
    from .media_paths import OutsideMediaRoot, resolve_under_media_root
    asked = str(path or '').replace('\\', '/').strip()
    try:
        rel = resolve_under_media_root(asked, must_exist=False)[1] if asked else ''
    except (OutsideMediaRoot, OSError, ValueError):
        return ''
    return '' if rel in ('', '.') else rel          # la racine des médias n'est pas un média


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


def marks_state(rel: str, *, schedule: bool = True, retry_failed: bool = False,
                asked: Tuple[str, ...] = ()) -> Dict[str, dict]:
    """Où en est l'analyse de chaque piste automatique de ce média : `{clé: {'status': 'ready',
    'count', 'start', 'end', 'params'} | {'status': 'pending' | 'failed' | 'none'}}`. `schedule`
    met en file celles qui n'y sont pas (une page ou l'assistant qui DEMANDE la piste) ;
    `retry_failed` relance un échec. Une piste `on_demand` (un modèle) ne part — et ne se relance
    — que si elle est NOMMÉE dans `asked` : sinon elle dit `'none'` et `'on_demand': True`. Ne
    lève jamais."""
    out = {}
    for producer in producers_for(rel):
        wanted = not producer.on_demand or producer.key in asked
        state = producer.derived.state(rel, schedule=schedule and wanted,
                                       retry_failed=retry_failed and wanted)
        if state['status'] == 'ready':
            data = state['data']
            state = {'status': 'ready', **extent(data.get('marks') or []),
                     'params': data.get('params') or {}}
        elif producer.on_demand and state['status'] == 'none':
            state = {**state, 'on_demand': True}
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
    rel = media_rel(rel)
    if not rel or producer not in producers_for(rel):
        raise ValueError(f"« {key} » n'analyse pas ce média ({', '.join(producer.natures)}, "
                         "dans les médias de WAMA)")
    wanted = _checked_params(producer, params)
    derived = producer.derived
    stored = derived.fresh(rel)
    if stored and stored.get('v') == STORED_VERSION and (
            params is None or wanted == (stored.get('params') or {})):
        return True
    if version_of(rel) is None:
        return False
    try:
        found = resolve_impl(producer.detect)(absolute(rel), **wanted)
    except Exception as error:
        logging.getLogger(__name__).warning('[marques] %s de %s en échec : %s', key, rel, error)
        found = None
    return _store(producer, rel, wanted, found)


def _store(producer: Producer, rel: str, params: dict, found) -> bool:
    """Range ce qu'une analyse a trouvé. Un producteur seul : ses lignes. Une ANALYSE partagée :
    `{clé: lignes}`, chaque piste de l'analyse dans son fichier — une piste laissée vide est prête
    et vide. Rien du tout : l'échec se marque pour cette version du média. Rend True si la piste
    de `producer` est rangée."""
    if not producer.analysis:
        rows = list(found or [])
        return producer.derived.store(rel, {'v': STORED_VERSION, 'producer': producer.key,
                                            'params': params, 'marks': rows} if rows else None)
    found = {key: list(rows or []) for key, rows in dict(found or {}).items()}
    if not any(found.values()):
        return producer.derived.store(rel, None)
    done = False
    for mate in producers_for(rel):
        if mate.analysis == producer.analysis:
            stored = mate.derived.store(rel, {
                'v': STORED_VERSION, 'producer': mate.key, 'analysis': mate.analysis,
                'params': params, 'marks': found.get(mate.key) or []})
            done = done or (stored and mate.key == producer.key)
    return done


def mark_failed(rel: str, key: str) -> None:
    """Dit l'ÉCHEC de l'analyse de la piste `key` pour cette version du média quand elle n'a pas
    pu commencer (la tâche d'une app dont le modèle ne s'installe pas) : sans cela la piste
    resterait « en file » jusqu'à l'oubli de sa marque. Ne lève jamais."""
    try:
        producer = producers().get(key)     # le registre CHARGÉ : un worker neuf n'a rien lu
        rel = media_rel(rel)
        if producer is not None and rel:
            producer.derived.store(rel, None)
    except Exception:
        pass


def deposit(rel: str, analysis: str, found: Optional[dict]) -> bool:
    """Range les pistes de l'ANALYSE `analysis` de ce média quand elle a tourné AILLEURS — le
    process d'une card qui fait passer le même modèle sur le même fichier (la partition réduite
    d'un cover décode aussi la structure du morceau) : ce qui est calculé une fois n'est ni jeté ni
    recalculé. `found` : `{clé de piste: lignes}`. Rend True si quelque chose est rangé ; ne lève
    jamais (un dépôt ne fait pas échouer le process qui l'offre)."""
    import logging

    from .derived_json import version_of
    try:
        rel = media_rel(rel)
        mates = [p for p in producers_for(rel) if rel and analysis and p.analysis == analysis]
        if (not mates or version_of(rel) is None
                or not any((found or {}).get(p.key) for p in mates)):
            return False
        return _store(mates[0], rel, {}, found)
    except Exception as error:
        logging.getLogger(__name__).warning('[marques] dépôt de %s pour %s en échec : %s',
                                            analysis, rel, error)
        return False


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
