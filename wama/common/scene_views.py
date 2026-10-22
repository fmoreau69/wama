"""Les pages des SCÈNES de proximité (constellations 3D) — une page et une route de données pour
toute scène déclarée (`common/scenes.py`). La page ne porte aucune donnée ; la brique les lit."""
from django.http import Http404, JsonResponse
from django.shortcuts import redirect, render

from .scenes import get_scene, page_context, scene_data
from .utils.volet import VOLET_AUCUN


def render_scene(request, scene):
    """La page commune d'une scène — servie aussi par les scènes qui gardent leur adresse
    (`page_url_name`, la constellation des utilisateurs). `?embed=1` : la même page sans barre ni
    volet, pour une présentation qui l'intègre en iframe."""
    context = page_context(scene, embed=request.GET.get('embed') == '1')
    context['volet'] = VOLET_AUCUN                  # scène plein écran : aucun volet de page
    return render(request, 'common/constellation.html', context)


def _guarded(scene, view):
    """La garde que la scène DÉCLARE (`permission`), par les décorateurs qui gardent déjà les
    pages de WAMA — `admin_required` (le niveau du profil) ou `login_required`."""
    from django.contrib.auth.decorators import login_required

    from wama.accounts.views import admin_required
    return admin_required(view) if scene.permission == 'admin' else login_required(view)


def _scene(key):
    scene = get_scene(key)
    if scene is None:
        raise Http404(f"aucune scène « {key} »")
    return scene


def _page(request, scene):
    if scene.page_url_name:
        # Une scène qui garde sa propre adresse s'ouvre là, avec la garde de sa vue.
        return redirect(scene.page_url_name)
    return render_scene(request, scene)


def _data(request, scene):
    if not scene.data:
        return redirect(scene.data_url_name)
    return JsonResponse(scene_data(scene, request.user))


def scene_page(request, key):
    scene = _scene(key)
    return _guarded(scene, _page)(request, scene)


def scene_data_view(request, key):
    scene = _scene(key)
    return _guarded(scene, _data)(request, scene)


def hand_model_view(request):
    """Le modèle des gestes de la main (`common/hand_gestures.py`), INSTALLÉ par la route, servi au
    navigateur qui le charge (les mains des scènes 3D). Absent, la réponse le dit et donne la page
    où l'installer — la scène l'affiche ; rien ne se télécharge à côté de la route."""
    from django.contrib.auth.decorators import login_required
    from django.http import FileResponse
    from django.urls import reverse

    from .hand_gestures import gesture_model_installed, gesture_model_path

    @login_required
    def view(request):
        if not gesture_model_installed():
            return JsonResponse({'installed': False, 'manage_url': reverse('model_manager:index')},
                                status=404)
        return FileResponse(open(gesture_model_path(), 'rb'), content_type='application/octet-stream')
    return view(request)
