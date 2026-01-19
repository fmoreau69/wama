"""
WAMA - Main Views
Handles home page and admin AI chat functionality
"""

import json
import logging
import os
from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_protect
from django.contrib.admin.views.decorators import staff_member_required
from django.conf import settings

logger = logging.getLogger(__name__)

# System prompt for WAMA AI assistant
WAMA_SYSTEM_PROMPT = """You are a helpful assistant for WAMA (Web App for Media Automation), a Django-based web application for media processing including video anonymization, audio transcription, voice synthesis, image generation, and image/video enhancement. Answer questions concisely and helpfully."""


def home(request):
    """Home page view with admin check for AI chat."""
    context = {
        'is_admin': request.user.is_staff if request.user.is_authenticated else False
    }
    return render(request, 'home.html', context)


def presentation(request):
    """WAMA presentation slideshow."""
    return render(request, 'includes/wama_presentation.html')


def _chat_with_ollama(message: str, model: str = "fast") -> dict:
    """
    Chat with local Ollama server (wama-dev-ai).

    Args:
        message: User message
        model: Model role from wama-dev-ai config ('dev', 'fast', 'ultra_fast', etc.)

    Returns:
        dict with success, response, model, and usage info
    """
    import httpx

    # Model mapping from wama-dev-ai config
    MODEL_MAP = {
        'dev': 'qwen3:30b-instruct',
        'coder': 'qwen3-coder:30b',
        'debug': 'deepseek-coder-v2:16b',
        'architect': 'qwen3:30b-thinking',
        'fast': 'qwen3:14b-q8_0',
        'ultra_fast': 'qwen3:8b-q8_0',
    }

    ollama_model = MODEL_MAP.get(model, model)
    ollama_url = "http://127.0.0.1:11434/api/chat"

    try:
        # Use httpx directly with trust_env=False to bypass proxy
        with httpx.Client(timeout=120.0, trust_env=False) as client:
            response = client.post(
                ollama_url,
                json={
                    "model": ollama_model,
                    "messages": [
                        {"role": "system", "content": WAMA_SYSTEM_PROMPT},
                        {"role": "user", "content": message}
                    ],
                    "options": {
                        "temperature": 0.7,
                        "num_predict": 4096,
                    },
                    "stream": False
                }
            )

            if response.status_code != 200:
                return {
                    'error': f'Ollama error: {response.text}',
                    'status': response.status_code
                }

            data = response.json()

            return {
                'success': True,
                'response': data.get("message", {}).get("content", ""),
                'model': f"wama-dev-ai ({ollama_model})",
                'usage': {
                    'input_tokens': data.get("prompt_eval_count", 0),
                    'output_tokens': data.get("eval_count", 0)
                }
            }

    except httpx.ConnectError:
        return {
            'error': 'Ollama server not running. Start it with: ollama serve',
            'status': 503
        }
    except httpx.TimeoutException:
        return {
            'error': 'Ollama request timed out. The model might be loading.',
            'status': 504
        }
    except Exception as e:
        error_msg = str(e)
        logger.error(f"Ollama error: {error_msg}")
        return {'error': f'Ollama error: {error_msg}', 'status': 500}


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
            # Default: wama-dev-ai (Ollama)
            result = _chat_with_ollama(message, model)

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
