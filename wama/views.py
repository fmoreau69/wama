"""
WAMA - Main Views
Handles home page and admin AI chat functionality
"""

import json
import logging
import os
import re
import threading
from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_protect
from django.conf import settings

from wama.common.utils.tts_text import text_for_speech

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Assistant IA — le moteur (prompts, résolution de modèle, boucle agentique)
# est EXTRAIT vers wama/common/services/assistant_engine.py (2026-08-20) :
# UN cerveau pour N surfaces — cette vue web, l'API v1 token
# (/api/v1/assistant/chat/), et les adaptateurs de canaux à venir.
# ---------------------------------------------------------------------------
from wama.common.services.assistant_engine import run_assistant_turn  # noqa: E402


def _chat_thread(user) -> list:
    """Entrées d'affichage du fil `web` de `user` (vide sans compte ou sans fil)."""
    if not getattr(user, 'is_authenticated', False):
        return []
    from wama.common.models import Conversation
    from wama.common.services import conversation_store
    fil = Conversation.objects.filter(user=user, surface='web', thread_key='').first()
    entries = conversation_store.display_entries(fil)
    # Un traitement long lancé depuis le fil survit à la page : à son rechargement, la réponse qui
    # l'a lancé retrouve sa barre (`jobs`) tant qu'il tourne (2026-10-20). Les derniers tours
    # seulement — chaque élément se relit.
    from wama.common.services.job_follow_ups import turn_jobs
    steps_seen = 0
    for i in range(len(entries) - 1, -1, -1):
        if entries[i]['type'] != 'tool_steps' or i + 1 >= len(entries):
            continue
        steps_seen += 1
        if steps_seen > THREAD_JOBS_TURNS:
            break
        jobs = turn_jobs(user, entries[i]['steps'])
        if jobs and entries[i + 1]['type'] == 'assistant':
            entries[i + 1]['jobs'] = jobs
    return entries


def home(request):
    """Home page view with admin check for AI chat."""
    # ⚠ NE PAS re-poser `is_admin` dans le contexte de cette vue — c'était le cas jusqu'au
    # 2026-08-31, avec `request.user.is_staff`. Le context processor `user_role` le fournit
    # DÉJÀ à toutes les pages, avec le prédicat canonique (`accounts.views.is_admin` →
    # `permissions.is_admin_tier`, le niveau du profil), et le contexte d'une vue ÉCRASE celui d'un
    # processor : le menu « Users »/« Models » de `header.html` (inclus par `base.html`,
    # donc rendu partout) suivait donc UNE règle sur `/` et UNE AUTRE sur toutes les autres
    # pages. Même menu, deux barèmes, selon l'endroit où on se trouve.
    # C'est exactement le défaut soldé le 27/08 sur le model_manager (S2,
    # `PROFILES_PERMISSIONS §8.9`, `accounts/tests/tests_access_points.py`) ; celui-ci avait
    # échappé au balayage parce qu'il masque par le CONTEXTE et non par un décorateur —
    # aucun `is_staff` n'apparaissait dans une garde. « Deux barèmes pour une même question
    # ne restent d'accord que par chance. »
    # Depuis le 2026-10-21 (décision de Fabien), « administrateur » n'a plus qu'UNE définition
    # dans WAMA, le niveau du profil : `is_staff` n'est plus lu nulle part pour décider d'un
    # droit (il n'ouvre que le site d'administration Django, posé par `set_account_tier`).
    from wama.accounts.views import is_admin as _predicat_admin
    est_admin = _predicat_admin(request.user)
    # Accueil DÉCLARÉ, variant selon l'état de connexion : un visiteur non identifié doit
    # toujours s'entendre dire le parcours (s'identifier, puis attendre la modération). Voir
    # `assistant_skills.greeting()` pour le pourquoi du déclaratif plutôt que du généré.
    from wama.common.utils.assistant_skills import greeting
    from wama.common.utils.volet import volet
    # ⚠ VARIABLE DÉDIÉE, et non `is_admin` : le fournisseur « abonnement » est ouvert PLUS
    # LARGEMENT que l'administration (groupes `dev`/`developpeur` et tiers de profil y ont
    # droit aussi). La visibilité se calcule donc avec le MÊME prédicat que la garde serveur
    # (`claude_code.subscription_allowed`, domicile unique), sans quoi l'écran et la garde
    # divergeraient dans les deux sens — un test verrouille l'invariant sur 5 profils.
    # 2026-09-16 : le sélecteur de l'assistant est celui des APPS. Son schéma déclare le champ
    # `model` (source `catalog`, « auto » + modèles distants ouverts par les clés) et le curseur
    # Rapide ↔ Qualité ; les valeurs viennent du réglage DURABLE de l'utilisateur. Plus aucune
    # liste de fournisseurs ni de rôles dans le gabarit : le fournisseur se dérive du modèle.
    from wama.assistant.params import GROUPS_JSON as CHAT_GROUPS
    from wama.assistant.params import PARAMS_JSON as CHAT_PARAMS
    from wama.common.services.assistant_engine import assistant_settings
    context = {
        # `is_admin` VOLONTAIREMENT ABSENT : il vient du context processor (cf. plus haut).
        'accueil_assistant': greeting(request.user),
        # Résolution catalogue à chaque rendu : 5 requêtes DB, uniquement pour l'admin
        # qui voit la surface chat.
        # Schéma + valeurs du sélecteur, rendus par la brique commune `WamaParams` (json_script).
        'chat_params': CHAT_PARAMS,
        'chat_groups': CHAT_GROUPS,
        'chat_values': assistant_settings(request.user),
        # Fil `web` de l'utilisateur, relu du store SERVEUR (plus du localStorage) : la même
        # conversation se retrouve sur tout appareil.
        'chat_thread': _chat_thread(request.user),
        # Volet = l'AVATAR SEUL, en bloc de tête (`right_panel_top`, home.html). Les trois
        # sections restaient rendues SOUS lui — « Sélectionnez un fichier pour l'aperçu » sur
        # l'accueil — parce que `base.html` les servait à toute page (WAMA_VOLETS §5).
        # `tete=True` garde le volet ouvert pour l'avatar sans rien d'autre.
        # + 2026-10-18 (décision de Fabien) : la section « Paramètres » porte les RÉGLAGES de
        # l'assistant, comme le volet d'une app — ils encombraient la carte du chat. En mode
        # simplifié (volets masqués), la ⚙ du chat ouvre la modale commune.
        'volet': volet(tete=True, medias=False, parametres=True, actions=False),
        # Menu « Présentations & annexes » : les archives se listent depuis leur déclaration.
        'archived_presentations': [{'slug': k, 'label': v['label']}
                                   for k, v in ARCHIVED_PRESENTATIONS.items()],
        # … et les rapports, depuis LEUR déclaration (même geste).
        'reports': [{'slug': k, 'label': v['label'], 'detail': v['detail']}
                    for k, v in REPORTS.items()],
    }
    return render(request, 'home.html', context)


def presentation(request):
    """WAMA presentation — canvas zoomable (constat → quatre mondes → accès → fabrique → roadmap).

    La frise de la roadmap est LUE dans `ROADMAP.md` (`common/roadmap_timeline.py`), jamais
    recopiée dans le gabarit. Illisible, elle le DIT sur sa diapositive au lieu de casser la page.
    """
    return render(request, 'includes/wama_presentation.html', presentation_context())


def presentation_context():
    """Ce que le gabarit de la présentation reçoit — partagé par la page et son export PDF."""
    from wama.common.roadmap_timeline import milestones
    try:
        timeline, timeline_error = milestones(), ''
    except (OSError, ValueError) as exc:
        timeline, timeline_error = [], str(exc)
    return {'timeline': timeline, 'timeline_error': timeline_error}


# Présentations ARCHIVÉES (jamais détruites, décision Fabien 2026-09-25) : slug → gabarit.
# Ajouter une version = y déplacer l'ancien gabarit (git mv) et déclarer sa ligne ici ;
# le menu de l'accueil les liste depuis ce même dict.
ARCHIVED_PRESENTATIONS = {
    '2026-v1': {
        'template': 'includes/archive/wama_presentation_2026-v1.html',
        'label': 'Présentation v1 (diaporama, 2026)',
    },
    # Remplacée le 2026-10-13 par la v3, resserrée pour un exposé de 20 minutes.
    '2026-v2': {
        'template': 'includes/archive/wama_presentation_2026-v2.html',
        'label': 'Présentation v2 (canvas, octobre 2026)',
    },
    # Remplacée le 2026-10-03 par l'architecture sur le moteur « canvas » de la présentation v2.
    'architecture-2026-v1': {
        'template': 'includes/archive/wama_architecture_2026-v1.html',
        'label': 'Architecture v1 (diaporama, juin 2026)',
    },
}


def presentation_archive(request, slug):
    """Une présentation archivée, servie telle quelle."""
    from django.http import Http404
    entry = ARCHIVED_PRESENTATIONS.get(slug)
    if entry is None:
        raise Http404(f"Présentation archivée inconnue : {slug}")
    return render(request, entry['template'])


def presentation_access_cases(request):
    """Cas du modèle d'accès (tier × rôles × app) pour la vue 3D des droits de la présentation.

    Calculé par `accounts.permissions.access_cases()` sur la politique EFFECTIVE : la
    présentation montre les droits réels, pas une copie. Mis en cache une minute.
    """
    from django.core.cache import cache
    from wama.accounts.permissions import access_cases
    data = cache.get('presentation:access_cases')
    if data is None:
        data = access_cases()
        cache.set('presentation:access_cases', data, 60)
    return JsonResponse(data)


def architecture(request):
    """WAMA technical/architectural presentation (accessible aux non-spécialistes)."""
    return render(request, 'includes/wama_architecture.html')


def fiches(request):
    """WAMA — système de fiches (manifestes) expliqué en vulgarisé pour un utilisateur."""
    return render(request, 'includes/wama_fiches.html')


# RAPPORTS servis depuis l'accueil (« Présentations & annexes », catégorie Rapports) : slug →
# gabarit, titre, ligne de détail. Le menu les liste depuis cette déclaration, comme les archives :
# un rapport s'AJOUTE par sa ligne, jamais par une entrée de menu écrite à la main. La génération
# automatique des rapports d'évaluation (WAMA_QUALITE, « Rapports d'évaluation générés ») y
# déclarera les siens.
REPORTS = {
    'transcription': {
        'template': 'includes/wama_rapport_transcription.html',
        'label': 'Évaluation des moteurs de transcription',
        'detail': 'Mesuré dans WAMA, octobre 2026',
    },
    'cam-analyzer': {
        'template': 'includes/wama_rapport_cam_analyzer.html',
        'label': 'Analyse vidéo de la navette aux intersections',
        'detail': 'Pipeline du cam_analyzer sur les données ENA, généré depuis les registres',
    },
    'anonymizer': {
        'template': 'includes/wama_rapport_anonymizer.html',
        'label': "Évaluation des détecteurs de l'Anonymizer",
        'detail': 'Visages (WIDER FACE) et plaques, généré depuis les mesures du banc',
    },
}


def report(request, slug):
    """Un rapport déclaré dans `REPORTS`, servi tel quel."""
    from django.http import Http404
    entry = REPORTS.get(slug)
    if entry is None:
        raise Http404(f"Rapport inconnu : {slug}")
    return render(request, entry['template'])


# Pages de l'accueil exportables en PDF (`<page>/pdf/`) : nom de route → gabarit, et si c'est une
# présentation « canvas » (une page 16:9 par étape) plutôt qu'un document A4. Les rapports de
# `REPORTS` le sont tous, en document. Les archives ne le sont pas : autre moteur de diaporama.
PDF_PAGES = {
    # `context` : la fonction qui donne au gabarit ce que lui donne sa vue (la frise, ici).
    'presentation': {'template': 'includes/wama_presentation.html', 'slides': True,
                     'context': presentation_context},
    'architecture': {'template': 'includes/wama_architecture.html', 'slides': True},
    'fiches': {'template': 'includes/wama_fiches.html', 'slides': False},
}


def page_pdf(request, page, slug=None):
    """Le PDF d'une page de `PDF_PAGES` (ou du rapport `slug`), rendu hors serveur par Chromium."""
    from django.http import FileResponse, Http404, HttpResponse
    from django.urls import reverse
    from wama.common.services.page_pdf import page_pdf as build_pdf
    if page == 'report':
        entry = REPORTS.get(slug)
        if entry is None:
            raise Http404(f"Rapport inconnu : {slug}")
        template, slides, page_path, name = entry['template'], False, reverse('report', args=[slug]), slug
    elif page in PDF_PAGES:
        entry = PDF_PAGES[page]
        template, slides, page_path, name = entry['template'], entry['slides'], reverse(page), page
    else:
        raise Http404(f"Page sans export PDF : {page}")
    context = entry['context']() if entry.get('context') else None
    pdf = build_pdf(request, template, page_path=page_path, slides=slides, context=context)
    if pdf is None:
        return HttpResponse("Export PDF indisponible : le navigateur de rendu (Chromium) n'a pas pu "
                            "produire le document sur ce serveur.", status=503,
                            content_type='text/plain; charset=utf-8')
    return FileResponse(open(pdf, 'rb'), content_type='application/pdf', as_attachment=True,
                        filename=f'wama-{name}.pdf')


#: Ce que l'assistant répond pendant qu'une libération de la carte est en cours — un message
#: d'attente automatique, jamais un silence ni une erreur nue (l'utilisateur doit savoir).
_RELEASE_WAIT_MESSAGE = ("Un traitement lourd libère la carte graphique en ce moment : je reste "
                         "silencieux quelques instants pour ne pas la reprendre. Réessayez dans "
                         "une minute.")


def _turn_message(user, data) -> str:
    """Le message d'un tour web : le texte, et les fichiers GLISSÉS sur le chat (2026-10-18) — la
    graphie de la passerelle (`assistant_engine.message_with_deposits`). Seuls les fichiers que
    l'utilisateur peut LIRE entrent (`filemanager.services.resoudre_chemin_lisible`, la garde du
    gestionnaire de fichiers) : un chemin posté n'est pas un chemin à soi."""
    from wama.common.services.assistant_engine import message_with_deposits
    from wama.filemanager.services import resoudre_chemin_lisible
    paths = [p for p in (data.get('files') or [])[:20]
             if isinstance(p, str) and resoudre_chemin_lisible(user, p)[0] is not None]
    return message_with_deposits(str(data.get('message') or ''), paths)


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
        message = _turn_message(request.user, data)
        # Rien d'imposé par la surface : le fournisseur et le modèle se résolvent par le réglage
        # durable de l'utilisateur, puis par le tirage « auto » commun (`resolve_turn_model`).
        provider = data.get('provider') or None
        model = data.get('model') or None
        # L'historique n'est PLUS fourni par le navigateur (2026-09-15) : il est tenu côté
        # SERVEUR, comme pour Discord et l'API (`conversation_turn`, fil `web` de l'utilisateur).
        # Domaine d'intervention (`assistant_skills.DOMAINES`). Facultatif : sans lui,
        # l'assistant part en `general` et charge lui-même la compétence dont il a besoin
        # via l'outil `charger_competence`. Le passer ne sert qu'à l'AMORCER dans un
        # domaine — utile quand la surface le sait d'avance (futur sélecteur d'UI).
        # ⚠ Sans cette ligne, la surface WEB ne pouvait PAS amorcer un domaine, alors que
        # l'API v1 le pouvait déjà : les deux surfaces divergeaient en silence.
        domain = data.get('domain')

        if not message:
            return JsonResponse({'error': 'Message is required'}, status=400)

        # Fenêtre de LIBÉRATION de la carte (B1, 2026-09-20 — décision Fabien du 16/09) :
        # l'assistant reste MUET et répond un message d'attente automatique. Il charge un LLM
        # (Ollama) et une voix : répondre maintenant rechargerait ce que le gouverneur vient
        # de faire rendre pour un traitement qu'un utilisateur a explicitement demandé.
        from wama.common.services.resource_governor import release_in_progress
        if release_in_progress():
            return JsonResponse({'response': _RELEASE_WAIT_MESSAGE, 'busy': True})

        # Moteur commun (assistant_engine) : cette vue n'est plus qu'une surface
        # cliente parmi N — même boucle à outils pour local ET cloud, même store.
        from wama.common.services.assistant_engine import conversation_turn
        result = conversation_turn(request.user, message, surface='web', provider=provider,
                                   model=model, domain=domain)
        _turn_follow_ups(request, result)

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


def _turn_follow_ups(request, result) -> None:
    """Les fins de tâche ARRIVÉES pendant ce tour (`job_notices`, `conversation_turn`) racontées
    comme une relève de la cloche (`web_follow_ups`) et rendues avec la réponse (`follow_ups`) : la
    cloche a pu passer avant que le tour soit au fil — une tâche plus rapide que la réponse qui
    l'a lancée n'était alors jamais racontée (2026-10-18)."""
    notices = result.pop('job_notices', None)
    if notices:
        from wama.common.services.job_follow_ups import web_follow_ups
        result['follow_ups'] = web_follow_ups(request.user, notices,
                                              absolute=request.build_absolute_uri)
    # Les éléments que le tour a lancés et qui tournent ENCORE : la réponse les porte, le chat en
    # suit la progression sous elle (2026-10-20, `ai_chat_jobs`) — l'utilisateur n'a plus à
    # redemander où en est un traitement long ; sa fin reste racontée par la relève.
    if result.get('tool_steps'):
        from wama.common.services.job_follow_ups import turn_jobs
        jobs = turn_jobs(request.user, result['tool_steps'])
        if jobs:
            result['jobs'] = jobs


#: Tours relus, à l'affichage du fil, pour y remettre la progression des jobs encore en cours.
THREAD_JOBS_TURNS = 10


@require_http_methods(["GET"])
def ai_chat_jobs(request):
    """L'état des éléments qu'un tour de l'assistant a lancés — la barre de progression de
    l'échange l'interroge (2026-10-20). `?items=famille:id,famille:id` ; chacun rendu par
    `tool_api.job_progress` (la ligne du geste « statut », bornée aux éléments de l'utilisateur) —
    un élément inconnu ou à autrui est simplement absent de la réponse."""
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Authentification requise'}, status=401)
    from wama.common.services.job_follow_ups import TURN_JOBS_MAX
    from wama.tool_api import job_progress
    jobs = []
    for key in (request.GET.get('items') or '').split(',')[:TURN_JOBS_MAX]:
        family, _, pk = key.strip().rpartition(':')
        row = job_progress(request.user, family, pk) if family and pk.isdigit() else None
        if row:
            jobs.append(row)
    return JsonResponse({'jobs': jobs})


@require_http_methods(["POST"])
@csrf_protect
def ai_chat_follow_ups(request):
    """Les FINS DE TÂCHE à raconter dans le fil web de l'assistant (2026-10-18).

    La cloche du navigateur relève les notifications et en annonce l'arrivée
    (`wama:notifications`) ; le chat poste ici leurs ids. Celles d'une tâche lancée DEPUIS ce fil
    sont enregistrées au fil et rendues comme des tours de l'assistant — la brique commune
    `job_follow_ups`, celle de la passerelle pour les canaux. Une notification se raconte une fois,
    quel que soit le nombre d'onglets ouverts."""
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Authentification requise'}, status=401)
    try:
        data = json.loads(request.body or '{}')
    except json.JSONDecodeError:
        return JsonResponse({'error': 'JSON invalide'}, status=400)
    from wama.common.services.job_follow_ups import web_follow_ups
    return JsonResponse({'follow_ups': web_follow_ups(request.user, data.get('ids') or [],
                                                      absolute=request.build_absolute_uri)})


@require_http_methods(["GET", "POST"])
@csrf_protect
def ai_chat_settings(request):
    """Réglages de l'assistant (modèle, curseur, voix) — enregistrés par la brique commune.

    Même chemin que les apps : les valeurs sont bornées par le SCHÉMA (`coerce_params`) et
    persistées par `user_settings` (app `assistant`). Elles valent alors pour TOUTES les
    surfaces, la passerelle comprise.

    GET (2026-10-18) : `{schema, groups, values}` — ce que la modale ⚙ commune
    (`WamaParams.settingsModal`) rend depuis le chat de n'importe quelle page, volets masqués
    (mode simplifié) compris. POST : du JSON (le volet de l'accueil) ou le FORMULAIRE que poste
    la modale commune — une route, deux transports.
    """
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Authentification requise'}, status=401)
    from wama.assistant.params import GROUPS_JSON, PARAMS_JSON, USER_SETTINGS_DEFAULTS
    if request.method == 'GET':
        from wama.common.services.assistant_engine import assistant_settings
        return JsonResponse({'schema': PARAMS_JSON, 'groups': GROUPS_JSON,
                             'values': assistant_settings(request.user)})
    if 'json' in (request.content_type or ''):
        try:
            data = json.loads(request.body or '{}')
        except json.JSONDecodeError:
            return JsonResponse({'error': 'JSON invalide'}, status=400)
    else:
        data = request.POST.dict()
        data.pop('csrfmiddlewaretoken', None)

    from wama.common.utils.auto_model import is_auto, read_quality_intent
    from wama.common.utils.param_schema import coerce_params
    from wama.common.utils.user_settings import save_user_app_settings

    # Les numériques sont bornés par le SCHÉMA ; le curseur de qualité a son helper commun
    # (`read_quality_intent` : type `intent`, hors du champ de `coerce_params`) ; le modèle est
    # validé à part, contre le catalogue et les clés de l'utilisateur.
    # Seuls ceux PRÉSENTS dans la requête (2026-10-21) : `coerce_params` rend aussi le défaut des
    # absents — une température laissée hors du POST (le volet n'envoie que le modèle) serait
    # revenue à « celle du modèle » à chaque choix de modèle.
    valeurs = {k: v for k, v in coerce_params(PARAMS_JSON, data).items()
               if k in USER_SETTINGS_DEFAULTS and k in data}
    # Les INTERRUPTEURS du schéma (avatar parlant, avatar replié) : `coerce_params` ne borne
    # que le numérique, un toggle se lit ici — en booléen, quelle que soit la graphie du client
    # (`false`/`0` d'un formulaire valent False). Seuls ceux PRÉSENTS dans la requête sont
    # écrits : un réglage absent n'est pas un réglage remis à zéro.
    for p in PARAMS_JSON:
        if p.get('type') == 'toggle' and p['name'] in data and p['name'] in USER_SETTINGS_DEFAULTS:
            raw = data.get(p['name'])
            valeurs[p['name']] = (raw.strip().lower() not in ('', '0', 'false', 'off', 'no')
                                  if isinstance(raw, str) else bool(raw))
    if 'quality_intent' in data:
        valeurs['quality_intent'] = read_quality_intent(data.get('quality_intent'))
    if 'model' in data:
        modele = (data.get('model') or '').strip()
        if not is_auto(modele):
            from wama.model_manager.models import AIModel
            from wama.model_manager.services.cloud_models import allowed_cloud_keys
            ligne = AIModel.objects.filter(model_key=modele, is_available=True).first()
            if ligne is None:
                return JsonResponse({'error': f"Modèle inconnu du catalogue : {modele}"}, status=400)
            # Un modèle DISTANT doit être ouvert par les clés de CET utilisateur : le refuser ici
            # évite d'enregistrer un choix que chaque tour refuserait ensuite.
            if ligne.execution == 'cloud' and modele not in allowed_cloud_keys(request.user,
                                                                              automatic=False):
                return JsonResponse({'error': "Ce modèle distant n'est pas ouvert par vos clés "
                                              "d'API, ou votre profil est en « 100 % local »."},
                                    status=403)
        valeurs['model'] = modele or USER_SETTINGS_DEFAULTS['model']
    # Le modèle de VOIX et la voix (2026-10-28) : un modèle de synthèse que le compte voit, une
    # voix que la source commune lui propose — jamais un choix que la vocalisation refuserait.
    if 'voice_model' in data:
        voice_model = (data.get('voice_model') or '').strip()
        if not is_auto(voice_model):
            # Le domaine du menu (`options_query` du schéma) : ce qui s'y choisit, rien d'autre.
            from wama.model_manager.models import AIModel
            from wama.model_manager.services.model_selector import domain_q
            query = next(p['options_query'] for p in PARAMS_JSON if p['name'] == 'voice_model')
            if not (AIModel.objects.catalogue_visible_to(request.user)
                    .filter(domain_q(query), model_key=voice_model).exists()):
                return JsonResponse({'error': f"Modèle de voix inconnu : {voice_model}"}, status=400)
        valeurs['voice_model'] = voice_model or USER_SETTINGS_DEFAULTS['voice_model']
    if 'voice_preset' in data:
        from wama.common.utils.voice_options import voice_display_options
        voice = (data.get('voice_preset') or '').strip() or USER_SETTINGS_DEFAULTS['voice_preset']
        if voice not in {v for v, _ in voice_display_options(request.user)}:
            return JsonResponse({'error': f"Voix inconnue : {voice}"}, status=400)
        valeurs['voice_preset'] = voice
    if not valeurs:
        return JsonResponse({'error': 'Aucun réglage connu dans la requête'}, status=400)
    save_user_app_settings(request.user, 'assistant', valeurs)
    return JsonResponse({'success': True, 'settings': valeurs})


@require_http_methods(["POST"])
@csrf_protect
def ai_chat_stream(request):
    """UN tour d'assistant EN FLUX (SSE) — levier 5 de `WAMA_LLM §1bis`.

    MÊME moteur, MÊME fil, MÊMES gardes que `ai_chat` : cette vue n'est qu'un second
    TRANSPORT. C'est la condition pour qu'elle n'ouvre aucune divergence — le tour synchrone
    reste le chemin de l'API v1, de la passerelle, et du repli quand le navigateur ne sait pas
    lire un flux.

    ⚠ POURQUOI UN FIL D'EXÉCUTION. `conversation_turn` est bloquante et rend à la fin ; on ne
    peut pas `yield` depuis le rappel qu'elle appelle. Le moteur tourne donc dans un thread qui
    POUSSE ses événements dans une file, et la vue les tire pour les écrire. L'ORM y est touché
    (store de conversation) : les connexions sont refermées en sortie, comme dans tout worker.

    Événements : `delta` (fragment de réponse), `step` (outil joué), `done` (réponse complète,
    modèle, étapes — c'est LUI qui fait foi pour l'affichage final et la trace), `error`.
    Un commentaire SSE part toutes les 15 s tant que rien n'arrive : un modèle qui se charge
    peut rester muet plus longtemps qu'un proxy n'est patient.
    """
    import queue
    import threading

    from django.db import close_old_connections
    from django.http import StreamingHttpResponse

    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Authentification requise'}, status=401)
    try:
        data = json.loads(request.body or '{}')
    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    message = _turn_message(request.user, data)
    if not message:
        return JsonResponse({'error': 'Message is required'}, status=400)

    # MÊME garde que le tour synchrone : pendant une libération de la carte, l'assistant reste
    # muet et le dit. La dupliquer serait une divergence ; on la lit au même endroit.
    from wama.common.services.resource_governor import release_in_progress
    if release_in_progress():
        return JsonResponse({'response': _RELEASE_WAIT_MESSAGE, 'busy': True})

    user, domain = request.user, data.get('domain')
    # Modèle imposé pour CE message seul — le relais PROPOSÉ quand le modèle choisi est saturé
    # (2026-10-13) ; même paramètre que le tour synchrone, mêmes gardes (`cloud_access`).
    model = data.get('model') or None
    events: 'queue.Queue' = queue.Queue()

    def engine():
        from wama.common.services.assistant_engine import conversation_turn
        try:
            result = conversation_turn(user, message, surface='web', domain=domain,
                                       model=model, on_event=events.put)
            _turn_follow_ups(request, result)
            events.put({'type': 'done', 'result': result})
        except Exception as e:                      # jamais de trace nue vers le navigateur
            logger.exception('ai_chat_stream')
            events.put({'type': 'error', 'error': str(e)})
        finally:
            close_old_connections()
            events.put(None)

    threading.Thread(target=engine, daemon=True, name='wama-assistant-stream').start()

    def stream():
        while True:
            try:
                event = events.get(timeout=15)
            except queue.Empty:
                yield ': keep-alive\n\n'
                continue
            if event is None:
                return
            yield 'data: ' + json.dumps(event, ensure_ascii=False, default=str) + '\n\n'

    response = StreamingHttpResponse(stream(), content_type='text/event-stream')
    response['Cache-Control'] = 'no-cache'
    # `X-Accel-Buffering` est lu par nginx ; Apache, lui, relaie le chunked au fil de l'eau.
    # Posé quand même : le frontal de production changera (`ROADMAP §11`).
    response['X-Accel-Buffering'] = 'no'
    return response


@require_http_methods(["GET"])
def ai_chat_thread(request):
    """Le fil `web` de l'utilisateur, au format d'affichage — pour le mini-chat du volet droit
    (toutes les pages, 2026-09-22) : MÊME fil que l'accueil, chargé à la demande plutôt que rendu
    dans chaque page."""
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Authentification requise'}, status=401)
    return JsonResponse({'entries': _chat_thread(request.user)})


@require_http_methods(["POST"])
@csrf_protect
def ai_chat_clear(request):
    """« Effacer » du chat web : supprime le fil `web` de l'utilisateur (store commun)."""
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Authentification requise'}, status=401)
    from wama.common.services import conversation_store
    cleared = conversation_store.clear_thread(request.user, surface='web', thread_key='')
    return JsonResponse({'success': True, 'cleared': cleared})


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
                # 3ᵉ VOIE (ROADMAP §5b, 2026-09-04) — REMPLACE la bascule scopée du cache.
                # `KModel` accepte des CHEMINS : on range les poids dans `speech/kokoro` et
                # on les lui passe. Différence décisive avec le scope : celui-ci restaurait
                # l'environnement mais JAMAIS les fichiers — il laissait donc les
                # sous-dépendances tirées pendant le chargement dans le dossier kokoro
                # (c'est l'origine documentée du dump de modèles étrangers ici même).
                from pathlib import Path as _P

                from kokoro import KModel, KPipeline
                from wama.common.utils.hf_weights import poids_locaux
                _repo = 'hexgrad/Kokoro-82M'
                _racine = poids_locaux(_repo, kokoro_dir)
                _modele = KModel(
                    repo_id=_repo,
                    config=str(_P(_racine) / 'config.json'),
                    model=str(_P(_racine) / KModel.MODEL_NAMES[_repo]),
                )
                _kokoro_pipelines[lang_code] = KPipeline(
                    lang_code=lang_code, repo_id=_repo, model=_modele)
    return _kokoro_pipelines[lang_code]


# NB : plus de thread de préchargement Kokoro ici. Il causait (a) une course d'imports
# accelerate et (b) le dump de modèles dans speech/kokoro (os.environ['HF_HUB_CACHE']
# global muté en concurrence). Le warm-loading est désormais assuré par le MICROSERVICE
# TTS dédié (common/tts/service.py, port 8001), que kokoro_tts() appelle ; `_get_kokoro` ci-dessus
# ne sert plus que de repli en-process si le service est indisponible.


# Le nettoyage du texte A DIRE est une BRIQUE COMMUNE depuis le 2026-09-26 :
# `common/utils/tts_text.py`. Il etait ecrit ici ET dans le synthesizer, sous le MEME nom,
# avec deux comportements disjoints - cette vue avait les respirations et le retrait des
# emojis, l'autre celui des URL. Les deux surfaces passent par la meme chaine maintenant.


def _voice_options(user) -> dict:
    """Les PAUSES de la voix, du réglage DURABLE de l'assistant (`assistant/params.py`,
    2026-10-18) — lues ici, côté serveur, pour toute surface qui vocalise : le navigateur n'a
    rien à transmettre, et une surface sans volet (API, canal) parle pareil."""
    from wama.common.services.assistant_engine import assistant_settings
    settings_ = assistant_settings(user)
    return {'sentence_pause': settings_.get('voice_sentence_pause'),
            'clause_pause': settings_.get('voice_clause_pause')}


def _tts_via_service(text: str, voice: dict, options: dict = None, user=None):
    """
    Génère la vocalisation via le microservice TTS (modèle chaud, process dédié → pas de
    course env dans Django). Renvoie le WAV en base64, ou None si le service est indisponible
    (→ l'appelant retombe sur Kokoro en-process).

    `voice` : `{model, voice_preset, language}` (`common/tts/assistant_voice.assistant_voice`,
    2026-10-28) — le modèle choisi ou tiré, la voix, la langue du profil. Le moteur se résout au
    catalogue par le client commun (`tts_engine_declared`), comme pour le synthesizer ; la voix
    clonée d'un moteur qui clone, par la même porte (`speaker_wav_for`). Jusque-là : une
    constante d'environnement pour le moteur, et le nom d'une voix Kokoro relu à l'envers en
    (langue, genre) — R184.
    """
    try:
        import base64
        from wama.common.tts.service_client import tts_via_service
        from wama.common.tts.voice_refs import speaker_wav_for

        if not voice.get('model'):
            raise RuntimeError("aucun modèle de voix temps réel installé")
        # Client COMMUN du service (2026-08-28) ; ici TOUTE indisponibilité — 503
        # « loading » compris — vaut repli en-process, d'où le except large.
        wav = tts_via_service(
            text, voice['model'], language=voice['language'], voice_preset=voice['voice_preset'],
            speaker_wav=speaker_wav_for(voice['model'], voice['voice_preset'], user,
                                        language=voice['language']),
            options=options, read_timeout=30, raw=True, user=user)
        return base64.b64encode(wav).decode('utf-8')
    except Exception as e:
        logger.info(f"[kokoro_tts] TTS service indisponible ({e}) → repli en-process")
    return None


def _tts_stream_response(text: str, voice: dict, options: dict, user):
    """La voix rendue AU FIL DE L'EAU par le service (`tts_stream_via_service`), en
    `StreamingHttpResponse` — ou None si le service ne répond pas (l'appelant rend la réponse
    entière). `X-Spoken` : le texte EFFECTIVEMENT dit, encodé pour un en-tête (l'écho de la voix se
    reconnaît sur lui)."""
    try:
        from urllib.parse import quote

        from django.http import StreamingHttpResponse

        from wama.common.tts.service_client import tts_stream_via_service
        from wama.common.tts.voice_refs import speaker_wav_for
        rate, chunks = tts_stream_via_service(
            text, voice['model'], language=voice['language'], voice_preset=voice['voice_preset'],
            speaker_wav=speaker_wav_for(voice['model'], voice['voice_preset'], user,
                                        language=voice['language']),
            options=options, user=user)
    except Exception as e:
        logger.info(f"[kokoro_tts] flux indisponible ({e}) → réponse entière")
        return None
    response = StreamingHttpResponse(chunks, content_type='audio/L16')
    response['X-Sample-Rate'] = str(rate)
    response['X-Spoken'] = quote(text)
    # Aucun tampon entre le service et le navigateur (proxy frontal compris) : c'est tout l'objet.
    response['X-Accel-Buffering'] = 'no'
    response['Cache-Control'] = 'no-cache'
    return response


@require_http_methods(["POST"])
@csrf_protect
def kokoro_tts(request):
    """
    La voix de l'assistant : le texte dit par son modèle de voix, en WAV base64.
    Body: {"text": "..."} — le modèle et la voix sont les réglages DURABLES du compte
    (`assistant/params.py` : `voice_model`, `voice_preset`, 2026-10-28), la langue celle de son
    profil : une surface sans sélecteur (API, canal) parle comme l'accueil.

    `pronunciation` (facultatif, 2026-10-27) : la clé d'une prononciation que le compte VOIT —
    elle est dite pour cette demande, la sienne ou celle qu'on lui partage : on écoute une
    entrée avant de l'adopter (page des prononciations).
    """
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Authentification requise'}, status=401)
    try:
        data = json.loads(request.body)
        text = (data.get('text') or '').strip()
        from wama.common.tts.assistant_voice import assistant_voice
        voice = assistant_voice(request.user)
        if not text:
            return JsonResponse({'error': 'text requis'}, status=400)

        # Lire le texte, pas décrire les images : retire emojis/Markdown avant la TTS.
        text = text_for_speech(text)
        if not text:
            return JsonResponse({'error': 'texte vide après nettoyage'}, status=400)

        # Fenêtre de libération de la carte (B1) : pas de voix — ni par le service (qui vient
        # de se décharger), ni par le repli en-process (qui chargerait Kokoro dans gunicorn).
        from wama.common.services.resource_governor import release_in_progress
        if release_in_progress():
            return JsonResponse({'error': _RELEASE_WAIT_MESSAGE, 'busy': True}, status=503)

        # 1) Voie normale : microservice TTS (modèle chaud, hors process Django).
        # `spoken` : le texte EFFECTIVEMENT dit (2026-10-18). Le navigateur cale les lèvres de
        # l'avatar et reconnaît l'écho de la voix sur CE texte — il ne nettoie plus rien
        # lui-même : il le faisait à sa façon, en effaçant le code en ligne.
        from wama.common.services.user_pronunciations import tried_entry
        tried = tried_entry(request.user, data.get('pronunciation'))
        options = {**_voice_options(request.user), **({'lexicon': tried} if tried else {})}
        # 1 bis) AU FIL DE L'EAU (`stream`, 2026-10-28) : le navigateur joue le premier son pendant
        # que le reste se calcule — PCM 16 bits, la fréquence et le texte dit en en-têtes. Tout
        # échec avant le premier son retombe sur la réponse entière ci-dessous.
        if data.get('stream') and voice.get('model'):
            streamed = _tts_stream_response(text, voice, options, request.user)
            if streamed is not None:
                return streamed
        audio_b64 = _tts_via_service(text, voice, options, user=request.user)
        if audio_b64 is not None:
            return JsonResponse({'audio_b64': audio_b64, 'spoken': text})

        # 2) Repli en-process (service indisponible) : Kokoro .pt, la voix choisie si c'en est
        # une de Kokoro, sinon celle de la langue (`kokoro_voice`).
        from wama.common.tts.voices import code_langue, kokoro_voice
        voice_language = voice['language']
        lang_code = code_langue(voice_language)
        pipeline = _get_kokoro(lang_code)
        # Le lexique de prononciation (fichier + lignes du compte), comme par le service (27/10).
        from wama.common.backends.kokoro_backend import say_lexicon_through
        from wama.common.services.user_pronunciations import lexicon_for
        said = say_lexicon_through(pipeline, lang_code, voice_language, text,
                                   {**lexicon_for(request.user, voice_language), **tried})

        import io
        import wave
        import base64
        import numpy as np

        samples = []
        for _, _, audio in pipeline(said, voice=kokoro_voice(voice_language, voice['voice_preset']),
                                    speed=1.0):
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
        # Repli en-process (Kokoro .pt, service indisponible) : sans les pauses réglées — la
        # voie de secours garde le comportement d'avant.
        return JsonResponse({'audio_b64': audio_b64, 'spoken': text})

    except json.JSONDecodeError:
        return JsonResponse({'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        logger.exception('kokoro_tts error')
        return JsonResponse({'error': str(e)}, status=500)


#: Plafond d'un extrait de parole : ~65 s de WAV 16 kHz mono 16 bits. La brique d'écoute coupe
#: une phrase à 30 s ; au-delà, ce n'est plus une réplique de conversation. Sous le plafond de
#: Django (`DATA_UPLOAD_MAX_MEMORY_SIZE`, 2,5 Mo), qui sinon répondrait un 400 sans raison.
_STT_MAX_BYTES = 2 * 1024 * 1024


@require_http_methods(["POST"])
@csrf_protect
def speech_to_text(request):
    """
    Transcrit ce que l'utilisateur vient de DIRE à l'assistant (corps : l'audio, WAV de
    préférence) → `{"text": "...", "language": "fr"}`. Conversation vocale, 2026-10-10.

    Le MOTEUR se décide dans `common/tts/speech_input.py` : le modèle distant que le profil
    ouvre au tirage automatique (Albert, 2026-10-11), sinon le service vocal LOCAL (Whisper,
    `constants.ASSISTANT_STT_MODEL`). La dictée passait jusqu'au 10/10 par la reconnaissance du
    navigateur, qui envoie l'audio à Google. Aucun repli en-process pour le local, à la
    différence de la voix : charger Whisper dans gunicorn coûterait des Go par worker web, et
    un micro qui échoue se DIT (l'utilisateur peut toujours écrire).
    `?warmup=1` : la brique d'écoute s'ouvre et fait charger le local d'avance.
    """
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Authentification requise'}, status=401)
    # La taille ANNONCÉE d'abord : lire `request.body` au-delà du plafond de Django lève avant
    # qu'on puisse répondre la vraie raison.
    try:
        announced = int(request.META.get('CONTENT_LENGTH') or 0)
    except ValueError:
        announced = 0
    if announced > _STT_MAX_BYTES:
        return JsonResponse({'error': 'extrait trop long pour une réplique'}, status=413)
    audio = request.body
    if not audio:
        return JsonResponse({'error': 'audio vide'}, status=400)
    if len(audio) > _STT_MAX_BYTES:
        return JsonResponse({'error': 'extrait trop long pour une réplique'}, status=413)

    from wama.common.services.resource_governor import release_in_progress
    if release_in_progress():
        return JsonResponse({'error': _RELEASE_WAIT_MESSAGE, 'busy': True}, status=503)

    # Langue du profil, réduite au code que Whisper connaît (`zh-cn` → `zh`). Vide = détection.
    language = (getattr(getattr(request.user, 'profile', None), 'preferred_language', '') or '')
    language = language.split('-')[0].lower()
    from wama.common.tts.service_client import TTSServiceLoadingError
    from wama.common.tts.speech_input import transcribe_utterance
    try:
        result = transcribe_utterance(request.user, audio,
                                      content_type=request.content_type or 'audio/wav',
                                      language=language,
                                      warm_up=request.GET.get('warmup') == '1')
    except TTSServiceLoadingError:
        return JsonResponse({'error': "Le service vocal démarre — réessayez dans un instant.",
                             'busy': True}, status=503)
    except RuntimeError as e:
        logger.warning(f"[speech_to_text] {e}")
        return JsonResponse({'error': "Reconnaissance vocale indisponible : " + str(e)}, status=502)
    return JsonResponse({'text': (result.get('text') or '').strip(),
                         'language': result.get('language') or language,
                         'engine': result.get('engine', 'local')})


@require_http_methods(["POST"])
@csrf_protect
def end_of_turn(request):
    """
    La personne a-t-elle FINI sa phrase ? (corps : la phrase dite jusqu'ici, WAV 16 kHz) →
    `{available, complete, probability}`. L'écoute de la conversation le demande après une pause
    courte (2026-10-28, `common/tts/end_of_turn.py`). `complete: null` = pas d'avis : l'écoute
    garde le silence d'avant ; `available: false` = aucun modèle installé, elle cesse de demander.
    """
    if not request.user.is_authenticated:
        return JsonResponse({'error': 'Authentification requise'}, status=401)
    try:
        announced = int(request.META.get('CONTENT_LENGTH') or 0)
    except ValueError:
        announced = 0
    if announced > _STT_MAX_BYTES or len(request.body) > _STT_MAX_BYTES:
        return JsonResponse({'error': 'extrait trop long pour une réplique'}, status=413)
    if not request.body:
        return JsonResponse({'error': 'audio vide'}, status=400)
    from wama.common.tts.end_of_turn import judge
    return JsonResponse(judge(request.body))
