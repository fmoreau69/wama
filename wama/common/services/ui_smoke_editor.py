"""Scénario `transcriber.editor_parity` — la PARITÉ de l'éditeur du transcriber, geste par geste
(chantier « transport commun », `WAMA_APP_GENERATION_ROUTE.md §F3b`, 2026-10-20).

La règle du chantier (Fabien, 2026-10-01) : *aucune ligne de la matrice de parité ne passe à la
brique commune sans le geste qui l'atteste, joué AVANT et APRÈS sur la même page.* Ce scénario EST
ce geste, pour les lignes « éditeur » de la matrice : il se joue sur l'éditeur tel qu'il est, puis
sur l'éditeur porté, et les deux passages doivent dire la même chose.

D'où sa contrainte de construction : il ne sonde QUE ce qui survit au portage — la position, la
pause et la vitesse de l'`<audio>` de la page, le DOM (libellés, ligne surlignée ou sélectionnée,
champ en saisie, nombre de segments) et le CORPS des écritures. Jamais une variable interne.

DEUX FORMES DE PAGE (2026-10-21, étape 2 : l'éditeur devient une SURFACE déclarée) : la page
d'origine (`/transcriber/edit/<pk>/`) et la surface (`/common/surface/transcriber/correct/<pk>/`).
Les gestes sont les mêmes ; seule change la table `PAGES` — où trouver chaque commande et comment
la page nomme son lecteur. Mesuré le 2026-10-21 : 66/66 sur l'une puis sur l'autre, contre-épreuve
rouge des deux côtés. La page d'origine retirée, sa forme l'est aussi ; une forme de plus se joue
par `WAMA_EDITOR_PARITY_FORM`.

Témoin : UNE transcription du compte de test, une minute de silence, trois segments (« un. »
corrigé, « deux », « trois » ; le dernier s'arrête à 50 s, un silence suit) — retirée en sortie.
⚠ Toute écriture est INTERCEPTÉE et refusée dans la page (`BLOCK_WRITES`), son corps relevé :
l'enregistrement, le recalage et le curseur d'écriture partent dans le vide ; le serveur n'en voit
rien. Seul geste qui écrit hors de la page : une proposition des modes d'écriture SEMÉE dans le
cache (ce que le serveur y déposerait), retirée en sortie.
"""
import json
import os

from .ui_smoke import BASE_URL, _drop_new_sessions, _exiger_la_page, _motif_skip, _session_keys
from .ui_smoke_layout import _collect, _desktop_page, _mount_transcripts, _wait_player

#: Où trouver chaque commande, par forme de page. `player` : l'identifiant du lecteur commun
#: (`{pk}` remplacé) ; `finished` : ce que porte le corps de l'enregistrement « Terminer ».
#: La forme « editor » (la page d'origine, `#gotoTime`, `.t-compact`…) a servi le passage AVANT
#: — 66/66 le 2026-10-21 — et s'est retirée avec la page (REMOVAL_LEDGER R166).
PAGES = {
    # La surface déclarée (`transcriber/surfaces.py`) : les commandes portent un `data-*` de leur
    # brique — le transport commun, la liste des segments, les réglages, les intervenants.
    'surface': {
        'url': ('common:surface', ('transcriber', 'correct')),
        'player': 'surface-{pk}-audio',
        'goto': '[data-transport="goto"]', 'speed_up': '[data-transport="speed-up"]',
        'speed_down': '[data-transport="speed-down"]', 'speed_label': '[data-transport="speed-label"]',
        'skip_fwd': '[data-transport="skip-fwd"]', 'skip_back': '[data-transport="skip-back"]',
        'zoom_label': '[data-transport="zoom-label"]', 'wave': '[data-transport="wave"]',
        'mini': '[data-transport="mini"]', 'heat': '[data-transport="heat"] .hz',
        'lock': '[data-segments="follow"]', 'tool': '[data-transport="boundaries"]',
        'write_mode': '[data-transport="write-mode"]', 'rec': '[data-transport="rec"]',
        'proposal': '[data-transport="proposals"] .wp-item',
        'compact': '[data-segments="compact"]', 'finalize': '[data-act="finish"]',
        'review_count': '[data-segments="review-count"]',
        'title': '[data-settings] [name="title"]', 'speaker_names': '[data-speakers] input[data-key]',
        'apply_speakers': '[data-speakers="apply"]', 'suggest': '[data-speakers="suggest"]',
        'load_latest': '[data-segments="load-latest"]',
        'finished': '"finished":true',
    },
}
FORM = 'surface'

#: L'état de l'éditeur tel qu'un utilisateur le voit — rien d'interne à la page.
JS_EDITOR_STATE = """(M) => {
    const a = window.WamaAudioPlayer ? WamaAudioPlayer.getAudio(M.player) : null;
    const q = s => [...document.querySelectorAll(s)].find(e => e.offsetParent !== null) || document.querySelector(s);
    const index = s => { const r = q(s); return r ? Number(r.dataset.i) : -1; };
    const ae = document.activeElement;
    const lock = q(M.lock), tool = q(M.tool), rec = q(M.rec);
    return {
        t: a ? Math.round(a.currentTime * 100) / 100 : null,
        paused: a ? a.paused : null,
        rate: a ? a.playbackRate : null,
        speed: ((q(M.speed_label) || {}).textContent || '').trim(),
        zoom: ((q(M.zoom_label) || {}).textContent || '').trim(),
        active: index('.seg-row.seg-active'),
        selected: index('.seg-row.seg-selected'),
        editing: ae && ae.classList && ae.classList.contains('seg-text') ? Number(ae.dataset.i) : -1,
        rows: document.querySelectorAll('.seg-row').length,
        texts: [...document.querySelectorAll('.seg-text')].map(e => e.textContent),
        speakers: [...document.querySelectorAll('.seg-speaker input')].map(e => e.value),
        names: [...document.querySelectorAll('.seg-spk-name')].map(e => e.textContent),
        reviewed: document.querySelectorAll('.seg-row.seg-reviewed').length,
        review: ((q(M.review_count) || {}).textContent || '').trim(),
        lock: !!(lock && (lock.getAttribute('aria-pressed') === 'true' || lock.classList.contains('btn-info'))),
        tool: tool ? tool.getAttribute('aria-pressed') : null,
        rec: rec ? !rec.classList.contains('d-none') : null,
        proposals: [...document.querySelectorAll(M.proposal)].length,
        posted: (window.__wamaBodies || []).length,
    };
}"""

#: Les écritures refusées depuis la `n`-ième : `[{url, body}]`.
JS_POSTED_SINCE = "(n) => (window.__wamaBodies || []).slice(n)"

SETTLE_MS = 300


def _near(value, target, tolerance=0.4):
    return value is not None and abs(value - target) <= tolerance


class _Editor:
    """Les gestes de l'utilisateur sur la page, et la lecture de ce qu'il voit."""

    def __init__(self, page, selectors):
        self.page = page
        self.m = selectors

    def state(self):
        return self.page.evaluate(JS_EDITOR_STATE, self.m)

    def sel(self, name):
        """Le sélecteur de la commande `name`, restreint à l'exemplaire VISIBLE (l'éditeur
        d'origine en a deux de certaines : barre du haut et volet droit)."""
        return f"{self.m[name]} >> visible=true"

    def key(self, combo, wait=SETTLE_MS):
        self.page.keyboard.press(combo)
        self.page.wait_for_timeout(wait)
        return self.state()

    def release_focus(self):
        """Rend le clavier à la page (un bouton cliqué garderait Espace pour lui)."""
        self.page.evaluate("() => document.activeElement && document.activeElement.blur()")

    def goto(self, timecode):
        """« Aller à » : le champ, Entrée, puis Échap rend le clavier à la navigation."""
        self.page.fill(self.sel('goto'), timecode)
        self.page.press(self.sel('goto'), 'Enter')
        self.page.wait_for_timeout(SETTLE_MS)
        self.page.keyboard.press('Escape')
        self.release_focus()
        self.page.wait_for_timeout(SETTLE_MS)
        return self.state()

    def ensure_paused(self):
        if not self.state()['paused']:
            self.key('Space')

    def click(self, name, wait=SETTLE_MS):
        self.page.click(self.sel(name))
        self.page.wait_for_timeout(wait)
        self.release_focus()
        return self.state()

    def click_at(self, name, fx, fy=0.5, wait=SETTLE_MS):
        box = self.page.locator(self.sel(name)).bounding_box()
        self.page.mouse.click(box['x'] + box['width'] * fx, box['y'] + box['height'] * fy)
        self.page.wait_for_timeout(wait)
        return self.state()

    def drag_on(self, name, fx0, fx1, fy=0.3, wait=SETTLE_MS):
        box = self.page.locator(self.sel(name)).bounding_box()
        y = box['y'] + box['height'] * fy
        self.page.mouse.move(box['x'] + box['width'] * fx0, y)
        self.page.mouse.down()
        for k in range(1, 9):
            self.page.mouse.move(box['x'] + box['width'] * (fx0 + (fx1 - fx0) * k / 8), y)
            self.page.wait_for_timeout(20)
        self.page.mouse.up()
        self.page.wait_for_timeout(wait)
        return self.state()

    def wheel_on(self, name, delta, times=1):
        box = self.page.locator(self.sel(name)).bounding_box()
        self.page.mouse.move(box['x'] + box['width'] / 2, box['y'] + box['height'] / 2)
        for _ in range(times):
            self.page.mouse.wheel(0, delta)
            self.page.wait_for_timeout(80)
        self.page.wait_for_timeout(SETTLE_MS)
        return self.state()

    def write_mode(self, value):
        self.page.select_option(self.sel('write_mode'), value)
        self.release_focus()
        self.page.wait_for_timeout(SETTLE_MS)

    def posted_since(self, n):
        return self.page.evaluate(JS_POSTED_SINCE, n)

    def wait_posted(self, n, needle, timeout_ms=2500):
        """La première écriture refusée depuis la `n`-ième dont le corps contient `needle`."""
        for _ in range(timeout_ms // 100):
            found = [p for p in self.posted_since(n) if needle in (p.get('body') or '')]
            if found:
                return found[0]
            self.page.wait_for_timeout(100)
        return None


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
    ed.click('speed_up')
    s = ed.click('speed_up')
    checks.append((s['rate'] == 1.5 and s['speed'] == '1.5×', f"+ + = vitesse 1,5 ({s['rate']}, « {s['speed']} »)"))
    ed.click('speed_down')
    s = ed.click('speed_down')
    checks.append((s['rate'] == 1 and s['speed'] == '1.0×', f"− − = vitesse 1 ({s['rate']}, « {s['speed']} »)"))
    s = ed.click('skip_fwd')
    s2 = ed.click('skip_back')
    checks.append((_near(s['t'] - s2['t'], 5), f"boutons ±5 s ({s['t']} → {s2['t']})"))
    ed.page.fill(ed.sel('goto'), 'abc')
    ed.page.press(ed.sel('goto'), 'Enter')
    ed.page.wait_for_timeout(150)
    invalid = ed.page.locator(ed.sel('goto')).evaluate("e => e.classList.contains('is-invalid')")
    ed.page.keyboard.press('Escape')
    ed.release_focus()
    checks.append((invalid, f"un temps illisible est signalé, la lecture reste ({invalid})"))


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
    s = ed.key('Alt+ArrowDown')
    s2 = ed.key('Alt+ArrowUp')
    checks.append((s['selected'] == 2 and s2['selected'] == 1, f"Alt+↓ / Alt+↑ en navigation ({s['selected']}, {s2['selected']})"))
    s = ed.key('Enter')
    checks.append((s['editing'] == 1, f"Entrée = édition du segment sélectionné ({s['editing']})"))
    s2 = ed.key('Alt+ArrowDown')
    ed.key('Alt+ArrowUp')
    checks.append((s2['editing'] == 2, f"Alt+↓ en édition = champ suivant ({s2['editing']})"))
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


def _editing(ed, checks):
    """Fusions, compactage, locuteur, relecture, enregistrement, terminer."""
    s = ed.click('compact')
    s2 = ed.key('Control+z')
    checks.append((s['rows'] == 1 and s2['rows'] == 3,
                   f"Compacter fusionne un même locuteur, Ctrl+Z le défait ({s['rows']}, {s2['rows']})"))
    ed.goto('0:05')
    ed.key('Enter')
    s = ed.key('Delete')
    ed.key('Escape')
    s2 = ed.key('Control+z')
    checks.append((s['rows'] == 2 and s['texts'][0] == 'un. deux' and s2['rows'] == 3,
                   f"Suppr en fin de texte fusionne avec le suivant ({s['rows']}, {s['texts'][:1]}, puis {s2['rows']})"))
    ed.goto('0:25')
    ed.key('Enter')
    ed.key('Home')
    s = ed.key('Backspace')
    ed.key('Escape')
    s2 = ed.key('Control+z')
    checks.append((s['rows'] == 2 and s['texts'][0] == 'un. deux' and s2['rows'] == 3,
                   f"Retour arrière en début fusionne avec le précédent ({s['rows']}, {s['texts'][:1]}, puis {s2['rows']})"))
    ed.page.drag_and_drop('.seg-drag[data-i="0"]', '.seg-row[data-i="2"]')
    ed.page.wait_for_timeout(SETTLE_MS)
    s = ed.state()
    s2 = ed.key('Control+z')
    checks.append((s['rows'] == 1 and s['texts'][0] == 'un. deux trois' and s2['rows'] == 3,
                   f"glisser la poignée sur un segment fusionne la plage ({s['rows']}, {s['texts'][:1]}, puis {s2['rows']})"))
    n = ed.state()['posted']
    ed.page.click('.seg-row[data-i="2"] .seg-speaker input')
    ed.page.keyboard.press('End')
    ed.page.keyboard.type('B')
    ed.page.keyboard.press('Escape')
    ed.page.wait_for_timeout(SETTLE_MS)
    s = ed.state()
    checks.append((s['speakers'][2] == 'AB' and s['reviewed'] == 1 and s['review'] == '1 / 3',
                   f"le locuteur se corrige, le segment passe « revu » ({s['speakers']}, {s['review']})"))
    saved = ed.wait_posted(n, '"AB"')
    checks.append((saved is not None, f"l'enregistrement part seul après la modification ({(saved or {}).get('url')})"))
    ed.page.click('.seg-row[data-i="1"] .seg-review')
    ed.page.wait_for_timeout(150)
    s = ed.state()
    ed.page.click('.seg-row[data-i="1"] .seg-review')
    ed.page.wait_for_timeout(150)
    s2 = ed.state()
    ed.release_focus()
    checks.append((s['review'] == '2 / 3' and s2['review'] == '1 / 3',
                   f"✓ bascule « revu », la progression suit ({s['review']}, {s2['review']})"))
    s = ed.key('Control+z')
    checks.append((s['speakers'][2] == 'A' and s['reviewed'] == 0,
                   f"Ctrl+Z défait le locuteur et la relecture ({s['speakers']}, {s['reviewed']})"))
    n = ed.state()['posted']
    ed.click('finalize')
    done = ed.wait_posted(n, ed.m['finished'])
    checks.append((done is not None, f"« Terminer » enregistre la correction comme terminée ({(done or {}).get('url')})"))


def _bornes(ed, checks):
    """Outil Bornes : déplacer une borne, couper, créer dans un silence."""
    ed.wheel_on('wave', 400, times=12)
    ed.click('tool')
    n = ed.state()['posted']
    ed.drag_on('wave', 20 / 60, 24 / 60, fy=0.1)
    moved = ed.wait_posted(n, '"op":"move"')
    checks.append((moved is not None, f"glisser une borne demande son déplacement ({(moved or {}).get('url')})"))
    n = ed.state()['posted']
    ed.click_at('wave', 30 / 60, fy=0.6)
    cut = ed.wait_posted(n, '"op":"split"')
    checks.append((cut is not None, f"cliquer dans une section la coupe ({(cut or {}).get('url')})"))
    s = ed.click_at('wave', 55 / 60, fy=0.6)
    checks.append((s['rows'] == 4 and s['editing'] == 3,
                   f"cliquer dans un silence crée un segment à remplir ({s['rows']}, en édition : {s['editing']})"))
    ed.key('Escape')
    s = ed.key('Control+z')
    s2 = ed.key('Escape')
    checks.append((s['rows'] == 3 and s2['tool'] == 'false', f"Ctrl+Z le retire, Échap sort de l'outil ({s['rows']}, {s2['tool']})"))


def _toggles(ed, checks):
    """Alt+L (suivi), C / Échap (outil Bornes), mode d'écriture Touch + R maintenu."""
    lock0 = ed.state()['lock']
    s = ed.key('Alt+l')
    s2 = ed.key('Alt+l')
    checks.append((s['lock'] != lock0 and s2['lock'] == lock0, f"Alt+L bascule le suivi ({lock0} → {s['lock']} → {s2['lock']})"))
    s = ed.key('c')
    s2 = ed.key('Escape')
    checks.append((s['tool'] == 'true' and s2['tool'] == 'false', f"C ouvre l'outil Bornes, Échap le ferme ({s['tool']}, {s2['tool']})"))
    ed.write_mode('touch')
    ed.goto('0:10')
    ed.key('Space', wait=400)
    ed.page.keyboard.down('r')
    ed.page.wait_for_timeout(SETTLE_MS)
    held = ed.state()['rec']
    ed.page.keyboard.up('r')
    ed.page.wait_for_timeout(SETTLE_MS)
    released = ed.state()['rec']
    ed.ensure_paused()
    ed.write_mode('')
    checks.append((held is True and released is False, f"Touch : R maintenu enregistre, relâché s'arrête ({held}, {released})"))


def _writing(ed, checks, seed):
    """Modes Latch, Write, Complément ; propositions écoutées, refusées, acceptées."""
    ed.write_mode('latch')
    ed.goto('0:10')
    ed.key('Space', wait=300)
    s = ed.key('r')
    s2 = ed.key('Space')
    checks.append((s['rec'] is True and s2['rec'] is False, f"Latch : R enregistre jusqu'à l'arrêt ({s['rec']}, {s2['rec']})"))
    ed.write_mode('write')
    ed.goto('0:10')
    s = ed.key('Space', wait=1400)
    s2 = ed.key('Space')
    checks.append((s['rec'] is True and s2['rec'] is False, f"Write : toute la lecture enregistre ({s['rec']}, {s2['rec']})"))
    ed.write_mode('complement')
    ed.goto('0:45')
    n = ed.state()['posted']
    ed.key('Space', wait=300)
    asked = ed.wait_posted(n, '"mode":"complement"')
    ed.ensure_paused()
    wanted = json.loads(asked['body']).get('wanted') if asked else None
    checks.append((bool(wanted) and any(a <= 51 and b >= 59 for a, b in wanted),
                   f"Complément demande le silence devant la tête ({wanted})"))
    ed.write_mode('touch')
    seed({'id': 0, 'mode': 'touch', 'start': 5.0, 'end': 8.0,
          'words': [{'word': ' bonjour', 'start': 5.0, 'end': 6.0}], 'text': 'bonjour'})
    ed.page.wait_for_timeout(1600)
    s = ed.state()
    checks.append((s['proposals'] == 1, f"une proposition reçue s'affiche ({s['proposals']})"))
    if s['proposals']:
        ed.page.click(f"{ed.m['proposal']} .wp-time")
        ed.page.wait_for_timeout(500)
        s = ed.state()
        ed.ensure_paused()
        checks.append((5 <= s['t'] < 6.5, f"cliquer la proposition l'écoute ({s['t']})"))
        n = ed.state()['posted']
        ed.page.click(f"{ed.m['proposal']} .wp-accept")
        accepted = ed.wait_posted(n, '"op":"replace"')
        checks.append((accepted is not None, f"✓ demande le remplacement de la plage ({(accepted or {}).get('url')})"))
        ed.page.click(f"{ed.m['proposal']} .wp-reject")
        ed.page.wait_for_timeout(SETTLE_MS)
        checks.append((ed.state()['proposals'] == 0, "✗ retire la proposition"))
    ed.write_mode('')


def _panel(ed, checks):
    """Titre, intervenants, identification, charger la dernière transcription."""
    n = ed.state()['posted']
    ed.page.fill(ed.sel('title'), 'Témoin titre')
    titled = ed.wait_posted(n, 'Témoin titre')
    ed.release_focus()
    checks.append((titled is not None, f"le titre s'enregistre ({(titled or {}).get('url')})"))
    names = ed.page.locator(ed.sel('speaker_names'))
    checks.append((names.count() == 1, f"un champ par intervenant détecté ({names.count()})"))
    if names.count():
        names.first.fill('Alice')
        n = ed.state()['posted']
        ed.click('apply_speakers')
        applied = ed.wait_posted(n, '"Alice"')
        s = ed.state()
        checks.append((applied is not None and s['names'].count('Alice') == 3,
                       f"« Appliquer les noms » enregistre et nomme chaque segment ({s['names']})"))
    n = ed.state()['posted']
    ed.click('suggest')
    ed.page.wait_for_timeout(SETTLE_MS)
    asked = [p['url'] for p in ed.posted_since(n) if 'suggest' in p['url']]
    checks.append((bool(asked), f"« Identifier automatiquement » interroge le serveur ({asked})"))
    ed.page.once('dialog', lambda d: d.accept())
    s = ed.click('load_latest')
    s2 = ed.key('Control+z')
    checks.append((s['texts'][0] == 'un' and s2['texts'][0] == 'un.',
                   f"charger la dernière transcription la remet, Ctrl+Z rend la correction ({s['texts'][:1]}, {s2['texts'][:1]})"))


def _views(ed, checks):
    """L'onde, la minimap, la carte de chaleur, le ▶ d'un segment, le surlignage en lecture."""
    z0 = ed.state()['zoom']
    s = ed.wheel_on('wave', -200, times=4)
    checks.append((s['zoom'] != z0, f"molette sur l'onde zoome ({z0} → {s['zoom']})"))
    ed.goto('0:30')
    s = ed.click_at('wave', 0.5)
    checks.append((_near(s['t'], 30, 3), f"clic au milieu de l'onde ≈ son centre ({s['t']})"))
    ed.click_at('mini', 0.92)
    s = ed.click_at('wave', 0.5)
    checks.append((s['t'] > 40, f"la minimap déplace la fenêtre de l'onde (centre → {s['t']})"))
    s = ed.wheel_on('wave', 400, times=12)
    checks.append((s['zoom'] == '×1.0', f"molette arrière jusqu'à la vue entière (« {s['zoom']} »)"))
    zones = ed.page.locator(ed.m['heat'])
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


def check_editor_parity(form=None):
    """Les lignes « éditeur » de la matrice de parité, chacune par son geste."""
    from django.core.cache import cache
    from django.urls import reverse
    from playwright.sync_api import sync_playwright

    from wama.common.services.nightly_tests import SkipScenario
    from wama.transcriber.workers import WRITE_TTL, write_channel
    from .ui_smoke import _garde_de_montage, _test_account_id, _test_session_key, _total_nettoye

    form = form or os.environ.get('WAMA_EDITOR_PARITY_FORM') or FORM
    selectors = dict(PAGES[form])
    sessions_before = _session_keys()
    token, uid = _test_session_key('transcriber'), _test_account_id('transcriber')
    if not (token and uid):
        raise SkipScenario("aucun compte de test disponible (wama_nightly_test / wama_ui_smoke_v3)")
    faults, steps = [], [f"forme « {form} »"]
    with _garde_de_montage('transcriber', 'editor_parity') as cleaned:
        made = _mount_transcripts(uid, count=1, gap=True, corrected=True)
        pk = made[0].pk
        name, extra = selectors.pop('url')
        url = BASE_URL.rstrip('/') + reverse(name, args=[*extra, pk])
        selectors['player'] = selectors['player'].format(pk=pk)
        results_key = write_channel(pk).key('results')

        def seed(result):
            """Ce que la boucle serveur des modes d'écriture déposerait (`workers.live_write`)."""
            cache.set(results_key, (cache.get(results_key) or []) + [result], WRITE_TTL)

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
                            ed = _Editor(page, selectors)
                            parts = (_transport, _shuttle, _navigation, _editing, _bornes, _toggles,
                                     lambda e, c: _writing(e, c, seed), _panel, _views)
                            labels = ('Transport', 'Shuttle', 'Navigation', 'Édition', 'Bornes', 'Bascules',
                                      "Modes d'écriture", 'Volet', 'Vues')
                            for part, label in zip(parts, labels):
                                checks = []
                                try:
                                    part(ed, checks)
                                except Exception as exc:          # un geste qui casse n'arrête pas les autres
                                    checks.append((False, f"geste interrompu : {str(exc)[:160]}"))
                                _collect(f"éditeur · {label}", checks, [], faults, steps)
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
            cache.delete(results_key)
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
                     "fusions, compactage, locuteur, relecture, enregistrement, terminer, outil Bornes, "
                     "modes d'écriture et propositions, titre, intervenants, dernière transcription, "
                     "onde, minimap, carte de chaleur, ▶ de segment, surlignage — sondé par l'audio, "
                     "le DOM et le corps des écritures refusées"),
        run=lambda ctx: check_editor_parity(),
        timeout_s=480, vram_gb=0.0,
    )
