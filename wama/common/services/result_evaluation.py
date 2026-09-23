"""
Évaluation d'un résultat contre sa RÉFÉRENCE — la brique commune que chaque app adopte par une
DÉCLARATION (`register_evaluation`), jamais par du code d'évaluation à elle.

Place dans la chaîne qualité (`WAMA_QUALITE.md §5`) : la référence entre par le port
`reference_result` (⑤), la métrique la confronte au résultat (⑥, `text_metrics`), la mesure est
conservée par élément (`ResultEvaluation`) — et c'est cette table que l'agrégation en indice
interne des modèles lira (⑧, `benchmark_meta` source `internal`). Rien ici ne classe un modèle :
on MESURE, l'agrégation interprétera, avec le nombre pour elle.

CE QUE L'APP DÉCLARE (`EvaluationSpec`), et rien d'autre :
  • le champ fichier qui porte la référence sur son élément ;
  • comment lire le TEXTE de son résultat (le transcriber lit la sortie ASR, pas la correction) ;
  • comment lire une référence (le transcriber sait lire SRT, VTT, Sonal…) et quelles extensions ;
  • quel modèle a produit le résultat (clé catalogue) ;
  • quelles métriques ont un sens pour sa tâche.
La capacité d'app `has_reference_result` (`app_registry.app_result_ports`) et cette déclaration
vont ensemble : un contrôle (`tests_result_evaluation`) refuse l'une sans l'autre.

RÈGLE D'INTÉGRATION — best-effort. Une mesure manquée ne casse jamais la tâche ou le geste qui,
eux, ont réussi (même précaution que `run_outcome`). Les erreurs se journalisent.
"""
from __future__ import annotations

import hashlib
import logging
import os
from dataclasses import dataclass
from typing import Callable, Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)

#: Version du protocole de mesure texte : normalisation de `text_metrics` (casse, ponctuation,
#: apostrophe séparatrice, hésitations conservées). La changer change l'ÉCHELLE.
TEXT_PROTOCOL = 'text_v1'

#: Préfixe d'un résultat produit hors de WAMA : mesurable, jamais agrégé comme un modèle du parc.
EXTERNAL_PREFIX = 'external:'


def _text_metrics():
    from wama.common.services.text_metrics import character_error_rate, word_error_rate
    return {
        'wer': ('Taux d’erreur par mot (WER)', word_error_rate),
        'cer': ('Taux d’erreur par caractère (CER)', character_error_rate),
    }


@dataclass(frozen=True)
class EvaluationSpec:
    """Ce qu'une surface déclare pour être évaluable. Voir l'en-tête du module."""

    surface: str
    reference_field: str
    #: élément → texte de son résultat, ou None s'il n'en a pas encore.
    result_text: Callable[[object], Optional[str]]
    #: chemin → (texte de référence, détail de lecture : ce qui a été écarté, format…).
    read_reference: Callable[[str], Tuple[str, dict]]
    #: élément → clé catalogue du modèle qui a produit le résultat (`EXTERNAL_PREFIX…` sinon).
    model_key: Callable[[object], str]
    reference_extensions: Tuple[str, ...] = ()
    metrics: Tuple[str, ...] = ('wer', 'cer')
    protocol: str = TEXT_PROTOCOL


_REGISTRY: Dict[str, EvaluationSpec] = {}


def register_evaluation(spec: EvaluationSpec) -> None:
    """Appelé depuis le `apps.py:ready()` de l'app — le registre ne connaît jamais ses apps."""
    known = _text_metrics()
    unknown = [m for m in spec.metrics if m not in known]
    if unknown:
        raise ValueError(f"métriques inconnues pour {spec.surface} : {unknown}")
    _REGISTRY[spec.surface] = spec


def evaluation_spec(surface: str) -> Optional[EvaluationSpec]:
    return _REGISTRY.get(surface)


def evaluable_surfaces() -> List[str]:
    return sorted(_REGISTRY)


def evaluable_surface_of(element_model) -> Optional[str]:
    """La surface ÉVALUABLE dont `element_model` est le modèle d'élément, None sinon.

    Pour les lecteurs qui tiennent des éléments sans leur surface — la file (`build_batches_list`
    ne reçoit que le modèle de lot). On ne cherche que parmi les surfaces déclarées : l'enhancer
    en expose deux, à modèles distincts, et chacune se reconnaît à son modèle.
    """
    from wama.common.utils.preview_registry import PreviewRegistry
    for surface in _REGISTRY:
        if PreviewRegistry.get_model(surface) is element_model:
            return surface
    return None


# ── Mesure ──────────────────────────────────────────────────────────────────────────────────

def _file_sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, 'rb') as handle:
        for block in iter(lambda: handle.read(1 << 20), b''):
            digest.update(block)
    return digest.hexdigest()


def _rows_of(surface: str, item):
    from wama.common.models import ResultEvaluation
    return ResultEvaluation.objects.filter(app=surface, object_type=type(item).__name__,
                                           object_id=item.pk)


def clear(surface: str, item) -> None:
    """Retire la mesure d'un élément (référence retirée, résultat disparu)."""
    try:
        _rows_of(surface, item).delete()
    except Exception as exc:
        logger.debug('[evaluation] effacement %s#%s impossible : %s', surface, item.pk, exc)


def evaluate(surface: str, item) -> List:
    """Mesure le résultat COURANT de `item` contre sa référence ; rend les lignes écrites.

    Sans référence ou sans résultat, il n'y a rien à mesurer : la mesure précédente est retirée
    (elle décrirait un état qui n'existe plus). Best-effort : ne lève jamais.
    """
    spec = evaluation_spec(surface)
    if spec is None or item is None:
        return []
    try:
        reference = getattr(item, spec.reference_field, None)
        hypothesis = spec.result_text(item)
        if not reference or not getattr(reference, 'name', '') or hypothesis is None:
            clear(surface, item)
            return []
        path = reference.path
        reference_text, reading = spec.read_reference(path)
        sha = _file_sha256(path)
        name = os.path.basename(reference.name)
        model_key = spec.model_key(item) or ''

        from wama.common.models import ResultEvaluation
        written = []
        known = _text_metrics()
        for metric in spec.metrics:
            measure = known[metric][1](reference_text, hypothesis)
            row, _ = ResultEvaluation.objects.update_or_create(
                app=surface, object_type=type(item).__name__, object_id=item.pk, metric=metric,
                defaults={
                    'user': getattr(item, 'user', None), 'model_key': model_key,
                    'value': measure.rate, 'direction': 'lower', 'protocol': spec.protocol,
                    'reference_sha256': sha, 'reference_name': name,
                    'detail': {**measure.as_dict(), 'reading': reading},
                })
            written.append(row)
        # Une métrique qui n'est plus déclarée ne doit pas survivre à côté des autres.
        _rows_of(surface, item).exclude(metric__in=spec.metrics).delete()
        return written
    except Exception as exc:
        logger.warning('[evaluation] mesure %s#%s impossible : %s',
                       surface, getattr(item, 'pk', '?'), exc)
        return []


# ── Lecture (interface) ─────────────────────────────────────────────────────────────────────

def _model_label(model_key: str) -> str:
    if not model_key:
        return 'Modèle inconnu'
    if model_key.startswith(EXTERNAL_PREFIX):
        return f"Résultat externe · {model_key[len(EXTERNAL_PREFIX):] or 'sans nom'}"
    try:
        from wama.model_manager.models import AIModel
        found = AIModel.objects.filter(model_key=model_key).values_list('name', flat=True).first()
        if found:
            return found
    except Exception:
        pass
    return model_key.split(':', 1)[-1]


def item_evaluation(surface: str, item) -> Optional[dict]:
    """La mesure d'un élément, prête pour l'onglet « Évaluation » ; None s'il n'y en a pas."""
    spec = evaluation_spec(surface)
    if spec is None or item is None:
        return None
    rows = list(_rows_of(surface, item))
    if not rows:
        reference = getattr(item, spec.reference_field, None)
        if reference and getattr(reference, 'name', ''):
            return {'reference_name': os.path.basename(reference.name), 'metrics': [],
                    'pending': True}
        return None
    labels = _text_metrics()
    first = rows[0]
    return {
        'reference_name': first.reference_name,
        'reference_sha256': first.reference_sha256,
        'model_key': first.model_key,
        'model_label': _model_label(first.model_key),
        'protocol': first.protocol,
        'measured_at': first.measured_at.isoformat(),
        'reading': (first.detail or {}).get('reading') or {},
        'metrics': [{'metric': r.metric, 'label': labels.get(r.metric, (r.metric,))[0],
                     'value': r.value, 'direction': r.direction,
                     **{k: (r.detail or {}).get(k) for k in (
                         'substitutions', 'deletions', 'insertions', 'errors',
                         'reference_length', 'hypothesis_length', 'unit')}}
                    for r in sorted(rows, key=lambda r: spec.metrics.index(r.metric)
                                    if r.metric in spec.metrics else 99)],
        'pending': False,
    }


def batch_evaluation(surface: str, items: Iterable) -> Optional[dict]:
    """Comparaison des modèles d'un lot — le résumé de la ligne de la card mère.

    Par modèle : le taux AGRÉGÉ du corpus (Σ erreurs / Σ longueurs de référence — la définition
    standard d'un WER de corpus, pas une moyenne de taux, qui donnerait le même poids à 3 mots
    qu'à 3 000). `comparable` est faux quand les modèles n'ont pas été mesurés sur les MÊMES
    références : un classement sur des corpus différents ne veut rien dire, et on le dit.
    """
    spec = evaluation_spec(surface)
    if spec is None:
        return None
    items = [i for i in items if i is not None]
    if not items:
        return None
    from wama.common.models import ResultEvaluation
    rows = ResultEvaluation.objects.filter(
        app=surface, object_type=type(items[0]).__name__,
        object_id__in=[i.pk for i in items])
    if not rows.exists():
        return None

    per_model: Dict[str, dict] = {}
    for r in rows:
        entry = per_model.setdefault(r.model_key, {'model_key': r.model_key,
                                                   'model_label': _model_label(r.model_key),
                                                   'items': set(), 'references': set(),
                                                   'metrics': {}})
        entry['items'].add(r.object_id)
        entry['references'].add(r.reference_sha256)
        d = r.detail or {}
        agg = entry['metrics'].setdefault(r.metric, {'errors': 0, 'reference_length': 0})
        agg['errors'] += int(d.get('errors') or 0)
        agg['reference_length'] += int(d.get('reference_length') or 0)

    primary = spec.metrics[0]
    models = []
    for entry in per_model.values():
        rates = {m: (round(a['errors'] / a['reference_length'], 4) if a['reference_length'] else None)
                 for m, a in entry['metrics'].items()}
        models.append({'model_key': entry['model_key'], 'model_label': entry['model_label'],
                       'items': len(entry['items']), 'references': len(entry['references']),
                       'rates': rates,
                       # Le taux de la métrique PRINCIPALE, en pour cent — ce qu'affiche la ligne.
                       'primary_percent': (round(rates[primary] * 100, 1)
                                           if rates.get(primary) is not None else None),
                       'reference_set': sorted(entry['references'])})
    models.sort(key=lambda m: (m['rates'].get(primary) is None, m['rates'].get(primary) or 0))
    comparable = len({tuple(m['reference_set']) for m in models}) <= 1
    for m in models:
        del m['reference_set']
    labels = _text_metrics()
    return {'primary': primary, 'primary_label': labels[primary][0], 'models': models,
            'comparable': comparable, 'evaluated_items': len({r.object_id for r in rows}),
            'total_items': len(items)}


# ── Attacher / retirer une référence ────────────────────────────────────────────────────────

class ReferenceRefused(ValueError):
    """La référence ne peut pas être posée — le motif est DIT à l'utilisateur."""


def attach_reference(surface: str, targets: List, uploaded) -> dict:
    """Pose UNE référence sur un ou plusieurs éléments (une card, ou toutes celles d'un lot).

    Le fichier est enregistré UNE fois ; les autres éléments désignent le même chemin — c'est le
    contrat de partage que `safe_delete_file` sait tenir (un fichier encore désigné n'est pas
    supprimé). Chaque élément est ensuite remesuré.
    """
    spec = evaluation_spec(surface)
    if spec is None:
        raise ReferenceRefused(f"{surface} ne sait pas évaluer ses résultats")
    if not targets:
        raise ReferenceRefused("aucun élément à qui poser la référence")
    ext = os.path.splitext(getattr(uploaded, 'name', '') or '')[1].lower()
    if spec.reference_extensions and ext not in spec.reference_extensions:
        raise ReferenceRefused(
            f"format {ext or '(sans extension)'} non lu — formats acceptés : "
            f"{', '.join(spec.reference_extensions)}")

    detach_reference(surface, targets)
    first = targets[0]
    getattr(first, spec.reference_field).save(os.path.basename(uploaded.name), uploaded, save=False)
    first.save(update_fields=[spec.reference_field])
    stored = getattr(first, spec.reference_field).name
    for other in targets[1:]:
        setattr(other, spec.reference_field, stored)
        other.save(update_fields=[spec.reference_field])

    # Une référence illisible se dit ICI, pas plus tard sous forme d'onglet vide.
    try:
        spec.read_reference(getattr(first, spec.reference_field).path)
    except Exception as exc:
        detach_reference(surface, targets)
        raise ReferenceRefused(f"référence illisible : {exc}")

    measured = sum(1 for t in targets if evaluate(surface, t))
    return {'reference_name': os.path.basename(stored), 'targets': len(targets),
            'measured': measured}


def detach_reference(surface: str, targets: List) -> int:
    """Retire la référence d'éléments ; le fichier n'est supprimé que s'il n'est plus désigné."""
    import copy
    from wama.common.utils.queue_duplication import safe_delete_file
    spec = evaluation_spec(surface)
    if spec is None:
        return 0
    released = {}                                   # chemin → une card qui le désignait
    detached = 0
    for item in targets:
        name = getattr(getattr(item, spec.reference_field, None), 'name', '')
        if not name:
            continue
        released.setdefault(name, item)
        detached += 1
        setattr(item, spec.reference_field, None)
        item.save(update_fields=[spec.reference_field])
        clear(surface, item)
    # Supprimer APRÈS avoir tout détaché : sinon le partage garderait le fichier en vie par une
    # card qu'on s'apprête justement à détacher. La règle reste celle de `safe_delete_file` —
    # propriété (fichier chez l'app) ET plus aucune autre ligne ne le désigne. La copie garde
    # le propriétaire et la clé de la card, que la règle lit ; seul le chemin y est rétabli.
    for name, item in released.items():
        probe = copy.copy(item)
        setattr(probe, spec.reference_field, name)
        safe_delete_file(probe, spec.reference_field)
    return detached
