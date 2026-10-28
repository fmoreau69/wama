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

MESURES SANS RÉFÉRENCE (2026-10-22, décision de Fabien : la garde (b) de `WAMA_QUALITE §9bis`) —
ce qui se juge sur la sortie elle-même, sans vérité en face : la part de la parole que couvre
une transcription. Un REGISTRE commun (`register_check`), DÉCLARÉ par process
(`ProcessSpec.checks`), joué par le squelette quand la card a réussi (`run_checks`), gardé sur la
LIGNE du process et non dans `ResultEvaluation` — celle-ci est une mesure CONTRE une référence,
la matière de l'indice des modèles : une mesure sans référence la fausserait. La bande des
process la montre sur sa ligne, la face « Évaluation » à côté des mesures contre référence
(`item_evaluation`, qui les réunit).
"""
from __future__ import annotations

import hashlib
import logging
import os
from dataclasses import dataclass
from typing import Callable, Dict, Iterable, List, Optional, Tuple

from wama.common.services.diarization_metrics import DIARIZATION_PROTOCOL

logger = logging.getLogger(__name__)

#: Version du protocole de mesure texte : normalisation de `text_metrics` (casse, ponctuation,
#: apostrophe séparatrice, hésitations conservées). La changer change l'ÉCHELLE.
#: `text_v2` (2026-09-28) : + soulignement séparateur, + nombres en chiffres dans la langue de
#: l'élément. Les mesures `text_v1` déjà écrites restent sur leur échelle (une autre population,
#: `internal_quality` ne les mêle pas) ; un élément remesuré passe en v2.
TEXT_PROTOCOL = 'text_v2'

#: Préfixe d'un résultat produit hors de WAMA : mesurable, jamais agrégé comme un modèle du parc.
EXTERNAL_PREFIX = 'external:'

#: Clé du détail de lecture par laquelle une référence dit ne couvrir QUE certaines plages du
#: temps (`[[début, fin], …]` en secondes) — ex. un export Sonal aux extraits laissés vides.
#: Le résultat est alors restreint à ses segments dont le MILIEU tombe dans ces plages : ce que
#: le moteur a entendu ailleurs n'a rien en face, le compter ferait des « ajouts » fictifs
#: (mesuré le 2026-09-30 : ~1 190 mots sur un entretien de 2 h 22). Sans segments horodatés,
#: rien n'est restreint, et le détail le dit.
COVERED_SPANS = 'covered_spans'


def _within_spans(segment: dict, spans: list) -> bool:
    middle = (segment['start_time'] + segment['end_time']) / 2
    return any(start <= middle < end for start, end in spans)


def _restricted(spec: 'EvaluationSpec', item, reading: dict):
    """(segments du résultat restreints aux plages de la référence ou None, lecture à stocker)."""
    spans = reading.get(COVERED_SPANS)
    stored = {k: v for k, v in reading.items() if k != COVERED_SPANS}
    if not spans:
        return None, stored
    segments = (spec.result_segments(item) or []) if spec.result_segments else []
    timed = bool(segments) and all(
        isinstance(s.get('start_time'), (int, float)) and isinstance(s.get('end_time'), (int, float))
        for s in segments)
    if not timed:
        stored['restricted'] = None          # la référence est partielle, le résultat sans temps
        return None, stored
    kept = [s for s in segments if _within_spans(s, spans)]
    stored['restricted'] = {'spans': len(spans), 'segments_kept': len(kept),
                            'segments': len(segments)}
    return kept, stored


def _text_metrics():
    from wama.common.services.text_metrics import character_error_rate, word_error_rate
    return {
        'wer': ('Taux d’erreur par mot (WER)', word_error_rate),
        'cer': ('Taux d’erreur par caractère (CER)', character_error_rate),
    }


def _segment_metrics():
    """Métriques qui lisent des SEGMENTS (locuteur, temps), pas un texte — la diarisation
    (`diarization_metrics`, 2026-09-30). Une mesure sans objet y rend None : pas de ligne."""
    from wama.common.services.diarization_metrics import (
        cp_word_error_rate, diarization_error_rate,
    )
    return {
        'cpwer': ('Taux d’erreur par mot, locuteurs compris (cpWER)', cp_word_error_rate),
        'der': ('Taux d’erreur de diarisation (DER)', diarization_error_rate),
    }


def _all_metrics():
    return {**_text_metrics(), **_segment_metrics()}


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
    #: Port `work_result` (capacité `has_result_import`) — facultatif : le champ fichier qui porte
    #: un résultat produit AILLEURS, et comment l'app en fait SON résultat (élément → None ; lève
    #: si le fichier ne se lit pas). Ses extensions : celles de la référence, sauf mention.
    result_field: str = ''
    import_result: Optional[Callable[[object], None]] = None
    #: Lot SANS référence (M1/M6) — facultatif : ce qui identifie l'ENTRÉE d'un élément (on ne
    #: compare que des résultats d'une même entrée), et le DÉSACCORD entre deux résultats (0..1,
    #: None = non comparables, ex. un résultat sans temps face à un résultat horodaté).
    input_identity: Optional[Callable[[object], Optional[str]]] = None
    disagreement: Optional[Callable[[object, object], Optional[float]]] = None
    #: Réglages du schéma (`params.py`) qui CHANGENT le résultat mesuré. Deux éléments d'un lot
    #: au même modèle mais à réglages différents sont deux CONFIGURATIONS, comparées séparément
    #: (mesuré le 2026-09-25 : un lot « whisper avec / sans prétraitement » sortait sur UNE ligne,
    #: les deux cards fondues). Vide = regroupement par modèle seul. DÉCLARÉ, jamais deviné :
    #: un schéma mêle réglages, ENTRÉES (le prompt d'un composer diffère d'un élément à l'autre
    #: sans en faire deux configurations) et options sans effet sur le résultat (un résumé).
    config_params: Tuple[str, ...] = ()
    #: Langue du résultat (élément → code ISO ou '') — facultatif : la normalisation `text_v2`
    #: écrit les nombres en chiffres DANS cette langue (`text_metrics.comparable_words`).
    language: Optional[Callable[[object], str]] = None
    #: Métriques À SEGMENTS (`cpwer`, `der`) — facultatif : les segments du résultat (élément →
    #: liste de dicts `speaker_id`/`start_time`/`end_time`/`text`, None s'il n'en a pas) et ceux
    #: de la référence (chemin → liste). Les deux vont ensemble avec ces métriques.
    result_segments: Optional[Callable[[object], Optional[list]]] = None
    read_reference_segments: Optional[Callable[[str], list]] = None
    #: Le modèle qui a ATTRIBUÉ les locuteurs (élément → clé catalogue) : les mesures de
    #: diarisation se rangent sous LUI, pas sous le moteur ASR — sans quoi l'indice interne
    #: prêterait à Whisper la qualité de pyannote. None = `model_key`.
    segment_model_key: Optional[Callable[[object], str]] = None
    segment_protocol: str = DIARIZATION_PROTOCOL


_REGISTRY: Dict[str, EvaluationSpec] = {}


def register_evaluation(spec: EvaluationSpec) -> None:
    """Appelé depuis le `apps.py:ready()` de l'app — le registre ne connaît jamais ses apps."""
    known = _all_metrics()
    unknown = [m for m in spec.metrics if m not in known]
    if unknown:
        raise ValueError(f"métriques inconnues pour {spec.surface} : {unknown}")
    segment_metrics = [m for m in spec.metrics if m in _segment_metrics()]
    if segment_metrics and (spec.result_segments is None or spec.read_reference_segments is None):
        raise ValueError(f"{spec.surface} déclare {segment_metrics} sans dire lire ses segments "
                         f"(result_segments + read_reference_segments)")
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
        kept_segments, reading = _restricted(spec, item, reading)
        if kept_segments is not None:
            hypothesis = ' '.join((s.get('text') or '').strip() for s in kept_segments).strip()
        sha = _file_sha256(path)
        name = os.path.basename(reference.name)
        model_key = spec.model_key(item) or ''
        language = (spec.language(item) or '') if spec.language else ''

        from wama.common.models import ResultEvaluation
        written = []
        text_metrics = _text_metrics()
        segment_metrics = _segment_metrics()
        segments = None
        for metric in spec.metrics:
            common = {'user': getattr(item, 'user', None), 'direction': 'lower',
                      'reference_sha256': sha, 'reference_name': name}
            if metric in text_metrics:
                measure = text_metrics[metric][1](reference_text, hypothesis,
                                                  language=language or None)
                defaults = {**common, 'model_key': model_key, 'protocol': spec.protocol,
                            'detail': {**measure.as_dict(), 'reading': reading,
                                       'language': language}}
            else:
                # Une métrique à segments qui échoue n'emporte pas les autres (best-effort).
                try:
                    if segments is None:
                        segments = (spec.read_reference_segments(path),
                                    kept_segments if kept_segments is not None
                                    else spec.result_segments(item) or [])
                    measure = segment_metrics[metric][1](*segments, language=language or None)
                except Exception as exc:
                    logger.warning('[evaluation] %s %s#%s impossible : %s',
                                   metric, surface, item.pk, exc)
                    measure = None
                if measure is None:          # sans objet : sortie non diarisée, pas de temps…
                    continue
                speaker_key = (spec.segment_model_key(item) if spec.segment_model_key
                               else model_key) or model_key
                defaults = {**common, 'model_key': speaker_key, 'protocol': spec.segment_protocol,
                            'detail': {**measure.as_dict(), 'reading': reading,
                                       'language': language, 'result_model_key': model_key}}
            row, _ = ResultEvaluation.objects.update_or_create(
                app=surface, object_type=type(item).__name__, object_id=item.pk, metric=metric,
                defaults={**defaults, 'value': measure.rate})
            written.append(row)
        # Une métrique qui n'est plus déclarée — ou plus mesurable (diarisation retirée à la
        # relance) — ne doit pas survivre à côté des autres.
        _rows_of(surface, item).exclude(metric__in=[r.metric for r in written]).delete()
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


def _configurations(spec: EvaluationSpec, items: list) -> Dict[int, Tuple[str, str]]:
    """{pk: (clé, libellé)} de la CONFIGURATION de chaque élément : son modèle, plus les réglages
    qui DIFFÈRENT d'un élément à l'autre du lot (libellés et valeurs lus au schéma de l'app).
    Un réglage identique partout n'est pas nommé : il ne distingue rien."""
    from wama.common.utils.param_schema import schema_for_app
    schema = {p['name']: p for p in schema_for_app(spec.surface)}
    names = list(spec.config_params)
    values = {i.pk: {n: getattr(i, n, None) for n in names} for i in items}
    varying = [n for n in names if len({repr(v[n]) for v in values.values()}) > 1]

    def shown(name, value):
        choices = dict((schema.get(name) or {}).get('choices') or [])
        if isinstance(value, bool):
            return 'oui' if value else 'non'
        text = str(choices.get(value, value) or '—')
        return text if len(text) <= 30 else text[:29] + '…'

    out = {}
    for item in items:
        model_key = spec.model_key(item) or ''
        settings = [(n, values[item.pk][n]) for n in varying]
        key = model_key + ''.join(f'|{n}={v!r}' for n, v in settings)
        label = _model_label(model_key)
        if settings:
            label += ' · ' + ', '.join(
                f"{(schema.get(n) or {}).get('label') or n} : {shown(n, v)}" for n, v in settings)
        out[item.pk] = (key, label)
    return out


def item_evaluation(surface: str, item) -> Optional[dict]:
    """La mesure d'un élément, prête pour l'onglet « Évaluation » ; None s'il n'y en a pas.
    `checks` : ses mesures SANS référence (`item_checks`), présentes même sans référence."""
    if item is None:
        return None
    checks = item_checks(item)
    spec = evaluation_spec(surface)
    if spec is None:
        return _checks_only(checks)
    rows = list(_rows_of(surface, item))
    if not rows:
        reference = getattr(item, spec.reference_field, None)
        if reference and getattr(reference, 'name', ''):
            return {'reference_name': os.path.basename(reference.name), 'metrics': [],
                    'pending': True, 'checks': checks}
        return _checks_only(checks)
    labels = _all_metrics()
    # Le modèle de la card est celui des mesures de TEXTE ; une mesure de diarisation est rangée
    # sous le diariseur (`segment_model_key`) et ne doit pas renommer la card.
    first = next((r for r in rows if r.metric in _text_metrics()), rows[0])
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
                     'model_key': r.model_key, 'protocol': r.protocol,
                     **{k: (r.detail or {}).get(k) for k in (
                         'substitutions', 'deletions', 'insertions', 'errors',
                         'reference_length', 'hypothesis_length', 'unit',
                         'attribution_errors', 'missed', 'false_alarm', 'confusion')}}
                    for r in sorted(rows, key=lambda r: spec.metrics.index(r.metric)
                                    if r.metric in spec.metrics else 99)],
        'pending': False,
        'checks': checks,
    }


def _checks_only(checks: list) -> Optional[dict]:
    """La face « Évaluation » d'un élément SANS mesure contre une référence, mais dont une sortie
    a été mesurée sans elle ; None s'il n'y a rien."""
    if not checks:
        return None
    return {'reference_name': '', 'metrics': [], 'pending': False, 'checks': checks}


def evaluation_text(measure: dict) -> str:
    """La mesure d'`item_evaluation` en TEXTE — ce que Copier emporte de la face « Évaluation »
    de la visionneuse (le dessin est `WamaEvaluation.renderItem`)."""
    lines = []
    if measure.get('pending'):
        lines.append(f"Référence {measure.get('reference_name')} posée — la mesure suivra le "
                     f"prochain résultat.")
    elif measure.get('metrics'):
        lines.append(f"{measure.get('model_label')} comparé à {measure.get('reference_name')}")
    for m in measure.get('metrics') or ():
        rate = '—' if m.get('value') is None else f"{m['value'] * 100:.1f} %"
        lines.append(f"{m.get('label')} : {rate} (substitutions {m.get('substitutions')}, "
                     f"suppressions {m.get('deletions')}, insertions {m.get('insertions')})")
    for check in measure.get('checks') or ():
        lines.append(f"{check.get('process_label')} — {check.get('label')} : {check.get('message')}")
    return '\n'.join(lines)


# ── Mesures SANS référence d'une sortie (2026-10-22) ────────────────────────────────────────

@dataclass(frozen=True)
class Check:
    """Une mesure sans référence de la sortie d'un process. `measure(app_id, item, pipeline,
    spec, model_key)` rend `{value, short, message, detail?, suggest?}` ou None (rien à juger).
    `suggest` : `{field, value, label}` — le réglage de la card qui la corrigerait, posé par la
    bande des process avant de relancer le process (« Relancer avec … »). `input` : l'empreinte de
    l'entrée mesurée. `defect_label` : le libellé court d'un modèle que cette mesure prend en
    défaut. `compares_models` : la valeur se COMPARE d'un modèle à l'autre sur la même entrée —
    sans cette déclaration, la mesure reste un signal de la card et ne propose aucun défaut
    (`model_quality.defect_evidence`, 2026-10-28).
    ⚠ Mesuré le 2026-10-28 sur 462 transcriptions : `speech_coverage` ne se compare PAS entre
    moteurs — le filtre de parole ne s'applique qu'à Whisper et Albert, les moteurs NeMo rendent des
    segments plus courts, un modèle qui couvre tout l'audio de segments obtient 100 %. Elle aurait
    proposé de griser Whisper, Canary, Parakeet, Kyutai et LinTO, et pas Albert."""

    key: str
    label: str
    measure: Callable
    defect_label: str = ''
    compares_models: bool = False


CHECKS: Dict[str, Check] = {}


def register_check(check: Check) -> None:
    """Inscrit une mesure ; un process la DÉCLARE par sa clé (`ProcessSpec.checks`)."""
    CHECKS[check.key] = check


def run_checks(app_id: str, item, task_id: str = '') -> list:
    """Joue les mesures DÉCLARÉES des process que ce lancement a rendus (ligne `SUCCESS` de la
    tâche `task_id`) et les garde sur leur ligne ; rend celles qui ont été écrites. Appelé par le
    squelette quand la card a réussi — le résultat se lit alors (`result_segments`). Best-effort :
    une mesure qui casse est journalisée, jamais levée."""
    from wama.common.models import JOB_SUCCESS
    from wama.common.services import process_runs
    from wama.common.services.process_pipeline import pipeline_of
    pipeline = pipeline_of(item)
    if pipeline is None:
        return []
    rows = pipeline.rows(item)
    written = []
    for spec in pipeline.specs:
        row = rows.get(spec.key)
        if not spec.checks or row is None or row.status != JOB_SUCCESS:
            continue
        if task_id and row.task_id and row.task_id != task_id:
            continue
        results = []
        for key in spec.checks:
            try:
                found = CHECKS[key].measure(app_id, item, pipeline, spec, row.model_key or '')
            except Exception as exc:
                logger.warning("[%s] mesure « %s » de #%s impossible : %s", app_id, key, item.pk, exc)
                continue
            if found:
                results.append({'key': key, 'label': CHECKS[key].label, **found})
        process_runs.safely(process_runs.annotate, item, spec.key, checks=results)
        written += [dict(r, process=spec.key, process_label=spec.label or spec.key)
                    for r in results]
        if row.model_key and any(r.get('short') and getattr(CHECKS.get(r.get('key')), 'compares_models', False)
                                 for r in results):
            # Un modèle pris en défaut sur un audio qu'un autre a bien couvert : le défaut est
            # PROPOSÉ à un administrateur, jamais posé d'office (`ROADMAP §16.5`, 2026-10-28).
            try:
                from wama.model_manager.services.model_quality import propose_defect
                propose_defect(row.model_key)
            except Exception as exc:
                logger.warning("[%s] proposition de défaut pour %s impossible : %s",
                               app_id, row.model_key, exc)
    return written


def item_checks(item) -> list:
    """Les mesures sans référence gardées sur les lignes de l'élément, dans l'ordre du pipeline,
    chacune avec son process (`process`, `process_label`)."""
    try:
        from wama.common.services.process_pipeline import pipeline_of
        pipeline = pipeline_of(item)
        if pipeline is None:
            return []
        rows = pipeline.rows(item)
    except Exception:
        return []
    out = []
    for spec in pipeline.ordered():
        row = rows.get(spec.key)
        for check in ((row.output_summary or {}).get('checks') or []) if row is not None else []:
            out.append(dict(check, process=spec.key, process_label=spec.label or spec.key))
    return out


def _local_alternative(app_id: str, item, model_key: str) -> Optional[dict]:
    """Le modèle LOCAL que le tirage « auto » de la card retiendrait, quand sa sortie vient d'un
    modèle DISTANT — `{field, value, label}` sur le réglage du modèle de l'app (`catalog_field`).
    Le même tirage que le lancement, les distants exclus (`cloud_keys=[]`, `select_model`)."""
    from wama.model_manager.services.cloud_models import is_cloud_key
    if not model_key or not is_cloud_key(model_key):
        return None
    from wama.common.utils.auto_model import catalog_field, resolve_model_choice
    field = catalog_field(app_id)
    if not field:
        return None
    local = resolve_model_choice('auto', app_id=app_id, item=item, cloud_keys=[])
    if not local or is_cloud_key(local):
        return None
    return {'field': field['name'], 'value': local, 'label': _model_label(local)}


def _speech_coverage(app_id: str, item, pipeline, spec, model_key: str) -> Optional[dict]:
    """La part de la PAROLE que couvrent les segments de la transcription
    (`speech_activity.speech_coverage`), sur l'audio que le process a écouté
    (`AppPipeline.input_of`) et les segments que l'app déclare lire (`result_segments`)."""
    evaluation = evaluation_spec(app_id)
    if evaluation is None or evaluation.result_segments is None:
        return None
    path = pipeline.input_of(item, spec.key, 'audio')
    from wama.common.app_registry import category_of_path
    # L'entrée principale de la card peut ne pas être un son (une image d'avatar) ; une VIDÉO en
    # porte un, que le décodage lit.
    if not path or not os.path.isfile(path) or category_of_path(path) not in ('audio', 'video'):
        return None
    from wama.common.utils.audio_decode import probe_duration_seconds
    from wama.common.utils.speech_activity import COVERAGE_FLOOR, speech_coverage
    segments = evaluation.result_segments(item) or []
    measured = speech_coverage(path, [(s.get('start_time'), s.get('end_time')) for s in segments],
                               duration_s=probe_duration_seconds(path) or 0)
    if measured['ratio'] is None:
        return None
    percent = round(measured['ratio'] * 100)
    from wama.common.utils.provenance import sha256_of
    # `input` : l'empreinte de l'audio ÉCOUTÉ — deux cards qui le partagent se comparent
    # (`model_quality.defect_evidence`, 2026-10-28).
    found = {'value': measured['ratio'], 'floor': COVERAGE_FLOOR, 'short': measured['short'],
             'message': f"{percent} % de la parole transcrite", 'input': sha256_of(path),
             'detail': {k: measured[k] for k in ('active_s', 'covered_s', 'windows')}}
    if measured['short']:
        found['message'] = f"{percent} % seulement de la parole transcrite : du texte manque"
        suggestion = _local_alternative(app_id, item, model_key)
        if suggestion:
            found['suggest'] = suggestion
    return found


register_check(Check('speech_coverage', 'Parole transcrite', _speech_coverage,
                     defect_label='omet de la parole'))


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

    configurations = _configurations(spec, items)
    per_model: Dict[str, dict] = {}
    for r in rows:
        key, label = configurations.get(r.object_id, (r.model_key, _model_label(r.model_key)))
        # Le modèle de la CONFIGURATION (tête de sa clé), pas celui de la ligne : une ligne de
        # diarisation est rangée sous le diariseur.
        entry = per_model.setdefault(key, {'model_key': key.split('|', 1)[0], 'model_label': label,
                                           'items': set(), 'references': set(),
                                           'metrics': {}})
        entry['items'].add(r.object_id)
        entry['references'].add(r.reference_sha256)
        d = r.detail or {}
        agg = entry['metrics'].setdefault(r.metric, {'errors': 0, 'reference_length': 0})
        # Flottants : le DER compte des SECONDES (un `int` tronquait chaque élément).
        agg['errors'] += float(d.get('errors') or 0)
        agg['reference_length'] += float(d.get('reference_length') or 0)

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
    labels = _all_metrics()
    return {'primary': primary, 'primary_label': labels[primary][0], 'models': models,
            'comparable': comparable, 'evaluated_items': len({r.object_id for r in rows}),
            'total_items': len(items)}


# ── Lot SANS référence : l'accord entre moteurs (M1 deux à deux, M6 à partir de trois) ─────

#: Un accord calculé reste valable tant qu'aucun résultat du groupe ne change (empreinte) ;
#: la durée ne sert qu'à laisser le cache se vider de lui-même.
AGREEMENT_CACHE_SECONDS = 24 * 3600


def batch_agreement(surface: str, items: Iterable) -> Optional[dict]:
    """Le désaccord entre les moteurs d'un lot, SANS référence (`WAMA_QUALITE` M1, M6).

    On ne compare que des résultats d'une MÊME entrée (`input_identity`) : un lot ordinaire,
    un fichier par card, ne forme aucun groupe et ne coûte rien. Par moteur : la MÉDIANE de ses
    désaccords deux à deux — son taux d'isolement (M6). À partir de trois, le plus isolé est
    SIGNALÉ ; il n'est jamais déclaré « le pire », ni un autre « le meilleur » : un modèle isolé
    peut être le seul juste (M6, « jamais un tri seul »).

    Calculé à l'affichage de la file, donc mis en CACHE sous l'empreinte des résultats : un
    résultat qui change change l'empreinte, et l'accord est recalculé.
    """
    import hashlib
    import statistics
    from itertools import combinations
    from django.core.cache import cache

    spec = evaluation_spec(surface)
    if spec is None or spec.input_identity is None or spec.disagreement is None:
        return None
    groups: Dict[str, list] = {}
    for item in items:
        if item is None:
            continue
        text = spec.result_text(item)
        key = spec.input_identity(item)
        if text is None or not key:
            continue
        groups.setdefault(key, []).append((item, text))
    groups = {k: v for k, v in groups.items() if len(v) >= 2}
    if not groups:
        return None

    fingerprint = hashlib.sha1(repr(sorted(
        (key, item.pk, spec.model_key(item), hashlib.sha1(text.encode('utf-8')).hexdigest())
        for key, members in groups.items() for item, text in members)).encode('utf-8')).hexdigest()
    cache_key = f'wama:agreement:{surface}:{fingerprint}'
    try:
        cached = cache.get(cache_key)
    except Exception:
        cached = None
    if cached is not None:
        return cached

    configurations = _configurations(spec, [item for members in groups.values()
                                            for item, _ in members])
    out = []
    for key, members in groups.items():
        pairs = []
        for (a, _), (b, _) in combinations(members, 2):
            try:
                value = spec.disagreement(a, b)
            except Exception as exc:
                logger.debug('[evaluation] désaccord %s#%s/%s impossible : %s', surface, a.pk, b.pk, exc)
                value = None
            pairs.append((a.pk, b.pk, value))
        engines = []
        for item, _ in members:
            mine = [v for x, y, v in pairs if item.pk in (x, y) and v is not None]
            engines.append({'pk': item.pk, 'model_key': spec.model_key(item),
                            'model_label': configurations[item.pk][1],
                            'isolation': round(statistics.median(mine), 4) if mine else None,
                            'isolation_percent': (round(statistics.median(mine) * 100, 1)
                                                  if mine else None),
                            'compared': len(mine)})
        engines.sort(key=lambda e: (e['isolation'] is None, e['isolation'] or 0))
        measured = [e for e in engines if e['isolation'] is not None]
        most_isolated = None
        if len(measured) >= 3 and measured[-1]['isolation'] > measured[-2]['isolation']:
            most_isolated = measured[-1]['pk']
        out.append({'input': os.path.basename(key), 'engines': engines,
                    'pairs': len(pairs), 'comparable_pairs': sum(1 for p in pairs if p[2] is not None),
                    'most_isolated': most_isolated})
    result = {'groups': out, 'method': 'M1/M6'}
    try:
        cache.set(cache_key, result, AGREEMENT_CACHE_SECONDS)
    except Exception:
        pass
    return result


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


def attach_result(surface: str, item, uploaded) -> dict:
    """Pose un RÉSULTAT EXISTANT sur un élément (port `work_result`) : il tient lieu de traitement.

    L'app en fait son résultat (`import_result`), puis l'élément est mesuré s'il porte une
    référence. Un seul élément : un résultat appartient à UNE entrée — le poser sur un lot
    n'aurait pas de sens. Un fichier illisible est refusé ET retiré.
    """
    spec = evaluation_spec(surface)
    if spec is None or not spec.result_field or spec.import_result is None:
        raise ReferenceRefused(f"{surface} ne sait pas reprendre un résultat existant")
    ext = os.path.splitext(getattr(uploaded, 'name', '') or '')[1].lower()
    if spec.reference_extensions and ext not in spec.reference_extensions:
        raise ReferenceRefused(
            f"format {ext or '(sans extension)'} non lu — formats acceptés : "
            f"{', '.join(spec.reference_extensions)}")
    detach_result(surface, item)
    getattr(item, spec.result_field).save(os.path.basename(uploaded.name), uploaded, save=False)
    item.save(update_fields=[spec.result_field])
    try:
        spec.import_result(item)
    except Exception as exc:
        detach_result(surface, item)
        raise ReferenceRefused(f"résultat illisible : {exc}")
    evaluate(surface, item)
    return {'result_name': os.path.basename(getattr(item, spec.result_field).name)}


def detach_result(surface: str, item) -> int:
    """Retire le fichier du résultat existant. Le RÉSULTAT de l'élément reste tel quel jusqu'à
    sa prochaine relance (on n'efface pas un texte sous les yeux de l'utilisateur)."""
    import copy
    from wama.common.utils.queue_duplication import safe_delete_file
    spec = evaluation_spec(surface)
    name = getattr(getattr(item, spec.result_field, None), 'name', '') if spec and spec.result_field else ''
    if not name:
        return 0
    setattr(item, spec.result_field, None)
    item.save(update_fields=[spec.result_field])
    probe = copy.copy(item)
    setattr(probe, spec.result_field, name)
    safe_delete_file(probe, spec.result_field)
    return 1


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
