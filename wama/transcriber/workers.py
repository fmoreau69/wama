"""
Transcriber Celery Workers

Background tasks for audio transcription using pluggable backends.
"""

import os
import torch
from celery import shared_task
from django.core.cache import cache
from django.db import close_old_connections

from .models import Transcript, TranscriptSegment
from wama.common.utils.console_utils import push_console_line

# Import backend system
try:
    from .backends import get_backend, get_available_backends, TranscriptionResult
    BACKENDS_AVAILABLE = True
except ImportError:
    BACKENDS_AVAILABLE = False

# Import audio preprocessor
try:
    from .utils.audio_preprocessor import AudioPreprocessor
except Exception:
    AudioPreprocessor = None

DEVICE = "cuda" if torch.cuda.is_available() else "cpu"


def _set_progress(transcript: Transcript, value: int, *, force: bool = False) -> None:
    """Update transcript progress in cache and database."""
    key = f"transcriber_progress_{transcript.id}"
    current = cache.get(key)
    if current is None:
        current = Transcript.objects.filter(pk=transcript.id).values_list('progress', flat=True).first()
    if not force and current is not None and value < current and value != 0:
        value = int(current)
    cache.set(key, value, timeout=3600)
    Transcript.objects.filter(pk=transcript.id).update(progress=value)


def _set_status_message(transcript: Transcript, message: str) -> None:
    """Message d'étape courant (« action en cours ») affiché sur la card pendant le traitement.

    Stocké en cache (lecture par la vue `progress`) pour éviter d'écrire en base à chaque étape.
    """
    cache.set(f"transcriber_status_msg_{transcript.id}", message or '', timeout=3600)


def _console(user_id: int, message: str, level: str = None) -> None:
    """Send message to user's console."""
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
        push_console_line(user_id, message, level=level, app='transcriber')
    except Exception:
        pass


def _set_partial_text(transcript_id: int, text: str) -> None:
    """Texte partiel de transcription — BRIQUE COMMUNE (2026-08-13) : une seule clé,
    lue par l'endpoint de progression ET par le volet `?side=during` (during_preview)."""
    from wama.common.utils.preview_utils import publish_partial_text
    publish_partial_text('transcriber', transcript_id, text)


def _preprocess_audio(transcript: Transcript, audio_path: str) -> str:
    """
    Preprocess audio file for better transcription quality.

    Args:
        transcript: Transcript instance
        audio_path: Path to original audio file

    Returns:
        Path to preprocessed audio file (or original if preprocessing fails)
    """
    if AudioPreprocessor is None:
        return audio_path

    try:
        _console(transcript.user_id, "Prétraitement audio en cours...")
        _set_progress(transcript, 10)

        preprocessor = AudioPreprocessor(
            target_sr=16000,
            noise_reduction=0.5,
            stationary=False
        )

        # Écrire le fichier prétraité dans un dossier temp (PAS dans input/) pour
        # ne pas déclencher de refresh du filemanager sur un fichier intermédiaire.
        import tempfile
        base_name = os.path.splitext(os.path.basename(audio_path))[0]
        cleaned_path = os.path.join(tempfile.gettempdir(), f"{base_name}_cleaned.wav")
        result_path = preprocessor.preprocess(audio_path, cleaned_path)

        _console(transcript.user_id, "Prétraitement terminé ✓")
        _set_progress(transcript, 15)

        return result_path

    except Exception as e:
        _console(transcript.user_id, f"Avertissement: prétraitement échoué ({e}), utilisation du fichier original")
        return audio_path


def _get_output_stem(transcript: Transcript, backend_name: str) -> str:
    """Build the output filename stem: {input_stem}_{backend}."""
    input_stem = os.path.splitext(os.path.basename(transcript.audio.name))[0]
    return f"{input_stem}_{backend_name}" if backend_name else input_stem


def _get_output_dir(transcript: Transcript) -> str:
    """Get (and create) the output directory for a transcript."""
    from wama.common.utils.media_paths import get_app_media_path
    output_dir = get_app_media_path('transcriber', transcript.user_id, 'output')
    output_dir.mkdir(parents=True, exist_ok=True)
    return str(output_dir)


def _build_txt_content(transcript: Transcript) -> str:
    """
    Build enriched TXT content:
      - Full transcription text
      - Diarization table (if segments exist)
      - LLM summary / meeting notes (if generated)
      - Coherence report (if verified)
    """
    parts: list[str] = []

    # ── 1. Transcription ──────────────────────────────────────────────────
    parts.append("=" * 60)
    parts.append("TRANSCRIPTION")
    parts.append("=" * 60)
    parts.append(transcript.text or '')
    parts.append('')

    # ── 2. Diarisation ────────────────────────────────────────────────────
    segments = TranscriptSegment.objects.filter(transcript=transcript).order_by('order')
    if segments.exists() and any(s.speaker_id for s in segments):
        parts.append("=" * 60)
        parts.append("DIARISATION — LOCUTEURS")
        parts.append("=" * 60)
        for seg in segments:
            speaker = seg.speaker_id or 'Inconnu'
            time_range = seg.format_time_range()
            parts.append(f"[{speaker}]  {time_range}")
            parts.append(f"  {seg.text}")
            parts.append('')

    # ── 3. Résumé LLM ────────────────────────────────────────────────────
    if transcript.summary:
        parts.append("=" * 60)
        label = "COMPTE-RENDU DE RÉUNION" if transcript.summary_type == 'meeting' else "RÉSUMÉ"
        parts.append(label)
        parts.append("=" * 60)
        parts.append(transcript.summary)
        if transcript.key_points:
            parts.append('')
            parts.append("Points clés :")
            for kp in transcript.key_points:
                parts.append(f"  • {kp}")
        if transcript.action_items:
            parts.append('')
            parts.append("Actions :")
            for ai in transcript.action_items:
                parts.append(f"  • {ai}")
        parts.append('')

    # ── 4. Vérification de cohérence ──────────────────────────────────────
    if transcript.coherence_score is not None:
        parts.append("=" * 60)
        parts.append("VÉRIFICATION DE COHÉRENCE")
        parts.append("=" * 60)
        parts.append(f"Score : {transcript.coherence_score}/100")
        if transcript.coherence_notes:
            parts.append('')
            parts.append("Problèmes détectés :")
            for note in transcript.coherence_notes.splitlines():
                if note.strip():
                    parts.append(f"  • {note.strip()}")
        if (transcript.coherence_suggestion
                and transcript.coherence_suggestion.strip() != transcript.text.strip()):
            parts.append('')
            parts.append("Version corrigée proposée :")
            parts.append("-" * 40)
            parts.append(transcript.coherence_suggestion)
        parts.append('')

    return '\n'.join(parts)


def _save_output_files(transcript: Transcript, backend_name: str) -> None:
    """Save SRT (after diarization) and enriched TXT (after all steps) to output folder."""
    try:
        output_dir = _get_output_dir(transcript)
        stem = _get_output_stem(transcript, backend_name)

        # ── SRT (diarization-aware) ────────────────────────────────────────
        segments = TranscriptSegment.objects.filter(transcript=transcript).order_by('order')
        if segments.exists():
            srt_content = ''
            for i, seg in enumerate(segments, 1):
                srt_content += seg.to_srt_entry(i)
        elif transcript.text:
            srt_content = f"1\n00:00:00,000 --> 00:00:00,000\n{transcript.text}\n\n"
        else:
            srt_content = ''

        if srt_content:
            srt_path = os.path.join(output_dir, f"{stem}.srt")
            with open(srt_path, 'w', encoding='utf-8') as f:
                f.write(srt_content)

        # ── TXT (enriched — called AFTER summary + coherence) ─────────────
        txt_path = os.path.join(output_dir, f"{stem}.txt")
        with open(txt_path, 'w', encoding='utf-8') as f:
            f.write(_build_txt_content(transcript))

        _console(transcript.user_id, f"Fichiers de sortie sauvegardés: {stem}.txt / .srt")
    except Exception as e:
        _console(transcript.user_id, f"Avertissement: sauvegarde fichiers de sortie échouée ({e})")


def _save_segments(transcript: Transcript, result: 'TranscriptionResult') -> int:
    """
    Save transcription segments to database.

    Args:
        transcript: Transcript instance
        result: TranscriptionResult with segments

    Returns:
        Number of segments saved
    """
    if not result.segments:
        return 0

    # Delete existing segments
    TranscriptSegment.objects.filter(transcript=transcript).delete()

    # Create new segments
    segments_to_create = []
    for i, seg in enumerate(result.segments):
        segments_to_create.append(TranscriptSegment(
            transcript=transcript,
            speaker_id=seg.speaker_id,
            start_time=seg.start_time,
            end_time=seg.end_time,
            text=seg.text,
            confidence=seg.confidence,
            order=i
        ))

    TranscriptSegment.objects.bulk_create(segments_to_create)

    # Also save segments as JSON backup
    transcript.segments_json = [s.to_dict() for s in result.segments]
    transcript.save(update_fields=['segments_json'])

    return len(segments_to_create)


# ── Découpage des audios longs (chunking + recollage des timestamps) ─────────
def _split_audio_chunks(audio_path: str, chunk_seconds: float, out_dir: str):
    """Découpe l'audio en morceaux ≤ chunk_seconds. Retourne [(chunk_path, start_offset_s), …].
    Lecture par tranches via soundfile (un morceau en mémoire à la fois)."""
    import soundfile as sf
    src = audio_path
    try:
        info = sf.info(src)
    except Exception:
        # Format non lisible par soundfile (ex. m4a) → transcode en wav via ffmpeg (résolveur
        # commun ; ffmpeg WSL2 peu fiable → override FFMPEG_BINARY possible). Fallback demandé.
        import subprocess
        from wama.common.utils.ffmpeg_utils import get_ffmpeg_exe, adapt_path_for_ffmpeg
        src = os.path.join(out_dir, "_decoded.wav")
        _ff = get_ffmpeg_exe()
        subprocess.run(
            [_ff, '-nostdin', '-y', '-i', adapt_path_for_ffmpeg(audio_path, _ff),
             '-ac', '1', '-ar', '16000', adapt_path_for_ffmpeg(src, _ff)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True,
        )
        info = sf.info(src)
    sr = info.samplerate
    total = info.frames
    step = max(int(chunk_seconds * sr), 1)
    chunks, idx, start = [], 0, 0
    while start < total:
        stop = min(start + step, total)
        data, _ = sf.read(src, start=start, stop=stop, dtype='float32')
        cpath = os.path.join(out_dir, f"_chunk_{idx:03d}.wav")
        sf.write(cpath, data, sr)
        chunks.append((cpath, start / float(sr)))
        start, idx = stop, idx + 1
    return chunks


def _offset_segments(segments, offset: float):
    """Décale les timestamps (segment ET mots) de `offset` secondes — pour recoller un chunk."""
    for seg in segments or []:
        seg.start_time = (seg.start_time or 0) + offset
        seg.end_time = (seg.end_time or 0) + offset
        for w in (seg.words or []):
            if isinstance(w, dict):
                if w.get('start') is not None:
                    w['start'] += offset
                if w.get('end') is not None:
                    w['end'] += offset
    return segments or []


def _transcribe_maybe_chunked(backend, audio_path: str, duration: float, kwargs: dict):
    """
    Transcrit l'audio. Si sa durée dépasse la capacité du moteur (`max_audio_seconds`,
    ex. VibeVoice ~55 min), le DÉCOUPE en morceaux, transcrit chacun et RECOLLE les
    timestamps (offset = début du morceau). Moteurs illimités (Whisper) → chemin direct.

    Limite connue (v1) : coupes à intervalle fixe (sans recouvrement) → un mot à la
    frontière peut être imparfait ; et la diarisation est indépendante par morceau
    (les identifiants de locuteurs ne sont pas réconciliés d'un morceau à l'autre).
    """
    cap = getattr(backend, 'max_audio_seconds', None)
    if not cap or not duration or duration <= cap:
        return backend.transcribe(audio_path=audio_path, **kwargs)

    import tempfile
    import shutil
    base_progress = kwargs.pop('progress_callback', None)
    tmp = tempfile.mkdtemp(prefix='wama_chunk_')
    try:
        chunks = _split_audio_chunks(audio_path, cap, tmp)
        n = len(chunks) or 1
        merged, texts, lang = [], [], ''
        for i, (cpath, offset) in enumerate(chunks):
            if base_progress:
                # Progression de CE morceau [0,1] → fenêtre globale [i/n, (i+1)/n].
                kwargs['progress_callback'] = (
                    lambda i: lambda r: base_progress((i + max(0.0, min(1.0, r))) / n)
                )(i)
            r = backend.transcribe(audio_path=cpath, **kwargs)
            if not r.success:
                return r
            lang = lang or (r.language or '')
            merged.extend(_offset_segments(r.segments, offset))
            if r.text:
                texts.append(r.text)
        return TranscriptionResult(success=True, text='\n'.join(texts),
                                   language=lang, segments=merged)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)




def _run_transcription(task, transcript_id: int):
    """La tâche d'item du transcriber passe par le squelette COMMUN (`run_item_task`, 2026-09-25) :
    gardes (redélivrance après crash), ingestion d'une source distante, statuts canoniques, durée
    max, chrono, console, notifications et signal d'exécution — l'app ne fournit que sa GLU.
    La progression reste écrite par `_set_progress` (clé et champ que lit le front), déclarée au
    squelette par `progress_fn` : une seule main écrit la progression."""
    from wama.common.utils.task_skeleton import run_item_task
    run_item_task(task, app_id='transcriber', model=Transcript, item_id=transcript_id,
                  process=_transcribe_item, notify_label='Transcriber',
                  progress_fn=lambda item, pct, msg: _set_progress(item, pct, force=True))


@shared_task(bind=True)
def transcribe(self, transcript_id: int):
    """Transcription d'une card, prétraitement selon son réglage."""
    return _run_transcription(self, transcript_id)


@shared_task(bind=True)
def transcribe_without_preprocessing(self, transcript_id: int):
    """Transcription d'une card SANS prétraitement (le réglage est remis à faux d'abord). Même
    squelette, lancé avec CETTE tâche : la garde de redélivrance lit le drapeau de SON message."""
    Transcript.objects.filter(pk=transcript_id).update(preprocess_audio=False)
    return _run_transcription(self, transcript_id)


def _transcribe_item(t, ctx):
    """La GLU du squelette : prétraitement → ASR → diarisation → sauvegarde → résumé → cohérence,
    puis mesure contre la référence, apprentissage ETA et forme d'onde. Le statut SUCCESS, la
    progression 100, la durée et la notification sont posés par le squelette APRÈS ce retour ;
    une exception le fait passer en FAILURE."""
    import time
    from django.utils import timezone

    _console(t.user_id, f"Transcription {t.id} démarrée.")
    _set_partial_text(t.id, "🎙️ Transcription en cours...\n")
    audio_path = t.audio.path
    cleaned_path = None

    try:
        # Step 1: Preprocessing (if enabled)
        if t.preprocess_audio:
            _set_status_message(t, "Prétraitement audio…")
            _set_partial_text(t.id, "🔧 Prétraitement audio...\n")
            cleaned_path = _preprocess_audio(t, audio_path)
        else:
            cleaned_path = audio_path

        # Step 2: Get backend
        if not BACKENDS_AVAILABLE:
            raise RuntimeError("Backend system not available")

        backend_name = t.backend if t.backend and t.backend != 'auto' else None
        backend = get_backend(backend_name)

        # Repli transparent : l'utilisateur a demandé un moteur précis mais il est
        # indisponible (ex. VibeVoice KO) → on le signale clairement au lieu d'un
        # changement silencieux. used_backend (enregistré plus bas) reflète le réel.
        if backend_name and backend.name != backend_name:
            _console(
                t.user_id,
                f"⚠ Moteur « {backend_name} » indisponible — repli sur {backend.display_name}.",
                level='warning',
            )
            _set_status_message(t, f"« {backend_name} » indisponible → {backend.display_name}")

        _console(t.user_id, f"Utilisation de {backend.display_name}...")
        _set_progress(t, 20)
        _set_status_message(t, f"Chargement du moteur {backend.display_name}…")
        _set_partial_text(t.id, f"📥 Chargement de {backend.display_name}...\n\n")

        # Step 3: Load model (chronométré pour l'apprentissage du seed ETA : chargement à froid).
        _t_load0 = time.time()
        if not backend.load():
            raise RuntimeError(f"Failed to load {backend.display_name}")
        _load_seconds = time.time() - _t_load0
        _t_proc0 = time.time()   # début du traitement réel (hors chargement)

        _console(t.user_id, f"{backend.display_name} chargé sur {DEVICE}")
        _set_progress(t, 30)
        _set_partial_text(t.id, "🎯 Transcription en cours...\n\nCela peut prendre quelques instants selon la durée de l'audio.\n")

        # Step 4: Transcribe
        _set_status_message(t, "Transcription en cours…")
        _console(t.user_id, "Transcription en cours...")

        # Build kwargs for transcription.
        # NB : on NE passe PLUS temperature/max_tokens. En ASR on veut la REPRODUCTIBILITÉ
        # (décodage déterministe par défaut des moteurs), pas l'échantillonnage ; et le câblage
        # max_tokens était de toute façon inerte (clé attendue = max_new_tokens). Le découpage des
        # audios longs se gère par chunking interne (cf. _maybe_chunk_transcribe), pas par un plafond.
        transcribe_kwargs = {}
        if t.hotwords:
            transcribe_kwargs['hotwords'] = t.hotwords

        # Progression intermédiaire pendant l'ASR (30 → 75 %) → l'ETA peut s'estimer.
        def _asr_progress(ratio: float) -> None:
            _set_progress(t, 30 + int(round(ratio * 45)))
        transcribe_kwargs['progress_callback'] = _asr_progress

        # Découpe automatiquement si l'audio dépasse la capacité du moteur (recolle les timestamps).
        result: TranscriptionResult = _transcribe_maybe_chunked(
            backend, cleaned_path, float(t.duration_seconds or 0), transcribe_kwargs
        )

        if not result.success:
            raise RuntimeError(result.error or "Transcription failed")

        _set_progress(t, 75)

        # Step 4b: Pyannote diarization (Whisper + Qwen3-ASR — VibeVoice has its own)
        if backend.name in ('whisper', 'qwen_asr') and t.enable_diarization and result.segments:
            try:
                from wama.common.backends.pyannote_diarizer import is_available as pyannote_ok, diarize
                if pyannote_ok():
                    _set_status_message(t, "Diarisation des locuteurs…")
                    _console(t.user_id, "Diarisation des locuteurs (pyannote)…")
                    _set_partial_text(t.id, "🔎 Identification des locuteurs…\n")
                    result.segments = diarize(cleaned_path, result.segments)
                    _console(t.user_id, "Diarisation terminée ✓")
                else:
                    _console(t.user_id, "pyannote non disponible, diarisation ignorée", level='warning')
            except Exception as dia_err:
                _console(t.user_id, f"Avertissement: diarisation échouée ({dia_err})", level='warning')

        _set_progress(t, 80)

        # Step 5: Save results
        # NB : on NE passe PAS en SUCCESS ici — les étapes LLM (résumé, cohérence,
        # cohérence par-segment) suivent. Sinon le front voit SUCCESS trop tôt et
        # recharge avant la fin (barre figée + options/cohérence absentes).
        # Le statut SUCCESS est posé à la toute fin (après _set_progress 100).
        t.text = result.text
        t.language = result.language
        t.used_backend = backend.name
        # La clé catalogue EXACTE, lue maintenant : `unload()` (plus bas) efface le modèle chargé.
        from .backends.manager import TranscriberBackendManager
        t.model_key = TranscriberBackendManager.catalogue_key_for(
            backend.name, getattr(backend, '_current_model', '') or '')

        # Save segments if available (diarization)
        num_segments = _save_segments(t, result)
        if num_segments > 0:
            _console(t.user_id, f"{num_segments} segments avec diarisation sauvegardés")

        _set_partial_text(t.id, t.text)
        _set_progress(t, 90)
        t.save(update_fields=['text', 'language', 'used_backend', 'model_key', 'status',
                              'segments_json'])

        # Step 6: Save output files (TXT + SRT) to output folder
        _save_output_files(t, backend.name)
        _set_progress(t, 95)

        # Le modèle ASR RESTE chargé (décision de Fabien, 2026-09-25 — la protection de juillet
        # contre les crashs n'a plus lieu d'être) : un lot au même moteur ne le recharge plus à
        # chaque card (12-16 s mesurés pour Whisper large-v3). La VRAM se partage par le
        # gouverneur commun : reclaim local avant un gros chargement, libération à la demande.

        # Step 7: Optional LLM summary (structured or meeting compte-rendu)
        if t.generate_summary and t.text:
            _set_progress(t, 96)
            _set_status_message(t, "Génération du résumé…")
            try:
                _set_partial_text(t.id, t.text + "\n\n⏳ Génération du résumé en cours…")
                from wama.common.utils.llm_utils import (
                    generate_structured_summary, generate_meeting_summary,
                )
                lang = t.language or 'fr'

                if t.summary_type == 'meeting':
                    _console(t.user_id, "Génération du compte-rendu de réunion (Ollama)…")
                    # Collect identified speakers from diarized segments if available
                    speakers = list(
                        TranscriptSegment.objects.filter(transcript=t)
                        .exclude(speaker_id='')
                        .values_list('speaker_id', flat=True)
                        .distinct()
                    )
                    t.summary = generate_meeting_summary(t.text, language=lang, speakers=speakers or None)
                    t.key_points = []
                    t.action_items = []
                else:
                    _console(t.user_id, "Génération du résumé LLM (Ollama)…")
                    summary_data = generate_structured_summary(
                        t.text, content_hint='transcription', language=lang,
                    )
                    t.summary = summary_data['summary']
                    t.key_points = summary_data['key_points']
                    t.action_items = summary_data['action_items']

                t.save(update_fields=['summary', 'key_points', 'action_items'])
                _console(t.user_id, "Résumé LLM généré ✓")
            except Exception as llm_err:
                _console(t.user_id, f"Avertissement: résumé LLM échoué ({llm_err})", level='warning')

        # Step 8: Optional coherence verification
        if t.verify_coherence and t.text:
            _set_progress(t, 98)
            _set_status_message(t, "Vérification de la cohérence…")
            try:
                _console(t.user_id, "Vérification de cohérence (Ollama)…")
                from wama.common.utils.llm_utils import verify_text_coherence
                coherence = verify_text_coherence(t.text, 'transcription', t.language or 'fr')
                t.coherence_score = coherence['score']
                t.coherence_notes = '\n'.join(coherence['notes'])
                t.coherence_suggestion = coherence['suggestion']
                t.save(update_fields=['coherence_score', 'coherence_notes', 'coherence_suggestion'])
                _console(t.user_id, f"Cohérence vérifiée — score: {coherence['score']}/100 ✓")
            except Exception as coh_err:
                _console(t.user_id, f"Avertissement: vérification cohérence échouée ({coh_err})", level='warning')

            # Step 8b: cohérence PAR SEGMENT → heatmap de l'éditeur (1 appel LLM, défensif :
            # en cas d'échec, segments_json reste sans coh → l'éditeur retombe sur la confiance).
            try:
                segs = t.segments_json or []
                if segs:
                    from wama.common.utils.llm_utils import analyze_segments_coherence
                    issues = analyze_segments_coherence(
                        [{'index': i, 'text': s.get('text', '')} for i, s in enumerate(segs)],
                        t.language or 'fr',
                    )
                    for i, s in enumerate(segs):
                        iss = issues.get(i)
                        if iss:
                            s['coh_severity'] = iss['severity']
                            s['coh_note'] = iss['note']
                        else:
                            s.pop('coh_severity', None)
                            s.pop('coh_note', None)
                    t.segments_json = segs
                    t.save(update_fields=['segments_json'])
                    if issues:
                        _console(t.user_id, f"Cohérence par segment : {len(issues)} segment(s) signalé(s)")
            except Exception as seg_err:
                _console(t.user_id, f"Avertissement: cohérence par-segment échouée ({seg_err})", level='warning')

        _set_status_message(t, '')                            # plus d'action en cours

        # Mesure contre la RÉFÉRENCE, si l'élément en porte une (brique commune, best-effort :
        # une mesure manquée ne fait jamais échouer une transcription réussie).
        if t.reference_result:
            from wama.common.services.result_evaluation import evaluate
            if evaluate('transcriber', t):
                _console(t.user_id, "Évaluation contre la référence enregistrée ✓")

        # Apprentissage ETA (eta_estimator) : durées RÉELLES (chargement à froid + traitement)
        # rapportées à la durée audio → affine le seed des prochains runs (par modèle × hardware).
        try:
            from wama.model_manager.services.eta_estimator import record_run, make_key
            _dur = float(t.duration_seconds or 0)
            if _dur > 0:
                record_run(
                    make_key('transcriber', backend.name),
                    size=_dur, unit='audio_sec',
                    process_seconds=time.time() - _t_proc0,
                    load_seconds=(_load_seconds if _load_seconds >= 2.0 else None),  # cold load uniquement
                )
        except Exception:
            pass
        # Enveloppe de forme d'onde (peaks) — calcul asynchrone, non bloquant (éditeur /edit).
        try:
            compute_waveform_peaks.delay(t.id)
        except Exception:
            pass

        return {
            'fields': {'finished_at': timezone.now()},
            'label': getattr(t, 'filename', '') or f"transcription #{t.id}",
            'console_success': f"Transcription {t.id} terminée ({backend.display_name}) ✓",
            'models': [t.model_key] if t.model_key else None,
        }
    except Exception as e:
        _set_progress(t, 0, force=True)
        _set_partial_text(t.id, f"❌ Erreur lors de la transcription:\n\n{e}")
        raise
    finally:
        # Cleanup: remove preprocessed temporary file
        if cleaned_path and cleaned_path != audio_path and os.path.exists(cleaned_path):
            try:
                os.remove(cleaned_path)
                _console(t.user_id, "Fichier temporaire nettoyé")
            except OSError as e:
                _console(t.user_id, f"Avertissement: impossible de supprimer {cleaned_path}: {e}")


@shared_task(bind=True, name='wama.transcriber.enrich_transcript')
def enrich_transcript(self, transcript_id: int, summary_type: str = 'structured'):
    """
    On-demand LLM enrichment of an already-transcribed item.

    Runs generate_structured_summary or generate_meeting_summary on the
    existing transcript text and saves the result without re-running STT.
    """
    close_old_connections()

    try:
        t = Transcript.objects.select_related('user').get(pk=transcript_id)
    except Transcript.DoesNotExist:
        return {'ok': False, 'error': f'Transcript {transcript_id} introuvable'}

    if not t.text:
        return {'ok': False, 'error': 'Pas de texte transcrit'}

    user_id = t.user_id
    lang = t.language or 'fr'

    try:
        push_console_line(user_id, f"[Transcriber] Enrichissement LLM — type: {summary_type}…", app='transcriber')
        from wama.common.utils.llm_utils import (
            generate_structured_summary, generate_meeting_summary,
        )

        if summary_type == 'meeting':
            speakers = list(
                TranscriptSegment.objects.filter(transcript=t)
                .exclude(speaker_id='')
                .values_list('speaker_id', flat=True)
                .distinct()
            )
            t.summary = generate_meeting_summary(t.text, language=lang, speakers=speakers or None)
            t.key_points = []
            t.action_items = []
        else:
            summary_data = generate_structured_summary(
                t.text, content_hint='transcription', language=lang,
            )
            t.summary = summary_data['summary']
            t.key_points = summary_data['key_points']
            t.action_items = summary_data['action_items']

        t.save(update_fields=['summary', 'key_points', 'action_items'])
        push_console_line(user_id, f"[Transcriber] Enrichissement terminé ✓", app='transcriber')
        return {'ok': True}

    except Exception as exc:
        push_console_line(user_id, f"[Transcriber] Enrichissement échoué : {exc}", app='transcriber', level='error')
        return {'ok': False, 'error': str(exc)}


def _anchor_words_for(t: Transcript):
    """Les mots HORODATÉS d'une sortie ASR de la MÊME audio, la clé du modèle qui les a produits, et
    la LANGUE qu'il a entendue — c'est par elle que l'étage B choisit son aligneur au catalogue.

    Dans l'ordre : la card elle-même (son résultat avant l'import, ou les ancres d'un import
    précédent — `_reset_for_relaunch` les garde pour une card à résultat existant), puis une card
    SŒUR du même utilisateur sur le même fichier (les doubles d'un lot le partagent), la plus
    récente d'abord. Jamais un résultat externe : il n'a pas entendu l'audio. `([], '', '')` sinon.
    """
    from wama.common.services.result_evaluation import EXTERNAL_PREFIX

    def words_of(item):
        return [w for s in (item.segments_json or []) if isinstance(s, dict)
                for w in (s.get('words') or []) if isinstance(w, dict)]

    # De la card elle-même, seuls les mots réellement ENTENDUS (sortie ASR, ou `exact` d'un
    # ancrage précédent) — jamais des temps déjà estimés, qui s'ancreraient sur eux-mêmes.
    own = [w for w in words_of(t) if w.get('timing') in (None, 'exact')]
    if own:
        return own, t.model_key or f'transcriber:{t.used_backend}', t.language
    siblings = (Transcript.objects.filter(user_id=t.user_id, audio=t.audio.name, status='SUCCESS')
                .exclude(pk=t.pk).exclude(model_key__startswith=EXTERNAL_PREFIX)
                .order_by('-finished_at'))
    for sibling in siblings:
        words = words_of(sibling)
        if words:
            return words, sibling.model_key or f'transcriber:{sibling.used_backend}', sibling.language
    return [], '', ''


def _outside_windows(segments, doc, tolerance: float = 10.0) -> int:
    """Tours ancrés HORS de la fenêtre que le document leur donnait (extraits Sonal) — le contrôle
    de cohérence que ces fenêtres permettent, à la tolérance près."""
    outside = 0
    for s in segments:
        window = doc.windows[s['window']] if s.get('window') is not None else None
        if window and s.get('start_time') is not None and not (
                window['start'] - tolerance <= s['start_time'] <= window['end'] + tolerance):
            outside += 1
    return outside


def _anchoring_said(report: dict, source: str, outside: int) -> str:
    said = (f"Texte ancré sur les mots de {source or 'la transcription'} : "
            f"{report['exact_ratio']:.1%} de mots retrouvés à l'identique, "
            f"{report['estimated']} estimé(s) dans la durée des mots corrigés, "
            f"{report['interpolated']} placé(s) entre voisins")
    if outside:
        said += f" — ⚠ {outside} tour(s) hors de l'extrait que le document indiquait"
    return said


def import_existing_result(t: Transcript) -> None:
    """Fait d'une transcription produite AILLEURS (port `work_result`) le résultat de la card.

    Déclaré à la brique commune (`register_evaluation(import_result=…)`) : c'est ce qu'elle appelle
    quand on pose le fichier, et ce que relance ▶ (`import_existing_result_task`) — le résultat
    existant TIENT LIEU de transcription, relancer ne doit donc pas lancer l'ASR à sa place.

    Même écriture que le moteur : un document HORODATÉ (SRT, VTT) passe par `_save_segments`,
    comme une sortie ASR (lignes de segments comprises, donc SRT et aperçus). Un document SANS
    temps (Sonal, texte) n'en invente aucun : `segments_json` porte les tours avec des temps
    nuls, et aucune ligne de segment n'est créée — ce sera l'affaire de l'alignement forcé.
    La clé du « modèle » est `external:<nom du fichier>` : mesurable, jamais agrégée comme un
    modèle du parc. Lève si le document ne contient aucune parole.
    """
    from django.db import transaction
    from django.utils import timezone
    from wama.common.services.result_evaluation import EXTERNAL_PREFIX
    from wama.common.services.word_anchoring import anchor_turns
    from .utils.transcript_documents import read_transcript_document

    doc = read_transcript_document(t.work_result.path)
    if not doc.segments:
        raise ValueError("aucune parole lue dans ce document (aucun label de locuteur suivi de texte)")
    segments = doc.segments
    timed = doc.is_timed
    if not timed:
        # ÉTAGE A de l'alignement : le texte sans temps s'ANCRE sur les mots d'une sortie ASR de
        # la même audio (brique commune `word_anchoring`) — sans modèle, sans retranscrire.
        words, source, language = _anchor_words_for(t)
        anchored = anchor_turns(segments, words) if words else None
        if anchored:
            segments, report = anchored
            timed = True
            t.language = t.language or language or ''
            _console(t.user_id, _anchoring_said(report, source, _outside_windows(segments, doc)))
    t.text = doc.text
    t.used_backend = 'externe'
    t.model_key = EXTERNAL_PREFIX + os.path.splitext(os.path.basename(t.work_result.name))[0]
    if timed:
        _save_turns(t, segments)
    else:
        TranscriptSegment.objects.filter(transcript=t).delete()
        t.segments_json = [{k: s[k] for k in ('speaker_id', 'start_time', 'end_time', 'text')}
                           for s in doc.segments]
    t.progress = 100
    t.status = 'SUCCESS'
    t.error_message = ''
    t.finished_at = timezone.now()
    t.save(update_fields=['text', 'language', 'used_backend', 'model_key', 'segments_json',
                          'progress', 'status', 'error_message', 'finished_at'])
    # ÉTAGE B, APRÈS la validation de la transaction : l'aligneur acoustique reprend ce que l'étage A
    # n'a fait qu'estimer — sur la file GPU, jamais dans la requête. Le résultat est déjà utilisable.
    if _needs_acoustic_alignment(t.segments_json):
        transaction.on_commit(lambda: align_existing_result.delay(t.pk))


def _save_turns(t: Transcript, turns) -> int:
    """Écrit des tours horodatés (`{speaker_id, start_time, end_time, text, words}`) comme une
    sortie ASR — lignes de segments comprises : éditeur, SRT et comparaison entre moteurs les lisent."""
    from wama.common.backends.speech_to_text_base import TranscriptionResult, TranscriptionSegment
    return _save_segments(t, TranscriptionResult(success=True, text=t.text, segments=[
        TranscriptionSegment(speaker_id=s.get('speaker_id') or '', start_time=s['start_time'],
                             end_time=s['end_time'] if s['end_time'] is not None else s['start_time'],
                             text=s['text'], words=s.get('words'))
        for s in turns]))


def _needs_acoustic_alignment(segments) -> bool:
    """Un tour sans heure, ou un mot dont l'heure n'a été qu'estimée : l'étage B a de quoi faire."""
    from wama.common.services.word_anchoring import UNSURE_TIMINGS
    for s in segments or []:
        if not isinstance(s, dict):
            continue
        if s.get('start_time') is None:
            return True
        if any(isinstance(w, dict) and w.get('timing') in UNSURE_TIMINGS for w in s.get('words') or []):
            return True
    return False


@shared_task(name='wama.transcriber.import_existing_result')
def import_existing_result_task(transcript_id: int):
    """▶ sur une card qui porte un résultat existant : il est RE-importé, jamais retranscrit.
    Tâche nommée, routée sur `default` (settings) : c'est de la lecture de texte, pas du GPU."""
    close_old_connections()
    try:
        t = Transcript.objects.get(pk=transcript_id)
    except Transcript.DoesNotExist:
        return {'ok': False, 'error': f'Transcript {transcript_id} introuvable'}
    try:
        import_existing_result(t)
        from wama.common.services.result_evaluation import evaluate
        evaluate('transcriber', t)
        _console(t.user_id, f"Résultat existant repris ({os.path.basename(t.work_result.name)}) ✓")
        return {'ok': True}
    except Exception as exc:
        t.status = 'FAILURE'
        t.error_message = f"Résultat existant illisible : {exc}"
        t.save(update_fields=['status', 'error_message'])
        _console(t.user_id, t.error_message, level='error')
        return {'ok': False, 'error': str(exc)}


def _aligner_model(language: str):
    """L'aligneur du CATALOGUE pour `language` : un modèle de tâche `alignment` dont les langues
    couvrent celle de l'audio, départagé par la brique commune (`select_model` : VRAM, déjà chargé).
    Aucun nom de modèle ici — un aligneur d'une autre langue se déclare dans `model_config`."""
    from wama.common.utils.lang_routing import model_languages
    from wama.model_manager.models import AIModel
    from wama.model_manager.services import select_model

    if not language:
        return None
    keys = [m.model_key for m in AIModel.objects.filter(source='transcriber')
            if (m.capabilities or {}).get('task') == 'alignment'
            and ({'*', language} & set(model_languages(m.capabilities)))]
    # ⚠ `candidates=[]` ne filtre RIEN : sans candidat, on s'arrête ici.
    # `downloaded_only=False` : le premier alignement télécharge le modèle, comme un premier ASR.
    return select_model(source='transcriber', candidates=keys, downloaded_only=False) if keys else None


def _alignment_said(report: dict, model_name: str) -> str:
    said = (f"Alignement acoustique ({model_name}) : {report['aligned']} mot(s) recalé(s) sur "
            f"{report['unsure']} estimé(s), en {report['windows']} fenêtre(s)")
    kept = report['failed'] + report['too_long']
    if kept:
        said += f" — {kept} passage(s) gardent leur estimation"
    return said


@shared_task(bind=True)
def align_existing_result(self, transcript_id: int):
    """ÉTAGE B de l'alignement forcé — un résultat repris (port `work_result`) sans heures sûres.

    1. Des ancres : les mots déjà `exact` de la card ; s'il n'y en a aucune (aucune sortie ASR de
       cet audio), Whisper transcrit D'ABORD pour en fournir — sa sortie ne sert qu'à ancrer, le
       texte de la card reste celui du document repris ;
    2. l'aligneur acoustique du catalogue (tâche `alignment`, langue de l'audio) reprend les seuls
       mots `estimated`/`interpolated`, par fenêtres que tiennent leurs voisins sûrs
       (`word_anchoring.refine_turns`) ;
    3. écrit comme une sortie ASR. Rien ne se perd : un échec garde l'étage A, déjà enregistré.

    Tâche du module `workers` : file GPU (route `wama.transcriber.workers.*`), gouverneur VRAM par
    le contrat commun des backends.
    """
    close_old_connections()
    try:
        t = Transcript.objects.get(pk=transcript_id)
    except Transcript.DoesNotExist:
        return {'ok': False, 'error': f'Transcript {transcript_id} introuvable'}
    from wama.common.utils.process_control import refuse_crash_redelivery
    if refuse_crash_redelivery(self, t):
        return {'ok': False, 'error': 'reprise après crash refusée'}
    if not _needs_acoustic_alignment(t.segments_json):
        return {'ok': True, 'skipped': 'rien à aligner'}

    from wama.common.backends.manager import backend_for_model
    from wama.common.services.word_anchoring import anchor_turns, refine_turns
    from wama.common.utils.audio_decode import decode_window

    turns = [s for s in (t.segments_json or []) if isinstance(s, dict)]
    audio_path = t.audio.path
    try:
        if any(s.get('start_time') is None for s in turns):
            words, source, language = _anchor_words_for(t)
            if not words:
                _console(t.user_id, "Alignement : aucune transcription de cet audio — Whisper "
                                    "transcrit d'abord pour fournir des repères…")
                asr = get_backend('whisper')
                if not asr.load():
                    raise RuntimeError("Whisper indisponible")
                try:
                    heard = _transcribe_maybe_chunked(asr, audio_path, float(t.duration_seconds or 0), {})
                finally:
                    asr.unload()
                if not heard.success:
                    raise RuntimeError(heard.error or "transcription des repères échouée")
                words = [w for s in heard.segments for w in (s.words or []) if isinstance(w, dict)]
                source, language = 'Whisper', heard.language
            anchored = anchor_turns(turns, words) if words else None
            if not anchored:
                raise RuntimeError("aucun mot horodaté sur lequel s'ancrer")
            turns, report = anchored
            t.language = t.language or language or ''
            _console(t.user_id, _anchoring_said(report, source, 0))

        model = _aligner_model(t.language)
        if model is None:
            _save_turns(t, turns)
            t.save(update_fields=['language'])
            _console(t.user_id, f"Alignement acoustique : aucun aligneur au catalogue pour la langue "
                                f"« {t.language or '?'} » — les heures restent estimées.", level='warning')
            return {'ok': True, 'skipped': 'aucun aligneur'}
        aligner_class = backend_for_model(model)
        if aligner_class is None:
            raise RuntimeError(f"aucun moteur installé ne sert {model.name}")
        aligner = aligner_class()
        if not aligner.load(model.hf_id):
            raise RuntimeError(f"{model.name} indisponible")
        try:
            def align_window(start, end, words):
                wave, _ = decode_window(audio_path, aligner.sample_rate, start, end - start)
                return aligner.align(wave, words)
            turns, report = refine_turns(turns, align_window, aligner.max_audio_seconds,
                                         audio_end=float(t.duration_seconds or 0) or None)
        finally:
            aligner.unload()
        _save_turns(t, turns)
        t.save(update_fields=['language'])
        _console(t.user_id, _alignment_said(report, model.name))
        return {'ok': True, **report}
    except Exception as exc:
        _console(t.user_id, f"Alignement acoustique non fait ({exc}) — les heures estimées restent.",
                 level='warning')
        return {'ok': False, 'error': str(exc)}


# ── Modes d'écriture de l'éditeur : transcrire AU FIL DE LA LECTURE (2026-09-24) ─────────────
# Demande de Fabien (2026-09-23) : calquer les modes d'écriture d'une station audio (Pro Tools :
# Write / Touch / Latch) sur la correction — le modèle reste chargé pendant l'édition, et la lecture
# « écrit ». Mécanique = la boucle COMMUNE `playhead_follow` (née du mode Live du cam_analyzer) ;
# ce qui est propre ici : le modèle (l'ASR de la card), la tranche (une plage d'audio transcrite),
# et le rangement du résultat. ⚠ Le serveur N'ÉCRIT PAS la correction : il dépose ses résultats en
# cache, l'éditeur les applique (Complément) ou les propose (Touch/Latch/Write) et son auto-save
# enregistre — une seule main écrit la correction, comme pour l'outil Bornes.

#: Les modes que l'éditeur peut demander (« Lecture » = aucun, la boucle ne tourne pas).
WRITE_MODES = ('complement', 'touch', 'latch', 'write')
#: Une tranche au plus par tour : la fenêtre native de Whisper.
WRITE_SLICE_SECONDS = 30.0
#: Durée de vie des résultats et du registre de ce qui est déjà transcrit.
WRITE_TTL = 3600


def write_channel(transcript_id):
    from wama.common.services.playhead_follow import Channel
    return Channel('transcriber_write', transcript_id)


def _transcribe_span(backend, audio_path: str, start: float, end: float, language: str = None):
    """Les mots horodatés (temps ABSOLUS) qu'entend `backend` dans [start, end] de l'audio."""
    import tempfile
    import soundfile as sf
    from wama.common.utils.audio_decode import decode_window

    wave, rate = decode_window(audio_path, 16000, start, end - start)
    if not len(wave):
        return []
    with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as handle:
        path = handle.name
    try:
        sf.write(path, wave, rate)
        kwargs = {'language': language} if language else {}
        result = backend.transcribe(audio_path=path, **kwargs)
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
    if not result.success:
        raise RuntimeError(result.error or 'transcription de la plage échouée')
    words = []
    for seg in _offset_segments(result.segments, start):
        for w in seg.words or []:
            if isinstance(w, dict) and w.get('start') is not None and w.get('end') is not None \
                    and start <= (w['start'] + w['end']) / 2 <= end:
                words.append({'word': w.get('word') or '', 'start': round(w['start'], 3),
                              'end': round(w['end'], 3), 'probability': w.get('probability')})
    return words


@shared_task(bind=True)
def live_write_task(self, transcript_id: int):
    """La boucle des modes d'écriture : suit le curseur de l'éditeur et transcrit les plages qu'il
    demande (`wanted`) et qui ne l'ont pas encore été pour ce mode — la plus proche de la tête de
    lecture d'abord, 30 s au plus par tour. Tâche du module `workers` : file GPU.

    Cède la place dès qu'une transcription a la main (`RUNNING`, `AWAITING_RESOURCES`) : les
    transcriptions de la file passent AVANT l'écoute d'un utilisateur.
    """
    from wama.common.models import JOB_AWAITING_RESOURCES, JOB_RUNNING
    from wama.common.services.playhead_follow import follow
    from wama.common.services.word_anchoring import spoken_text
    from wama.common.utils.intervals import merge_intervals, subtract_intervals

    close_old_connections()
    try:
        t = Transcript.objects.get(pk=transcript_id)
    except Transcript.DoesNotExist:
        return {'ok': False, 'error': f'Transcript {transcript_id} introuvable'}
    channel = write_channel(t.pk)
    state = {'backend': None}

    def start():
        name = t.backend if t.backend and t.backend != 'auto' else None
        backend = get_backend(name)
        if not backend.load():
            raise RuntimeError(f"{backend.display_name} indisponible")
        state['backend'] = backend
        _console(t.user_id, f"Écriture au fil de la lecture : {backend.display_name} chargé "
                            f"(libéré après 90 s sans lecture)")

    def should_yield():
        busy = (Transcript.objects.filter(status__in=(JOB_RUNNING, JOB_AWAITING_RESOURCES))
                .exclude(pk=t.pk).exists())
        if busy:
            _console(t.user_id, "Une transcription attend : l'écriture au fil de la lecture "
                                "s'interrompt (relancez la lecture ensuite)", level='warning')
        return busy

    def step(cursor):
        mode = cursor.get('mode')
        wanted = [[float(a), float(b)] for a, b in cursor.get('wanted') or [] if float(b) > float(a)]
        done = cache.get(channel.key('done')) or {}
        missing = subtract_intervals(wanted, done.get(mode) or [], min_len=0.5)
        if not missing:
            return False
        at = float(cursor.get('t') or 0.0)
        a, b = min(missing, key=lambda r: (r[1] < at, abs(r[0] - at)))   # devant d'abord
        b = min(b, a + WRITE_SLICE_SECONDS)
        words = _transcribe_span(state['backend'], t.audio.path, a, b, t.language or None)
        results = cache.get(channel.key('results')) or []
        results.append({'id': len(results), 'mode': mode, 'start': round(a, 3), 'end': round(b, 3),
                        'words': words, 'text': spoken_text(words)})
        cache.set(channel.key('results'), results, WRITE_TTL)
        done[mode] = merge_intervals((done.get(mode) or []) + [[a, b]])
        cache.set(channel.key('done'), done, WRITE_TTL)
        return True

    try:
        reason = follow(channel, self.request.id, step, on_start=start, should_yield=should_yield)
        if reason not in ('cooldown', 'already_running'):
            _console(t.user_id, "Écriture au fil de la lecture arrêtée — modèle libéré")
        return {'ok': True, 'reason': reason}
    except Exception as exc:
        _console(t.user_id, f"Écriture au fil de la lecture interrompue ({exc})", level='warning')
        return {'ok': False, 'error': str(exc)}
    finally:
        if state['backend'] is not None:
            try:
                state['backend'].unload()
            except Exception:
                pass


@shared_task(name='wama.transcriber.compute_waveform_peaks')
def compute_waveform_peaks(transcript_id: int):
    """Calcule l'enveloppe de forme d'onde (peaks) UNE fois, en asynchrone.

    Stocke le JSON sur disque (utils/waveform.py) et met à jour `waveform_status`
    (pending → ready/failed). Utilisé par l'éditeur de correction pour le zoom fenêtré.
    """
    close_old_connections()
    from .utils.waveform import compute_peaks, write_peaks
    try:
        t = Transcript.objects.get(pk=transcript_id)
    except Transcript.DoesNotExist:
        return {'ok': False, 'error': 'introuvable'}
    if not t.audio:
        Transcript.objects.filter(pk=transcript_id).update(waveform_status='failed')
        return {'ok': False, 'error': 'pas d\'audio'}

    Transcript.objects.filter(pk=transcript_id).update(waveform_status='pending')
    try:
        peaks, duration = compute_peaks(t.audio.path)
        if peaks is None:
            Transcript.objects.filter(pk=transcript_id).update(waveform_status='failed')
            return {'ok': False, 'error': 'ffmpeg indisponible'}
        write_peaks(t, peaks, duration)
        Transcript.objects.filter(pk=transcript_id).update(waveform_status='ready')
        return {'ok': True, 'buckets': len(peaks)}
    except Exception as exc:
        import traceback
        print(f"[Transcriber] peaks error: {traceback.format_exc()}")
        Transcript.objects.filter(pk=transcript_id).update(waveform_status='failed')
        return {'ok': False, 'error': str(exc)}
