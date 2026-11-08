"""La VOIX d'une génération du composer — chantée ou instrumentale (réglage `vocals`, 2026-10-04).

Question de Fabien : « l'utilisateur peut-il préciser chant / pas de chant dans le prompt ? Ou
vaut-il mieux un réglage instrumental ↔ chanson ? » Le prompt le dit déjà par sa FORME : des
paroles balisées (`[Verse]`, `[Chorus]`… — `tagged_lyrics`) se chantent. Mais une phrase
(« une chanson sur la mer ») ne le dit pas, depuis que le LLM n'écrit plus de paroles (contrats
musicaux du même jour). D'où trois valeurs, et un seul lieu qui les lit :

  • `auto`         — chanté si le prompt ou la card porte des paroles, instrumental sinon ;
  • `instrumental` — rien n'est chanté, même si le prompt porte des paroles ;
  • `song`         — chanté ; sans paroles fournies, elles sont ÉCRITES (skill `composer-lyrics`),
                     dans une langue que le modèle chante, et GARDÉES sur la card (`lyrics`) pour
                     être corrigées et rejouées. Seul cas où un LLM écrit des paroles.

Qui chante : la capacité `supports_vocals` du MODÈLE, déclarée par son manifeste — jamais un nom
de modèle ici. Sous « auto », le tirage ne retient que les modèles qui chantent quand la voix est
voulue ; un modèle CHOISI qui ne chante pas reçoit la description seule, et la console le dit.
"""
AUTO = 'auto'
INSTRUMENTAL = 'instrumental'
SONG = 'song'
CHOICES = [(AUTO, 'Auto'), (INSTRUMENTAL, 'Instrumental'), (SONG, 'Chanson')]
VALUES = tuple(v for v, _ in CHOICES)

#: La capacité du catalogue qui dit qu'un modèle CHANTE des paroles (vocabulaire commun).
CAPABILITY = 'supports_vocals'


def normalize(value) -> str:
    value = str(value or '').strip()
    return value if value in VALUES else AUTO


def has_lyrics(text, stored_lyrics='') -> bool:
    """Des paroles sont-elles DONNÉES ? Balisées dans le prompt, ou posées sur la card (`lyrics`).
    Une lecture, trois lecteurs : la voix voulue sous « auto » (ci-dessous), l'étape « Écrire les
    paroles » (`function_specs._lyrics_to_write`) et le champ qu'une écoute remplit
    (`tasks._lyrics_field_open`) — 2026-11-08."""
    from wama.common.backends.music_generation_base import tagged_lyrics
    return bool(tagged_lyrics(text or '')[1]) or bool(str(stored_lyrics or '').strip())


def wants_vocals(mode, text, stored_lyrics='') -> bool:
    """La voix est-elle voulue ? `auto` : oui si le prompt porte des paroles balisées, ou si la
    card en porte (`lyrics`, posées par l'utilisateur ou écrites à un lancement précédent)."""
    mode = normalize(mode)
    if mode != AUTO:
        return mode == SONG
    return has_lyrics(text, stored_lyrics)


def sings(model_key) -> bool:
    """Le modèle chante-t-il ? Capacité DÉCLARÉE au catalogue ; absente = non."""
    from wama.common.utils.model_capabilities import catalog_capabilities
    return bool(catalog_capabilities(model_key).get(CAPABILITY))


def singing_models(task) -> list:
    """Clés des modèles de `task` qui chantent — candidats du tirage quand la voix est voulue."""
    from wama.common.utils.auto_model import candidates_with
    return candidates_with(CAPABILITY, True, capabilities__task=task)


#: La langue des paroles à écrire — remontée au commun le 2026-11-08 (le bouton du réglage et
#: l'étape du pipeline posent la même question). Réexportée ici pour ses appelants.
from wama.common.utils.app_metadata import lyrics_language  # noqa: E402,F401


def as_lyrics(text) -> str:
    """Des paroles posées sur la card, sous la forme que lisent les moteurs : sans balise, elles
    deviennent un couplet (`[Verse]`) — sinon la découpe les prendrait pour une description."""
    text = str(text or '').strip()
    if not text:
        return ''
    return text if text.lstrip().startswith('[') else f"[Verse]\n{text}"


def prepare_prompt(mode, text, model_key, *, stored_lyrics='', user=None, console=None) -> str:
    """Le prompt de CE lancement selon la voix voulue et le modèle qui le joue.

    Les paroles viennent du prompt (balisées sous la description — elles priment), sinon de la
    card (`lyrics`). Le texte rendu va à la pipeline, qui traduit/enrichit la description et garde
    les paroles telles quelles. Ne lève jamais.
    ⚠ Elles ne s'ÉCRIVENT plus ici (2026-11-08, décision de Fabien) : c'est l'étape « Écrire les
    paroles » (`write_lyrics`), visible sur la card et AVANT la partition composée, ou le bouton du
    réglage. « Chanson » sans paroles ici = cette étape n'a rien écrit : instrumental, et c'est dit."""
    from wama.common.backends.music_generation_base import tagged_lyrics
    say = console or (lambda *a, **k: None)
    caption, lyrics = tagged_lyrics(text or '')
    stored = as_lyrics(stored_lyrics)
    from_prompt = bool(lyrics)
    if from_prompt and stored:
        say("🎤 Paroles du prompt chantées — celles de la card sont ignorées.")
    lyrics = lyrics or stored
    mode = normalize(mode)
    if not wants_vocals(mode, text, stored):
        if lyrics:
            say("🎼 Voix : instrumental — les paroles ne sont pas chantées.")
            return caption
        return text
    if not sings(model_key):
        from .model_choice import label_of
        name = label_of(model_key)
        if lyrics:
            say(f"🎤 {name} ne chante pas : les paroles sont ignorées, le morceau est instrumental "
                f"(choisir un modèle qui chante, ou « auto »).")
            return caption
        say(f"🎤 {name} ne chante pas : le morceau est instrumental.")
        return text
    if lyrics:
        return text if from_prompt else _with(sung_in(caption, lyrics), lyrics)
    say("⚠️ Chanson demandée sans paroles (l'étape « Écrire les paroles » n'en a pas écrit) : le "
        "morceau est instrumental.")
    return text


def sung_in(caption, lyrics) -> str:
    """La description, en tête la LANGUE des paroles de la card (2026-11-03) : c'est là que YuE2 la
    lit — « Put genre, instruments, vocal character, language, and tempo in `style` »
    (`vendor/yue/docs/generation.md`), et un cover ne la reçoit de nulle part ailleurs. Langue
    détectée (`detect_text_language`), nommée par la table commune. Inchangée si la langue n'est
    pas sûre, ou si la description la nomme déjà."""
    from wama.common.tts.constants import LANGUAGE_NAMES_EN
    from wama.common.utils.text_language import detect_text_language
    name = LANGUAGE_NAMES_EN.get(detect_text_language(lyrics))
    if not name or name.lower() in str(caption or '').lower():
        return caption
    return f"{name}, {caption}" if caption else name


def _with(caption, lyrics) -> str:
    return f"{caption}\n\n{lyrics}" if caption else lyrics
