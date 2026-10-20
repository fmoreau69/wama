"""Lire une CHARTE graphique pour en tirer un thème (chantier thèmes, étape 7, voie 2, 2026-10-20,
`ROADMAP §28`).

Fabien, 2026-10-19 : « fournir une charte graphique complète ? » ; le §28.7 : « le LLM lit les
valeurs dans le texte (comme la p. 7 de la charte UGE), un humain valide, le thème est partagé
selon la portée ».

Deux étages, et chacun fait ce qu'il sait faire :
  1. les RÈGLES relèvent les couleurs ÉCRITES dans le texte — hexadécimal `#rrggbb` et triplets
     RVB/RGB —, chacune avec ce qui la précède (`colour_candidates`). Rien n'est deviné ;
  2. le LLM choisit parmi CES couleurs la principale, propose un nom, la base (claire ou sombre)
     et la police (`propose`). La mise en page brouille l'ordre du texte — mesuré sur la charte
     UGE : « Couleur principale : » sort APRÈS la plupart des secondaires —, c'est pourquoi la
     proximité seule ne suffit pas. Une couleur qu'il rendrait sans l'avoir lue est refusée : il
     choisit, il n'invente pas. Sans LLM, ou s'il ne répond rien d'utilisable, les règles
     choisissent (le mot « principale » le plus proche, sinon la première couleur franche).

Un humain valide ensuite au Profil : la proposition n'est qu'une proposition. Seules les GRAINES
sont gardées (`common.UserTheme`) ; le bloc se génère (`theme_generator`)."""
from __future__ import annotations

import logging
import re

from wama.common.theme_generator import valid_font, valid_seed
from wama.common.theme_mirror import chroma, hex_of, rgb_of

logger = logging.getLogger(__name__)

#: Ce que le Profil accepte comme charte : les formats que lit `extract_batch_file_text`.
CHARTER_EXTENSIONS = ('.pdf', '.docx', '.txt', '.md')
#: Une charte de 36 pages pèse quelques Mo ; au-delà, ce n'est plus une charte.
MAX_CHARTER_BYTES = 40 * 1024 * 1024
#: Le texte que reçoit le LLM, au plus (les couleurs, elles, sont toutes relevées avant).
MAX_LLM_TEXT = 6000
#: Ce qui précède une couleur, gardé comme contexte (le LLM et l'humain le lisent).
CONTEXT_CHARS = 120

#: Six chiffres hexadécimaux, sauf s'ils ouvrent un code à huit (`#rrggbbaa`) ou un nombre plus long.
#: Le mot qui suit peut y être COLLÉ par l'extraction (`#ef7d00Couleur`) : son « C » n'en fait pas un
#: septième chiffre.
_HEX = re.compile(r'#([0-9a-fA-F]{6})(?![0-9a-fA-F]{2}\b)(?![0-9])')
_RGB = re.compile(r'\b(?:RVB|RGB)\b[\s:]*(\d{1,3})[^\d\n]{1,4}(\d{1,3})[^\d\n]{1,4}(\d{1,3})(?!\d)')
#: Le LIBELLÉ d'une couleur principale (« Couleur principale », « Primary colour »…), pas le mot
#: seul : « les principes de la charte », en page 2, n'en désigne aucune (mesuré sur la charte
#: UGE, le 2026-10-20 — les règles y prenaient le bleu nuit, première couleur de la page). Pas de
#: `\b` en tête : l'extraction du PDF COLLE le libellé au code qui le précède (`#ef7d00Couleur
#: principale`), et entre `0` et `C` il n'y a pas de frontière de mot.
_PRINCIPAL = re.compile(r'(?<![^\W\d_])(?:couleurs?|colou?rs?)\s+(?:principales?|primaires?|dominantes?|primary|main)\b'
                        r'|(?<![^\W\d_])(?:primary|main|brand)\s+colou?rs?\b', re.I)
_NAME_MAX = 96

SYSTEM_PROMPT = """You read a graphic charter (brand guidelines) extracted as plain text.
The text order may be scrambled by the page layout: a label like "Couleur principale" can appear
far from its colour.
You receive the list of colours FOUND in the text, each with the words written just before it.
Answer with ONE JSON object and nothing else:
{"name": "<the organisation or charter name, short>",
 "principal": "<the main/primary brand colour, copied EXACTLY from the list>",
 "base": "light" or "dark" (the background the charter mostly uses; "light" if unsure),
 "font": "<the main typeface name as written, or empty>"}
Rules: "principal" MUST be one of the listed colours; never invent a colour. Prefer the colour
the charter calls principal/primary/main; otherwise the most characteristic non-grey colour."""


def colour_candidates(text: str) -> list[dict]:
    """Les couleurs ÉCRITES dans `text`, dans l'ordre de leur première apparition, sans doublon :
    [{hex, at, context, count}]. Un triplet RVB/RGB donne son hexadécimal ; un triplet hors de
    0-255 n'est pas une couleur."""
    found = []
    for m in _HEX.finditer(text):
        found.append((m.start(), '#' + m.group(1).lower()))
    for m in _RGB.finditer(text):
        channels = [int(m.group(i)) for i in (1, 2, 3)]
        if all(0 <= c <= 255 for c in channels):
            found.append((m.start(), hex_of(channels)))
    by_hex = {}
    for at, colour in sorted(found):
        if colour in by_hex:
            by_hex[colour]['count'] += 1
            continue
        before = text[max(0, at - CONTEXT_CHARS):at]
        by_hex[colour] = {'hex': colour, 'at': at, 'count': 1,
                          'context': re.sub(r'\s+', ' ', before).strip()}
    return list(by_hex.values())


def labelled_principal(candidates: list[dict]) -> str:
    """La première couleur que son contexte IMMÉDIAT dit principale (« Couleur principale : … »
    dans les `CONTEXT_CHARS` qui la précèdent), ou ''. Un libellé lointain — un sommaire, une
    introduction — ne désigne aucune couleur."""
    return next((c['hex'] for c in candidates if _PRINCIPAL.search(c['context'])), '')


def rules_proposal(text: str, candidates: list[dict], fallback_name: str = '') -> dict:
    """Ce que proposent les RÈGLES seules : la couleur dite principale par son contexte, sinon la
    première couleur franche (chroma OKLCH ≥ 0,05), sinon la première relevée."""
    principal = labelled_principal(candidates)
    if not principal:
        vivid = [c['hex'] for c in candidates if chroma(rgb_of(c['hex'])) >= 0.05]
        principal = vivid[0] if vivid else (candidates[0]['hex'] if candidates else '')
    return {'name': clean_name(fallback_name), 'principal': principal, 'base': 'light', 'font': ''}


#: Où une charte nomme sa police : le LLM en reçoit les lignes qui suivent.
_TYPE = re.compile(r'typograph|typeface|police|font', re.I)


def llm_excerpt(text: str) -> str:
    """Ce que le LLM lit du document, au plus `MAX_LLM_TEXT` caractères : le début (le nom de
    l'organisation y est), puis ce qui suit chaque mention de la typographie. Les couleurs, elles,
    lui arrivent toutes par leur liste — une charte de 36 pages dépasse vite la limite, et la page
    des couleurs n'est pas la première."""
    parts = [text[:1500]]
    for m in _TYPE.finditer(text):
        parts.append(text[m.start():m.start() + 300])
    return re.sub(r'[ \t]+', ' ', '\n…\n'.join(parts))[:MAX_LLM_TEXT]


def clean_name(value) -> str:
    return re.sub(r'\s+', ' ', str(value or '')).strip()[:_NAME_MAX]


def _chat(messages):
    """L'appel au LLM local, par la porte commune (`llm_chat`, modèle tiré par le catalogue)."""
    from wama.common.utils.llm_utils import llm_chat
    return llm_chat(messages, provider='ollama', think=False, timeout=120, num_predict=400,
                    temperature=0.1)


def propose(text: str, candidates: list[dict], *, fallback_name: str = '', chat=None) -> dict:
    """La proposition à valider : {name, principal, base, font, reader, note}. `reader` dit qui a
    choisi — 'llm' ou 'rules' —, `note` pourquoi les règles ont pris la main."""
    rules = rules_proposal(text, candidates, fallback_name)
    if not candidates:
        return {**rules, 'reader': 'rules', 'note': "aucune couleur écrite dans le document"}
    hint = labelled_principal(candidates)
    listing = '\n'.join(f"- {c['hex']} (written after: \"{c['context']}\")"
                        + (" ← its label says principal" if c['hex'] == hint else '')
                        for c in candidates)
    messages = [{'role': 'system', 'content': SYSTEM_PROMPT},
                {'role': 'user', 'content': f"Colours found:\n{listing}\n\nCharter text (excerpts):\n"
                                            f"{llm_excerpt(text)}"}]
    try:
        out, err = (chat or _chat)(messages)
    except Exception as exc:
        out, err = None, str(exc)
    if err or not out:
        return {**rules, 'reader': 'rules', 'note': f"modèle de langue indisponible ({err or 'réponse vide'})"}
    from wama.common.utils.llm_utils import extract_json_from_llm
    answer = extract_json_from_llm(out) or {}
    principal = str(answer.get('principal') or '').strip().lower()
    if principal not in {c['hex'] for c in candidates}:
        return {**rules, 'reader': 'rules',
                'note': f"le modèle a rendu une couleur qui n'est pas dans la charte ({principal or '—'})"}
    font = clean_name(answer.get('font'))[:64]
    return {'name': clean_name(answer.get('name')) or rules['name'], 'principal': principal,
            'base': answer.get('base') if answer.get('base') in ('light', 'dark') else 'light',
            'font': font if valid_font(font) else '', 'reader': 'llm', 'note': ''}


def read_charter(path: str, *, fallback_name: str = '', chat=None) -> dict:
    """Une charte sur disque → {candidates, proposal}. Le texte vient de la brique commune
    `extract_batch_file_text` (PDF, docx, texte)."""
    from wama.common.utils.batch_parsers import extract_batch_file_text
    text = extract_batch_file_text(path)
    candidates = colour_candidates(text)
    return {'candidates': candidates,
            'proposal': propose(text, candidates, fallback_name=fallback_name, chat=chat)}


def check_seeds(name, base, accent, font) -> dict:
    """Les graines d'un thème de charte, VALIDÉES (`ValueError` sinon) — ce qu'une ligne
    `UserTheme` reçoit : rien de saisi n'entre tel quel dans une feuille."""
    name = clean_name(name)
    if not name:
        raise ValueError("Donnez un nom au thème.")
    if base not in ('light', 'dark'):
        raise ValueError(f"Base inconnue : {base!r}")
    if not valid_seed(accent):
        raise ValueError(f"Couleur invalide : {accent!r} (attendu : #rrggbb)")
    font = clean_name(font)
    if not valid_font(font):
        raise ValueError(f"Nom de police invalide : {font!r}")
    return {'name': name, 'base': base, 'accent': accent.lower(), 'font': font}
