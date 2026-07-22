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
    """Store partial transcription text in cache for live display."""
    key = f"transcriber_partial_text_{transcript_id}"
    cache.set(key, text, timeout=3600)


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


def _ensure_local_audio_from_source_url(t):
    """Import par URL / batch : télécharge le média si l'item n'a pas encore de
    fichier audio local mais possède un source_url. Plateformes média (YouTube,
    Vimeo…) → extraction AUDIO (download_youtube_audio, yt-dlp) ; sinon (URL de
    fichier direct ou chemin local accessible) → téléchargement du média
    (upload_media_from_url), l'ASR extraira l'audio au prétraitement.

    Comble le trou historique : batch_create stockait source_url sans jamais le
    télécharger. Permet aussi l'uniformisation de la card URL (n'importe quelle
    URL, plus seulement YouTube).
    """
    if t.audio.name or not t.source_url:
        return
    import os
    import tempfile
    import shutil
    from django.core.files import File
    from wama.common.utils.video_utils import download_youtube_audio, upload_media_from_url
    from wama.common.utils.url_ingest import MEDIA_PLATFORM_DOMAINS

    url = t.source_url
    _console(t.user_id, "Téléchargement du média depuis l'URL…")
    temp_dir = tempfile.mkdtemp()
    try:
        if any(d in url for d in MEDIA_PLATFORM_DOMAINS):
            path, video_title = download_youtube_audio(url, temp_dir)
        else:
            path = upload_media_from_url(url, temp_dir)
            video_title = ''
        fname = os.path.basename(path)
        with open(path, 'rb') as fh:
            t.audio.save(fname, File(fh), save=False)
        if not t.title:
            t.title = video_title or fname
        t.save(update_fields=['audio', 'title'])
        _console(t.user_id, f"Média téléchargé : {fname}")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


@shared_task(bind=True)
def transcribe(self, transcript_id: int):
    """
    Main transcription task with preprocessing and backend selection.

    Uses the backend system to select the best available engine.
    Supports VibeVoice (diarization) and Whisper backends.
    """
    import time
    _t0 = time.time()
    close_old_connections()
    t = Transcript.objects.get(pk=transcript_id)
    _set_progress(t, 5, force=True)
    _console(t.user_id, f"Transcription {t.id} démarrée.")

    _set_partial_text(t.id, "🎙️ Transcription en cours...\n")

    # Import par URL / batch : télécharger l'audio si pas encore de fichier local.
    _ensure_local_audio_from_source_url(t)

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
                from .backends.pyannote_diarizer import is_available as pyannote_ok, diarize
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

        # Save segments if available (diarization)
        num_segments = _save_segments(t, result)
        if num_segments > 0:
            _console(t.user_id, f"{num_segments} segments avec diarisation sauvegardés")

        _set_partial_text(t.id, t.text)
        _set_progress(t, 90)
        t.save(update_fields=['text', 'language', 'used_backend', 'status', 'segments_json'])

        # Step 6: Save output files (TXT + SRT) to output folder
        _save_output_files(t, backend.name)
        _set_progress(t, 95)

        # Unload the ASR model NOW — before LLM steps — to free GPU VRAM for Ollama
        try:
            backend.unload()
        except Exception:
            pass

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

        _set_progress(t, 100)
        # SUCCESS seulement maintenant : tout est prêt (texte, segments, résumé,
        # cohérence globale + par-segment) → le front recharge au bon moment.
        from django.utils import timezone
        t.processing_seconds = round(time.time() - _t0, 1)   # durée réelle (affichée à la place de l'ETA)
        t.finished_at = timezone.now()
        t.status = 'SUCCESS'
        t.save(update_fields=['status', 'processing_seconds', 'finished_at'])
        _set_status_message(t, '')                            # plus d'action en cours

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
        _console(t.user_id, f"Transcription {t.id} terminée ({backend.display_name}) ✓ "
                            f"en {t.processing_display}")

        # Notification email (respecte les préférences du profil ; fail-safe).
        try:
            from wama.common.utils.notifications import notify_job
            notify_job(t.user, 'Transcriber', getattr(t, 'name', '') or f"transcription #{t.id}",
                       True, detail=f"{num_segments} segment(s) · {t.processing_display}")
        except Exception:
            pass

        # Enveloppe de forme d'onde (peaks) — calcul asynchrone, non bloquant (éditeur /edit).
        try:
            compute_waveform_peaks.delay(t.id)
        except Exception:
            pass

        # Unload model to free memory
        try:
            backend.unload()
        except Exception:
            pass

        return {
            'ok': True,
            'engine': backend.name,
            'preprocessed': t.preprocess_audio,
            'segments': num_segments,
            'language': result.language
        }

    except Exception as e:
        import traceback
        error_msg = str(e)
        _console(t.user_id, f"Erreur transcription {t.id}: {error_msg}")
        print(f"[Transcriber] Error: {traceback.format_exc()}")

        t.status = 'FAILURE'
        t.save(update_fields=['status'])
        _set_progress(t, 0, force=True)
        _set_partial_text(t.id, f"❌ Erreur lors de la transcription:\n\n{error_msg}")

        # Notification email d'échec (respecte les préférences ; fail-safe).
        try:
            from wama.common.utils.notifications import notify_job
            notify_job(t.user, 'Transcriber', getattr(t, 'name', '') or f"transcription #{t.id}",
                       False, detail=error_msg)
        except Exception:
            pass

        return {'ok': False, 'error': error_msg}

    finally:
        # Cleanup: remove preprocessed temporary file
        if cleaned_path and cleaned_path != audio_path and os.path.exists(cleaned_path):
            try:
                os.remove(cleaned_path)
                _console(t.user_id, "Fichier temporaire nettoyé")
            except OSError as e:
                _console(t.user_id, f"Avertissement: impossible de supprimer {cleaned_path}: {e}")


@shared_task(bind=True)
def transcribe_without_preprocessing(self, transcript_id: int):
    """
    Transcription task without audio preprocessing.

    Delegates to the main transcribe task after disabling preprocessing.
    """
    close_old_connections()

    # Update transcript to disable preprocessing
    Transcript.objects.filter(pk=transcript_id).update(preprocess_audio=False)

    # Delegate to main task (Celery injects self automatically for bind=True)
    return transcribe(transcript_id)


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
