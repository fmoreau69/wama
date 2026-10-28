"""
Détecteur de DONNÉES PERSONNELLES GLiNER2 — `fastino/gliner2-privacy-filter-PII-multi` (2026-10-28).

GLiNER2 (205 M de paramètres) affiné sur 42 types de données personnelles, 7 langues (en, fr, es,
de, it, pt, nl). Vocabulaire OUVERT : on lui NOMME les types à chercher, il conditionne sur eux —
c'est la décision D2 du 2026-10-17 (« le GLiNER le plus large »), confrontée à la recherche du
2026-10-28 (`ROADMAP §16.4bis`). Rappel élevé, précision faible selon l'éditeur (0,35 sur SPY,
il sur-détecte les noms) : il entre dans une UNION où d'autres détecteurs le complètent, et une
mesure WAMA réglera ses seuils.

Librairie `gliner2` (distincte de `gliner`), chargée depuis le dossier local — `checkpoint_file`
ne va au Hub que pour un identifiant, jamais pour un dossier. Les fichiers sont DÉCLARÉS
(`GLINER2_FILES`) et posés par le pilote `files` ; la ligne de catalogue vit dans
`model_registry._discover_pii_models`.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Optional

from .pii_detection_base import PIIDetectionBackend

logger = logging.getLogger(__name__)

HF_REPO = 'fastino/gliner2-privacy-filter-PII-multi'
#: Commit du dépôt au 2026-10-28 (dernière modification le 2026-09-28).
HF_REVISION = '1cb4166094dc58fa8d836429f060d6c95f62b495'
MODEL_KEY = f'huggingface:{HF_REPO}'


def _hub(path: str) -> dict:
    return {'source': 'huggingface', 'repo': HF_REPO, 'revision': HF_REVISION, 'file': path}


GLINER2_FILES = [
    {'path': 'config.json', 'size': 252,
     'sha256': '164f17362bcf9d114067d3465e7374bfdd79ce6b605acb745de5a49dabb9595c',
     'origin': _hub('config.json')},
    {'path': 'encoder_config/config.json', 'size': 895,
     'sha256': 'f27dd63cc43a248d2566f0b6ad7a115db353676ce0561dcbca45bac766464c1a',
     'origin': _hub('encoder_config/config.json')},
    {'path': 'tokenizer.json', 'size': 16020604,
     'sha256': 'f6df10ec83bea993035b2dd7c39345a3d4fcf23421c2adb6cb4ffc1e6d1bc4b5',
     'origin': _hub('tokenizer.json')},
    {'path': 'tokenizer_config.json', 'size': 711,
     'sha256': '233beed1f1095cccfc7907cde31a8d90a0c6aa4fdfaf6493f8e55fd162e81ae6',
     'origin': _hub('tokenizer_config.json')},
    {'path': 'model.safetensors', 'size': 1228421964,
     'sha256': '0280f6f39f6012da50b6640bad438d9b7e763a1b0102094115d1b710c4dd79b6',
     'origin': _hub('model.safetensors')},
]

LANGUAGES = ['de', 'en', 'es', 'fr', 'it', 'nl', 'pt']
#: Seuil de la carte du modèle. À régler par type sur une mesure WAMA (la carte conseille de le
#: relever pour `person`, sur-détecté).
DEFAULT_THRESHOLD = 0.5
#: Au-delà, découpage en morceaux qui se chevauchent (`extract_entities_long`).
LONG_TEXT_CHARS = 2000


def model_folder() -> Path:
    """Le dossier du modèle (`settings.MODEL_PATHS['nlp']['gliner2_pii']`)."""
    from django.conf import settings
    return Path(settings.MODEL_PATHS['nlp']['gliner2_pii'])


def model_installed() -> bool:
    from wama.model_manager.services.model_installer import declared_files_present
    return declared_files_present(model_folder(), GLINER2_FILES)


class Gliner2PIIBackend(PIIDetectionBackend):
    """GLiNER2-PII — extraction d'entités à vocabulaire ouvert, sur les types déclarés."""

    ENGINE = 'gliner2'
    name = 'gliner2-pii'
    display_name = 'GLiNER2-PII'
    description = ("Détecteur de données personnelles à vocabulaire ouvert (42 types, 7 langues), "
                   "GLiNER2 de Fastino.")
    REQUIRED_PACKAGES = ['gliner2', 'torch', 'transformers']
    PIP_PACKAGES = ['gliner2']
    PIP_NO_DEPS = True
    recommended_vram_gb = 1.5

    #: Types du MODÈLE (sa carte en liste 42) → vocabulaire commun ; seuls ceux-là lui sont
    #: demandés. TUS : `state_or_region`, `country` (trop larges pour désigner quelqu'un),
    #: `document_date`, `expiration_date`, `transaction_date` (dates de document, pas de personne).
    ENTITY_MAP = {
        'person': 'PERSON', 'full_name': 'PERSON', 'first_name': 'PERSON',
        'middle_name': 'PERSON', 'last_name': 'PERSON',
        'date_of_birth': 'DATE_TIME', 'sensitive_date': 'DATE_TIME',
        'email': 'EMAIL_ADDRESS', 'phone_number': 'PHONE_NUMBER',
        'address': 'LOCATION', 'street_address': 'LOCATION', 'city': 'LOCATION',
        'postal_code': 'LOCATION',
        'government_id': 'ID_NUMBER', 'national_id_number': 'ID_NUMBER',
        'passport_number': 'ID_NUMBER', 'drivers_license_number': 'ID_NUMBER',
        'license_number': 'ID_NUMBER', 'tax_id': 'ID_NUMBER', 'tax_number': 'ID_NUMBER',
        'username': 'ID_NUMBER', 'account_id': 'ID_NUMBER', 'sensitive_account_id': 'ID_NUMBER',
        'bank_account': 'ID_NUMBER', 'account_number': 'ID_NUMBER', 'routing_number': 'ID_NUMBER',
        'iban': 'IBAN_CODE',
        'payment_card': 'CREDIT_CARD', 'card_number': 'CREDIT_CARD', 'card_expiry': 'CREDIT_CARD',
        'card_cvv': 'CREDIT_CARD',
        'ip_address': 'IP_ADDRESS',
        'password': 'SECRET', 'secret': 'SECRET', 'api_key': 'SECRET', 'access_token': 'SECRET',
        'recovery_code': 'SECRET',
    }

    def __init__(self):
        super().__init__()
        self._model = None

    def load(self, model: Optional[str] = None) -> bool:
        if self._model is not None:
            return True
        folder = model_folder()
        if not model_installed():
            raise RuntimeError(f"GLiNER2-PII : fichiers absents de {folder} — installer "
                               f"{MODEL_KEY} par la route (model manager, `pull_model`).")
        import torch
        from gliner2 import GLiNER2
        device = 'cuda' if torch.cuda.is_available() else 'cpu'
        self._model = GLiNER2.from_pretrained(str(folder), map_location=device)
        self._model.to(device)
        self._model.eval()
        self._loaded = True
        self._current_model = HF_REPO
        logger.info("[GLiNER2-PII] chargé sur %s", device)
        return True

    def unload(self) -> None:
        self._model = None
        self._loaded = False
        self._current_model = None
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass

    def detect_entities(self, model_id: str, text: str, language: str,
                        entities: Optional[List[str]] = None,
                        threshold: Optional[float] = None) -> List[dict]:
        if not self._loaded:
            self.load(model_id)
        if not (text or '').strip():
            return []
        labels = [lab for lab, entity in self.ENTITY_MAP.items()
                  if not entities or entity in entities]
        if not labels:
            return []
        threshold = DEFAULT_THRESHOLD if threshold is None else threshold
        extract = (self._model.extract_entities_long if len(text) > LONG_TEXT_CHARS
                   else self._model.extract_entities)
        result = extract(text, labels, threshold=threshold, include_confidence=True,
                         include_spans=True)
        out = []
        for label, found in ((result or {}).get('entities') or {}).items():
            entity = self.ENTITY_MAP.get(label)
            if entity is None:
                continue
            for item in found or []:
                start, end = item.get('start'), item.get('end')
                if start is None or end is None or not (0 <= start < end <= len(text)):
                    continue
                out.append({'start': int(start), 'end': int(end), 'entity': entity,
                            'score': round(float(item.get('confidence', threshold)), 4)})
        return sorted(out, key=lambda f: (f['start'], f['end']))
