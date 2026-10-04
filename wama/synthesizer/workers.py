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


def synthesizer_eta_key_size(synthesis):
    """(clé, taille, unité) de l'ETA d'une synthèse — durée ∝ longueur du texte, par modèle TTS ;
    None sans texte. UN lieu, partagé par la glu (`record_run`) et la vue de progression
    (`estimate`) : les deux l'écrivaient chacune (ROUTE §11 #37)."""
    from wama.model_manager.services.eta_estimator import make_key
    text = synthesis.text_content or ''
    return (make_key('synthesizer', synthesis.tts_model), len(text), 'char') if text else None


@shared_task(bind=True, max_retries=60, default_retry_delay=10)
def synthesize_voice(self, synthesis_id: int, process: str = None):
    """Tâche principale de synthèse vocale — par le squelette COMMUN (`run_item_task`, marche P6
    du 2026-10-03) : gardes (redélivrance après crash), ingestion d'une voix de référence
    distante, statuts canoniques, durée max, chrono, ETA, console, notifications, ligne
    d'exécution, révision. L'app ne fournit que ses GLUS.

    La card porte un PIPELINE de deux process (`function_specs.PIPELINE`) : `generate`
    (`_synthesize`, le WAV) puis `output` (`_output`, format et qualité). Un lancement ne rejoue
    que ce qui n'est plus à jour : changer le format ne re-synthétise pas. `process` borne le
    lancement à UN process (⚠ argument de tâche nouveau : workers à relancer)."""
    from wama.common.services.output_process import forget_lost_generation
    from wama.common.utils.task_skeleton import run_item_task
    from .function_specs import PIPELINE
    # La sortie repart du WAV que la synthèse a laissé : s'il n'est plus là, la synthèse rejoue.
    known = VoiceSynthesis.objects.filter(pk=synthesis_id).first()
    if known is not None:
        forget_lost_generation(known, 'audio_output', 'generate')
    run_item_task(self, app_id='synthesizer', model=VoiceSynthesis, item_id=synthesis_id,
                  pipeline=PIPELINE, processes={'generate': _synthesize, 'output': _output},
                  notify_label='Synthesizer', only=process)


def _output(synthesis, ctx):
    """GLU du process `output` : format et qualité de sortie, par la glu COMMUNE
    (`output_process.output_step`) — le WAV est gardé tant que la sortie le transforme. La
    mention « généré par IA » et les propriétés audio sont celles du fichier FINAL : c'est lui que
    l'utilisateur emporte."""
    from wama.common.services import process_runs
    from wama.common.services.output_process import output_step
    from wama.common.utils.file_references import relative_to_media

    def finish(item, finals):
        from wama.common.tts.voice_refs import is_cloned_voice
        from wama.common.utils.generated_media import mark_as_generated
        spoken = process_runs.line(item, 'generate')
        mark_as_generated(finals[0], app='synthesizer',
                          model=(spoken.model_key if spoken else '') or item.tts_model,
                          detail='voix clonée' if is_cloned_voice(item.voice_preset) else '')
        item.audio_output.name = relative_to_media(finals[0])
        _update_audio_properties(item)
        return {}

    return output_step('audio_output', domain='audio', app_id='synthesizer',
                       console=lambda item, message: _console(item.user_id, message),
                       extra_fields=finish)(synthesis, ctx)


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
        # Le modèle tiré vaut pour CE lancement et se lit sur la ligne d'exécution
        # (`ProcessRun.model_key`) : il n'est plus ÉCRIT dans le réglage `tts_model` (écart
        # soldé le 2026-10-03) — « auto » reste « auto », et un réglage surveillé qui changerait
        # pendant son propre process se périmerait lui-même.
        from wama.common.utils.auto_model import is_auto, read_quality_intent
        tts_model = synthesis.tts_model
        if is_auto(tts_model):
            quality_intent = getattr(synthesis, 'quality_intent', None)
            tts_model = resolve_tts_model(
                tts_model, synthesis.voice_preset, quality_intent,
                fallback=VoiceSynthesis._meta.get_field('tts_model').get_default())
            _console(synthesis.user_id,
                     f"Choix automatique du moteur → {tts_model} "
                     f"(capacités + VRAM libre au lancement, curseur qualité "
                     f"{read_quality_intent(quality_intent)}/100)")

        # Étape 2: Génération audio via le service TTS
        _console(synthesis.user_id, f"Envoi au service TTS (modèle: {tts_model})...")
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
            tts_model, synthesis.voice_preset, synthesis.user,
            reference_path=synthesis.voice_reference.path if synthesis.voice_reference else None,
            language=synthesis.language or '')

        # Segments par moteur → service TTS → assemblage → vitesse/hauteur : LA chaîne de
        # rendu (`utils/speech_render`), la même que celle de l'aperçu de voix.
        ctx.progress(40)
        final_output = render_speech(
            text_content, temp_output,
            model=tts_model, language=synthesis.language,
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
                app='synthesizer', model=tts_model,
                source_name=(synthesis.text_file.name or ''),
                item_id=synthesis.id, ext='.wav')
            # Le rendu et l'original gardé de la fois d'avant partent d'abord : le lanceur ne
            # retire plus l'audio au clic, et le stockage renommerait le nouveau fichier.
            from wama.common.services.output_process import drop_previous_outputs, generated
            drop_previous_outputs(synthesis, 'audio_output')
            synthesis.audio_output.save(audio_filename, ContentFile(f.read()))

        # Le format et la qualité de sortie sont le process suivant, `output` (`_output`).
        # La mention « généré par IA » dans les MÉTADONNÉES (décision de Fabien, 2026-09-30 :
        # usage recherche, métadonnée seule, pas de tampon audio) : posée ICI sur le WAV, et
        # reposée par `output` sur le fichier final.
        from wama.common.tts.voice_refs import is_cloned_voice
        from wama.common.utils.generated_media import mark_as_generated
        mark_as_generated(synthesis.audio_output.path, app='synthesizer', model=tts_model,
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
        return generated(
            [synthesis.audio_output.path],
            # La sortie de la card, pour sa RÉVISION (le fichier est déjà écrit et rattaché).
            fields={'audio_output': synthesis.audio_output.name},
            eta=synthesizer_eta_key_size(synthesis),
            label=getattr(synthesis, 'name', '') or f"synthèse #{synthesis.id}",
            models=[tts_model] if tts_model else None,
            console_success=f"Synthèse #{synthesis.id} terminée ✓")

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
