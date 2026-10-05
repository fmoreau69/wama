"""La LANGUE d'un texte — pendant écrit de `spoken_language` (2026-10-05).

Premier besoin : les PAROLES d'une chanson (composer). Elles ne passent jamais par le LLM et ne
sont jamais traduites (`app_metadata`, `lyrics`) ; il faut donc savoir si le modèle CHANTE leur
langue — jusque-là on la supposait égale à celle du profil, ce qui avertissait à tort d'anglais
tapé par un francophone et taisait du français confié à un modèle anglais.

Moteur : `langid` (BSD, déclaré en dépendance directe ce jour — il n'était qu'une dépendance de
`boson_multimodal`). Un identifiant LOCAL à la brique (`LanguageIdentifier`, probabilités
normalisées) : `langid.classify` tient un état de module partagé, que d'autres réglages pourraient
borner. Les balises de section (`[Verse]`, `[Chorus]`…) sont retirées avant de juger ; un verdict
peu sûr (< `MIN_CONFIDENCE`) vaut « inconnue » — un faux « espagnol » sur « la la la » ferait
pire qu'aucun avis. Ne lève jamais.
"""
import re

#: En dessous, la langue est dite INCONNUE (mesuré : 0,71 « es » sur « la la la » balisé).
MIN_CONFIDENCE = 0.9
#: Trop court pour juger (quelques mots ne portent pas une langue).
MIN_CHARS = 20

_identifier = None
_TAG_LINE = re.compile(r'^\s*\[[^\]]*\]\s*$', re.MULTILINE)


def _model():
    global _identifier
    if _identifier is None:
        from langid.langid import LanguageIdentifier, model
        _identifier = LanguageIdentifier.from_modelstring(model, norm_probs=True)
    return _identifier


def detect_text_language(text) -> str:
    """Code ISO 639-1 de la langue du texte (`fr`, `en`, `zh`…), ou '' si elle n'est pas sûre."""
    plain = _TAG_LINE.sub('', str(text or '')).strip()
    if len(plain) < MIN_CHARS:
        return ''
    try:
        language, confidence = _model().classify(plain)
    except Exception:
        return ''
    return language if confidence >= MIN_CONFIDENCE else ''
