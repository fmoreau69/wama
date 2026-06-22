"""
Routing de langue (ROADMAP §10.B) — décide s'il faut traduire l'entrée/sortie d'un run modèle.

Principe : si le modèle gère la langue → rentrer DIRECTEMENT (pas de MT en chaîne). Sinon, un
traducteur fait le pont (en amont pour les entrées textuelles, en aval pour les sorties texte).
La décision est pilotée par `AIModel.capabilities['languages']` (la métadonnée déjà construite),
avec repli par type de modèle. Produit aussi une `reason` lisible pour la TRANSPARENCE pré-lancement.

Langues = codes courts (ex. 'fr', 'en'). Marqueur `'*'` = multilingue (toutes langues).
Médias non-textuels : `has_text_input`/`has_text_output=False` (ex. image en entrée du describer,
image en sortie de l'imager) → pas de traduction sur ce côté.
"""
from __future__ import annotations

# Repli par type de modèle quand `capabilities['languages']` est absent.
_TYPE_LANG_DEFAULT = {
    'diffusion': ['en'],   # générateurs image/vidéo : prompts en anglais
    'upscaling': ['en'],
}


def model_languages(capabilities, model_type=None):
    """Langues gérées par un modèle : capabilities['languages'], sinon repli type, sinon '*'."""
    langs = (capabilities or {}).get('languages')
    if langs:
        return list(langs)
    if model_type in _TYPE_LANG_DEFAULT:
        return list(_TYPE_LANG_DEFAULT[model_type])
    return ['*']  # inconnu → supposé multilingue (on tente en direct, signalé dans la raison)


def _handles(langs, lang):
    return '*' in langs or lang in langs


def resolve_language_routing(model_langs, input_lang=None, output_lang=None,
                             has_text_input=True, has_text_output=True):
    """
    Décide la traduction entrée/sortie pour un run.

    Retourne {direct, input_translate, input_pivot, output_translate, output_source,
              model_languages, languages_known, reason}.
    `reason` = texte lisible pour l'avis de transparence pré-lancement.
    """
    langs = list(model_langs or ['*'])
    known = bool(langs) and langs != ['*'] or '*' in langs  # '*' compte comme "connu = multilingue"
    multilingual = '*' in langs
    # Pivot que le modèle accepte (préférer l'anglais).
    if _handles(langs, 'en'):
        pivot = 'en'
    else:
        pivot = next((l for l in langs if l != '*'), 'en')

    in_tr = bool(has_text_input and input_lang and not _handles(langs, input_lang))
    out_tr = bool(has_text_output and output_lang and not _handles(langs, output_lang))
    direct = not in_tr and not out_tr

    parts = []
    if in_tr:
        parts.append(f"entrée {input_lang}→{pivot} (le modèle ne gère pas « {input_lang} »)")
    if out_tr:
        parts.append(f"sortie {pivot}→{output_lang} (le modèle ne gère pas « {output_lang} »)")
    if direct:
        reason = ("direct — le modèle est multilingue" if multilingual
                  else f"direct — le modèle gère {langs}")
        if not _handles(langs, '*') and not langs:
            reason = "direct — capacités de langue inconnues (tentative en direct)"
    else:
        reason = "traduction auto : " + " ; ".join(parts) + " (qualité possiblement réduite)"

    return {
        'direct': direct,
        'input_translate': in_tr,
        'input_pivot': pivot if in_tr else None,
        'output_translate': out_tr,
        'output_source': pivot if out_tr else None,
        'model_languages': langs,
        'languages_known': known,
        'reason': reason,
    }


def routing_for_model(capabilities, model_type, input_lang=None, output_lang=None,
                      has_text_input=True, has_text_output=True):
    """Raccourci : résout les langues du modèle puis le routing en un appel."""
    return resolve_language_routing(
        model_languages(capabilities, model_type),
        input_lang=input_lang, output_lang=output_lang,
        has_text_input=has_text_input, has_text_output=has_text_output,
    )
