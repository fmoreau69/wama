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
    """Tâche principale de synthèse vocale — par le squelette COMMUN (`run_item_task`, marche P6
    du 2026-10-03) : gardes (redélivrance après crash), ingestion d'une voix de référence
    distante, statuts canoniques, durée max, chrono, ETA, console, notifications, ligne
    d'exécution, révision. L'app ne fournit que sa GLU (`_synthesize`)."""
    from wama.common.utils.task_skeleton import run_item_task
    run_item_task(self, app_id='synthesizer', model=VoiceSynthesis, item_id=synthesis_id,
                  process=_synthesize, notify_label='Synthesizer')


def _synthesize(synthesis, ctx):
    """La GLU : extraction du texte → choix du moteur → rendu par le service TTS → sauvegarde,
    format de sortie, mention « généré par IA », propriétés audio. Le statut SUCCESS, la
    progression 100, la durée et la notification sont posés par le squelette APRÈS ce retour ;
    une exception le fait passer en FAILURE ; un service TTS qui charge encore fait RE-LIVRER la
    tâche (`ServiceNotReady`), sans échec."""
    ctx.progress(5)
    _console(synthesis.user_id, f"Synthèse vocale #{synthesis.id} démarrée")

    try:
        # Étape 1: Extraction du texte
        _console(synthesis.user_id, "Extraction du texte du fichier...")
        ctx.progress(10)

        text_content = extract_text_from_file(synthesis.text_file.path)

        if not text_content or len(text_content.strip()) == 0:
            raise ValueError("Le fichier ne contient pas de texte valide")

        synthesis.text_content = text_content
        synthesis.update_metadata()

        _console(synthesis.user_id, f"Texte extrait: {synthesis.word_count} mots")
        ctx.progress(20)

        # Choix AUTOMATIQUE du moteur (brique commune `auto_model`, 2026-09-02) : résolu
        # AU LANCEMENT — la VRAM libre du moment fait foi, jamais l'état à la création
        # (un batch résout chaque élément avec l'état GPU de son tour). Le domaine du
        # tirage est CELUI que le schéma déclare pour les options (`params.py`) ; la
        # prévision affichée sous le select était une photo, on dit ici le choix réel.
        # Le tirage vit dans `speech_render.resolve_tts_model`, que l'APERÇU appelle aussi.
        # ⚠ ÉCART DÉCLARÉ au contrat du squelette (« un réglage ne s'écrit pas ») : le modèle
        # tiré est encore ÉCRIT dans le réglage `tts_model` — la card n'a pas d'autre endroit où
        # le montrer. Comportement d'avant le portage, gardé tel quel ; à solder en lisant le
        # modèle employé sur la ligne d'exécution (`ProcessRun.model_key`).
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
        ctx.progress(30)

        # Créer le fichier de sortie temporaire
        output_dir = os.path.dirname(synthesis.text_file.path)
        temp_output = os.path.join(output_dir, f"synthesis_{synthesis.id}_temp.wav")

        # (L'ingestion d'une voix de référence donnée par URL — `VoiceSynthesis.WAMA_INGEST` —
        # est faite par le squelette, avant cette glue.)

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
        ctx.progress(40)
        final_output = render_speech(
            text_content, temp_output,
            model=synthesis.tts_model, language=synthesis.language,
            voice_preset=synthesis.voice_preset, speaker_wav=speaker_wav,
            multi_speaker=getattr(synthesis, 'multi_speaker', False),
            scene_description=getattr(synthesis, 'scene_description', ''),
            speed=synthesis.speed, pitch=synthesis.pitch,
            on_segment=lambda i, n: ctx.progress(40 + int(i / n * 35)),
            on_partial=_during_preview(synthesis),
            console=lambda m: _console(synthesis.user_id, m),
        )
        _clear_during(synthesis)
        ctx.progress(85)

        # Étape 5: Sauvegarde du résultat
        _console(synthesis.user_id, "Sauvegarde du fichier audio...")
        ctx.progress(90)

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

        # La mention « généré par IA » dans les MÉTADONNÉES du fichier final (décision de Fabien,
        # 2026-09-30 : usage recherche, métadonnée seule, pas de tampon audio). Après la
        # conversion : c'est ce fichier-là que l'utilisateur emporte.
        from wama.common.tts.voice_refs import is_cloned_voice
        from wama.common.utils.generated_media import mark_as_generated
        mark_as_generated(synthesis.audio_output.path, app='synthesizer', model=synthesis.tts_model,
                          detail='voix clonée' if is_cloned_voice(synthesis.voice_preset) else '')

        # Mettre à jour les propriétés audio
        _update_audio_properties(synthesis)

        # Nettoyage des fichiers temporaires
        for temp_file in [temp_output, final_output]:
            if os.path.exists(temp_file) and temp_file != synthesis.audio_output.path:
                try:
                    os.remove(temp_file)
                except OSError:
                    pass

        # Apprentissage ETA : durée réelle ∝ longueur du texte (unit='char'), par modèle TTS.
        # Service-based (chargement non séparable) → total dans per_unit, sans temps de
        # chargement : c'est le squelette qui l'enregistre (`eta` du retour).
        from wama.model_manager.services.eta_estimator import make_key
        text = synthesis.text_content or ''
        return {
            # La sortie de la card, pour sa RÉVISION (le fichier est déjà écrit et rattaché).
            'fields': {'audio_output': synthesis.audio_output.name},
            'eta': (make_key('synthesizer', synthesis.tts_model), len(text), 'char') if text else None,
            'label': getattr(synthesis, 'name', '') or f"synthèse #{synthesis.id}",
            'models': [synthesis.tts_model] if synthesis.tts_model else None,
            'console_success': f"Synthèse #{synthesis.id} terminée ✓",
            'output_ref': synthesis.audio_output.name,
        }

    except TTSServiceLoadingError as e:
        # Le service TTS démarre encore : on rend le worker GPU et on reviendra — politique du
        # squelette commun (60 × 10 s, puis échec dit).
        _clear_during(synthesis)
        from wama.common.utils.task_skeleton import ServiceNotReady
        raise ServiceNotReady(
            "Service TTS en chargement", countdown=10, max_attempts=60,
            gave_up="Service TTS non disponible après 10 minutes d'attente (60 tentatives)") from e

    except Exception:
        _clear_during(synthesis)
        ctx.reset_progress()
        raise


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
