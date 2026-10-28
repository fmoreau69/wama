"""
Détecteur de DONNÉES PERSONNELLES bardsai — `bardsai/eu-pii-anonimization-multilang-v3` (2026-10-28).

Classifieur de jetons ModernBERT (mmBERT-base, 307 M de paramètres), 37 types en BIO, les 24
langues officielles de l'UE. Servi par onnxruntime (export ONNX publié par l'auteur : FP32 sur la
carte, INT8 sur le processeur — même F1 annoncé, 0,980), sans torch sur ce chemin. Retenu par la
recherche du 2026-10-28 (`ROADMAP §16.4bis`) ; ses chiffres sont ceux de l'éditeur, une mesure
WAMA fera foi.

LE DÉCODEUR est celui que l'auteur publie avec le modèle (`pii_detector.py`, Apache-2.0, au commit
déclaré ci-dessous) et sur lequel portent tous ses scores — un argmax par jeton rendrait des
fragments de mots. Il est repris ici pas à pas, en numpy : fenêtres de 512 jetons qui se
chevauchent de 128, une étiquette par MOT (moyenne des probabilités de ses sous-jetons, masses B-
et I- réunies par type), fusion des mots voisins du même type sauf début d'entité, contrôles de
format (un lien ressemble à une URL, un téléphone a 5 chiffres, un identifiant 2), et toute adresse
électronique trouvée par motif est rendue comme telle.

Les fichiers sont DÉCLARÉS (`BARDSAI_FILES`) et posés par le pilote `files` de la route
d'installation ; la ligne de catalogue vit dans `model_registry._discover_pii_models`.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import List, Optional

import numpy as np

from .pii_detection_base import PIIDetectionBackend

logger = logging.getLogger(__name__)

HF_REPO = 'bardsai/eu-pii-anonimization-multilang-v3'
#: Commit du dépôt au 2026-10-28 (v3, publiée le 2026-10-27).
HF_REVISION = '091984b5fbce4c161abc4776ed0f4e3206e1b374'
MODEL_KEY = f'huggingface:{HF_REPO}'
WEIGHTS_GPU = 'onnx/model.onnx'
WEIGHTS_CPU = 'onnx/model_quantized.onnx'


def _hub(path: str) -> dict:
    return {'source': 'huggingface', 'repo': HF_REPO, 'revision': HF_REVISION, 'file': path}


BARDSAI_FILES = [
    {'path': 'config.json', 'size': 6415,
     'sha256': '9f34718817db63125b1dcd85b0b6923381ea7c443802675e81dd163d1f12b06c',
     'origin': _hub('config.json')},
    {'path': 'tokenizer.json', 'size': 34363188,
     'sha256': '609d8f4c067cd3950f88594c5a802616cea245823836ef5848ee4fc40aab5b6f',
     'origin': _hub('tokenizer.json')},
    {'path': 'tokenizer_config.json', 'size': 573,
     'sha256': '02055b886266b1a475bc324da83e273fe96e4974002f9d970f26e94aa73e5885',
     'origin': _hub('tokenizer_config.json')},
    {'path': WEIGHTS_GPU, 'size': 1230934625,
     'sha256': '5612139cb594bf524dd47e5fe0ade4d13ec018b556ab853c819e7cd0e9abdf6d',
     'origin': _hub(WEIGHTS_GPU)},
    {'path': WEIGHTS_CPU, 'size': 308593401,
     'sha256': '762c851fd948915cc40c5b226f0c8d19dd3a48064a171368fbc56ba97a8d1ce5',
     'origin': _hub(WEIGHTS_CPU)},
]

#: Les 24 langues officielles de l'UE (carte du modèle).
LANGUAGES = ['bg', 'cs', 'da', 'de', 'el', 'en', 'es', 'et', 'fi', 'fr', 'ga', 'hr', 'hu', 'it',
             'lt', 'lv', 'mt', 'nl', 'pl', 'pt', 'ro', 'sk', 'sl', 'sv']


def model_folder() -> Path:
    """Le dossier du modèle (`settings.MODEL_PATHS['nlp']['bardsai_pii']`)."""
    from django.conf import settings
    return Path(settings.MODEL_PATHS['nlp']['bardsai_pii'])


def model_installed() -> bool:
    from wama.model_manager.services.model_installer import declared_files_present
    return declared_files_present(model_folder(), BARDSAI_FILES)


# ── Le décodeur de l'auteur (pii_detector.py), en numpy ─────────────────────────────────────
_EMAIL = re.compile(r"(?<![\w.+-])[\w.+-]+@[\w-]+(?:\.[\w-]+)*\.[A-Za-z]{2,}(?![\w-])")
_URLISH = re.compile(r"(https?://|www\.|\w\.[a-z]{2,}\b|/\w)", re.I)
_WORD = re.compile(r"[^\s,;|\"<>()\[\]{}*^]+")
_ID_TYPES = ('PERSON_IDENTIFIER', 'BANK_ACCOUNT_IDENTIFIER', 'PAYMENT_CARD', 'ACCOUNT_IDENTIFIER',
             'DOCUMENT_IDENTIFIER', 'VEHICLE_IDENTIFIER')
MAX_LEN, STRIDE = 512, 128


def _plausible(text: str, start: int, end: int, label: str) -> bool:
    """Contrôle de format par type (étape 4 du décodeur)."""
    value = text[start:end]
    digits = sum(c.isdigit() for c in value)
    if label == 'IDENTIFYING_LINK':
        return bool(_URLISH.search(value))
    if label == 'PHONE_NUMBER':
        return digits >= 5
    if label in _ID_TYPES:
        return digits >= 2
    return True


#: Réglages du découpeur repris de `tokenizer_config.json` (les autres sont propres à transformers 5).
_TOKENIZER_KEYS = ('bos_token', 'eos_token', 'cls_token', 'sep_token', 'pad_token', 'mask_token',
                   'unk_token', 'padding_side', 'model_max_length', 'clean_up_tokenization_spaces')


def _tokenizer(folder: Path):
    """Le découpeur, construit sur `tokenizer.json`. Le dépôt déclare `tokenizer_class:
    TokenizersBackend`, une classe de transformers 5 que le venv (4.57.6) ne connaît pas
    (`AutoTokenizer` lève, mesuré le 2026-10-28) ; elle ne fait que charger ce `tokenizer.json`
    — `PreTrainedTokenizerFast` le fait aussi, avec les jetons spéciaux du fichier déclaré."""
    from transformers import PreTrainedTokenizerFast
    config = json.loads((folder / 'tokenizer_config.json').read_text(encoding='utf-8'))
    return PreTrainedTokenizerFast(tokenizer_file=str(folder / 'tokenizer.json'),
                                   **{k: config[k] for k in _TOKENIZER_KEYS if k in config})


class BardsaiPIIBackend(PIIDetectionBackend):
    """bardsai EU PII v3 — classifieur de jetons ONNX, décodage par mot de l'auteur."""

    ENGINE = 'onnxruntime'
    name = 'bardsai-pii'
    display_name = 'bardsai EU PII v3'
    description = ("Détecteur de données personnelles multilingue (24 langues de l'UE), "
                   "classifieur ModernBERT servi en ONNX.")
    REQUIRED_PACKAGES = ['onnxruntime', 'transformers']
    #: La distribution GPU, jamais `onnxruntime` processeur à côté (patch n°10).
    PIP_PACKAGES = ['onnxruntime-gpu', 'transformers']
    recommended_vram_gb = 1.5

    #: Étiquettes du modèle → vocabulaire commun. TUES (non déclarées) : `DATE_TIME` et `URL` (dates
    #: et adresses web GÉNÉRIQUES — la carte le dit : à écarter si l'on ne veut que des données
    #: personnelles), `FINANCIAL_AMOUNT`, `PROPER_NAME`, `DOCUMENT_REFERENCE`, `PERSON_ATTRIBUTE`,
    #: `PERSON_ROLE_OR_TITLE` — rien de cela ne désigne une personne à lui seul.
    ENTITY_MAP = {
        'PERSON_NAME': 'PERSON', 'PERSON_ALIAS': 'PERSON',
        'PERSON_IDENTIFIER': 'ID_NUMBER', 'DOCUMENT_IDENTIFIER': 'ID_NUMBER',
        'VEHICLE_IDENTIFIER': 'ID_NUMBER', 'DEVICE_IDENTIFIER': 'ID_NUMBER',
        'ACCOUNT_IDENTIFIER': 'ID_NUMBER', 'CONTACT_HANDLE': 'ID_NUMBER',
        'ORGANIZATION_IDENTIFIER': 'ID_NUMBER',
        'DATE_OF_BIRTH': 'DATE_TIME',
        'EMAIL_ADDRESS': 'EMAIL_ADDRESS', 'PHONE_NUMBER': 'PHONE_NUMBER',
        'POSTAL_ADDRESS': 'LOCATION', 'LOCATION': 'LOCATION', 'GEO_LOCATION': 'LOCATION',
        'IP_ADDRESS': 'IP_ADDRESS', 'IDENTIFYING_LINK': 'URL',
        'BANK_ACCOUNT_IDENTIFIER': 'IBAN_CODE',
        'PAYMENT_CARD': 'CREDIT_CARD', 'PAYMENT_CARD_SECURITY': 'CREDIT_CARD',
        'AUTH_SECRET': 'SECRET',
        'ORGANIZATION_NAME': 'ORGANIZATION',
        'HEALTH_DATA': 'SENSITIVE_DATA', 'BIOMETRIC_DATA': 'SENSITIVE_DATA',
        'ETHNIC_ORIGIN': 'SENSITIVE_DATA', 'POLITICAL_OPINION': 'SENSITIVE_DATA',
        'RELIGION_OR_BELIEF': 'SENSITIVE_DATA', 'SEXUAL_ORIENTATION': 'SENSITIVE_DATA',
        'TRADE_UNION_MEMBERSHIP': 'SENSITIVE_DATA', 'CRIMINAL_OFFENCE_DATA': 'SENSITIVE_DATA',
    }

    def __init__(self):
        super().__init__()
        self._session = None
        self._tokenizer = None
        self.execution_provider = None

    def load(self, model: Optional[str] = None) -> bool:
        if self._session is not None:
            return True
        folder = model_folder()
        if not model_installed():
            raise RuntimeError(f"bardsai PII : fichiers absents de {folder} — installer "
                               f"{MODEL_KEY} par la route (model manager, `pull_model`).")
        import onnxruntime as ort

        from wama.common.utils.onnx_utils import onnx_providers
        providers = onnx_providers()
        # FP32 sur la carte, INT8 sur le processeur (mêmes scores annoncés, quatre fois moins lourd).
        on_gpu = providers and providers[0] != 'CPUExecutionProvider'
        weights = folder / (WEIGHTS_GPU if on_gpu else WEIGHTS_CPU)
        options = ort.SessionOptions()
        options.log_severity_level = 3
        self._session = ort.InferenceSession(str(weights), sess_options=options,
                                             providers=providers)
        self.execution_provider = self._session.get_providers()[0]
        self._tokenizer = _tokenizer(folder)
        config = json.loads((folder / 'config.json').read_text(encoding='utf-8'))
        id2label = {int(k): v for k, v in config['id2label'].items()}
        self._labels = [id2label[i] for i in range(len(id2label))]
        self._types = sorted({lab.split('-', 1)[1] for lab in self._labels if lab != 'O'})
        index = {t: i for i, t in enumerate(self._types)}
        # Étiquette → type (dernière colonne = O), et masse « début d'entité » par étiquette.
        self._to_type = np.zeros((len(self._labels), len(self._types) + 1), dtype=np.float32)
        for i, lab in enumerate(self._labels):
            self._to_type[i, len(self._types) if lab == 'O' else index[lab.split('-', 1)[1]]] = 1
        self._is_begin = np.array([1.0 if lab.startswith(('B-', 'S-')) else 0.0
                                   for lab in self._labels], dtype=np.float32)
        self._loaded = True
        self._current_model = HF_REPO
        logger.info("[bardsai PII] chargé : %s sur %s", weights.name, self.execution_provider)
        return True

    def unload(self) -> None:
        self._session = None
        self._tokenizer = None
        self._loaded = False
        self._current_model = None

    def _char_probs(self, text: str):
        enc = self._tokenizer(text, return_offsets_mapping=True, truncation=True,
                              max_length=MAX_LEN, stride=STRIDE, return_overflowing_tokens=True,
                              padding=True, return_tensors='np')
        offsets = enc['offset_mapping']
        ids, mask = enc['input_ids'], enc['attention_mask']
        logits = self._session.run(None, {'input_ids': ids.astype(np.int64),
                                          'attention_mask': mask.astype(np.int64)})[0]
        logits = logits - logits.max(-1, keepdims=True)
        probs = np.exp(logits)
        probs /= probs.sum(-1, keepdims=True)
        n = len(text)
        acc = np.zeros((n, len(self._types) + 1), dtype=np.float32)
        count = np.zeros(n, dtype=np.float32)
        begin = np.zeros(n, dtype=np.float32)
        for w in range(probs.shape[0]):
            per_type, per_begin = probs[w] @ self._to_type, probs[w] @ self._is_begin
            for j, (s, e) in enumerate(offsets[w].tolist()):
                if e <= s or mask[w, j] == 0:
                    continue
                while s < e - 1 and text[s].isspace():   # les offsets BPE incluent l'espace
                    s += 1
                acc[s] += per_type[j]
                count[s] += 1
                begin[s] += per_begin[j]
        return acc, count, begin

    def _word_spans(self, text: str) -> list:
        acc, count, begin = self._char_probs(text)
        spans = []
        for m in _WORD.finditer(text):
            ws, we = m.start(), m.end()
            while ws < we and text[ws] in "([{<\"'«„":
                ws += 1
            while we > ws and text[we - 1] in ")]}>\"'».,;:!?":
                we -= 1
            if we <= ws:
                continue
            sel = count[ws:we] > 0
            if not sel.any():
                continue
            mean = acc[ws:we][sel].sum(0) / count[ws:we][sel].sum()
            k = int(mean.argmax())
            if k == len(self._types):
                continue
            first = int(np.nonzero(sel)[0][0])
            starts_entity = begin[ws + first] / max(count[ws + first], 1)
            label = self._types[k]
            if (spans and spans[-1][2] == label and text[spans[-1][1]:ws].strip(' ,-/.()') == ''
                    and '\n\n' not in text[spans[-1][1]:ws] and starts_entity < 0.5):
                spans[-1][1] = we
            else:
                spans.append([ws, we, label, float(mean[k])])
        return spans

    def detect_entities(self, model_id: str, text: str, language: str,
                        entities: Optional[List[str]] = None,
                        threshold: Optional[float] = None) -> List[dict]:
        if not self._loaded:
            self.load(model_id)
        if not (text or '').strip():
            return []
        spans = [s for s in self._word_spans(text) if _plausible(text, s[0], s[1], s[2])]
        emails = [(m.start(), m.end()) for m in _EMAIL.finditer(text)]
        if emails:
            spans = ([s for s in spans if not any(s[0] < b and a < s[1] for a, b in emails)]
                     + [[a, b, 'EMAIL_ADDRESS', 1.0] for a, b in emails])
        out = []
        for start, end, label, score in sorted(spans):
            entity = self.ENTITY_MAP.get(label)
            if entity is None or (entities and entity not in entities):
                continue
            if threshold is not None and score < threshold:
                continue
            out.append({'start': start, 'end': end, 'entity': entity,
                        'score': round(min(max(score, 0.0), 1.0), 4)})
        return out
