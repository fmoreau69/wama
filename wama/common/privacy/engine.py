"""L'ORCHESTRATION — détecter les données personnelles d'un texte, puis les occulter (2026-10-28).

    detect(text, language='')            → document `detections` (forme texte, `common/utils/detections`)
    detect_segments([texte, …], language) → le même, un segment par « frame » (pages d'un document)
    occult(text, doc, language='')        → le texte, chaque passage remplacé par `[LIBELLÉ]`

L'UNION (décision D1 précisée le 2026-10-28, `ROADMAP §16.4bis`) : Presidio orchestre ; y entrent
ses motifs à chiffre de contrôle, les identifiants français, et CHAQUE modèle `pii-detection`
INSTALLÉ au catalogue qui couvre la langue du texte, par son backend (`recognizers.
BackendRecognizer`). Un détecteur de plus = une ligne de catalogue et son backend : rien à toucher
ici. Les passages qui se recouvrent sont RÉUNIS (le plus long gagne la place, le meilleur score
donne le type), et chaque passage garde les détecteurs qui l'ont vu (`sources`).

Occulter = remplacer par le libellé du type entre crochets, dans la langue du texte
(`entities.label_for`), avec l'anonymiseur de Presidio. Le document CORRIGÉ par l'humain
(`detections.apply_corrections`) s'occulte de la même façon : corriger ne redétecte rien.
"""
from __future__ import annotations

import logging
import re
import threading
from typing import Iterable, List, Optional

from wama.common.privacy.entities import DEFAULT_LANGUAGE, ENTITY_TYPES, label_for

logger = logging.getLogger(__name__)

#: Langues dont l'analyseur sait toujours traiter un texte (motifs), même sans modèle installé.
BASE_LANGUAGES = ('en', 'fr')
_lock = threading.Lock()
_analyzers: dict = {}


def installed_detectors() -> list:
    """`[(clé, langues)]` des modèles `pii-detection` INSTALLÉS — lu au catalogue, jamais écrit ici."""
    try:
        from wama.model_manager.models import AIModel
        rows = AIModel.objects.filter(capabilities__task='pii-detection', is_downloaded=True)
        return [(m.model_key, list((m.capabilities or {}).get('languages') or []))
                for m in rows.order_by('model_key')]
    except Exception as e:
        logger.warning("[privacy] catalogue illisible, motifs seuls : %s", e)
        return []


def _analyzer(language: str, detectors: tuple):
    """`(analyseur, détecteurs ÉCARTÉS)` d'une langue et d'un jeu de détecteurs — construit une fois
    par processus. Un détecteur qui ne se charge pas est ÉCARTÉ ET NOMMÉ (jamais en silence : un
    filtre qui perd un détecteur perd du rappel), et l'analyseur n'est alors PAS gardé, pour qu'un
    modèle installé entre-temps rejoigne l'union au prochain appel."""
    key = (language, detectors)
    with _lock:
        if key in _analyzers:
            return _analyzers[key], ()
        from presidio_analyzer import AnalyzerEngine, RecognizerRegistry

        from wama.common.backends.manager import backend_instance_for_key
        from wama.common.privacy.recognizers import (
            BackendRecognizer, BlankNlpEngine, pattern_recognizers,
        )
        nlp = BlankNlpEngine([language])
        nlp.load()
        registry = RecognizerRegistry(supported_languages=[language])
        for recognizer in pattern_recognizers(language):
            registry.add_recognizer(recognizer)
        unavailable = []
        for model_key in detectors:
            try:
                registry.add_recognizer(BackendRecognizer(backend_instance_for_key(model_key),
                                                          model_key, language))
            except Exception as e:
                logger.warning("[privacy] détecteur %s écarté : %s", model_key, e)
                unavailable.append(model_key)
        analyzer = AnalyzerEngine(registry=registry, nlp_engine=nlp,
                                  supported_languages=[language])
        if not unavailable:
            _analyzers[key] = analyzer
        return analyzer, tuple(unavailable)


def _language_of(text: str, language: str) -> str:
    if language:
        return language.split('-')[0].lower()
    from wama.common.utils.text_language import detect_text_language
    return detect_text_language(text) or DEFAULT_LANGUAGE


def _merge(results) -> list:
    """Les passages qui se RECOUVRENT deviennent un seul : son étendue est l'union, son type celui
    du meilleur score, ses `sources` tous les détecteurs qui l'ont vu. Une donnée personnelle vue
    à moitié par un détecteur et entière par un autre est occultée entière."""
    spans = []
    for r in sorted(results, key=lambda r: (r.start, -r.end)):
        meta = r.recognition_metadata or {}
        source = meta.get('recognizer_name') or ''
        if spans and r.start < spans[-1]['end']:
            last = spans[-1]
            last['end'] = max(last['end'], r.end)
            last['sources'].add(source)
            if r.score > last['score']:
                last['score'], last['entity'] = r.score, r.entity_type
        else:
            spans.append({'start': r.start, 'end': r.end, 'entity': r.entity_type,
                          'score': r.score, 'sources': {source}})
    return spans


#: Un identifiant de CODE — minuscules, chiffres, au moins un souligné (`writer_01`,
#: `dev_sandbox`). Ni un numéro de pièce, ni de sécurité sociale, ni de compte n'a cette forme.
_CODE_IDENTIFIER = re.compile(r'[a-z][a-z0-9]*(?:_[a-z0-9]+)+')


def _is_code_identifier(text: str, span: dict) -> bool:
    """Un passage « identifiant » qui n'est qu'un nom de code (2026-11-01, fil Discord n° 43) : la
    tâche confiée à Claude Code est partie avec `[IDENTIFIANT_1]` à la place de `dev_sandbox`, puis
    `[IDENTIFIANT_2]` à la place de `writer_01` — Claude Code a dû deviner de quoi on lui parlait.
    Seul le type ID_NUMBER est concerné : un NOM écrit `jean_dupont` reste une personne."""
    return (span['entity'] == 'ID_NUMBER'
            and _CODE_IDENTIFIER.fullmatch(text[span['start']:span['end']].strip(' `\'"')) is not None)


#: Une date du CALENDRIER écrite en chiffres : ISO (`2026-11-07`) ou jour d'abord (`07/11/2026`).
_CALENDAR_DATE = re.compile(r'(\d{4})([-/.])(\d{2})\2(\d{2})|(\d{2})([-/.])(\d{2})\6(\d{4})')


def _is_calendar_date(text: str, span: dict) -> bool:
    """Un « téléphone » qui n'est qu'une date (2026-11-08) : la reconnaissance des numéros prenait
    `2026-11-07` pour un numéro (score 0,4), dans une phrase comme dans un nom de fichier — la
    tâche confiée à Claude Code est partie avec `model_…_[TÉLÉPHONE_1]_21-46.json`. Une date
    valide n'est jamais un numéro de téléphone ; elle reste une DATE pour qui la détecte comme
    telle (`DATE_TIME`)."""
    import datetime
    if span['entity'] != 'PHONE_NUMBER':
        return False
    m = _CALENDAR_DATE.fullmatch(text[span['start']:span['end']].strip())
    if not m:
        return False
    year, month, day = ((m.group(1), m.group(3), m.group(4)) if m.group(1)
                        else (m.group(8), m.group(7), m.group(5)))
    try:
        datetime.date(int(year), int(month), int(day))
    except ValueError:
        return False
    return True


def _detect_one(analyzer, text: str, language: str, entities, threshold) -> list:
    if not (text or '').strip():
        return []
    results = analyzer.analyze(text=text, language=language,
                               entities=list(entities) if entities else None,
                               score_threshold=threshold)
    return [s for s in _merge(results)
            if s['entity'] in ENTITY_TYPES and not _is_code_identifier(text, s)
            and not _is_calendar_date(text, s)]


def _detectors_for(language: str, detectors: Optional[Iterable[str]]) -> tuple:
    if detectors is not None:
        return tuple(sorted(detectors))
    return tuple(key for key, langs in installed_detectors() if not langs or language in langs)


def detect_segments(segments: List[str], language: str = '', *, entities=None, detectors=None,
                    threshold: Optional[float] = None) -> dict:
    """Le document de détections de segments de texte (un segment = une « frame »).

    `models` nomme les détecteurs qui ont RÉELLEMENT tourné, `unavailable` ceux qui étaient choisis
    et n'ont pas pu se charger : à l'appelant de décider s'il peut s'en passer (la porte de
    l'assistant, non)."""
    from wama.common.utils import detections
    language = _language_of(' '.join(segments[:3]), language)
    chosen = _detectors_for(language, detectors)
    analyzer, unavailable = _analyzer(language, chosen)
    doc = detections.new_document(media='text', width=0, height=0, frame_count=len(segments),
                                  engine='presidio',
                                  models=[k for k in chosen if k not in unavailable],
                                  classes=sorted(entities or ENTITY_TYPES))
    doc['language'] = language
    doc['unavailable'] = list(unavailable)
    for index, segment in enumerate(segments):
        found = _detect_one(analyzer, segment, language, entities, threshold)
        detections.add(doc, index, [detections.text_span(start=s['start'], end=s['end'],
                                                         label=s['entity'], conf=s['score'],
                                                         sources=s['sources'])
                                    for s in found])
    doc.pop('_index', None)
    return doc


def detect(text: str, language: str = '', **kwargs) -> dict:
    """Le document de détections d'un texte (un seul segment)."""
    return detect_segments([text], language, **kwargs)


def occult_segment(text: str, spans: list, language: str = DEFAULT_LANGUAGE) -> str:
    """Le texte d'UN segment, chaque passage remplacé par son libellé entre crochets — par
    l'anonymiseur de Presidio, un opérateur `replace` par type (le réglage écrit le 2026-10-17)."""
    if not spans:
        return text
    from presidio_anonymizer import AnonymizerEngine
    from presidio_anonymizer.entities import OperatorConfig, RecognizerResult
    results = [RecognizerResult(entity_type=d['label'], start=d['span'][0], end=d['span'][1],
                                score=float(d.get('conf', 1.0))) for d in spans]
    operators = {entity: OperatorConfig('replace', {'new_value': label_for(entity, language)})
                 for entity in {d['label'] for d in spans}}
    return AnonymizerEngine().anonymize(text=text, analyzer_results=results,
                                        operators=operators).text


def detect_file(path, language: str = '', ocr=None, **kwargs) -> dict:
    """Le document de détections d'un FICHIER (PDF, DOCX, TXT) : ses segments lus par la couche
    texte commune (`common/utils/document_text`), un segment par « frame ». `ocr` : les lignes
    lues par l'étape OCR (`ocr_process.read_ocr_file`) — un scan, le texte d'une image."""
    from wama.common.utils.document_text import read_segments
    return detect_segments(read_segments(path, ocr=ocr), language, **kwargs)


def occult_file(path, out_path, doc: dict, language: str = '', ocr=None) -> dict:
    """Le fichier réécrit SUR PLACE, chaque passage du document (corrigé ou non) remplacé par son
    libellé — la forme d'origine conservée (`document_text.write_replacements`). `ocr` : le MÊME
    qu'à la détection (les index des segments en dépendent).

    Puis la CONTRE-ÉPREUVE (revue d'opus du 2026-10-17) : le fichier produit est RELU, et tout
    passage d'origine qui s'y trouve encore est rendu dans `remaining` — le même nom ailleurs, non
    détecté, ou un passage que le format n'a pas su atteindre. Rend `{'path', 'remaining'}` ;
    à l'appelant de ne pas livrer un fichier dont `remaining` n'est pas vide sans le dire. Elle
    relit la couche texte du fichier produit, sans OCR : un passage lu sur un scan y est effacé
    avec ses pixels, et le relire demanderait un second OCR."""
    from wama.common.utils.document_text import read_segments, write_replacements
    segments = read_segments(path, ocr=ocr)
    language = language or doc.get('language') or DEFAULT_LANGUAGE
    replacements, passages = {}, set()
    for frame in doc.get('frames') or []:
        index = int(frame['i'])
        for d in frame.get('d') or []:
            if 'span' not in d:
                continue
            start, end = d['span']
            replacements.setdefault(index, []).append((start, end, label_for(d['label'], language)))
            passage = segments[index][start:end].strip()
            if len(passage) >= 3:
                passages.add(passage)
    write_replacements(path, out_path, replacements, ocr=ocr)
    produced = '\n'.join(read_segments(out_path))
    return {'path': str(out_path), 'remaining': sorted(p for p in passages if p in produced)}


def occult(text: str, doc: dict, language: str = '', segment: int = 0) -> str:
    """Le texte occulté d'après le document (corrigé ou non) : les passages de son segment."""
    language = language or doc.get('language') or DEFAULT_LANGUAGE
    spans = [d for f in doc.get('frames') or [] if int(f['i']) == segment
             for d in f.get('d') or [] if 'span' in d]
    return occult_segment(text, spans, language)
