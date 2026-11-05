"""
Les FAITS VÉRIFIABLES d'un texte, et ceux qu'aucune source ne porte (2026-11-05).

Le défaut mesuré : la card 399 du Writer, un CV rédigé à partir d'un PDF, porte « Né en avril
2002 » — une date que le PDF ne contient pas. Ce n'est pas le modèle de rédaction qui l'a
inventée : c'est l'ASSISTANT, en écrivant la consigne de l'outil `add_to_writer_01` à partir du
texte que le reader venait d'extraire (fil du 2026-11-01, `tool_steps` du tour). Le Writer l'a
ensuite fidèlement mise en page.

Même nature que les contrôles de sortie de l'assistant (`assistant_engine._strip_unsourced_urls`,
`_unsourced_job_ids`) : *un contrôle, pas une consigne* — ce qu'un modèle écrit se confronte à
ce que les sources de son tour portent. Ici, ce qui se vérifie sans modèle et sans ambiguïté :
  • une ANNÉE (1900-2099) — une date de naissance, une période d'emploi ;
  • une ADRESSE ÉLECTRONIQUE ;
  • un NUMÉRO DE TÉLÉPHONE (9 chiffres et plus ; comparé sur ses 9 derniers chiffres, pour qu'un
    « +33 6 … » retrouve le « 06 … » de la source).
Un nom, un lieu, une phrase reformulée ne s'y vérifient pas : la brique ne prétend pas juger le
fond, elle attrape ce qu'une invention a de plus coûteux — une donnée personnelle fausse.

Brique PURE (aucun import Django) : la boucle de l'assistant l'appelle avant chaque outil qui
ÉCRIT, et toute rédaction qui garde ses sources sous la main peut l'appeler de même.
"""
from __future__ import annotations

import re

_YEAR = re.compile(r'(?<!\d)(?:19|20)\d{2}(?!\d)')
_EMAIL = re.compile(r"(?<![\w.+-])[\w.+-]+@[\w-]+(?:\.[\w-]+)*\.[A-Za-z]{2,}(?![\w-])")
_PHONE = re.compile(r'(?<![\w+])\+?\d(?:[ .\-]?\d){8,14}(?!\w)')
#: Les chiffres qui identifient un numéro, quel que soit son indicatif.
PHONE_KEY_DIGITS = 9


def checkable_facts(text: str) -> list:
    """Les faits vérifiables de `text`, dans leur ordre d'apparition, sans doublon :
    `[(nature, tel qu'écrit)]`, nature ∈ {'year', 'email', 'phone'}."""
    text = str(text or '')
    found = []
    phones = list(_PHONE.finditer(text))
    for match in phones:
        found.append((match.start(), 'phone', match.group(0)))
    for match in _EMAIL.finditer(text):
        found.append((match.start(), 'email', match.group(0)))
    inside_phone = [(m.start(), m.end()) for m in phones]
    for match in _YEAR.finditer(text):
        if not any(a <= match.start() < b for a, b in inside_phone):
            found.append((match.start(), 'year', match.group(0)))
    out = []
    for _pos, kind, value in sorted(found):
        if (kind, value) not in out:
            out.append((kind, value))
    return out


def _digits(value: str) -> str:
    return re.sub(r'\D', '', value)


def unsourced_facts(text: str, sources) -> list:
    """Les faits vérifiables de `text` qu'AUCUNE source ne porte (`sources` : un texte ou une
    liste de textes), tels qu'écrits dans `text`. Vide quand tout est sourcé."""
    joined = '\n'.join(sources) if isinstance(sources, (list, tuple)) else str(sources or '')
    years = set(_YEAR.findall(joined))
    emails = {e.lower() for e in _EMAIL.findall(joined)}
    digits = _digits(joined)
    missing = []
    for kind, value in checkable_facts(text):
        if kind == 'year':
            known = value in years
        elif kind == 'email':
            known = value.lower() in emails
        else:
            known = _digits(value)[-PHONE_KEY_DIGITS:] in digits
        if not known:
            missing.append(value)
    return missing
