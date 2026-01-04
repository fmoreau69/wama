"""
WAMA - Main Views
Handles home page and admin AI chat functionality
"""

import json
import logging
from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_protect
from django.contrib.admin.views.decorators import staff_member_required
from django.conf import settings

logger = logging.getLogger(__name__)


def home(request):
    """Home page view with admin check for AI chat."""
    context = {
        'is_admin': request.user.is_staff if request.user.is_authenticated else False
    }
    return render(request, 'home.html', context)


@require_http_methods(["POST"])
@csrf_protect
@staff_member_required
def ai_chat(request):
    """
    API endpoint for admin AI chat using Anthropic Claude.
    Only accessible to staff members.
    """
    try:
        data = json.loads(request.body)
        message = data.get('message', '').strip()

        if not message:
            return JsonResponse({'error': 'Message is required'}, status=400)

        # Check if anthropic is installed
        try:
            import anthropic
        except ImportError:
            return JsonResponse({
                'error': 'Anthropic library not installed. Run: pip install anthropic'
            }, status=500)

        # Get API key from environment or settings
        api_key = getattr(settings, 'ANTHROPIC_API_KEY', None)
        if not api_key:
            import os
            api_key = os.environ.get('ANTHROPIC_API_KEY')

        if not api_key:
            return JsonResponse({
                'error': 'ANTHROPIC_API_KEY not configured. Set it in settings.py or environment variables.'
            }, status=500)

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
            messages=[
                {
                    "role": "user",
                    "content": message
                }
            ],
            system="You are a helpful assistant for WAMA (Web App for Media Automation), a Django-based web application for media processing including video anonymization, audio transcription, voice synthesis, image generation, and image/video enhancement. Answer questions concisely and helpfully."
        )

        # Extract response text
        response_text = ""
        for block in response.content:
            if block.type == "text":
                response_text += block.text

        return JsonResponse({
            'success': True,
            'response': response_text,
            'model': response.model,
            'usage': {
                'input_tokens': response.usage.input_tokens,
                'output_tokens': response.usage.output_tokens
            }
        })

    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except anthropic.BadRequestError as e:
        error_msg = str(e)
        if 'credit balance' in error_msg.lower():
            return JsonResponse({
                'error': 'Anthropic API: Insufficient credits. Please add credits at console.anthropic.com/settings/billing'
            }, status=402)
        return JsonResponse({'error': f'API Error: {error_msg}'}, status=400)
    except anthropic.AuthenticationError:
        return JsonResponse({
            'error': 'Invalid API key. Please check your ANTHROPIC_API_KEY.'
        }, status=401)
    except Exception as e:
        logger.error(f"AI Chat error: {str(e)}")
        return JsonResponse({'error': str(e)}, status=500)
