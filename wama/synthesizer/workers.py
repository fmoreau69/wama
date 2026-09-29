"""
WAMA Synthesizer - Celery Workers
Tâches de synthèse vocale avec TTS

All TTS generation is delegated to the TTS microservice (tts_service.py)
running on TTS_SERVICE_URL (default: http://localhost:8001).
"""

import os
import re
import unicodedata
import logging
from celery import shared_task
from pathlib import Path

from django.conf import settings
from django.core.cache import cache
from django.db import close_old_connections
from django.core.files.base import ContentFile

from .models import VoiceSynthesis
from wama.common.utils.console_utils import push_console_line
from .utils.text_extractor import extract_text_from_file
from .utils.speech_render import render_speech, resolve_tts_model

logger = logging.getLogger(__name__)

# Client du microservice TTS : brique COMMUNE (`common/tts/service_client.py`, extraite
# 2026-08-28 — cette implémentation en était la souche ; 4 exemplaires du même POST /tts
# vivaient dans le dépôt). Il est appelé par `utils/speech_render` ; la POLITIQUE de retry sur
# 503 « loading » reste ici (Celery).
from wama.common.tts.service_client import TTSServiceLoadingError


@shared_task(name='wama.synthesizer.download_voice_refs', ignore_result=False)
def download_voice_refs_task(force: bool = False):
    """
    Tâche Celery : télécharge les fichiers de voix de référence manquants
    selon VOICE_DOWNLOAD_CATALOG défini dans common/tts/voice_refs.py.
    """
    from wama.common.tts.voice_refs import download_missing_voice_refs
    results = download_missing_voice_refs(force=force)
    n_ok   = sum(1 for s in results.values() if s == 'downloaded')
    n_fail = sum(1 for s in results.values() if s == 'failed')
    logger.info(f"[download_voice_refs_task] {n_ok} téléchargées, {n_fail} échec(s)")
    return {'downloaded': n_ok, 'failed': n_fail, 'details': results}


def _set_progress(synthesis: VoiceSynthesis, value: int) -> None:
    """Met à jour la progression de la synthèse."""
    cache.set(f"synthesizer_progress_{synthesis.id}", value, timeout=3600)
    VoiceSynthesis.objects.filter(pk=synthesis.id).update(progress=value)


def _console(user_id: int, message: str, level: str = None) -> None:
    """Envoie un message dans la console de l'utilisateur."""
    try:
        if level is None:
            msg_lower = message.lower()
            if any(w in msg_lower for w in ['error', 'failed', '\u2717', 'erreur']):
                level = 'error'
            elif any(w in msg_lower for w in ['warning', 'attention']):
                level = 'warning'
            elif any(w in msg_lower for w in ['[debug]', '[parallel']):
                level = 'debug'
            else:
                level = 'info'
        push_console_line(user_id, message, level=level, app='synthesizer')
    except Exception:
        pass


def _during_preview(synthesis):
    """Aperçu « PENDANT » (brique COMMUNE preview_utils, `?side=during`, 2026-09-28) : l'audio
    déjà synthétisé, publié après chaque segment d'un texte long — on entend la synthèse
    GRANDIR. Même patron que l'enhancer et l'anonymizer : un fichier à nom fixe sous
    `output/partials/`, réécrit, servi avec `?v=` ; les pics d'onde (`waveform.compute_peaks`)
    l'accompagnent pour que le lecteur commun dessine l'onde sans décoder.
    Vitesse et hauteur sont appliquées au partiel : il s'entend comme le résultat.
    Rend le `on_partial` de `render_speech`."""
    from wama.common.utils.media_paths import get_app_media_path
    from wama.common.utils.preview_utils import publish_partial, publish_partial_peaks
    from wama.common.utils.waveform import compute_peaks
    from .utils.audio_processor import process_audio_output

    folder = Path(get_app_media_path('synthesizer', synthesis.user_id, 'output')) / 'partials'
    folder.mkdir(parents=True, exist_ok=True)
    raw = folder / f'during_{synthesis.id}_raw.wav'
    heard = folder / f'during_{synthesis.id}.wav'

    def _publish(audio, done, total):
        audio.export(str(raw), format='wav')
        final = process_audio_output(str(raw), speed=synthesis.speed, pitch=synthesis.pitch,
                                     output_path=str(heard))
        rel = os.path.relpath(final, settings.MEDIA_ROOT).replace('\\', '/')
        publish_partial('synthesizer', synthesis.id, f'{settings.MEDIA_URL}{rel}?v={done}')
        peaks, duration = compute_peaks(final, buckets=800, dtype='uint8', with_duration=True)
        if peaks:
            publish_partial_peaks('synthesizer', synthesis.id, peaks, duration=duration)
        _console(synthesis.user_id, f"Aperçu : {done}/{total} segment(s) à l'écoute")

    return _publish


def _clear_during(synthesis):
    """Fin de run (succès, échec, nouvelle tentative) : la face SORTIE prend le relais."""
    from wama.common.utils.media_paths import get_app_media_path
    from wama.common.utils.preview_utils import clear_partial
    clear_partial('synthesizer', synthesis.id)
    folder = Path(get_app_media_path('synthesizer', synthesis.user_id, 'output')) / 'partials'
    for name in (f'during_{synthesis.id}_raw.wav', f'during_{synthesis.id}.wav'):
        try:
            (folder / name).unlink()
        except OSError:
            pass


def _apply_output_format(synthesis):
    """Convert the synthesized WAV to the user-chosen output format (Phase 3).

    No-op when output_format is 'original'/empty or already WAV. Updates
    audio_output to point at the converted file.
    """
    fmt = (getattr(synthesis, 'output_format', '') or 'original').lower()
    if fmt in ('', 'original') or not synthesis.audio_output:
        return
    try:
        import os as _os
        from django.conf import settings as _settings
        from wama.converter.utils.inline_convert import apply_inline_conversion
        new_path = apply_inline_conversion(
            synthesis.audio_output.path, fmt,
            getattr(synthesis, 'output_quality', 'balanced') or 'balanced',
        )
        rel = _os.path.relpath(new_path, _settings.MEDIA_ROOT).replace('\\', '/')
        if rel != synthesis.audio_output.name:
            synthesis.audio_output.name = rel
            synthesis.save(update_fields=['audio_output'])
    except Exception as exc:
        logger.warning(f"[synthesizer] conversion format sortie échouée: {exc}")


@shared_task(bind=True, max_retries=60, default_retry_delay=10)
def synthesize_voice(self, synthesis_id: int):
    """
    Tâche principale de synthèse vocale.
    Delegates audio generation to the TTS microservice.

    Args:
        synthesis_id: ID de l'objet VoiceSynthesis

    Returns:
        dict: Résultat de la synthèse
    """
    close_old_connections()
    import time as _time
    _t0 = _time.time()   # pour l'apprentissage ETA (durée de traitement réelle)

    try:
        synthesis = VoiceSynthesis.objects.get(pk=synthesis_id)
    except VoiceSynthesis.DoesNotExist:
        logger.error(f"VoiceSynthesis {synthesis_id} not found")
        return {'ok': False, 'error': 'Synthesis not found'}

    # Garde anti-boucle-de-crash (brique COMMUNE) : message `redelivered` = worker mort
    # sans acquitter (freeze/panic machine) → ne PAS rejouer l'exécution qui l'a tué.
    # Un `self.retry()` émet un message NEUF (non redelivered) : les retries restent OK.
    from wama.common.utils.process_control import refuse_crash_redelivery
    if refuse_crash_redelivery(self, synthesis, error_field='error_message'):
        logger.warning(f"[synthesizer] Synthesis #{synthesis_id}: reprise après crash refusée — relancer manuellement.")
        return {'ok': False, 'error': 'crash_redelivery'}

    _set_progress(synthesis, 5)
    _console(synthesis.user_id, f"Synthèse vocale #{synthesis.id} démarrée")

    try:
        # Étape 1: Extraction du texte
        _console(synthesis.user_id, "Extraction du texte du fichier...")
        _set_progress(synthesis, 10)

        text_content = extract_text_from_file(synthesis.text_file.path)

        if not text_content or len(text_content.strip()) == 0:
            raise ValueError("Le fichier ne contient pas de texte valide")

        synthesis.text_content = text_content
        synthesis.update_metadata()

        _console(synthesis.user_id, f"Texte extrait: {synthesis.word_count} mots")
        _set_progress(synthesis, 20)

        # Choix AUTOMATIQUE du moteur (brique commune `auto_model`, 2026-09-02) : résolu
        # AU LANCEMENT — la VRAM libre du moment fait foi, jamais l'état à la création
        # (un batch résout chaque élément avec l'état GPU de son tour). Le domaine du
        # tirage est CELUI que le schéma déclare pour les options (`params.py`) ; la
        # prévision affichée sous le select était une photo, on dit ici le choix réel.
        # Le tirage vit dans `speech_render.resolve_tts_model`, que l'APERÇU appelle aussi.
        from wama.common.utils.auto_model import is_auto, read_quality_intent
        if is_auto(synthesis.tts_model):
            quality_intent = getattr(synthesis, 'quality_intent', None)
            synthesis.tts_model = resolve_tts_model(
                synthesis.tts_model, synthesis.voice_preset, quality_intent,
                fallback=VoiceSynthesis._meta.get_field('tts_model').get_default())
            synthesis.save(update_fields=['tts_model'])
            _console(synthesis.user_id,
                     f"Choix automatique du moteur → {synthesis.get_tts_model_display()} "
                     f"(capacités + VRAM libre au lancement, curseur qualité "
                     f"{read_quality_intent(quality_intent)}/100)")

        # Étape 2: Génération audio via le service TTS
        _console(synthesis.user_id, f"Envoi au service TTS (modèle: {synthesis.tts_model})...")
        _set_progress(synthesis, 30)

        # Créer le fichier de sortie temporaire
        output_dir = os.path.dirname(synthesis.text_file.path)
        temp_output = os.path.join(output_dir, f"synthesis_{synthesis.id}_temp.wav")

        # ── Ingest URL déclaratif (brique commune, VoiceSynthesis.WAMA_INGEST) : si
        # une source_url de voix de référence est posée sans fichier local, on la
        # matérialise ici.
        try:
            from wama.common.utils.source_ingest import ensure_local_input
            ensure_local_input(synthesis, console=lambda m: _console(synthesis.user_id, m))
        except Exception as exc:
            logger.warning(f"[synthesizer] ensure_local_input({synthesis.id}) : {exc}")

        # La voix de référence — UNE porte commune, décidée par la CAPACITÉ du moteur
        # (`speaker_wav_for`, common/tts/voice_refs). Le bloc qui vivait ici recopiait la
        # résolution ua_/cv_ de la brique et testait `tts_model == 'coqui-xtts'` — un test
        # MORT (la colonne porte la clé entière `synthesizer:coqui-xtts`), si bien que XTTS
        # partait sans voix et que le SERVICE la résolvait à la place de Django. Depuis le
        # 13/09 tout `speaker_wav` est résolu ICI (MEDIA_STORAGE_TIERING §9.4, marche 2).
        from wama.common.tts.voice_refs import speaker_wav_for
        speaker_wav = speaker_wav_for(
            synthesis.tts_model, synthesis.voice_preset, synthesis.user,
            reference_path=synthesis.voice_reference.path if synthesis.voice_reference else None,
            language=synthesis.language or '')

        # Segments par moteur → service TTS → assemblage → vitesse/hauteur : LA chaîne de
        # rendu (`utils/speech_render`), la même que celle de l'aperçu de voix.
        _set_progress(synthesis, 40)
        final_output = render_speech(
            text_content, temp_output,
            model=synthesis.tts_model, language=synthesis.language,
            voice_preset=synthesis.voice_preset, speaker_wav=speaker_wav,
            multi_speaker=getattr(synthesis, 'multi_speaker', False),
            scene_description=getattr(synthesis, 'scene_description', ''),
            speed=synthesis.speed, pitch=synthesis.pitch,
            on_segment=lambda i, n: _set_progress(synthesis, 40 + int(i / n * 35)),
            on_partial=_during_preview(synthesis),
            console=lambda m: _console(synthesis.user_id, m),
        )
        _clear_during(synthesis)
        _set_progress(synthesis, 85)

        # Étape 5: Sauvegarde du résultat
        _console(synthesis.user_id, "Sauvegarde du fichier audio...")
        _set_progress(synthesis, 90)

        with open(final_output, 'rb') as f:
            # Brique COMMUNE de nommage (2026-08-25). Le synthesizer est de la famille
            # FICHIER — il dérive du texte d'entrée — mais il lui manquait le mot de process :
            # `{stem}_{modèle}.wav` devient `{stem}_voice_{modèle}.wav`.
            # ⚠ Il NORMALISAIT les accents (« Réunion » → « Reunion ») ; la règle de la
            # famille FICHIER est que l'utilisateur retrouve SON nom, et le stockage Django
            # assainit déjà à l'écriture. Les accents sont donc préservés désormais.
            # ⚠ `item_id` est passé en repli : sans fichier texte (synthèse directe), la
            # brique bascule d'elle-même sur la famille PROMPT au lieu de produire un nom vide.
            from wama.common.utils.output_naming import compose_output_name
            audio_filename = compose_output_name(
                app='synthesizer', model=synthesis.tts_model,
                source_name=(synthesis.text_file.name or ''),
                item_id=synthesis.id, ext='.wav')
            synthesis.audio_output.save(audio_filename, ContentFile(f.read()))

        # Conversion de format inline (Phase 3) — si l'utilisateur a choisi un
        # format de sortie autre que WAV natif.
        _apply_output_format(synthesis)

        # Mettre à jour les propriétés audio
        _update_audio_properties(synthesis)

        # Nettoyage des fichiers temporaires
        for temp_file in [temp_output, final_output]:
            if os.path.exists(temp_file) and temp_file != synthesis.audio_output.path:
                try:
                    os.remove(temp_file)
                except OSError:
                    pass

        # Finalisation
        synthesis.status = 'SUCCESS'
        synthesis.processing_seconds = _time.time() - _t0
        synthesis.save(update_fields=['status', 'audio_output', 'processing_seconds'])

        # Apprentissage ETA : durée réelle ∝ longueur du texte (unit='char'), par modèle TTS.
        # Service-based (chargement non séparable) → total dans per_unit, load_seconds=None.
        try:
            from wama.model_manager.services.eta_estimator import record_run, make_key
            _txt = synthesis.text_content or ''
            if _txt:
                record_run(make_key('synthesizer', synthesis.tts_model),
                           size=len(_txt), unit='char',
                           process_seconds=_time.time() - _t0, load_seconds=None,
                           user=synthesis.user)
        except Exception:
            pass
        _set_progress(synthesis, 100)

        _console(synthesis.user_id, f"Synthèse #{synthesis.id} terminée ✓")
        try:
            from wama.common.utils.notifications import notify_job
            notify_job(getattr(synthesis, 'user', None), 'Synthesizer',
                       getattr(synthesis, 'name', '') or f"synthèse #{synthesis.id}", True)
        except Exception:
            pass

        return {
            'ok': True,
            'synthesis_id': synthesis.id,
            'audio_url': synthesis.audio_output.url,
            'duration': synthesis.duration_display,
            'word_count': synthesis.word_count,
        }

    except TTSServiceLoadingError as e:
        # TTS service is still starting — release the GPU worker and retry later.
        retry_num = self.request.retries + 1
        wait_msg = f"Service TTS en chargement, nouvelle tentative dans 10s ({retry_num}/60)..."
        logger.info(f"synthesize_voice #{synthesis_id}: {wait_msg}")
        synthesis.error_message = wait_msg
        synthesis.save(update_fields=['error_message'])
        _clear_during(synthesis)
        _console(synthesis.user_id, wait_msg, level='warning')
        try:
            raise self.retry(exc=e, countdown=10)
        except self.MaxRetriesExceededError:
            # 60 retries × 10s = 10 minutes without TTS service → give up
            synthesis.status = 'FAILURE'
            synthesis.error_message = "Service TTS non disponible après 10 minutes d'attente (60 tentatives)"
            synthesis.save(update_fields=['status', 'error_message'])
            _set_progress(synthesis, 0)
            _console(synthesis.user_id, "Erreur: service TTS non disponible après 10 minutes", level='error')
            return {'ok': False, 'error': str(e)}

    except Exception as e:
        logger.error(f"Error in synthesize_voice task: {str(e)}", exc_info=True)
        _clear_during(synthesis)
        synthesis.status = 'FAILURE'
        synthesis.error_message = str(e)
        synthesis.save(update_fields=['status', 'error_message'])
        _set_progress(synthesis, 0)
        _console(synthesis.user_id, f"Erreur synthèse #{synthesis.id}: {e}")
        try:
            from wama.common.utils.notifications import notify_job
            notify_job(getattr(synthesis, 'user', None), 'Synthesizer',
                       getattr(synthesis, 'name', '') or f"synthèse #{synthesis.id}", False, detail=str(e))
        except Exception:
            pass

        return {'ok': False, 'error': str(e)}



def _update_audio_properties(synthesis):
    """
    Met à jour les propriétés du fichier audio généré.
    """
    import subprocess
    import json
    import shutil

    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return

    try:
        result = subprocess.run(
            [
                ffprobe,
                "-v", "error",
                "-select_streams", "a:0",
                "-show_entries", "stream=duration,codec_name,sample_rate,channels",
                "-of", "json",
                synthesis.audio_output.path,
            ],
            check=True,
            capture_output=True,
            text=True,
        )

        data = json.loads(result.stdout or "{}")
        stream = (data.get("streams") or [{}])[0]

        duration = float(stream.get("duration") or 0)
        sample_rate = stream.get("sample_rate")
        codec = stream.get("codec_name")
        channels = int(stream.get("channels") or 0)

        # Format des propriétés
        props_parts = []
        if codec:
            props_parts.append(codec.upper())
        if sample_rate:
            props_parts.append(f"{int(sample_rate) / 1000:.1f} kHz")
        if channels == 1:
            props_parts.append("mono")
        elif channels == 2:
            props_parts.append("stéréo")

        synthesis.properties = " • ".join(props_parts)
        synthesis.duration_seconds = duration
        synthesis.duration_display = synthesis.format_duration(duration)
        synthesis.save(update_fields=['properties', 'duration_seconds', 'duration_display'])

    except Exception as e:
        logger.warning(f"Could not extract audio properties: {e}")
