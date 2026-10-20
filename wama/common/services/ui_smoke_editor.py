"""Scénario `transcriber.editor_parity` — la PARITÉ de l'éditeur du transcriber, geste par geste
(chantier « transport commun », `WAMA_APP_GENERATION_ROUTE.md §F3b`, 2026-10-20).

La règle du chantier (Fabien, 2026-10-01) : *aucune ligne de la matrice de parité ne passe à la
brique commune sans le geste qui l'atteste, joué AVANT et APRÈS sur la même page.* Ce scénario EST
ce geste, pour les lignes « éditeur » de la matrice : il se joue sur l'éditeur tel qu'il est, puis
sur l'éditeur porté sur l'axe commun (`wama-axis.js`), et les deux passages doivent dire la même
chose.

D'où sa contrainte de construction : il ne sonde QUE ce qui survit au portage — la position, la
pause et la vitesse de l'`<audio>` de la page, et le DOM (libellés, ligne surlignée ou sélectionnée,
champ en saisie, nombre de segments). Jamais une variable interne de `edit.js`.

Témoin : UNE transcription du compte de test, une minute de silence, trois segments de 20 s
(« un », « deux », « trois ») — le montage des gestes au doigt (`ui_smoke_layout`), retiré en sortie.
⚠ Toute écriture est INTERCEPTÉE et refusée dans la page (`BLOCK_WRITES`) : l'enregistrement
automatique, le recalage et le curseur d'écriture partent dans le vide ; le serveur n'en voit rien.
"""
from .ui_smoke import BASE_URL, _drop_new_sessions, _exiger_la_page, _motif_skip, _session_keys
from .ui_smoke_layout import _collect, _desktop_page, _mount_transcripts, _wait_player

#: L'état de l'éditeur tel qu'un utilisateur le voit — rien d'interne à `edit.js`.
JS_EDITOR_STATE = """() => {
    const id = (window.TRANSCRIBER_EDIT || {}).playerId;
    const a = id != null && window.WamaAudioPlayer ? WamaAudioPlayer.getAudio(id) : null;
    const q = s => document.querySelector(s);
    const index = s => { const r = q(s); return r ? Number(r.dataset.i) : -1; };
    const ae = document.activeElement;
    const lock = q('#followLockBtn'), tool = q('#boundaryToolBtn'), rec = q('#writeRec');
    return {
        t: a ? Math.round(a.currentTime * 100) / 100 : null,
        paused: a ? a.paused : null,
        rate: a ? a.playbackRate : null,
        speed: ((q('#speedVal') || {}).textContent || '').trim(),
        zoom: ((q('#zoomLabel') || {}).textContent || '').trim(),
        active: index('.seg-row.seg-active'),
        selected: index('.seg-row.seg-selected'),
        editing: ae && ae.classList && ae.classList.contains('seg-text') ? Number(ae.dataset.i) : -1,
        rows: document.querySelectorAll('.seg-row').length,
        texts: [...document.querySelectorAll('.seg-text')].map(e => e.textContent),
        lock: !!(lock && lock.classList.contains('btn-info')),
        tool: tool ? tool.getAttribute('aria-pressed') : null,
        rec: rec ? !rec.classList.contains('d-none') : null,
    };
}"""

SETTLE_MS = 300


def _near(value, target, tolerance=0.4):
    return value is not None and abs(value - target) <= tolerance


class _Editor:
    """Les gestes de l'utilisateur sur la page, et la lecture de ce qu'il voit."""

    def __init__(self, page):
        self.page = page

    def state(self):
        return self.page.evaluate(JS_EDITOR_STATE)

    def key(self, combo, wait=SETTLE_MS):
        self.page.keyboard.press(combo)
        self.page.wait_for_timeout(wait)
        return self.state()

    def release_focus(self):
        """Rend le clavier à la page (un bouton cliqué garderait Espace pour lui)."""
        self.page.evaluate("() => document.activeElement && document.activeElement.blur()")

    def goto(self, timecode):
        """« Aller à » : le champ, Entrée, puis Échap rend le clavier à la navigation."""
        self.page.fill('#gotoTime', timecode)
        self.page.press('#gotoTime', 'Enter')
        self.page.wait_for_timeout(SETTLE_MS)
        self.page.keyboard.press('Escape')
        self.release_focus()
        self.page.wait_for_timeout(SETTLE_MS)
        return self.state()

    def ensure_paused(self):
        if not self.state()['paused']:
            self.key('Space')

    def click(self, selector, wait=SETTLE_MS):
        self.page.click(selector)
        self.page.wait_for_timeout(wait)
        self.release_focus()
        return self.state()

    def click_at(self, selector, fx, fy=0.5, wait=SETTLE_MS):
        box = self.page.locator(selector).bounding_box()
        self.page.mouse.click(box['x'] + box['width'] * fx, box['y'] + box['height'] * fy)
        self.page.wait_for_timeout(wait)
        return self.state()

    def wheel_on(self, selector, delta, times=1):
        box = self.page.locator(selector).bounding_box()
        self.page.mouse.move(box['x'] + box['width'] / 2, box['y'] + box['height'] / 2)
        for _ in range(times):
            self.page.mouse.wheel(0, delta)
            self.page.wait_for_timeout(80)
        self.page.wait_for_timeout(SETTLE_MS)
        return self.state()


def _transport(ed, checks):
    """Aller à, sauts, lecture, vitesse."""
    s = ed.goto('0:30')
    checks.append((_near(s['t'], 30) and s['paused'] and s['selected'] == 1,
                   f"aller à 0:30 → position, pause, segment 2 sélectionné ({s['t']}, {s['paused']}, {s['selected']})"))
    s = ed.key('ArrowRight')
    checks.append((_near(s['t'], 35), f"→ = +5 s ({s['t']})"))
    ed.key('ArrowLeft')
    s = ed.key('ArrowLeft')
    checks.append((_near(s['t'], 25), f"← ← = −10 s ({s['t']})"))
    s = ed.key('Space', wait=900)
    checks.append((s['paused'] is False and s['t'] > 25.3, f"Espace lance la lecture ({s['t']}, en pause : {s['paused']})"))
    s = ed.key('Space')
    checks.append((s['paused'] is True, "Espace remet en pause"))
    ed.click('#speedUp')
    s = ed.click('#speedUp')
    checks.append((s['rate'] == 1.5 and s['speed'] == '1.5×', f"+ + = vitesse 1,5 ({s['rate']}, « {s['speed']} »)"))
    ed.click('#speedDown')
    s = ed.click('#speedDown')
    checks.append((s['rate'] == 1 and s['speed'] == '1.0×', f"− − = vitesse 1 ({s['rate']}, « {s['speed']} »)"))
    s = ed.click('#skipFwd')
    s2 = ed.click('#skipBack')
    checks.append((_near(s['t'] - s2['t'], 5), f"boutons ±5 s ({s['t']} → {s2['t']})"))


def _shuttle(ed, checks):
    """J/K/L : l'échelle, l'arrière silencieux, Espace qui désengage."""
    ed.goto('0:10')
    s = ed.key('l')
    checks.append((s['paused'] is False and s['rate'] == 1 and s['speed'] == '▶▶ 1×',
                   f"L = avant ×1 ({s['paused']}, {s['rate']}, « {s['speed']} »)"))
    s = ed.key('l')
    checks.append((s['rate'] == 1.25 and s['speed'] == '▶▶ 1.25×', f"L L = ×1,25 ({s['rate']}, « {s['speed']} »)"))
    s = ed.key('k')
    checks.append((s['paused'] is True and s['speed'] == '1.0×', f"K = arrêt ({s['paused']}, « {s['speed']} »)"))
    ed.goto('0:40')
    s0 = ed.state()
    s = ed.key('j', wait=900)
    checks.append((s['t'] < s0['t'] - 0.4 and s['speed'] == '◀◀ 1×',
                   f"J = arrière silencieux ({s0['t']} → {s['t']}, « {s['speed']} »)"))
    s = ed.key('k')
    s2 = ed.key('Shift', wait=400)
    checks.append((s['speed'] == '1.0×' and _near(s['t'], s2['t'], 0.05),
                   f"K arrête l'arrière ({s['t']} → {s2['t']}, « {s['speed']} »)"))
    ed.goto('0:10')
    ed.key('l')
    ed.key('l')
    s = ed.key('Space')
    checks.append((s['paused'] is True and s['speed'] == '1.0×',
                   f"Espace pendant le shuttle = pause, échelle remise à zéro ({s['paused']}, « {s['speed']} »)"))
    s = ed.key('Space', wait=500)
    checks.append((s['paused'] is False and s['rate'] == 1, f"puis Espace = lecture à la vitesse réglée ({s['rate']})"))
    ed.ensure_paused()


def _navigation(ed, checks):
    """Tab / Maj+Tab, ↑/↓, Navigation ↔ Édition, coupe, annuler/rétablir."""
    ed.goto('0:05')
    s = ed.key('Tab')
    checks.append((_near(s['t'], 20) and s['selected'] == 1 and s['paused'],
                   f"Tab = début du segment suivant, sans lancer ({s['t']}, {s['selected']}, {s['paused']})"))
    s = ed.key('Tab')
    checks.append((_near(s['t'], 40) and s['selected'] == 2, f"Tab = segment 3 ({s['t']}, {s['selected']})"))
    s = ed.key('Shift+Tab')
    checks.append((_near(s['t'], 20) and s['selected'] == 1, f"Maj+Tab = segment 2 ({s['t']}, {s['selected']})"))
    s = ed.key('ArrowDown')
    checks.append((s['selected'] == 2 and _near(s['t'], 20), f"↓ sélectionne sans déplacer la lecture ({s['selected']}, {s['t']})"))
    s = ed.key('ArrowUp')
    checks.append((s['selected'] == 1, f"↑ ({s['selected']})"))
    s = ed.key('Enter')
    checks.append((s['editing'] == 1, f"Entrée = édition du segment sélectionné ({s['editing']})"))
    t_before = s['t']
    ed.key('ArrowLeft')
    s = ed.key('Space')
    checks.append((s['paused'] is True and _near(s['t'], t_before, 0.05) and s['texts'][1] != 'deux',
                   f"en édition, ← et Espace écrivent au lieu de piloter ({s['t']}, « {s['texts'][1]} »)"))
    s = ed.key('Escape')
    checks.append((s['editing'] == -1, f"Échap = retour en navigation ({s['editing']})"))
    s = ed.key('Control+z')
    checks.append((s['texts'][1] == 'deux', f"Ctrl+Z annule la frappe (« {s['texts'][1]} »)"))
    ed.key('Enter')
    ed.key('End')
    ed.key('ArrowLeft')
    ed.key('ArrowLeft')
    s = ed.key('Control+Enter')
    checks.append((s['rows'] == 4 and s['texts'][1:3] == ['de', 'ux'],
                   f"Ctrl+Entrée en édition coupe au curseur ({s['rows']} segments, {s['texts'][1:3]})"))
    ed.key('Escape')
    s = ed.key('Control+z')
    checks.append((s['rows'] == 3 and s['texts'][1] == 'deux', f"Ctrl+Z défait la coupe ({s['rows']})"))
    s = ed.key('Control+Shift+z')
    checks.append((s['rows'] == 4, f"Ctrl+Maj+Z la refait ({s['rows']})"))
    s = ed.key('Control+z')
    checks.append((s['rows'] == 3, "Ctrl+Z, retour à trois segments"))


def _toggles(ed, checks):
    """Alt+L (suivi), C / Échap (outil Bornes), mode d'écriture Touch + R maintenu."""
    lock0 = ed.state()['lock']
    s = ed.key('Alt+l')
    s2 = ed.key('Alt+l')
    checks.append((s['lock'] != lock0 and s2['lock'] == lock0, f"Alt+L bascule le suivi ({lock0} → {s['lock']} → {s2['lock']})"))
    s = ed.key('c')
    s2 = ed.key('Escape')
    checks.append((s['tool'] == 'true' and s2['tool'] == 'false', f"C ouvre l'outil Bornes, Échap le ferme ({s['tool']}, {s2['tool']})"))
    ed.page.select_option('#writeMode', 'touch')
    ed.release_focus()
    ed.goto('0:10')
    ed.key('Space', wait=400)
    ed.page.keyboard.down('r')
    ed.page.wait_for_timeout(SETTLE_MS)
    held = ed.state()['rec']
    ed.page.keyboard.up('r')
    ed.page.wait_for_timeout(SETTLE_MS)
    released = ed.state()['rec']
    ed.ensure_paused()
    ed.page.select_option('#writeMode', '')
    ed.release_focus()
    checks.append((held is True and released is False, f"Touch : R maintenu enregistre, relâché s'arrête ({held}, {released})"))


def _views(ed, checks):
    """L'onde, la minimap, la carte de chaleur, le ▶ d'un segment, le surlignage en lecture."""
    z0 = ed.state()['zoom']
    s = ed.wheel_on('#zoomWave', -200, times=4)
    checks.append((s['zoom'] != z0, f"molette sur l'onde zoome ({z0} → {s['zoom']})"))
    ed.goto('0:30')
    s = ed.click_at('#zoomWave', 0.5)
    checks.append((_near(s['t'], 30, 3), f"clic au milieu de l'onde ≈ son centre ({s['t']})"))
    ed.click_at('#zoomMini', 0.92)
    s = ed.click_at('#zoomWave', 0.5)
    checks.append((s['t'] > 40, f"la minimap déplace la fenêtre de l'onde (centre → {s['t']})"))
    s = ed.wheel_on('#zoomWave', 400, times=12)
    checks.append((s['zoom'] == '×1.0', f"molette arrière jusqu'à la vue entière (« {s['zoom']} »)"))
    zones = ed.page.locator('#segHeatmap .hz')
    if zones.count() >= 2:
        zones.nth(1).click()
        ed.page.wait_for_timeout(500)
        s = ed.state()
        checks.append((s['paused'] is False and 20 <= s['t'] < 21.5 and s['selected'] == 1,
                       f"clic sur la carte de chaleur = écouter le segment ({s['t']}, {s['paused']}, {s['selected']})"))
        ed.release_focus()
        ed.ensure_paused()
    else:
        checks.append((False, f"carte de chaleur : {zones.count()} zone(s), 3 attendues"))
    ed.page.click('.seg-play[data-i="2"]')
    ed.page.wait_for_timeout(900)
    s = ed.state()
    ed.release_focus()
    checks.append((s['paused'] is False and 40 <= s['t'] < 42 and s['active'] == 2,
                   f"▶ d'un segment = lecture depuis son début, segment surligné ({s['t']}, {s['active']})"))
    ed.ensure_paused()
    ed.goto('0:19')
    ed.key('Space', wait=1600)
    s = ed.state()
    ed.ensure_paused()
    checks.append((s['active'] == 1, f"en lecture, le segment joué se surligne ({s['t']}, {s['active']})"))


def check_editor_parity():
    """Les lignes « éditeur » de la matrice de parité, chacune par son geste."""
    from django.urls import reverse
    from playwright.sync_api import sync_playwright

    from wama.common.services.nightly_tests import SkipScenario
    from .ui_smoke import _garde_de_montage, _test_account_id, _test_session_key, _total_nettoye

    sessions_before = _session_keys()
    token, uid = _test_session_key('transcriber'), _test_account_id('transcriber')
    if not (token and uid):
        raise SkipScenario("aucun compte de test disponible (wama_nightly_test / wama_ui_smoke_v3)")
    faults, steps = [], []
    with _garde_de_montage('transcriber', 'editor_parity') as cleaned:
        made = _mount_transcripts(uid, count=1)
        url = BASE_URL.rstrip('/') + reverse('transcriber:edit', args=[made[0].pk])
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(args=['--autoplay-policy=no-user-gesture-required'])
                try:
                    ctx, page, resp, errors = _desktop_page(browser, token, url)
                    try:
                        wrong = _exiger_la_page(page, resp, url)
                        if wrong:
                            faults.append(f"éditeur : {wrong[1]}")
                        else:
                            page.wait_for_selector('.seg-row[data-i="2"]', timeout=30000)
                            _wait_player(page)
                            page.wait_for_timeout(800)
                            ed = _Editor(page)
                            for part in (_transport, _shuttle, _navigation, _toggles, _views):
                                checks = []
                                try:
                                    part(ed, checks)
                                except Exception as exc:          # un geste qui casse n'arrête pas les autres
                                    checks.append((False, f"geste interrompu : {str(exc)[:160]}"))
                                _collect(f"éditeur · {part.__doc__.split('.')[0].strip()}", checks, [], faults, steps)
                            if errors:
                                faults.append(f"éditeur : erreurs JS {errors}")
                    finally:
                        ctx.close()
                finally:
                    browser.close()
        except SkipScenario:
            raise
        except Exception as exc:
            raise SkipScenario(_motif_skip(exc))
        finally:
            _drop_new_sessions(sessions_before)
            for t in made:
                try:
                    t.audio.delete(save=False)
                except Exception:
                    pass
    if cleaned:
        steps.append(f"{_total_nettoye(cleaned)} objet(s) de montage retiré(s)")
    if faults:
        return False, ' ; '.join(faults)
    return True, ' → '.join(steps)


def register_editor_scenarios():
    """Enregistre `transcriber.editor_parity`."""
    from wama.common.services.nightly_tests import register
    register(
        id="transcriber.editor_parity", app="transcriber", stage="ui",
        description=("Parité de l'éditeur du transcriber, geste par geste (ROUTE §F3b) : aller à, sauts, "
                     "vitesse, shuttle J/K/L et arrière silencieux, Tab, modes Navigation/Édition, coupe, "
                     "annuler/rétablir, suivi, outil Bornes, mode Touch, onde, minimap, carte de chaleur, "
                     "▶ de segment, surlignage en lecture — sondé par l'audio et le DOM seuls"),
        run=lambda ctx: check_editor_parity(),
        timeout_s=300, vram_gb=0.0,
    )
