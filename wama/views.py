"""
WAMA - Main Views
Handles home page and admin AI chat functionality
"""

import json
import logging
import os
import re
import threading
from functools import wraps
from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_protect
from django.conf import settings

logger = logging.getLogger(__name__)


def _admin_api(view_func):
    """
    API decorator for admin-only endpoints.
    Returns JSON 401/403 instead of HTML redirects so AJAX callers always get JSON.
    Uses the same is_admin() logic as the home page template guard (admin group OR superuser).
    """
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse({'error': 'Authentification requise'}, status=401)
        from wama.accounts.views import is_admin
        if not is_admin(request.user):
            return JsonResponse({'error': 'Accès réservé aux administrateurs'}, status=403)
        return view_func(request, *args, **kwargs)
    return _wrapped


# ---------------------------------------------------------------------------
# System prompts
# ---------------------------------------------------------------------------

WAMA_SYSTEM_PROMPT = """You are a helpful assistant for WAMA (Web App for Media Automation), a Django-based web application for media processing including video anonymization, audio transcription, voice synthesis, image generation, and image/video enhancement. Answer questions concisely and helpfully in French."""

WAMA_TOOLS_PROMPT = """
You can interact with WAMA applications by calling tools.
When you need to perform an action, output ONLY the JSON tool call on a single line, with NO surrounding text:
{"tool": "<name>", "args": {<arguments>}}

Available tools:

Anonymizer:
- list_user_files(folder="temp"): List the user's files. Folders: "temp" (temporary uploads), "anon_input" (anonymizer input), "anon_output" (anonymizer output), "transcriber_input" (transcriber audio/video), "describer_input" (describer files).
- add_to_anonymizer(file_path, use_sam3=false, sam3_prompt="", classes=["face"], precision_level=50): Add a file to the anonymizer queue. file_path is the "path" value returned by list_user_files.
- start_anonymizer(media_id=null): Launch anonymizer processing. Provide media_id from add_to_anonymizer, or null to process all pending files.
- get_anonymizer_status(): Get the current status and progress of anonymizer jobs. Returns output_url when status="done".
- sam3_examples(): Get examples of SAM3 text prompts for segmentation.

Imager:
- create_image(prompt, model="hunyuan-image-2.1", width=1024, height=1024, steps=30, guidance_scale=7.5, negative_prompt="", seed=null, num_images=1): Create a text-to-image generation job (status: pending). Returns generation_id.
- start_imager(generation_id=null): Launch image generation. Provide generation_id from create_image, or null to start all pending jobs.
- get_imager_status(): Get status and progress of the user's recent image generation jobs. Returns output_urls (images) or video_url when status="SUCCESS".

Enhancer (image/vidéo):
- add_to_enhancer(file_path, ai_model="RealESR_Gx4", denoise=false, blend_factor=0.0): Register an image/video file for AI upscaling. file_path is the "path" value from list_user_files. Models: RealESR_Gx4 (fast), RealESR_Animex4 (anime), BSRGANx2/x4 (quality), RealESRGANx4 (high quality), IRCNN_Mx1/Lx1 (denoise only). Returns enhancement_id.
- start_enhancer(enhancement_id=null): Launch enhancement processing. Provide enhancement_id from add_to_enhancer, or null to start all pending jobs.
- get_enhancer_status(): Get status and progress of the user's recent image/video enhancement jobs. Returns output_url when status="SUCCESS".

Audio Enhancer (alternative à Adobe Podcast):
- add_to_audio_enhancer(file_path, engine="resemble", mode="both", denoising_strength=0.5, quality=64): Register an audio file for speech enhancement. Engines: "resemble" (quality, 44.1kHz) or "deepfilternet" (ultra-fast). Modes: "both" (denoise+enhance), "denoise", "enhance". Returns audio_enhancement_id.
- start_audio_enhancer(audio_enhancement_id=null): Launch audio enhancement. Provide audio_enhancement_id or null to start all pending jobs.
- get_audio_enhancer_status(): Get status and progress of the user's recent audio enhancement jobs. Returns output_url when status="SUCCESS".

Synthesizer:
- synthesize_text(text, language="fr", tts_model="xtts_v2", voice_preset="default", speed=1.0, pitch=1.0, emotion_intensity=1.0): Create a text-to-speech job from raw text. Returns synthesis_id.
- start_synthesizer(synthesis_id=null): Launch synthesis processing. Provide synthesis_id from synthesize_text, or null to start all pending jobs.
- get_synthesizer_status(): Get status and progress of the user's recent synthesis jobs. Returns audio_url when status="SUCCESS".

Describer:
- add_to_describer(file_path, output_format="detailed", output_language="fr", max_length=500): Register a file (image, video, audio, text, PDF) for AI description/summary. file_path is the "path" value from list_user_files. Formats: "summary", "detailed", "scientific", "bullet_points". Returns description_id.
- start_describer(description_id=null): Launch description processing. Provide description_id from add_to_describer, or null to start all pending jobs.
- get_describer_status(): Get status and result preview of the user's recent description jobs.

Transcriber:
- add_to_transcriber(file_path, backend="auto", preprocess_audio=false, hotwords="", enable_diarization=true): Register an audio or video file for transcription. file_path is the "path" value from list_user_files. Backends: "auto", "whisper", "vibevoice". Returns transcript_id.
- start_transcriber(transcript_id=null): Launch transcription. Provide transcript_id from add_to_transcriber, or null to start all pending jobs.
- get_transcriber_status(): Get status and text preview of the user's recent transcription jobs.

Reader (OCR — extraction de texte de documents):
- add_to_reader(file_path, backend="auto", mode="auto", output_format="txt", language=""): Register a PDF or image file for OCR text extraction. Backends: "auto", "olmocr" (GPU, quality), "doctr" (CPU, fast). Modes: "auto", "printed", "handwritten". Returns item_id.
- start_reader(item_id=null): Launch OCR processing. Provide item_id or null for all pending jobs.
- get_reader_status(): Get status and text preview of the user's recent OCR jobs.

Médiathèque (assets personnels réutilisables):
- list_media_assets(asset_type="", q=""): Liste les assets de la médiathèque de l'utilisateur. Types: "voice", "audio_music", "audio_sfx", "image", "video", "document", "avatar". Retourne id, name, asset_type, file_url pour chaque asset.
- get_media_asset_url(asset_id): Retourne l'URL de fichier d'un asset spécifique par son ID.

Interface:
- switch_ui_mode(mode): Bascule l'interface entre "simple" (chatbot) et "advanced" (complète). Utilise ce tool si l'utilisateur demande de changer de mode, d'afficher l'interface complète, ou de revenir à la vue simplifiée.

Rules:
- Make ONE tool call per turn. Wait for the result before calling another tool.
- When the user asks you to perform an action (add a file, launch processing, etc.), use the tools.
- When the user asks a question or wants information, answer directly without tools.
- Always confirm what you did after tool calls.
- Respond in French.
- COMPLETION NOTIFICATION: After starting a task (start_anonymizer, start_imager, start_enhancer, start_audio_enhancer, start_synthesizer, start_describer, start_transcriber), automatically call the corresponding get_*_status tool. If the task is already SUCCESS/done, immediately report the result with the file URL/preview link. If still RUNNING/PENDING, tell the user "La tâche a démarré — vous serez notifié dès la fin." and explain they can ask "quel est le statut ?" to check progress.
- OUTPUT LINKS: When a get_*_status result shows status="SUCCESS" or status="done" and contains output_url / audio_url / output_urls / video_url, ALWAYS include these links in your response using Markdown format: [📥 Télécharger](URL) or [🖼️ Voir l'image](URL).

File search strategy:
- When the user asks to anonymize a file: check "anon_input" first, then "temp".
- When the user asks to transcribe a file: check "transcriber_input" first, then "temp".
- When the user asks to describe a file: check "describer_input" first, then "temp".
- For any other request, search "temp" first.
- When the user references an asset from the médiathèque (e.g. "ma voix X", "l'image Y"), use list_media_assets to find it.
- If the file is not found in any folder, tell the user to upload it via the WAMA File Manager at /filemanager/ or the corresponding application page.
"""


def home(request):
    """Home page view with admin check for AI chat."""
    context = {
        'is_admin': request.user.is_staff if request.user.is_authenticated else False
    }
    return render(request, 'home.html', context)


def presentation(request):
    """WAMA presentation slideshow."""
    return render(request, 'includes/wama_presentation.html')


_OLLAMA_MODEL_MAP = {
    'dev':        'qwen3.5:35b-a3b',
    'coder':      'qwen3.5:35b-a3b',
    'debug':      'deepseek-coder-v2:16b',
    'architect':  'qwen3.5:35b-a3b',
    'fast':       'qwen3.5:9b',
    'ultra_fast': 'qwen3.5:4b',
}

# Safe context limits per model (chars, not tokens — ~4 chars/token estimate)
# Below these limits quality stays high; above them we upgrade to a larger model.
_MODEL_SAFE_CHARS = {
    'qwen3.5:4b':           80_000,   # ~20K tokens
    'qwen3.5:9b':          120_000,   # ~30K tokens
    'qwen3.5:35b-a3b':     300_000,   # ~75K tokens — MoE handles long context well
    'deepseek-coder-v2:16b': 48_000,  # ~12K tokens
}


def _build_wama_context(user) -> str:
    """
    Build a short WAMA status string to inject into the system prompt.
    Tells the assistant about current queue state without revealing sensitive data.
    """
    try:
        from django.apps import apps as django_apps
        lines = []
        checks = [
            ('anonymizer',   'Media',            'status'),
            ('transcriber',  'Transcript',       'status'),
            ('describer',    'Description',      'status'),
            ('enhancer',     'Enhancement',      'status'),
            ('imager',       'Generation',       'status'),
            ('synthesizer',  'VoiceSynthesis',   'status'),
            ('composer',     'ComposerGeneration','status'),
            ('reader',       'ReadingItem',      'status'),
        ]
        for app_label, model_name, _ in checks:
            try:
                model = django_apps.get_model(f'wama.{app_label}', model_name)
                pending = model.objects.filter(user=user, status='PENDING').count()
                running = model.objects.filter(user=user, status__in=['RUNNING', 'processing']).count()
                failed  = model.objects.filter(user=user, status__in=['FAILURE', 'ERROR', 'error']).count()
                if pending or running or failed:
                    parts = []
                    if pending: parts.append(f"{pending} en attente")
                    if running: parts.append(f"{running} en cours")
                    if failed:  parts.append(f"{failed} en erreur")
                    lines.append(f"  - {app_label}: {', '.join(parts)}")
            except Exception:
                pass
        if lines:
            return "\n\nÉtat actuel des files WAMA (utilisateur connecté):\n" + "\n".join(lines)
        return "\n\nToutes les files WAMA sont vides pour cet utilisateur."
    except Exception:
        return ""


def _route_model_by_context(ollama_model: str, messages: list) -> str:
    """
    Upgrade the Ollama model if the conversation context is too long for it.
    Uses a conservative char-based estimate (~4 chars per token).
    """
    total_chars = sum(len(m.get('content', '')) for m in messages)
    safe_limit = _MODEL_SAFE_CHARS.get(ollama_model, 120_000)
    if total_chars > safe_limit:
        # Upgrade to the largest available model
        upgraded = 'qwen3.5:35b-a3b'
        if ollama_model != upgraded:
            logger.info(
                f"[ai_chat] context too long ({total_chars} chars) for {ollama_model} "
                f"— upgrading to {upgraded}"
            )
        return upgraded
    return ollama_model


def _ollama_call(messages: list, ollama_model: str) -> tuple:
    """
    Low-level Ollama POST.

    Returns:
        (text: str, usage: dict) on success
        (None, error_dict) on failure
    """
    import httpx

    ollama_host = getattr(settings, 'OLLAMA_HOST', 'http://127.0.0.1:11434').rstrip('/')
    ollama_url = f"{ollama_host}/api/chat"

    try:
        with httpx.Client(timeout=180.0, trust_env=False) as client:
            resp = client.post(
                ollama_url,
                json={
                    "model": ollama_model,
                    "messages": messages,
                    "options": {"temperature": 0.7, "num_predict": 4096},
                    "stream": False,
                },
            )
        if resp.status_code != 200:
            return None, {'error': f'Ollama error: {resp.text}', 'status': resp.status_code}

        data = resp.json()
        text = data.get("message", {}).get("content", "")
        usage = {
            'input_tokens': data.get("prompt_eval_count", 0),
            'output_tokens': data.get("eval_count", 0),
        }
        return text, usage

    except httpx.ConnectError:
        host_cfg = getattr(settings, 'OLLAMA_HOST', 'http://127.0.0.1:11434')
        return None, {
            'error': (
                f'Ollama inaccessible à {ollama_url}. '
                f'Vérifiez que Ollama est démarré (ollama serve) et que OLLAMA_HOST '
                f'pointe sur la bonne adresse (actuel : {host_cfg}).'
            ),
            'status': 503,
        }
    except httpx.TimeoutException:
        return None, {'error': 'Ollama : délai dépassé. Le modèle est peut-être en cours de chargement.', 'status': 504}
    except Exception as e:
        logger.error(f"Ollama error: {e}")
        return None, {'error': f'Ollama error: {e}', 'status': 500}


def _strip_think_tags(text: str) -> str:
    """Remove <think>...</think> reasoning blocks emitted by thinking models."""
    return re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL).strip()


def _parse_tool_call(text: str) -> dict | None:
    """
    Detect a JSON tool call in the LLM response.

    Expected format (on any line):
        {"tool": "tool_name", "args": {...}}

    Returns parsed dict or None.
    """
    # Strip reasoning tags first
    clean = _strip_think_tags(text)
    # Look for {"tool": ..., "args": ...} anywhere in the text
    match = re.search(r'\{[^{}]*"tool"\s*:\s*"[^"]+"\s*,\s*"args"\s*:\s*\{[^{}]*\}\s*\}', clean)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    return None


def _chat_with_ollama(message: str, model: str = "fast", user=None, history: list = None) -> dict:
    """
    Agentic chat with local Ollama server.

    Supports tool-calling: if the LLM response contains a JSON tool call,
    the tool is executed and the result is fed back into the conversation
    (up to MAX_TOOL_ITERATIONS times). The final LLM response is returned
    along with the list of executed tool steps.

    Args:
        message: User message
        model:   Model key from _OLLAMA_MODEL_MAP
        user:    Django User instance (required for tool execution)
        history: Prior conversation turns as list of {role, content} dicts

    Returns:
        dict with success, response, model, usage, tool_steps
    """
    from .tool_api import execute_tool

    ollama_model = _OLLAMA_MODEL_MAP.get(model, model)

    # Inject current WAMA queue state into system prompt (when user is known)
    wama_context = _build_wama_context(user) if user else ""
    system_prompt = WAMA_SYSTEM_PROMPT + wama_context + (WAMA_TOOLS_PROMPT if user else "")

    # Build messages: system + prior history (capped) + current user message
    prior = (history or [])[-20:]  # keep last 10 exchanges max
    messages = [
        {"role": "system", "content": system_prompt},
        *prior,
        {"role": "user",   "content": message},
    ]

    # Auto-upgrade model if context is too long for the selected model
    ollama_model = _route_model_by_context(ollama_model, messages)

    tool_steps = []
    total_usage = {'input_tokens': 0, 'output_tokens': 0}
    MAX_TOOL_ITERATIONS = 5

    for _ in range(MAX_TOOL_ITERATIONS):
        text, result = _ollama_call(messages, ollama_model)
        if text is None:
            return result  # error dict

        # Accumulate token usage
        total_usage['input_tokens']  += result.get('input_tokens', 0)
        total_usage['output_tokens'] += result.get('output_tokens', 0)

        # Detect tool call in response
        tool_call = _parse_tool_call(text) if user else None

        if not tool_call:
            # No tool call → this is the final answer
            # Strip any remaining reasoning tags from the displayed response
            clean_text = _strip_think_tags(text)
            return {
                'success': True,
                'response': clean_text,
                'model': f"wama-dev-ai ({ollama_model})",
                'usage': total_usage,
                'tool_steps': tool_steps,
            }

        # Execute the tool
        tool_name = tool_call.get('tool', '')
        tool_args  = tool_call.get('args', {})
        logger.info(f"[ai_chat] tool_call: {tool_name}({tool_args})")

        tool_result = execute_tool(tool_name, tool_args, user)
        tool_steps.append({'tool': tool_name, 'args': tool_args, 'result': tool_result})

        # Add assistant tool-call turn + tool result to conversation
        messages.append({"role": "assistant", "content": text})
        messages.append({
            "role": "user",
            "content": f"Résultat du tool {tool_name} : {json.dumps(tool_result, ensure_ascii=False)}",
        })

    # Reached iteration limit — return last LLM text as-is
    logger.warning("[ai_chat] tool-calling iteration limit reached")
    last_text = messages[-2].get("content", "") if len(messages) >= 2 else ""
    return {
        'success': True,
        'response': _strip_think_tags(last_text),
        'model': f"wama-dev-ai ({ollama_model})",
        'usage': total_usage,
        'tool_steps': tool_steps,
    }


def _chat_with_claude(message: str, history: list = None) -> dict:
    """
    Chat with Anthropic Claude API.

    Args:
        message: User message
        history: Prior conversation turns as list of {role, content} dicts

    Returns:
        dict with success, response, model, and usage info
    """
    try:
        import anthropic
    except ImportError:
        return {
            'error': 'Anthropic library not installed. Run: pip install anthropic',
            'status': 500
        }

    # Get API key from environment or settings
    api_key = getattr(settings, 'ANTHROPIC_API_KEY', None)
    if not api_key:
        api_key = os.environ.get('ANTHROPIC_API_KEY')

    if not api_key:
        return {
            'error': 'ANTHROPIC_API_KEY not configured. Set it in settings.py or environment variables.',
            'status': 500
        }

    try:
        # Create Anthropic client with proxy support
        import httpx
        proxy_url = os.environ.get('HTTPS_PROXY') or os.environ.get('HTTP_PROXY')

        if proxy_url:
            http_client = httpx.Client(proxy=proxy_url)
            client = anthropic.Anthropic(api_key=api_key, http_client=http_client)
        else:
            client = anthropic.Anthropic(api_key=api_key)

        prior = (history or [])[-20:]
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4096,
            messages=[*prior, {"role": "user", "content": message}],
            system=WAMA_SYSTEM_PROMPT
        )

        # Extract response text
        response_text = ""
        for block in response.content:
            if block.type == "text":
                response_text += block.text

        return {
            'success': True,
            'response': response_text,
            'model': response.model,
            'usage': {
                'input_tokens': response.usage.input_tokens,
                'output_tokens': response.usage.output_tokens
            }
        }

    except anthropic.BadRequestError as e:
        error_msg = str(e)
        if 'credit balance' in error_msg.lower():
            return {
                'error': 'Anthropic API: Insufficient credits. Please add credits at console.anthropic.com/settings/billing',
                'status': 402
            }
        return {'error': f'API Error: {error_msg}', 'status': 400}
    except anthropic.AuthenticationError:
        return {
            'error': 'Invalid API key. Please check your ANTHROPIC_API_KEY.',
            'status': 401
        }
    except Exception as e:
        return {'error': str(e), 'status': 500}


@require_http_methods(["POST"])
@csrf_protect
def ai_chat(request):
    """
    API endpoint for AI chat (all authenticated users).
    Supports both wama-dev-ai (Ollama) and Claude providers.
    Default: wama-dev-ai (local, privacy-first)
    """
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Authentification requise'}, status=401)
    try:
        data = json.loads(request.body)
        message = data.get('message', '').strip()
        provider = data.get('provider', 'wama-dev-ai')  # Default to local
        model = data.get('model', 'fast')  # Default Ollama model
        history = data.get('history', [])  # Prior conversation turns

        if not message:
            return JsonResponse({'error': 'Message is required'}, status=400)

        # Route to appropriate provider
        if provider == 'claude':
            result = _chat_with_claude(message, history=history)
        else:
            # Default: wama-dev-ai (Ollama) — pass user for tool-calling support
            result = _chat_with_ollama(message, model, user=request.user, history=history)

        # Check for errors
        if 'error' in result:
            status = result.pop('status', 500)
            return JsonResponse(result, status=status)

        return JsonResponse(result)

    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        logger.error(f"AI Chat error: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)


# ---------------------------------------------------------------------------
# Kokoro TTS (AI assistant vocalization)
# ---------------------------------------------------------------------------

_kokoro_pipelines = {}  # lang_code → KPipeline (lazy, cached)
_kokoro_lock = threading.Lock()


def _get_kokoro(lang_code: str):
    """Lazy-load and cache a Kokoro pipeline per language code (thread-safe)."""
    if lang_code not in _kokoro_pipelines:
        with _kokoro_lock:
            if lang_code not in _kokoro_pipelines:
                kokoro_dir = str(settings.MODEL_PATHS.get('speech', {}).get(
                    'kokoro', settings.AI_MODELS_DIR / 'models' / 'speech' / 'kokoro'))
                os.makedirs(kokoro_dir, exist_ok=True)
                # Must be set BEFORE importing kokoro/huggingface_hub
                _prev_hf = os.environ.get('HF_HUB_CACHE')
                os.environ['HF_HUB_CACHE'] = kokoro_dir
                os.environ['HUGGINGFACE_HUB_CACHE'] = kokoro_dir
                try:
                    from kokoro import KPipeline
                    _kokoro_pipelines[lang_code] = KPipeline(
                        lang_code=lang_code, repo_id='hexgrad/Kokoro-82M')
                finally:
                    # Restore so subsequent model downloads don't land in kokoro_dir
                    if _prev_hf is not None:
                        os.environ['HF_HUB_CACHE'] = _prev_hf
                        os.environ['HUGGINGFACE_HUB_CACHE'] = _prev_hf
                    else:
                        os.environ.pop('HF_HUB_CACHE', None)
                        os.environ.pop('HUGGINGFACE_HUB_CACHE', None)
    return _kokoro_pipelines[lang_code]


def _preload_kokoro():
    """Pre-warm Kokoro French pipeline in background to avoid blocking first TTS request."""
    try:
        _get_kokoro('f')
        logger.info("Kokoro TTS: French pipeline ready")
    except Exception as e:
        logger.warning(f"Kokoro TTS preload failed: {e}")


threading.Thread(target=_preload_kokoro, daemon=True, name='kokoro-preload').start()


@require_http_methods(["POST"])
@csrf_protect
def kokoro_tts(request):
    """
    Generate TTS audio with Kokoro and return a base64-encoded WAV.
    Body: {"text": "...", "voice": "ff_siwis"}
    """
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Authentification requise'}, status=401)
    try:
        data = json.loads(request.body)
        text = (data.get('text') or '').strip()
        voice = data.get('voice', 'ff_siwis')
        if not text:
            return JsonResponse({'error': 'text requis'}, status=400)

        # Derive lang_code from voice prefix (ff_siwis → 'f', am_adam → 'a')
        lang_code = voice[0] if voice else 'f'
        pipeline = _get_kokoro(lang_code)

        import io
        import wave
        import base64
        import numpy as np

        samples = []
        for _, _, audio in pipeline(text, voice=voice, speed=1.0):
            if audio is not None:
                arr = audio.numpy() if hasattr(audio, 'numpy') else np.array(audio)
                samples.append(arr)

        if not samples:
            return JsonResponse({'error': 'Aucun audio généré'}, status=500)

        audio_np = np.concatenate(samples).astype(np.float32)
        peak = np.abs(audio_np).max()
        if peak > 1e-6:
            audio_np /= peak
        audio_int16 = (audio_np * 32767).clip(-32768, 32767).astype(np.int16)

        buf = io.BytesIO()
        with wave.open(buf, 'wb') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(24000)
            wf.writeframes(audio_int16.tobytes())

        audio_b64 = base64.b64encode(buf.getvalue()).decode('utf-8')
        return JsonResponse({'audio_b64': audio_b64})

    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        logger.exception('kokoro_tts error')
        return JsonResponse({'error': str(e)}, status=500)


@require_http_methods(["POST"])
@csrf_protect
def switch_ui_mode(request):
    """Persist the user's UI mode preference (simple / advanced)."""
    if not request.user.is_authenticated:
        return JsonResponse({'ok': True})  # silently ignore for anonymous
    try:
        data = json.loads(request.body)
        mode = data.get('mode', 'advanced')
        if mode not in ('simple', 'advanced'):
            mode = 'advanced'
        from wama.accounts.models import UserProfile
        profile, _ = UserProfile.objects.get_or_create(user=request.user)
        profile.ui_mode = mode
        profile.save(update_fields=['ui_mode'])
        return JsonResponse({'ok': True, 'mode': mode})
    except Exception:
        return JsonResponse({'ok': True})
