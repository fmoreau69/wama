"""
WAMA - Main Views
Handles home page and admin AI chat functionality
"""

import json
import logging
import os
import re
from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_protect
from django.contrib.admin.views.decorators import staff_member_required
from django.conf import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# System prompts
# ---------------------------------------------------------------------------

WAMA_SYSTEM_PROMPT = """You are a helpful assistant for WAMA (Web App for Media Automation), a Django-based web application for media processing including video anonymization, audio transcription, voice synthesis, image generation, and image/video enhancement. Answer questions concisely and helpfully in French."""

WAMA_TOOLS_PROMPT = """
You can interact with WAMA applications by calling tools.
When you need to perform an action, output ONLY the JSON tool call on a single line, with NO surrounding text:
{"tool": "<name>", "args": {<arguments>}}

Available tools:
- list_user_files(folder="temp"): List the user's files. Folders: "temp" (temporary uploads), "anon_input" (anonymizer input), "anon_output" (anonymizer output).
- add_to_anonymizer(file_path, use_sam3=false, sam3_prompt="", classes=["face"], precision_level=50): Add a file to the anonymizer queue. file_path is the "path" value returned by list_user_files.
- start_anonymizer(media_id=null): Launch anonymizer processing. Provide media_id from add_to_anonymizer, or null to process all pending files.
- get_anonymizer_status(): Get the current status and progress of anonymizer jobs.
- sam3_examples(): Get examples of SAM3 text prompts for segmentation.

Rules:
- Make ONE tool call per turn. Wait for the result before calling another tool.
- When the user asks you to perform an action (add a file, launch processing, etc.), use the tools.
- When the user asks a question or wants information, answer directly without tools.
- Always confirm what you did after tool calls.
- Respond in French.

File search strategy:
- When the user mentions a file by name, FIRST call list_user_files(folder="anon_input"), THEN list_user_files(folder="temp") if not found.
- If the file is not found in any folder, tell the user to upload it via the WAMA File Manager at /filemanager/ or directly in the Anonymizer at /anonymizer/.
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
    'dev':        'qwen3:30b-instruct',
    'coder':      'qwen3-coder:30b',
    'debug':      'deepseek-coder-v2:16b',
    'architect':  'qwen3:30b-thinking',
    'fast':       'qwen3:14b-q8_0',
    'ultra_fast': 'qwen3:8b-q8_0',
}


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


def _chat_with_ollama(message: str, model: str = "fast", user=None) -> dict:
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

    Returns:
        dict with success, response, model, usage, tool_steps
    """
    from .tool_api import execute_tool

    ollama_model = _OLLAMA_MODEL_MAP.get(model, model)
    system_prompt = WAMA_SYSTEM_PROMPT + (WAMA_TOOLS_PROMPT if user else "")

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user",   "content": message},
    ]

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


def _chat_with_claude(message: str) -> dict:
    """
    Chat with Anthropic Claude API.

    Args:
        message: User message

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

        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=4096,
            messages=[{"role": "user", "content": message}],
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
@staff_member_required
def ai_chat(request):
    """
    API endpoint for admin AI chat.
    Supports both wama-dev-ai (Ollama) and Claude providers.
    Default: wama-dev-ai (local, privacy-first)
    """
    try:
        data = json.loads(request.body)
        message = data.get('message', '').strip()
        provider = data.get('provider', 'wama-dev-ai')  # Default to local
        model = data.get('model', 'fast')  # Default Ollama model

        if not message:
            return JsonResponse({'error': 'Message is required'}, status=400)

        # Route to appropriate provider
        if provider == 'claude':
            result = _chat_with_claude(message)
        else:
            # Default: wama-dev-ai (Ollama) — pass user for tool-calling support
            result = _chat_with_ollama(message, model, user=request.user)

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
