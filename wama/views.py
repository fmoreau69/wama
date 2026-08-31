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
# Assistant IA — le moteur (prompts, résolution de modèle, boucle agentique)
# est EXTRAIT vers wama/common/services/assistant_engine.py (2026-08-20) :
# UN cerveau pour N surfaces — cette vue web, l'API v1 token
# (/api/v1/assistant/chat/), et les adaptateurs de canaux à venir.
# ---------------------------------------------------------------------------
from wama.common.services.assistant_engine import (  # noqa: E402
    resolve_chat_model,
    run_assistant_turn,
)


#: Intitulés des rôles de la surface chat (le RÔLE est la valeur stable ; le nom du
#: modèle est résolu au rendu — cf. `_chat_model_options`).
_ROLE_LIBELLES = (
    ('fast', 'Fast'),
    ('ultra_fast', 'Ultra Fast'),
    ('dev', 'Dev'),
    ('coder', 'Coder'),
    ('architect', 'Architect'),
)


def _chat_model_options():
    """
    Options du sélecteur de modèle du chat — libellés RÉSOLUS PAR LE CATALOGUE au rendu.

    Remplace les libellés codés en dur du gabarit (2026-08-18) : « Qwen3.5 35B-A3B (Dev) »
    affichait un modèle REMPLACÉ depuis le 2026-08-12 (qwen3.6:35b) alors que la value
    (le rôle) était, elle, correctement résolue par `resolve_chat_model` — l'UI mentait
    sur ce que le backend faisait. Même leçon que `_safe_char_limit` : un nom figé
    meurt au premier remplacement de modèle par la prospection.
    """
    options = []
    for role, libelle in _ROLE_LIBELLES:
        try:
            nom = resolve_chat_model(role)
        except Exception:
            nom = None
        options.append({'value': role, 'label': f"{nom or '?'} ({libelle})"})
    return options


def home(request):
    """Home page view with admin check for AI chat."""
    # ⚠ NE PAS re-poser `is_admin` dans le contexte de cette vue — c'était le cas jusqu'au
    # 2026-08-31, avec `request.user.is_staff`. Le context processor `user_role` le fournit
    # DÉJÀ à toutes les pages, avec le prédicat canonique (`accounts.views.is_admin` =
    # superutilisateur ou groupe `admin`), et le contexte d'une vue ÉCRASE celui d'un
    # processor : le menu « Users »/« Models » de `header.html` (inclus par `base.html`,
    # donc rendu partout) suivait donc UNE règle sur `/` et UNE AUTRE sur toutes les autres
    # pages. Même menu, deux barèmes, selon l'endroit où on se trouve.
    # C'est exactement le défaut soldé le 27/08 sur le model_manager (S2,
    # `PROFILES_PERMISSIONS §8.9`, `accounts/tests_access_points.py`) ; celui-ci avait
    # échappé au balayage parce qu'il masque par le CONTEXTE et non par un décorateur —
    # aucun `is_staff` n'apparaissait dans une garde. « Deux barèmes pour une même question
    # ne restent d'accord que par chance. »
    # `is_staff` reste légitime AILLEURS (voir autrui : common/views, detail_registry…) :
    # le défaut n'était pas de l'utiliser, mais de l'appeler `is_admin`.
    from wama.accounts.views import is_admin as _predicat_admin
    est_admin = _predicat_admin(request.user)
    # Voix de l'assistant DÉRIVÉES de la langue du profil (brique commune) au lieu des 3
    # options écrites en dur dans le gabarit — qui ignoraient `preferred_language` et 13 des
    # 16 voix disponibles. `preferred_language` vient déjà du context processor global, mais
    # la LISTE doit être construite côté serveur : c'est là que vit la table des voix.
    from wama.common.tts.voices import choix_voix
    langue = getattr(getattr(request.user, 'profile', None), 'preferred_language', None) or 'fr'
    # Accueil DÉCLARÉ, variant selon l'état de connexion : un visiteur non identifié doit
    # toujours s'entendre dire le parcours (s'identifier, puis attendre la modération). Voir
    # `assistant_skills.greeting()` pour le pourquoi du déclaratif plutôt que du généré.
    from wama.common.utils.assistant_skills import greeting
    from wama.common.utils.volet import volet
    # ⚠ VARIABLE DÉDIÉE, et surtout PAS `is_admin` — qui vaut ici `is_staff`, un TROISIÈME
    # vocabulaire de rôle (les deux autres : groupes `dev`/`admin`/`developpeur`, tiers de
    # profil). Gater le fournisseur « abonnement » sur `is_staff` aurait fait diverger l'UI
    # de la garde serveur dans LES DEUX SENS : un membre du groupe `dev` autorisé par le
    # moteur mais sans l'option à l'écran, et un compte `is_staff` voyant une option que le
    # serveur lui refuse. La visibilité se calcule donc avec le MÊME prédicat que la garde
    # (`claude_code.subscription_allowed`, domicile unique) — c'est un test qui le verrouille.
    from wama.common.services.claude_code import subscription_allowed
    context = {
        # `is_admin` VOLONTAIREMENT ABSENT : il vient du context processor (cf. plus haut).
        'abonnement_visible': subscription_allowed(request.user),
        'accueil_assistant': greeting(request.user),
        # Résolution catalogue à chaque rendu : 5 requêtes DB, uniquement pour l'admin
        # qui voit la surface chat.
        'chat_model_options': _chat_model_options() if est_admin else [],
        'voix_assistant': choix_voix(langue),
        # Volet = l'AVATAR SEUL, en bloc de tête (`right_panel_top`, home.html). Les trois
        # sections restaient rendues SOUS lui — « Sélectionnez un fichier pour l'aperçu » sur
        # l'accueil — parce que `base.html` les servait à toute page (WAMA_VOLETS §5).
        # `tete=True` garde le volet ouvert pour l'avatar sans rien d'autre.
        'volet': volet(tete=True, medias=False, parametres=False, actions=False),
    }
    return render(request, 'home.html', context)


def presentation(request):
    """WAMA presentation slideshow."""
    return render(request, 'includes/wama_presentation.html')


def architecture(request):
    """WAMA technical/architectural presentation (accessible aux non-spécialistes)."""
    return render(request, 'includes/wama_architecture.html')


def fiches(request):
    """WAMA — système de fiches (manifestes) expliqué en vulgarisé pour un utilisateur."""
    return render(request, 'includes/wama_fiches.html')


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
        # Domaine d'intervention (`assistant_skills.DOMAINES`). Facultatif : sans lui,
        # l'assistant part en `general` et charge lui-même la compétence dont il a besoin
        # via l'outil `charger_competence`. Le passer ne sert qu'à l'AMORCER dans un
        # domaine — utile quand la surface le sait d'avance (futur sélecteur d'UI).
        # ⚠ Sans cette ligne, la surface WEB ne pouvait PAS amorcer un domaine, alors que
        # l'API v1 le pouvait déjà : les deux surfaces divergeaient en silence.
        domain = data.get('domain')

        if not message:
            return JsonResponse({'error': 'Message is required'}, status=400)

        # Moteur commun (assistant_engine) : cette vue n'est plus qu'une surface
        # cliente parmi N — même boucle à outils pour local ET cloud.
        result = run_assistant_turn(request.user, message, provider=provider,
                                    model=model, history=history, domain=domain)

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
                # Bascule SCOPÉE du cache HF (kokoro n'accepte pas de cache_dir=) —
                # brique commune, restaure env ET constantes huggingface_hub (le
                # save/restore local ne couvrait pas les constantes : dans un process
                # où le hub est déjà importé, l'env seul ne suffit pas).
                from wama.common.utils.hf_cache import hf_cache_scope
                with hf_cache_scope(kokoro_dir):
                    from kokoro import KPipeline
                    _kokoro_pipelines[lang_code] = KPipeline(
                        lang_code=lang_code, repo_id='hexgrad/Kokoro-82M')
    return _kokoro_pipelines[lang_code]


# NB : plus de thread de préchargement Kokoro ici. Il causait (a) une course d'imports
# accelerate et (b) le dump de modèles dans speech/kokoro (os.environ['HF_HUB_CACHE']
# global muté en concurrence). Le warm-loading est désormais assuré par le MICROSERVICE
# TTS dédié (tts_service.py, port 8001), que kokoro_tts() appelle ; `_get_kokoro` ci-dessus
# ne sert plus que de repli en-process si le service est indisponible.


def _clean_text_for_tts(text: str) -> str:
    """
    Nettoie le texte avant vocalisation : la TTS doit LIRE le texte, pas décrire les images.
    - Retire emojis/pictogrammes (sinon espeak verbalise leur nom Unicode → illisible).
    - Aplatit le Markdown (tableaux `|`/`---`, titres `#`, gras/italique `*`, liens, code).
    Préserve les accents (catégories Mn non touchées → français intact).
    """
    if not text:
        return text
    import re
    import unicodedata
    text = unicodedata.normalize('NFC', text)
    # Flèches et puces → virgule (pause) : sinon le mot suivant est enchaîné sans respiration
    # (ex. « Anonymisation → Masque » lu d'un trait). À faire AVANT le strip des symboles.
    text = re.sub(r'\s*[→⇒➜➔↦⇨▶►▸‣•◦∙]\s*', ', ', text)
    # Emojis / pictos / modificateurs (So, Sk), marques englobantes des keycaps (Me),
    # surrogates (Cs) + sélecteurs de variation, ZWJ, keycap combiner. NFC d'abord →
    # les accents français restent des codepoints uniques (Ll/Lu), donc non retirés.
    _EMOJI_EXTRA = {'‍', '︎', '️', '⃣'}  # ZWJ, VS15/16, keycap combiner
    text = ''.join(
        c for c in text
        if unicodedata.category(c) not in ('So', 'Sk', 'Cs', 'Me') and c not in _EMOJI_EXTRA
    )
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)        # [libellé](url) → libellé
    text = re.sub(r'^[ \t]*\|?[ \t:|-]{3,}\|?[ \t]*$', '', text, flags=re.M)  # séparateurs de table
    text = text.replace('|', ' ')                               # cellules de table
    text = re.sub(r'[#*`_>~]', '', text)                        # marqueurs Markdown
    text = _rendre_audible(text)
    text = re.sub(r'[ \t]{2,}', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


#: Ponctuation qui porte déjà une respiration — ne pas en ajouter une seconde.
#: ⚠ `)`, `»` et les guillemets en sont VOLONTAIREMENT absents : ils ferment une incise, ils
#: ne terminent pas une phrase. « …nettoyage vocal) » s'enchaînait donc sur l'item suivant —
#: le défaut même qu'on corrige. On ponctue APRÈS la fermeture : « …nettoyage vocal). »
_FIN_PONCTUEE = '.,;:!?…'


def _rendre_audible(text: str) -> str:
    """
    Traduit la MISE EN FORME VISUELLE en respirations audibles.

    Le nettoyage ci-dessus rendait le texte *prononçable* (plus d'emoji verbalisé, plus de
    tuyaux de tableau) ; il ne le rendait pas *écoutable*. Une liste à puces reste une
    succession de fragments SANS ponctuation : le moteur les enchaîne d'un trait et
    l'auditeur perd le fil (constaté par Fabien le 2026-08-31 sur le descriptif de WAMA lu
    par Kokoro — cinq sections, quinze items, aucune pause).

    ⚠ Le saut de ligne n'est PAS une pause pour un moteur TTS : ni Kokoro (espeak/misaki) ni
    XTTS n'en font une — seule la PONCTUATION en produit une. C'est tout le sujet : on ne
    reformule pas, on rend audible ce que l'œil lisait dans la disposition.

    Quatre gestes, tous réversibles à la lecture :
      • marqueur de puce en tête de ligne retiré (« - » se prononce « moins ») ;
      • fin de ligne non ponctuée → point : c'est LA pause qui manquait ;
      • « / » entre deux mots → « ou » (« audio/vidéo » se dit « audio barre oblique vidéo ») ;
      • « & » → « et » ;
      • tiret ISOLÉ en incise (« via Celery - vous recevrez ») → virgule : espeak le prononce
        « moins » ou l'avale, alors qu'il porte visuellement une respiration. Le tiret COLLÉ
        d'un mot composé (« arrière-plan ») n'est pas touché — c'est l'espacement qui distingue
        les deux.
    Une ligne déjà ponctuée (dont un titre en « : ») est laissée intacte.
    """
    text = re.sub(r'(?<=[\w])\s*&\s*(?=[\w])', ' et ', text)
    # `/` entre deux MOTS seulement : préserve les dates, fractions et chemins résiduels.
    text = re.sub(r'(?<=[^\W\d_])\s*/\s*(?=[^\W\d_])', ' ou ', text)

    lignes = []
    for ligne in text.split('\n'):
        nue = ligne.strip()
        if not nue:
            lignes.append('')
            continue
        # Puce de tête : tiret, astérisque, point médian, tirets longs.
        nue = re.sub(r'^[-*•·–—]+\s+', '', nue).strip()
        # Tiret d'incise → virgule. ⚠ DANS la boucle, et sur [ \t] SEULEMENT : écrit
        # `\s+` et appliqué au texte entier, il traversait les SAUTS DE LIGNE et fusionnait
        # toute la liste en une phrase (mesuré au test — la « correction » était pire que
        # le défaut). Une classe d'espaces qui inclut `\n` n'a rien à faire dans une règle
        # qui raisonne sur la LIGNE.
        nue = re.sub(r'(?<=\S)[ \t]+[-–—][ \t]+(?=\S)', ', ', nue)
        if nue and nue[-1] not in _FIN_PONCTUEE:
            nue += '.'
        lignes.append(nue)
    return '\n'.join(lignes)


def _tts_via_service(text: str, voice: str):
    """
    Génère la vocalisation via le microservice TTS (modèle chaud, process dédié → pas de
    course env dans Django). Renvoie le WAV en base64, ou None si le service est indisponible
    (→ l'appelant retombe sur Kokoro en-process).

    Mapping exact voix brute → (language, voice_preset) : le service TTS RECALCULE la même
    voix de son côté, il faut donc lui passer la langue qui redonne cette voix-là. La
    convention de nommage Kokoro est encapsulée par `common/tts/voices.langue_de_voix()`
    (elle était dépliée ici, en miroir du calcul aller du backend).
    """
    try:
        import base64
        from wama.common.tts.constants import ASSISTANT_TTS_ENGINE
        from wama.common.tts.service_client import tts_via_service
        from wama.common.tts.voices import langue_de_voix

        # Sens RETOUR (voix → langue) : brique COMMUNE. Le calcul était écrit ici en miroir
        # de celui du backend Kokoro — deux exemplaires d'une même table lue à l'envers.
        language, is_male = langue_de_voix(voice)
        voice_preset = 'male_1' if is_male else 'default'

        # Client COMMUN du service (2026-08-28) ; ici TOUTE indisponibilité — 503
        # « loading » compris — vaut repli en-process, d'où le except large.
        # Moteur DÉCLARÉ (constants.ASSISTANT_TTS_ENGINE — 'kokoro-onnx' par défaut
        # depuis le 2026-08-31, bascule par WAMA_ASSISTANT_TTS_ENGINE), plus un
        # littéral ici. Les NOMS DE VOIX sont identiques entre les deux moteurs
        # (mêmes voix Kokoro), donc le calcul voix→langue ci-dessus vaut pour les deux.
        wav = tts_via_service(text, ASSISTANT_TTS_ENGINE, language=language,
                              voice_preset=voice_preset, read_timeout=30, raw=True)
        return base64.b64encode(wav).decode('utf-8')
    except Exception as e:
        logger.info(f"[kokoro_tts] TTS service indisponible ({e}) → repli en-process")
    return None


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
        # Défaut = la voix de la LANGUE DU PROFIL, plus `ff_siwis` en dur. Un utilisateur dont
        # le profil dit `en` était vocalisé en français alors que le synthesizer, lui, respecte
        # `preferred_language` depuis toujours. Le client reste maître : s'il envoie `voice`,
        # c'est le sien qui prime — seul le DÉFAUT change. Vaut donc aussi pour une surface
        # sans sélecteur (API, bot), qui n'en enverra jamais.
        from wama.common.tts.voices import voix_pour
        langue = getattr(getattr(request.user, 'profile', None), 'preferred_language', None) or 'fr'
        voice = data.get('voice') or voix_pour(langue)
        if not text:
            return JsonResponse({'error': 'text requis'}, status=400)

        # Lire le texte, pas décrire les images : retire emojis/Markdown avant la TTS.
        text = _clean_text_for_tts(text)
        if not text:
            return JsonResponse({'error': 'texte vide après nettoyage'}, status=400)

        # 1) Voie normale : microservice TTS (modèle chaud, hors process Django).
        audio_b64 = _tts_via_service(text, voice)
        if audio_b64 is not None:
            return JsonResponse({'audio_b64': audio_b64})

        # 2) Repli en-process (service indisponible) — comportement historique, même voix.
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
