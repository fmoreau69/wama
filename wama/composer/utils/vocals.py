"""La VOIX d'une génération du composer — chantée ou instrumentale (réglage `vocals`, 2026-10-04).

Question de Fabien : « l'utilisateur peut-il préciser chant / pas de chant dans le prompt ? Ou
vaut-il mieux un réglage instrumental ↔ chanson ? » Le prompt le dit déjà par sa FORME : des
paroles balisées (`[Verse]`, `[Chorus]`… — `tagged_lyrics`) se chantent. Mais une phrase
(« une chanson sur la mer ») ne le dit pas, depuis que le LLM n'écrit plus de paroles (contrats
musicaux du même jour). D'où trois valeurs, et un seul lieu qui les lit :

  • `auto`         — chanté si le prompt porte des paroles balisées, instrumental sinon ;
  • `instrumental` — rien n'est chanté, même si le prompt porte des paroles ;
  • `song`         — chanté ; sans paroles fournies, elles sont ÉCRITES (skill `composer-lyrics`),
                     dans une langue que le modèle chante. Seul cas où un LLM écrit des paroles.

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


def wants_vocals(mode, text) -> bool:
    """La voix est-elle voulue pour ce prompt ? `auto` : oui s'il porte des paroles balisées."""
    mode = normalize(mode)
    if mode != AUTO:
        return mode == SONG
    from wama.common.backends.music_generation_base import tagged_lyrics
    return bool(tagged_lyrics(text or '')[1])


def sings(model_key) -> bool:
    """Le modèle chante-t-il ? Capacité DÉCLARÉE au catalogue ; absente = non."""
    if not model_key:
        return False
    try:
        from wama.model_manager.models import AIModel
        row = AIModel.objects.filter(model_key=model_key).only('capabilities').first()
        return bool(row and (row.capabilities or {}).get(CAPABILITY))
    except Exception:
        return False


def singing_models(task) -> list:
    """Clés des modèles de `task` qui chantent — candidats du tirage quand la voix est voulue."""
    from wama.common.utils.auto_model import candidates_with
    return candidates_with(CAPABILITY, True, capabilities__task=task)


def lyrics_language(model_key, user) -> str:
    """La langue des paroles à ÉCRIRE : celle du profil si le modèle la chante, sinon l'anglais
    s'il le chante, sinon sa première langue déclarée."""
    from wama.common.utils.lang_routing import model_languages
    from wama.common.utils.prompt_pipeline import _user_lang
    caps, mtype = None, None
    try:
        from wama.model_manager.models import AIModel
        row = AIModel.objects.filter(model_key=model_key).only('capabilities', 'model_type').first()
        if row:
            caps, mtype = row.capabilities, row.model_type
    except Exception:
        pass
    langs = model_languages(caps, mtype)
    mine = _user_lang(user)
    if '*' in langs or mine in langs:
        return mine
    return 'en' if 'en' in langs else next((lang for lang in langs if lang != '*'), 'en')


def prepare_prompt(mode, text, model_key, *, user=None, console=None) -> str:
    """Le prompt de CE lancement selon la voix voulue et le modèle qui le joue.

    Rend le texte à confier à la pipeline (qui traduit/enrichit la description et garde les
    paroles telles quelles). Ne lève jamais : faute de paroles écrites, la pièce reste
    instrumentale, et c'est dit."""
    from wama.common.backends.music_generation_base import tagged_lyrics
    say = console or (lambda *a, **k: None)
    caption, lyrics = tagged_lyrics(text or '')
    mode = normalize(mode)
    if not wants_vocals(mode, text):
        if lyrics:
            say("🎼 Voix : instrumental — les paroles du prompt ne sont pas chantées.")
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
        return text
    language = lyrics_language(model_key, user)
    from wama.common.utils.app_metadata import write_lyrics_for
    written = write_lyrics_for('composer', 'prompt', caption, language=language)
    if not written:
        say("⚠️ Paroles non écrites (LLM local indisponible) : le morceau est instrumental.")
        return text
    say(f"✍️ Paroles écrites en « {language} » — pour les modifier, recopiez-les sous la "
        f"description du prompt :\n{written}")
    return f"{caption}\n\n{written}" if caption else written
