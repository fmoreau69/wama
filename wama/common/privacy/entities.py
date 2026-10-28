"""Le VOCABULAIRE COMMUN des données personnelles — les types qu'un détecteur rend et que
l'occultation remplace par leur libellé entre crochets (ROADMAP §16.4bis, décision du 2026-10-28).

POURQUOI ICI. Chaque détecteur parle sa langue : bardsai a ses 35 étiquettes, GLiNER2 rend celles
qu'on lui nomme, Presidio a les siennes. Sans un vocabulaire unique, l'union ne réunirait rien —
deux détecteurs qui voient la même personne la nommeraient différemment. Les clés sont celles de
Presidio (`PERSON`, `EMAIL_ADDRESS`…) : c'est lui qui orchestre l'union, ses détecteurs par motifs
les rendent déjà. Chaque backend déclare la correspondance de SES étiquettes vers ces clés
(`PIIDetectionBackend.ENTITY_MAP`) ; une étiquette qu'il ne déclare pas n'entre pas.

Le LIBELLÉ d'occultation suit la langue du texte (un document français porte « [PERSONNE] », un
document anglais « [PERSON] ») ; une langue sans libellé prend l'anglais.
"""

#: type → libellés d'occultation par langue (sans crochets ; `label_for` les pose).
ENTITY_TYPES = {
    'PERSON':        {'fr': 'PERSONNE',       'en': 'PERSON'},
    'EMAIL_ADDRESS': {'fr': 'EMAIL',          'en': 'EMAIL'},
    'PHONE_NUMBER':  {'fr': 'TÉLÉPHONE',      'en': 'PHONE'},
    'LOCATION':      {'fr': 'ADRESSE',        'en': 'ADDRESS'},
    'ORGANIZATION':  {'fr': 'ORGANISATION',   'en': 'ORGANIZATION'},
    'DATE_TIME':     {'fr': 'DATE',           'en': 'DATE'},
    'IBAN_CODE':     {'fr': 'IBAN',           'en': 'IBAN'},
    'CREDIT_CARD':   {'fr': 'CARTE_BANCAIRE', 'en': 'CREDIT_CARD'},
    'IP_ADDRESS':    {'fr': 'ADRESSE_IP',     'en': 'IP_ADDRESS'},
    'URL':           {'fr': 'URL',            'en': 'URL'},
    'ID_NUMBER':     {'fr': 'IDENTIFIANT',    'en': 'ID_NUMBER'},
    # Mots de passe, clés d'API, jetons : à occulter comme une donnée personnelle (ils ouvrent
    # l'accès à des comptes de personnes).
    'SECRET':        {'fr': 'SECRET',         'en': 'SECRET'},
    # Les CATÉGORIES PARTICULIÈRES de l'article 9 du RGPD (santé, origine, opinions, religion,
    # orientation sexuelle, syndicat, données biométriques) et les infractions (art. 10) : un
    # seul type, le libellé ne doit pas révéler ce qu'il cache.
    'SENSITIVE_DATA': {'fr': 'DONNÉE_SENSIBLE', 'en': 'SENSITIVE_DATA'},
    # Identifiants FRANÇAIS — aucun n'est fourni par Presidio (relevé du 2026-10-28) : ses
    # détecteurs nationaux couvrent 18 pays, pas la France.
    'FR_NIR':        {'fr': 'NIR',            'en': 'FR_SSN'},
    'FR_SIREN':      {'fr': 'SIREN',          'en': 'FR_SIREN'},
    'FR_SIRET':      {'fr': 'SIRET',          'en': 'FR_SIRET'},
}

DEFAULT_LANGUAGE = 'en'


def label_for(entity: str, language: str = DEFAULT_LANGUAGE) -> str:
    """Le libellé d'occultation `[…]` d'un type, dans la langue du texte. Un type hors
    vocabulaire est une ERREUR de l'appelant : aucun détecteur n'a le droit de le rendre."""
    labels = ENTITY_TYPES[entity]
    lang = (language or DEFAULT_LANGUAGE).split('-')[0].lower()
    return f"[{labels.get(lang) or labels[DEFAULT_LANGUAGE]}]"
