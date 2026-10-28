"""Les DÉTECTEURS de l'union que Presidio orchestre (ROADMAP §16.4bis, 2026-10-28).

Trois familles, toutes des recognizers Presidio :
  • `BackendRecognizer` — l'ADAPTATEUR d'un backend du contrat `pii-detection` (un modèle du
    catalogue, chargé par la porte commune `backend_instance_for_key`). C'est la réconciliation
    proposée par opus le 2026-10-17 : le backend garde le modèle (catalogue, gouverneur), Presidio
    l'orchestre. Un détecteur de plus = une ligne de catalogue et son backend, rien ici.
  • les motifs à CHIFFRE DE CONTRÔLE de Presidio (adresses électroniques, cartes, IBAN, IP,
    téléphones), instanciés pour chaque langue — Presidio ne les déclare qu'en anglais ;
  • les identifiants FRANÇAIS, que Presidio ne fournit pas (ses détecteurs nationaux couvrent
    18 pays, pas la France) : NIR (clé 97), SIREN et SIRET (Luhn).

`BlankNlpEngine` : Presidio exige un moteur de langue, par défaut un modèle spaCy qu'il TÉLÉCHARGE
au premier usage (`spacy.cli.download`) — ce que la route d'installation interdit. La détection des
noms est l'affaire des modèles de l'union ; le moteur ne sert qu'à découper les mots (contexte des
motifs) : `spacy.blank(langue)`, intégré à spaCy, sans aucun poids.
"""
from __future__ import annotations

import logging
from typing import List, Optional

from presidio_analyzer import EntityRecognizer, Pattern, PatternRecognizer, RecognizerResult
from presidio_analyzer.nlp_engine import SpacyNlpEngine
from presidio_analyzer.predefined_recognizers import (
    CreditCardRecognizer, EmailRecognizer, IbanRecognizer, IpRecognizer, PhoneRecognizer,
)

logger = logging.getLogger(__name__)

#: Régions des numéros de téléphone reconnus (`phonenumbers`) : l'Europe de l'Ouest d'abord.
PHONE_REGIONS = ('FR', 'BE', 'CH', 'LU', 'GB', 'DE', 'ES', 'IT', 'PT', 'NL', 'US', 'CA')


class BlankNlpEngine(SpacyNlpEngine):
    """Le moteur de langue de Presidio SANS modèle : `spacy.blank` par langue (découpage seul)."""

    def __init__(self, languages):
        super().__init__(models=[{'lang_code': lang, 'model_name': f'blank:{lang}'}
                                 for lang in languages])

    def load(self) -> None:
        import spacy
        self.nlp = {m['lang_code']: spacy.blank(m['lang_code']) for m in self.models}

    def get_supported_entities(self) -> List[str]:
        return []


class OfflineEmailRecognizer(EmailRecognizer):
    """Le détecteur d'adresses de Presidio, validé HORS LIGNE : `tldextract.extract` va chercher la
    liste des suffixes de domaine sur Internet au premier appel ; la liste EMBARQUÉE de la
    librairie suffit (`suffix_list_urls=()`, le même geste que `inference`)."""

    _extractor = None

    def validate_result(self, pattern_text: str):
        if OfflineEmailRecognizer._extractor is None:
            import tldextract
            OfflineEmailRecognizer._extractor = tldextract.TLDExtract(suffix_list_urls=())
        return OfflineEmailRecognizer._extractor(pattern_text).fqdn != ''


def _luhn(digits: str) -> bool:
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch)
        if i % 2:
            n = n * 2 - 9 if n > 4 else n * 2
        total += n
    return total % 10 == 0


def _only_digits(text: str) -> str:
    return ''.join(ch for ch in text if ch.isdigit())


class FrNirRecognizer(PatternRecognizer):
    """Numéro d'inscription au répertoire (« numéro de sécurité sociale ») : 13 caractères + clé.
    Clé = 97 − (numéro mod 97), la Corse (2A/2B) comptant 19/18 (règle de l'INSEE)."""

    PATTERNS = [Pattern('fr_nir', r'\b[12378]\s?\d{2}\s?\d{2}\s?(?:\d{2}|2[AaBb])\s?\d{3}\s?\d{3}\s?\d{2}\b', 0.5)]
    CONTEXT = ['sécurité sociale', 'securite sociale', 'nir', 'insee', 'social security', 'ssn']

    def __init__(self, supported_language: str):
        super().__init__(supported_entity='FR_NIR', patterns=self.PATTERNS, context=self.CONTEXT,
                         supported_language=supported_language, name='FrNirRecognizer')

    def validate_result(self, pattern_text: str):
        compact = ''.join(pattern_text.split()).upper()
        body, key = compact[:-2], compact[-2:]
        body = body.replace('2A', '19').replace('2B', '18')
        if not (body.isdigit() and key.isdigit()):
            return False
        return 97 - int(body) % 97 == int(key)


class FrSirenRecognizer(PatternRecognizer):
    """SIREN (9 chiffres, clé de Luhn) — l'identifiant d'une entreprise, qui désigne une personne
    quand elle exerce en nom propre."""

    PATTERNS = [Pattern('fr_siren', r'\b\d{3}\s?\d{3}\s?\d{3}\b', 0.3)]
    CONTEXT = ['siren', 'rcs', 'entreprise', 'company']

    def __init__(self, supported_language: str):
        super().__init__(supported_entity='FR_SIREN', patterns=self.PATTERNS, context=self.CONTEXT,
                         supported_language=supported_language, name='FrSirenRecognizer')

    def validate_result(self, pattern_text: str):
        digits = _only_digits(pattern_text)
        return len(digits) == 9 and _luhn(digits)


class FrSiretRecognizer(PatternRecognizer):
    """SIRET (14 chiffres : SIREN + établissement, clé de Luhn)."""

    PATTERNS = [Pattern('fr_siret', r'\b\d{3}\s?\d{3}\s?\d{3}\s?\d{5}\b', 0.4)]
    CONTEXT = ['siret', 'établissement', 'etablissement']

    def __init__(self, supported_language: str):
        super().__init__(supported_entity='FR_SIRET', patterns=self.PATTERNS, context=self.CONTEXT,
                         supported_language=supported_language, name='FrSiretRecognizer')

    def validate_result(self, pattern_text: str):
        digits = _only_digits(pattern_text)
        return len(digits) == 14 and _luhn(digits)


def pattern_recognizers(language: str) -> list:
    """Les détecteurs par MOTIFS d'une langue : ceux de Presidio (instanciés pour elle) et les
    identifiants français (valables dans un texte de toute langue)."""
    return [
        OfflineEmailRecognizer(supported_language=language),
        CreditCardRecognizer(supported_language=language),
        IbanRecognizer(supported_language=language),
        IpRecognizer(supported_language=language),
        PhoneRecognizer(supported_language=language, supported_regions=PHONE_REGIONS),
        FrNirRecognizer(language), FrSirenRecognizer(language), FrSiretRecognizer(language),
    ]


class BackendRecognizer(EntityRecognizer):
    """L'adaptateur d'un modèle `pii-detection` du catalogue dans l'analyseur de Presidio."""

    def __init__(self, backend, model_key: str, language: str):
        self.backend, self.model_key = backend, model_key
        super().__init__(supported_entities=sorted(set(backend.ENTITY_MAP.values())),
                         name=model_key, supported_language=language)

    def load(self) -> None:
        """Le modèle se charge par le backend, au premier appel (`detect_entities`)."""

    def analyze(self, text: str, entities: List[str], nlp_artifacts=None) -> List[RecognizerResult]:
        from wama.common.utils.model_keys import backend_model_id
        found = self.backend.detect_entities(model_id=backend_model_id(self.model_key), text=text,
                                             language=self.supported_language,
                                             entities=entities or None)
        return [RecognizerResult(entity_type=f['entity'], start=f['start'], end=f['end'],
                                 score=f['score'],
                                 recognition_metadata={
                                     RecognizerResult.RECOGNIZER_NAME_KEY: self.name,
                                     RecognizerResult.RECOGNIZER_IDENTIFIER_KEY: self.id})
                for f in found]
