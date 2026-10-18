"""
Scénario nocturne `output` du studio — un pipeline RÉEL de bout en bout.

Né du smoke du 2026-08-03 : l'interblocage runner↔converter (même file `default` en pool
solo) n'était détectable QUE par une exécution réelle — ce scénario l'aurait attrapé la
nuit de sa naissance. Chaîne exercée : media_import → converter (execute_tool, file
`default`) → studio_output (médiathèque), orchestrée par run_pipeline_task (file `studio`).

CPU seul (ffmpeg) ; l'entrée est un wav de 1 s généré sur place. Nettoyage par IDs précis
(règle de la charpente) : run, job converter et asset créés sont supprimés en `finally`.
"""
import os

from wama.common.services.nightly_tests import SkipScenario, register

#: La fixture vit CHEZ LE COMPTE DE TEST (`users/<uid>/temp/`), nommée en témoin
#: (`wama_temoin_*`) : c'est la zone que le balayage `sweep_test_witnesses` couvre, et la seule
#: où un test a le droit d'écrire dans `media/` — le nocturne passe par le serveur VIVANT, donc
#: par le vrai `MEDIA_ROOT` (le nœud `media_import` confine `asset_path` sous cette racine).
#: Jusqu'au 2026-09-13 elle vivait à `media/nightly_tests/` : un dossier de test à la RACINE du
#: média de production, signalé « égaré » par `check_media_integrity` et exclu à la main par
#: `migrate_media_to_user_home` — deux exceptions pour un fichier de 1 s.
_ENTREE_NOM = 'wama_temoin_studio_sine_1s.wav'


def _entree(media_root, user):
    """Wav sinus 1 s, généré via le ffmpeg CENTRALISÉ (ffmpeg_utils) ; rend le chemin RELATIF."""
    rel = f'users/{user.pk}/temp/{_ENTREE_NOM}'
    abs_path = os.path.join(media_root, rel)
    if not os.path.exists(abs_path):
        import subprocess
        from wama.common.utils.ffmpeg_utils import get_ffmpeg_exe
        os.makedirs(os.path.dirname(abs_path), exist_ok=True)
        subprocess.run([get_ffmpeg_exe(), '-y', '-f', 'lavfi', '-i',
                        'sine=frequency=440:duration=1', abs_path],
                       check=True, capture_output=True, timeout=60)
    return rel


def _worker_default_present():
    from celery import current_app
    try:
        reponses = current_app.control.ping(timeout=3) or []
    except Exception:
        return False
    return any(str(list(r)[0]).startswith('default@') for r in reponses)


def _run_pipeline_end_to_end(ctx):
    from django.conf import settings
    from wama.media_library.models import UserAsset
    from wama.studio.models import StudioRun
    from wama.studio.tasks import run_pipeline_task

    user = ctx['user']
    if not _worker_default_present():
        raise SkipScenario('aucun worker sur la file default (converter) — pile arrêtée ?')

    rel = _entree(settings.MEDIA_ROOT, user)
    nom_sortie = f'nightly-studio-{user.pk}'
    graph = {
        'nodes': [
            {'id': 'n1', 'app': 'media_import',
             'params': {'asset_path': rel, 'asset_category': 'audio'}},
            {'id': 'n2', 'app': 'converter',
             'params': {'output_format': 'mp3', 'channels': '1'}},
            {'id': 'n3', 'app': 'studio_output',
             # Une NATURE, ce que le nœud offre et que sa porte accepte (`node_params`) — pas la
             # catégorie `audio`, refusée depuis la porte commune des réglages (12/10).
             'params': {'asset_type': 'audio_music', 'asset_name': nom_sortie}},
        ],
        'links': [{'from': 'n1', 'to': 'n2'}, {'from': 'n2', 'to': 'n3'}],
    }
    run = StudioRun.objects.create(user=user, graph=graph)
    try:
        # Appel DIRECT (in-process) : l'orchestration s'exécute ici, la tâche converter
        # part réellement en file `default` — c'est elle que le scénario surveille.
        run_pipeline_task(run.pk)
        run.refresh_from_db()
        if run.status != 'SUCCESS':
            return False, f"run #{run.pk} {run.status} — {(run.error_message or '')[:200]}"
        asset = UserAsset.objects.filter(user=user, name__startswith=nom_sortie).first()
        if not asset or not os.path.exists(asset.file.path):
            return False, f"run #{run.pk} SUCCESS mais asset de sortie introuvable"
        return True, (f"run #{run.pk} SUCCESS en {run.processing_seconds or 0:.1f}s, "
                      f"sortie {os.path.basename(asset.file.name)}")
    finally:
        # Nettoyage par IDs précis : uniquement ce que CE run a créé.
        from wama.converter.models import ConversionJob
        etats = run.node_states or {}
        job_id = (etats.get('n2') or {}).get('item_id')
        if job_id:
            for job in ConversionJob.objects.filter(pk=job_id, user=user):
                try:
                    job.output_file and job.output_file.delete(save=False)
                    job.original_file and job.original_file.delete(save=False)
                except Exception:
                    pass
                job.delete()
        for asset in UserAsset.objects.filter(user=user, name__startswith=nom_sortie):
            try:
                asset.file.delete(save=False)
            except Exception:
                pass
            asset.delete()
        run.delete()


#: Ce que le geste lit dans la page : les champs RENDUS de l'inspecteur, l'état dit quand il n'y en
#: a pas, et les `params` du nœud au brouillon (`wama_studio_draft`, ce que l'enregistrement poste).
_FIELDS_JS = """() => { const h = document.querySelector('#studioInspectorBody .studio-node-params');
  if (!h) return {n: 0, state: null};
  const f = [...h.querySelectorAll('input, select, textarea')].filter(e => e.type !== 'hidden');
  const s = h.querySelector('.studio-node-params-state');
  return {n: f.length, state: s ? s.textContent.trim() : null}; }"""
_DRAFT_JS = """(id) => { try { const g = JSON.parse(localStorage.getItem('wama_studio_draft')).graph;
  return (g.nodes.find(n => n.id === id) || {}).params || null; } catch (e) { return null; } }"""


def _node_settings_gesture(ctx):
    """Régler un nœud du Studio, de BOUT EN BOUT (ROUTE §10.6 3.3bis, R2 — 2026-10-18).

    Constat live du jour même : un nœud sélectionné dans les 10 à 15 premières secondes ne montrait
    AUCUN réglage, sans rien dire ; et un réglage montré n'atteignait pas toujours l'élément. Le
    geste, à la souris et au clavier, sur le serveur vivant :
      1. déposer le nœud Converter depuis le catalogue, le sélectionner — ses réglages sont LÀ ;
      2. choisir un format de sortie au clavier (geste de confiance) — le brouillon ne garde QUE ce
         réglage décidé, jamais l'instantané des champs rendus ;
      3. enregistrer (requête interceptée : rien n'est écrit) — le corps posté porte la même valeur ;
      4. recharger — le nœud la montre encore ;
      5. lancer ce nœud dans un pipeline réel (wav témoin → Converter → médiathèque) — l'ÉLÉMENT
         créé porte le format choisi.
    L'ORM n'est touché qu'après la fermeture du navigateur (règle des gestes Playwright)."""
    import json
    from django.conf import settings
    from django.contrib.auth import get_user_model
    from wama.common.services.nightly_tests import SkipScenario
    from wama.common.services.ui_smoke import (BASE_URL, _drop_new_sessions, _session_keys,
                                               _test_account_id, _test_session_key)
    from wama.common.services.ui_smoke_matching import _cookie
    from wama.converter.utils.format_router import get_output_formats

    token, uid = _test_session_key('studio'), _test_account_id('studio')
    if not (token and uid):
        raise SkipScenario("aucun compte de test disponible (wama_nightly_test / wama_ui_smoke_v3)")
    if not _worker_default_present():
        raise SkipScenario('aucun worker sur la file default (converter) — pile arrêtée ?')
    audio_formats = set(get_output_formats('audio'))
    base, steps, faults = BASE_URL.rstrip('/'), [], []
    before = _session_keys()
    chosen, node_id = None, None
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch()
            context = browser.new_context(viewport={'width': 1440, 'height': 900})
            context.add_cookies(_cookie(token))
            posted = []
            context.route('**/studio/api/pipelines/', lambda r: (
                posted.append(r.request.post_data),
                r.fulfill(status=200, content_type='application/json',
                          body='{"id": 0, "name": "wama-node-settings", "created": true}'))
                if r.request.method == 'POST' else r.continue_())
            page = context.new_page()
            errors = []
            page.on('pageerror', lambda e: errors.append(str(e)[:160]))
            page.goto(base + '/studio/', wait_until='domcontentloaded')
            page.evaluate("() => localStorage.removeItem('wama_studio_draft')")
            page.reload(wait_until='domcontentloaded')
            page.wait_for_selector('.studio-pal-item[draggable="true"]', timeout=60000)
            # Une palette SANS AUCUNE app est une panne (catalogue mal lu) : jamais un saut, qui la
            # masquerait. Seul un compte à qui le Converter n'est pas ouvert saute le geste.
            if not page.locator('[data-section="apps"] .studio-pal-item').count():
                browser.close()
                return False, '1. aucune app au catalogue du Studio (palette mal lue)'
            item = page.locator('[data-section="apps"] .studio-pal-item:has-text("Converter")').first
            if not item.count():
                raise SkipScenario('le Converter n’est pas offert au catalogue de ce compte')
            item.scroll_into_view_if_needed()
            item.drag_to(page.locator('#studioCanvas'), target_position={'x': 220, 'y': 160})
            page.wait_for_selector('.studio-node', timeout=10000)
            node_id = page.locator('.studio-node').first.get_attribute('data-node')
            page.locator(f'.studio-node[data-node="{node_id}"] .studio-node-head').click(
                position={'x': 30, 'y': 10})
            page.wait_for_timeout(400)
            shown = page.evaluate(_FIELDS_JS)
            (steps if shown['n'] else faults).append(f"1. réglages à la sélection : {shown}")
            select = page.locator('#studioInspectorBody .studio-node-params select[name="output_format"]')
            if not select.count():
                faults.append('2. aucun champ « format de sortie » au nœud Converter')
            else:
                select.focus()
                for _ in range(40):                  # au CLAVIER : un geste, pas un remplissage
                    if select.input_value() in audio_formats:
                        break
                    page.keyboard.press('ArrowDown')
                    page.wait_for_timeout(60)
                chosen = select.input_value()
                page.keyboard.press('Tab')
                page.wait_for_timeout(400)
                draft = page.evaluate(_DRAFT_JS, node_id)
                (steps if draft == {'output_format': chosen} else faults).append(
                    f"2. brouillon après le geste : {draft} (choisi : {chosen!r})")
                page.fill('#studioPipelineName', 'wama-node-settings')
                page.click('#studioSaveBtn')
                page.wait_for_timeout(800)
                sent = json.loads(posted[0]) if posted else {}
                sent_params = next((n.get('params') for n in (sent.get('graph') or {}).get('nodes', [])
                                    if n.get('id') == node_id), None)
                (steps if sent_params == {'output_format': chosen} else faults).append(
                    f"3. enregistré : {sent_params}")
                page.reload(wait_until='domcontentloaded')
                page.wait_for_selector(f'.studio-node[data-node="{node_id}"]', timeout=60000)
                page.locator(f'.studio-node[data-node="{node_id}"] .studio-node-head').click(
                    position={'x': 30, 'y': 10})
                seen = None
                for _ in range(40):
                    seen = page.evaluate(
                        "() => { const e = document.querySelector('#studioInspectorBody "
                        "select[name=\"output_format\"]'); return e ? e.value : null; }")
                    if seen:
                        break
                    page.wait_for_timeout(250)
                (steps if seen == chosen else faults).append(f"4. après rechargement : {seen!r}")
            page.evaluate("() => localStorage.removeItem('wama_studio_draft')")
            if errors:
                faults.append(f'erreurs JS : {errors[:3]}')
            browser.close()
    finally:
        _drop_new_sessions(before)
    if faults or not chosen:
        return False, ' | '.join(faults + steps)
    # 5. Le même réglage, LANCÉ : l'élément créé par le nœud le porte.
    from wama.converter.models import ConversionJob
    from wama.studio.models import StudioRun
    from wama.studio.tasks import run_pipeline_task
    user = get_user_model().objects.get(pk=uid)
    rel = _entree(settings.MEDIA_ROOT, user)
    # L'entrée prend un identifiant que le canvas ne donne jamais (`n<k>`) : le nœud déposé est `n1`.
    graph = {'nodes': [{'id': 'witness_input', 'app': 'media_import',
                        'params': {'asset_path': rel, 'asset_category': 'audio'}},
                       {'id': node_id, 'app': 'converter', 'params': {'output_format': chosen}}],
             'links': [{'from': 'witness_input', 'to': node_id}]}
    run = StudioRun.objects.create(user=user, graph=graph)
    job = None
    try:
        run_pipeline_task(run.pk)
        run.refresh_from_db()
        job_id = ((run.node_states or {}).get(node_id) or {}).get('item_id')
        job = ConversionJob.objects.filter(pk=job_id, user=user).first() if job_id else None
        if job is None or job.output_format != chosen:
            return False, (f"5. élément : {getattr(job, 'output_format', None)!r} au lieu de "
                           f"{chosen!r} (run #{run.pk} {run.status} — "
                           f"{(run.error_message or '')[:240]}) | " + ' | '.join(steps))
        steps.append(f"5. élément n° {job.pk} : format {job.output_format!r}")
        return True, ' | '.join(steps)
    finally:
        if job is not None:
            try:
                job.output_file and job.output_file.delete(save=False)
            except Exception:
                pass
            job.delete()
        run.delete()


def register_scenarios():
    register(id='studio.node_settings', app='studio', stage='ui',
             description='Régler un nœud du Studio de bout en bout : réglages présents à la '
                         'sélection, seul le réglage décidé enregistré, gardé au rechargement, '
                         'porté par l’élément créé (Converter, CPU)',
             run=_node_settings_gesture, timeout_s=300, vram_gb=0.0)
    register(id='studio.pipeline.converter', app='studio', stage='output',
             description='Pipeline réel media_import → converter → médiathèque '
                         '(orchestration file studio, tâche app file default)',
             run=_run_pipeline_end_to_end, timeout_s=300)
    # 2026-09-30 : chaque port AFFICHÉ au nœud doit être LU par l'outil de l'app (argument du même
    # nom) — mesuré sur le catalogue RÉEL, dont les ports dérivent ; un test ne le peut pas (la base
    # de test n'a pas les modèles).
    from wama.studio.services.generic_runner import unwired_ports_report
    register(id='studio.node_ports_wired', app='studio', stage='consistency',
             description='les ports de chaque nœud d’app sont lus par son outil (budget du reste '
                         'à porter, qui ne peut que descendre)',
             run=lambda ctx: unwired_ports_report(), timeout_s=60)
