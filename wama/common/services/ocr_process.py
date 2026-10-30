"""Le process « OCR des pages scannées » d'une card — commun aux apps qui réécrivent un document
en gardant sa forme (2026-10-29, décision de Fabien : « une étape optionnelle, son interrupteur
s'adapte à l'entrée »). Le Translator d'abord ; le domaine document de l'Anonymizer ensuite.

Le patron est celui du process « Sortie » (`output_process`) : une brique, une GLU au contrat du
squelette, que l'app déclare comme un process OPTIONNEL à interrupteur (`ProcessSpec(degree=
'optional', toggle=…)`) — l'interrupteur propose sa valeur d'après le fichier d'entrée
(`Param.default_from`, propriété `needs_ocr` : un PDF sans couche texte le coche).

    PROCESSES = {'ocr': ocr_step('source_document', 'ocr_file'), 'translate': …}
    # et dans la glu du process suivant :
    translate_document(…, ocr=read_ocr_file(item, 'ocr_file'))

Ce que la brique tient pour l'app : le moteur est TIRÉ parmi les modèles d'OCR dont le moteur
rend la place du texte (`supports_text_positions`, `OCRBackend.read_lines`) ; seules les pages
sans couche texte sont lues (`document_text.read_pages_without_text`) ; leurs lignes sont rangées
dans un JSON sur la card, que le process suivant passe à la couche texte (`ocr=`). Un document
qui porte son texte partout ne coûte rien : le process le dit et ne range rien.
"""
import json
import logging
import os

logger = logging.getLogger(__name__)

#: Clé du process dans le pipeline d'une app, et libellé de sa ligne sur la card.
OCR_KEY = 'ocr'
OCR_LABEL = 'OCR des pages scannées'


def positioned_ocr_keys() -> list:
    """Les clés de catalogue des modèles d'OCR dont le MOTEUR rend la place du texte
    (`supports_text_positions`) — ceux que ce process peut employer."""
    from wama.common.backends.manager import backend_for_key
    from wama.model_manager.models import AIModel
    keys = AIModel.objects.filter(capabilities__task='ocr').values_list('model_key', flat=True)
    out = []
    for key in sorted(keys):
        try:
            if getattr(backend_for_key(key), 'supports_text_positions', False):
                out.append(key)
        except Exception:
            continue
    return out


def ocr_step(source_field: str, output_field: str):
    """La GLU du process OCR, au contrat du squelette (`glu(item, ctx) -> dict`).

    `source_field` : le champ fichier du document d'entrée ; `output_field` : le champ fichier où
    ranger les lignes lues (un JSON `{'model', 'pages': {page: page du contrat}}`)."""

    def step(item, ctx):
        from wama.common.utils.auto_model import resolve_model_choice
        from wama.common.utils.document_text import pages_without_text, read_pages_without_text
        source = getattr(item, source_field, None)
        if not source:
            raise ValueError("OCR : aucun document d'entrée")
        path = source.path
        pages = pages_without_text(path)
        if not pages:
            ctx.console("OCR : chaque page porte son texte — rien à lire")
            return {'fields': {output_field: None}, 'label': 'Aucune page sans texte',
                    'output_fingerprint': 'no-page'}
        candidates = positioned_ocr_keys()
        if not candidates:
            raise RuntimeError("OCR : aucun modèle d'OCR installé ne rend la place du texte "
                               "(docTR, par exemple)")
        key = resolve_model_choice('auto', spec={'task': 'ocr'}, candidates=candidates,
                                   item=item, fallback=candidates[0]) or candidates[0]
        ctx.console(f"OCR : {len(pages)} page(s) sans texte, moteur {key}")
        ctx.ensure_model(key)
        from wama.common.backends.manager import backend_instance_for_key
        backend = backend_instance_for_key(key, user=getattr(item, 'user', None))
        ctx.progress(10, f"Lecture de {len(pages)} page(s) scannée(s)…")
        read = read_pages_without_text(path, backend.read_lines)
        rel_path, abs_path = ctx.output_place('.json', source_name=os.path.basename(path) + '.ocr')
        with open(abs_path, 'w', encoding='utf-8') as out:
            json.dump({'model': key, 'pages': {str(k): v for k, v in read.items()}}, out,
                      ensure_ascii=False)
        lines = sum(len(p.get('lines') or []) for p in read.values())
        ctx.progress(100, 'Terminé')
        return {'fields': {output_field: rel_path}, 'models': [key], 'output_ref': rel_path,
                'label': f"{len(read)} page(s) lue(s), {lines} ligne(s)"}

    return step


def read_ocr_file(item, field: str):
    """Les lignes rangées par le process OCR (`{page: page du contrat}`), à passer à la couche
    texte (`ocr=`) — None si le process n'a rien rangé (interrupteur décoché, document natif)."""
    value = getattr(item, field, None)
    if not value:
        return None
    try:
        with open(value.path, encoding='utf-8') as source:
            return (json.load(source) or {}).get('pages') or None
    except (OSError, ValueError):
        logger.warning("[OCR] lignes illisibles sur %s #%s", type(item).__name__,
                       getattr(item, 'pk', '?'), exc_info=True)
        return None
