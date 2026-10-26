"""Scénario nocturne `ui` — la CAPTURE caméra / micro (`common/js/wama-capture.js`, 2026-10-26).

Pourquoi au navigateur : la brique n'agit que dans une page servie, sur un vrai périphérique. Ses
tests V8 (`tests_capture`) tiennent le contrat ; ce scénario tient les CONSOMMATEURS, avec la caméra
et le micro SIMULÉS de Chromium :
  1. la DICTÉE de l'assistant (accueil) ouvre UN micro, l'arrêt le rend ;
  2. le SPEAK du transcriber écoute, ENREGISTRE (même flux) et envoie l'audio à `save_realtime` à
     l'arrêt — envoi intercepté et refusé : aucune card n'est créée ;
  3. le temps réel du FACE ANALYZER liste les caméras par leur nom, s'y connecte avec UN seul flux
     (la demande des noms ne reste plus ouverte) et le rend en quittant la page (`pagehide`).
Les transcriptions sont rendues vides sans atteindre le service vocal. Zéro erreur JS.
L'enregistrement de la médiathèque est gardé par `synthesizer.voice_library_pick` (jusqu'au WAV) et
les mains par `common.scene.<clé>.ui` : ils ne se répètent pas ici.
⚠ Le compte de test reçoit le niveau administrateur le temps du passage (accès au Face Analyzer).
"""
from .ui_smoke import BASE_URL, _drop_new_sessions, _exiger_la_page, _session_keys
from .ui_smoke_accounts import GL_ARGS, PAGE_TIMEOUT_MS, _admin_session
from .ui_smoke_matching import _cookie
from .ui_smoke_scenes import FAKE_CAMERA_ARGS

#: Compte les flux ouverts par la page et leurs pistes encore vivantes, sans rien changer.
JS_COUNT_STREAMS = """(() => {
  const md = navigator.mediaDevices; if (!md || window.__wamaStreams) return;
  const streams = [], real = md.getUserMedia.bind(md);
  window.__wamaStreams = { calls: 0,
    live: () => streams.flatMap(s => s.getTracks()).filter(t => t.readyState === 'live').length };
  md.getUserMedia = c => { window.__wamaStreams.calls++; return real(c).then(s => { streams.push(s); return s; }); };
})()"""
JS_STREAMS = "window.__wamaStreams ? {calls: window.__wamaStreams.calls, live: window.__wamaStreams.live()} : null"


def check_capture():
    """(ok, détail) des trois consommateurs de la capture."""
    from django.urls import reverse
    from playwright.sync_api import sync_playwright

    from wama.common.services.nightly_tests import SkipScenario

    sessions_before = _session_keys()
    granted = _admin_session()
    if granted is None:
        raise SkipScenario("compte de test absent")
    user, previous_tier, session = granted
    base = BASE_URL.rstrip('/')
    urls = {'home': reverse('home'), 'transcriber': reverse('transcriber:index'),
            'face': reverse('wama_lab:face_analyzer:realtime')}
    save_realtime = reverse('transcriber:save_realtime')
    faults, steps, js_errors, saved = [], [], [], []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(args=GL_ARGS + FAKE_CAMERA_ARGS)
            try:
                ctx = browser.new_context(viewport={'width': 1500, 'height': 950},
                                          permissions=['camera', 'microphone'])
                ctx.add_cookies(_cookie(session.session_key))
                ctx.add_init_script(JS_COUNT_STREAMS)
                ctx.route('**/api/stt/**', lambda r: r.fulfill(json={'text': '', 'engine': 'local'}))
                ctx.route('**' + save_realtime,
                          lambda r: (saved.append(len(r.request.post_data_buffer or b'')),
                                     r.fulfill(json={'ok': False})))

                def open_page(key):
                    page = ctx.new_page()
                    page.on('pageerror', lambda e: js_errors.append(f"{key} pageerror: {e}"[:200]))
                    page.on('console', lambda m: js_errors.append(f"{key} console: {m.text}"[:200])
                            if m.type == 'error' else None)
                    url = base + urls[key]
                    resp = page.goto(url, wait_until='load', timeout=PAGE_TIMEOUT_MS)
                    wrong = _exiger_la_page(page, resp, url)
                    page.wait_for_timeout(2500)
                    return page, wrong

                # 1. La dictée de l'assistant.
                page, wrong = open_page('home')
                if wrong:
                    return wrong
                page.click('[data-assistant-mic]')
                page.wait_for_timeout(1500)
                state, during = page.evaluate('WamaAssistantListen.state()'), page.evaluate(JS_STREAMS)
                page.evaluate('WamaAssistantListen.stop()')
                page.wait_for_timeout(500)
                after = page.evaluate(JS_STREAMS)
                if state['mode'] != 'dictation' or during != {'calls': 1, 'live': 1} or after['live']:
                    faults.append(f"dictée : état {state}, flux {during} puis {after}")
                else:
                    steps.append('dictée : un micro ouvert puis rendu')
                page.close()

                # 2. Le Speak du transcriber : écouter, enregistrer, envoyer à l'arrêt.
                page, wrong = open_page('transcriber')
                if wrong:
                    return wrong
                page.evaluate("document.getElementById('transcriber-speak-btn').click()")
                page.wait_for_timeout(2500)
                during = page.evaluate(JS_STREAMS)
                page.evaluate("document.getElementById('transcriber-speak-btn').click()")
                page.wait_for_timeout(3000)
                after = page.evaluate(JS_STREAMS)
                if during != {'calls': 1, 'live': 1} or after['live'] or not (saved and saved[-1] > 1000):
                    faults.append(f"Speak : flux {during} puis {after}, envoi à l'arrêt {saved}")
                else:
                    steps.append(f"Speak : enregistrement envoyé à l'arrêt ({saved[-1]} octets), micro rendu")
                page.close()

                # 3. Le temps réel du Face Analyzer.
                page, wrong = open_page('face')
                if wrong:
                    return wrong
                page.wait_for_timeout(2500)
                cameras = page.evaluate("[...document.querySelectorAll('#cameraSelect option')]"
                                        ".map(o => o.textContent.trim())")
                status = page.evaluate("document.getElementById('connectionStatus').textContent.trim()")
                during = page.evaluate(JS_STREAMS)
                page.evaluate("window.dispatchEvent(new PageTransitionEvent('pagehide', {persisted: true}))")
                page.wait_for_timeout(300)
                after = page.evaluate(JS_STREAMS)
                if not cameras or status != 'Connecté' or during['live'] != 1 or after['live']:
                    faults.append(f"Face Analyzer : caméras {cameras}, statut « {status} », flux {during} "
                                  f"puis {after} après pagehide")
                else:
                    steps.append(f"Face Analyzer : {len(cameras)} caméra(s) nommée(s), un flux, rendu au pagehide")
                page.close()
            finally:
                browser.close()
    finally:
        from wama.accounts.permissions import set_account_tier
        set_account_tier(user, previous_tier)
        session.delete()
        _drop_new_sessions(sessions_before)
    if js_errors:
        faults.append(f"erreurs JS : {js_errors[:4]}")
    return (not faults), ' · '.join(faults or steps)


def register_capture_scenarios():
    """Enregistre `common.capture.ui`."""
    from wama.common.services.nightly_tests import register
    register(
        id='common.capture.ui', app='common', stage='ui',
        description=("Capture caméra / micro (brique commune) : la dictée de l'assistant, le Speak du "
                     "transcriber (enregistrement envoyé à l'arrêt) et le Face Analyzer ouvrent leur "
                     "périphérique simulé et le rendent — un seul flux chacun, zéro erreur JS"),
        run=lambda ctx: check_capture(),
        timeout_s=240, vram_gb=0.0,
    )
