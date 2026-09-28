"""
Rendre un texte en parole — UNE chaîne pour la synthèse ET pour son aperçu (2026-09-28).

POURQUOI. L'aperçu de voix avait sa propre chaîne (vue SSE + cache + découpage maison +
concaténation des WAV côté navigateur, en-têtes compris) : il n'entendait donc pas ce que la
synthèse produirait — texte non nettoyé, modèle « auto » envoyé tel quel au service, options
Higgs ignorées, pas de limite de segment par moteur (CARD_DESIGN §11.11 Étape 3, note sur
l'aperçu). Le worker et l'aperçu appellent désormais les mêmes fonctions ; seul le TEXTE diffère
(tout le document / ses `PREVIEW_WORDS` premiers mots).

Ce qui reste hors d'ici, par nature : la POLITIQUE d'attente d'un service pas encore chaud (le
worker réessaie par Celery, l'aperçu échoue vite) et le nettoyage du texte, fait en amont par la
brique commune `text_for_speech` (l'extracteur de document l'appelle pour la synthèse).

⚠ Candidate au commun (`common/tts/`) dès qu'une 2ᵉ app l'adopte : l'avatarizer fait UN appel
au service sans découpage, donc la même troncature que kokoro au-delà de ~400 caractères. Elle
vit ici tant qu'elle dépend de `local_model_name` (registre des backends du synthesizer).
"""
import logging
import os
import re
import shutil

from wama.common.tts.service_client import tts_via_service

logger = logging.getLogger(__name__)

#: Longueur maximale d'un segment envoyé au service, par moteur (nom NU, cf. `local_model_name`).
#: kokoro : EspeakG2P (FR/ES/IT/PT) tronque les textes longs — rester court.
CHUNK_LIMITS = {  # wama:redondance-ok — limites de segment par moteur (info nouvelle)
    'bark': 200,
    'kokoro': 400,
    'higgs-audio': 500,
    'coqui-xtts': 1000,
}
DEFAULT_CHUNK_CHARS = 800
#: Silence posé entre deux segments assemblés (ms).
CHUNK_GAP_MS = 200
#: Taille d'un aperçu : assez pour entendre la voix, assez court pour répondre en secondes.
PREVIEW_WORDS = 50


def resolve_tts_model(model, voice_preset, quality_intent, fallback):
    """Le modèle RÉEL d'un rendu : « auto » est tiré ici (capacités + VRAM libre du moment).

    Une voix CLONÉE exige un moteur qui clone : « auto » reste proposable dans l'UI (jamais
    grisé), la contrainte est portée au tirage (décision du 13/09).
    """
    from wama.common.utils.auto_model import is_auto, read_quality_intent, resolve_model_choice
    if not is_auto(model):
        return model
    from wama.common.tts.voice_refs import is_cloned_voice
    requires = ['supports_cloning'] if is_cloned_voice(voice_preset) else None
    return resolve_model_choice(
        model, app_id='synthesizer', quality_intent=read_quality_intent(quality_intent),
        requires=requires, fallback=fallback)


def chunk_limit(model):
    """Longueur maximale d'un segment pour ce modèle.

    ⚠ La table est indexée par le nom NU du moteur ; `model` porte la clé catalogue entière
    depuis la migration 0018 — sans cette traduction elle ne correspondait JAMAIS (800 pour
    tous, kokoro compris, qui tronque au-delà de 400 ; mesuré le 13/09).
    """
    from wama.synthesizer.backends import local_model_name
    return CHUNK_LIMITS.get(local_model_name(model), DEFAULT_CHUNK_CHARS)


def split_text_into_chunks(text, max_chars):
    """Découpe un texte en segments d'au plus `max_chars`, aux limites de phrase."""
    sentences = re.split(r'(?<=[.!?])\s+', text)
    chunks = []
    current = ''
    for sentence in sentences:
        if len(current) + len(sentence) + 1 <= max_chars:
            current += sentence + ' '
        else:
            if current:
                chunks.append(current.strip())
            current = sentence + ' '
    if current:
        chunks.append(current.strip())
    return chunks


def preview_text(text):
    """Les `PREVIEW_WORDS` premiers mots — suivis de « ... » si le texte continue."""
    words = (text or '').split()
    head = ' '.join(words[:PREVIEW_WORDS])
    return head + ('...' if len(words) > PREVIEW_WORDS else '')


def render_speech(text, output_path, *, model, language, voice_preset, speaker_wav=None,
                  multi_speaker=False, scene_description='', speed=1.0, pitch=1.0,
                  on_segment=None, console=None, read_timeout=None):
    """Rend `text` en WAV : segments par moteur → service TTS → assemblage → vitesse/hauteur.

    `output_path` reçoit l'assemblage ; le fichier FINAL (vitesse/hauteur appliquées) est rendu
    — c'est `output_path` lui-même quand il n'y a rien à transformer, un `<nom>_processed.wav`
    sinon. L'appelant supprime les deux.
    `on_segment(index, total)` est appelé avant chaque segment (progression) ; `console(msg)`
    reçoit les messages d'étape. Lève `TTSServiceLoadingError` (service pas encore chaud) et
    `RuntimeError` (toute autre indisponibilité) : la politique appartient à l'appelant.
    """
    from pydub import AudioSegment

    from .audio_processor import process_audio_output

    say = console or (lambda _m: None)
    max_chars = chunk_limit(model)
    if len(text) > max_chars:
        say('Texte long détecté, division en segments...')
        chunks = split_text_into_chunks(text, max_chars)
    else:
        chunks = [text]
    say(f'Génération audio: {len(chunks)} segment(s) via service TTS...')

    extra = {} if read_timeout is None else {'read_timeout': read_timeout}
    chunk_files = []
    try:
        for i, chunk in enumerate(chunks):
            if on_segment:
                on_segment(i, len(chunks))
            say(f'Génération segment {i + 1}/{len(chunks)}...')
            chunk_files.append(tts_via_service(
                chunk, model, language=language, voice_preset=voice_preset,
                speaker_wav=speaker_wav, multi_speaker=multi_speaker,
                # La description de scène (Higgs) ouvre le dialogue : premier segment seulement.
                scene_description=scene_description if i == 0 else '',
                **extra))

        if len(chunk_files) == 1:
            shutil.move(chunk_files.pop(), output_path)
        else:
            say('Assemblage des segments audio...')
            combined = AudioSegment.empty()
            for chunk_file in chunk_files:
                combined += AudioSegment.from_wav(chunk_file)
                combined += AudioSegment.silent(duration=CHUNK_GAP_MS)
            combined.export(output_path, format='wav')
    finally:
        for chunk_file in chunk_files:
            try:
                os.remove(chunk_file)
            except OSError:
                pass

    say(f'Audio généré: {output_path}')
    return process_audio_output(output_path, speed=speed, pitch=pitch)
