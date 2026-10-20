"""Scénarios nocturnes `ui` — l'APERÇU d'une card : son entrée, puis sa sortie (gestes 11 et 11b).

Né le 2026-10-12 de deux défauts relevés par Fabien le même jour : dans le Describer, ouvrir l'aperçu
de la card disait « No media URL available » ; dans le Reader, un clic sur le fichier d'entrée
n'ouvrait rien. Le geste 11 existait (`<app>.processing`), mais il n'est JOUÉ que là où un
traitement réel tourne sans GPU — le converter seul. Les faces TEXTE (Describer, Reader,
Transcriber) n'étaient donc jamais ouvertes par aucun scénario, et l'ENTRÉE d'aucune card.

CE QU'IL FAIT, sans GPU et sans connaître aucune app :
  1. monte un élément par le dépôt ordinaire (`_monter_un_lot`) ;
  2. lui POSE un résultat en base, comme `<app>.worker_death` pose un état de crash : le champ que
     la spec de détail déclare (`result_text`, sinon `result_file`), avec un témoin de la nature
     que l'app déclare produire (`APP_CATALOG.output_types`) ;
  3. clique le NOM d'entrée de la card (`.preview-media-link`) → la visionneuse doit MONTRER
     quelque chose, puis passer sur sa face Sortie par sa propre bascule ;
  4. double-clique l'aperçu de la card (`.wama-card-preview`) → la visionneuse commune, avec la
     face Entrée dans sa bascule quand la spec en déclare une. Une app qui intercepte
     `wama:card-expand` (transcriber) ouvre sa propre modale : dit en ⚠, elle n'a pas les faces.
     Une card FILLE de lot a son aperçu comme une card seule (enhancer aligné le 2026-10-12).
  4bis. (2026-10-13) sélectionne la card : le bouton d'agrandissement de l'aperçu du VOLET reçoit le
     clic, n'est pas posé sur l'aperçu, et ouvre la visionneuse commune ;
  5. (2026-10-13) passe au clavier de cette card à l'autre élément monté — face gardée — et, la
     visionneuse refermée, exige que le volet sélectionne la card d'arrivée.
Une erreur d'aperçu (le toast que lève `media-preview.js`) est un ÉCHEC, jamais un constat.

Trois matrices COMMUNES, sans élément monté : `common.preview_layout` (la place de la bascule des
faces, par nature de fichier), `common.preview_navigation` (les gestes de navigation : fichiers
d'un élément, cards voisines, face gardée, gestionnaire de fichiers, galerie et surcouche) et
`common.preview_during` (2026-10-20 : un élément EN COURS suivi en direct sur sa face Pendant).

Module à part d'`ui_smoke.py` (même raison qu'`ui_smoke_panel`) ; il en réutilise les briques et
ne redéfinit rien. ⚠ Tout l'ORM est HORS du contexte Playwright (`SynchronousOnlyOperation`).
"""
import os

from .ui_smoke import (BASE_URL, IDS_CARDS_JS, _exiger_la_page, _garde_de_montage, _image_temoin,
                       _in_plain_thread, _monter_un_lot, _motif_skip, _test_session_key,
                       _total_nettoye, _wav_silence, discoverable_apps)
from .ui_smoke_matching import _cookie

PAGE_TIMEOUT_MS = 90000
RESULT_TEXT = 'Résultat témoin du geste « aperçu » (scénario nocturne).'

#: Pose une sonde sur les deux voies par lesquelles la modale dit son échec (`showPreviewError`) :
#: le toast du gestionnaire de fichiers, sinon le toast global. Lue après chaque geste.
JS_PROBE = """() => {
    window.__previewErrors = [];
    const keep = (m) => window.__previewErrors.push(String(m));
    const wrap = (owner, name) => {
        const original = owner && owner[name];
        if (typeof original !== 'function' || original.__wamaProbe) return;
        const probe = function (message, kind) {
            if (kind === 'danger' || kind === 'error') keep(message);
            return original.apply(this, arguments);
        };
        probe.__wamaProbe = true;
        owner[name] = probe;
    };
    wrap(window.FileManager, 'showToast');
    wrap(window, 'showToast');
}"""

#: Ce que montre la visionneuse commune : un élément de CONTENU dans son conteneur (pas les
#: boutons de navigation ni la bascule des faces), et le texte d'un `<pre>` (une erreur de
#: chargement s'y écrit). `null` : aucune visionneuse commune ouverte.
JS_SHOWN = """() => {
    const modal = document.querySelector('#wamaMediaPreviewModal.show');
    if (!modal) return null;
    const box = modal.querySelector('.preview-container');
    // (Les bascules ne sont plus DANS le conteneur depuis le 2026-10-13 : emplacement dédié sous lui.)
    const parts = box ? Array.from(box.children).filter(e => !e.matches('.wama-preview-nav-btn')) : [];
    const media = box && box.querySelector('video, audio, img, embed, pre, canvas, [data-wama-3d], .wama-audio-player');
    const pre = box && box.querySelector('pre');
    // Le nom d'un contenu : sa balise, sinon (un <div> de lecteur, un conteneur) sa classe.
    const named = (e) => e.tagName === 'DIV' && e.className
        ? String(e.className).split(' ')[0] : e.tagName.toLowerCase();
    return {parts: parts.length,
            media: media ? named(media) : (parts[0] ? named(parts[0]) : ''),
            text: pre ? pre.textContent.slice(0, 80) : '',
            sides: Array.from(modal.querySelectorAll('.wama-modal-sides button'))
                        .map(b => b.textContent.trim())};
}"""


#: La PLACE de la bascule des faces (Entrée | … | Sortie) et des vues dans la visionneuse : sa boîte
#: ne croise pas celle de l'aperçu, elle est AU-DESSUS de lui (des onglets, depuis le 2026-10-14 —
#: sous lui avant), et visible sans défiler. Demande de Fabien (2026-10-13) : posée sur l'aperçu,
#: elle recouvrait la barre d'outils du lecteur PDF, le haut d'un texte, l'image ou la vidéo à tout
#: l'écran. `null` : pas de visionneuse ou pas de bascule.
#: Et les FLÈCHES de navigation (2026-10-15, Fabien : posées sur l'aperçu, elles masquaient le
#: bouton de lecture d'un son) : `nav_cross` = une flèche AFFICHÉE croise le contenu.
JS_SIDES_LAYOUT = """() => {
    const m = document.querySelector('#wamaMediaPreviewModal.show');
    if (!m) return null;
    const box = m.querySelector('.preview-container');
    const content = box && Array.from(box.children).find(e => !e.matches('.wama-preview-nav-btn'));
    const bars = Array.from(m.querySelectorAll('.wama-modal-sides, .wama-modal-variants'));
    if (!content || !bars.length) return null;
    const r = e => e.getBoundingClientRect();
    const c = r(content);
    const media = box.querySelector('img, video, embed, pre');
    const navs = Array.from(m.querySelectorAll('.wama-preview-nav-btn'))
        .filter(b => getComputedStyle(b).display !== 'none' && r(b).width > 0);
    return {
        navs: navs.length,
        nav_cross: navs.some(b => { const s = r(b);
            return !(s.right <= c.left + 0.5 || s.left >= c.right - 0.5 || s.bottom <= c.top || s.top >= c.bottom); }),
        bars: bars.map(b => { const s = r(b); return {
            cross: !(s.bottom <= c.top || s.top >= c.bottom || s.right <= c.left || s.left >= c.right),
            above: s.bottom <= c.top + 0.5,
            visible: s.top >= 0 && s.bottom <= window.innerHeight}; }),
        fills: media ? r(media).height >= c.height - 2 : true,
    };
}"""

#: Basculer la visionneuse à tout l'écran (`on`) ou la rendre à sa taille.
JS_FULL = """(on) => {
    const t = document.querySelector('#wamaMediaPreviewModal .wama-preview-full-toggle');
    const d = document.querySelector('#wamaMediaPreviewModal .modal-dialog');
    if (t && d && d.classList.contains('modal-fullscreen') !== on) t.click();
}"""


#: Le bouton d'agrandissement de l'aperçu du VOLET. Relevé par Fabien le 2026-10-13 : visible mais
#: inerte (un décor en `pointer-events:none`), et posé en absolu SUR l'aperçu, par-dessus
#: l'ascenseur d'un texte long. `receives` : au centre du bouton, c'est lui qui reçoit le clic.
JS_PANEL_EXPAND = """() => {
    const host = document.getElementById('preview-container');
    const btn = document.querySelector('.wama-preview-expand');
    if (!host || !btn) return {host: !!host, button: !!btn};
    const b = btn.getBoundingClientRect(), h = host.getBoundingClientRect();
    const hit = document.elementFromPoint(b.left + b.width / 2, b.top + b.height / 2);
    return {host: true, button: true, sized: b.width > 4 && b.height > 4,
            receives: !!hit && btn.contains(hit),
            crosses: !(b.bottom <= h.top || b.top >= h.bottom || b.right <= h.left || b.left >= h.right)};
}"""


def panel_expand_fault(state) -> str:
    """'' si le bouton d'agrandissement du volet est un vrai bouton, hors de l'aperçu ; sinon ce
    qui cloche. `None` ou pas d'hôte : la page n'a pas d'aperçu de volet, rien à juger."""
    if not state or not state.get('host'):
        return ''
    if not state.get('button'):
        return "volet : l'aperçu n'a pas de bouton d'agrandissement"
    if not state.get('sized'):
        return "volet : le bouton d'agrandissement n'a pas de taille (masqué)"
    if state.get('crosses'):
        return "volet : le bouton d'agrandissement est posé SUR l'aperçu (il en recouvre l'ascenseur)"
    if not state.get('receives'):
        return "volet : le bouton d'agrandissement ne reçoit pas le clic (décor ou recouvert)"
    return ''


def _check_panel_expand(page, card_sel: str, faults: list, findings: list):
    """La card sélectionnée, son aperçu dans le volet s'agrandit par SON bouton : la visionneuse
    commune s'ouvre (le même geste que le double-clic sur l'aperçu)."""
    page.locator(card_sel).first.click(position={'x': 6, 'y': 6}, timeout=6000)
    try:
        page.wait_for_selector('.wama-preview-expand', state='attached', timeout=10000)
    except Exception:
        pass                         # le verdict ci-dessous dit ce qui manque
    fault = panel_expand_fault(page.evaluate(JS_PANEL_EXPAND))
    if fault:
        faults.append(fault)
        return
    shown, errors = _open_and_read(page, lambda: page.locator('.wama-preview-expand').first.click(timeout=4000))
    fault = _verdict("agrandissement de l'aperçu du volet", shown, errors)
    if fault:
        faults.append(fault)
    else:
        findings.append(f"volet : le bouton d'agrandissement ouvre la visionneuse ({_seen(shown)})")
    _close(page)


def sides_layout_fault(layout, where: str, must_fill: bool = False) -> str:
    """'' si la bascule a SA place (au-dessus de l'aperçu, sans le croiser, visible), sinon ce qui
    cloche. `must_fill` : à tout l'écran, une image ou une vidéo prend la hauteur disponible."""
    if not layout:
        return ''
    for bar in layout['bars']:
        if bar['cross']:
            return f"{where} : la bascule des faces RECOUVRE l'aperçu"
        if not bar['above']:
            return f"{where} : la bascule des faces n'est pas AU-DESSUS de l'aperçu"
        if not bar['visible']:
            return f"{where} : la bascule des faces sort de l'écran"
    if layout.get('nav_cross'):
        return f"{where} : une flèche de navigation recouvre l'aperçu"
    if must_fill and not layout['fills']:
        return f"{where} : le média ne prend pas la hauteur disponible"
    return ''


def _check_sides_layout(page, where: str, faults: list):
    """La place de la bascule, la visionneuse à sa taille PUIS à tout l'écran (rendue ensuite)."""
    for full in (False, True):
        page.evaluate(JS_FULL, full)
        page.wait_for_timeout(500)
        fault = sides_layout_fault(page.evaluate(JS_SIDES_LAYOUT),
                                   f"{where} ({'tout l’écran' if full else 'modale'})")
        if fault:
            faults.append(fault)
    page.evaluate(JS_FULL, False)


def _check_contrast(page, where: str, faults: list, findings: list, context: str = ''):
    """Le contraste de l'état montré (`ui_smoke_contrast`) : un texte illisible est un défaut ;
    les composants faibles se disent dans les constats."""
    from .ui_smoke_contrast import contrast_verdict, measure_contrast
    try:
        found, weak = contrast_verdict(measure_contrast(page, context), where)
    except Exception as exc:                      # la mesure ne doit pas masquer le geste mesuré
        findings.append(f"contraste ({where}) non mesuré : {type(exc).__name__}")
        return
    faults.extend(found)
    if weak:
        findings.append(f"contraste ({where}) : faibles " + ', '.join(f'{k} ×{v}' for k, v in weak.most_common(4)))


def _store_a_witness_result(app: str, item_id) -> tuple:
    """Pose sur l'élément le résultat que sa spec DÉCLARE, et SUCCESS. Rend (ce qui a été posé,
    fichier témoin à retirer ou None) — ou (None, raison) si la spec ne nomme aucun champ."""
    from django.conf import settings
    from django.db.models import FileField

    from wama.common.app_registry import _result_natures
    from wama.common.utils.detail_registry import DetailRegistry
    from wama.common.utils.media_paths import app_media_dir
    from wama.common.utils.preview_registry import PreviewRegistry

    model = PreviewRegistry.get_model(app)
    spec = (DetailRegistry.get(app) or {}).get('spec') or {}
    fields = {f.name: f for f in model._meta.fields}
    changes = {'status': 'SUCCESS'} if 'status' in fields else {}
    text_field = spec.get('result_text')
    if isinstance(text_field, str) and text_field in fields:
        model.objects.filter(pk=item_id).update(**changes, **{text_field: RESULT_TEXT})
        return f'texte posé dans `{text_field}`', None
    declared = spec.get('result_file')
    names = [declared] if isinstance(declared, str) else list(declared or [])
    file_field = next((n for n in names if isinstance(fields.get(n), FileField)), None)
    if not file_field:
        return None, "la spec de détail ne nomme aucun champ de résultat (texte ou fichier)"
    natures = _result_natures(app) or ['image']
    nature = next((n for n in natures if n in ('audio', 'image', 'document')), None)
    if nature is None:
        return None, f"aucun témoin pour la nature déclarée {natures} (vidéo seule)"
    ext, data = {'audio': ('.wav', _wav_silence()), 'image': ('.png', _image_temoin('.png')),
                 'document': ('.txt', RESULT_TEXT.encode('utf-8'))}[nature]
    owner = model.objects.values_list('user_id', flat=True).get(pk=item_id)
    rel = f"{app_media_dir(app, owner, 'output')}/smoke_preview_{item_id}{ext}"
    path = os.path.join(str(settings.MEDIA_ROOT), rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'wb') as out:
        out.write(data)
    model.objects.filter(pk=item_id).update(**changes, **{file_field: rel})
    return f'fichier {nature} posé dans `{file_field}`', path


def _entry_declared(app: str) -> bool:
    """La spec déclare-t-elle une entrée (`source_file` ou `source_text`) ?"""
    from wama.common.utils.detail_registry import DetailRegistry
    spec = (DetailRegistry.get(app) or {}).get('spec') or {}
    return bool(spec.get('source_file') or spec.get('source_text'))


def _open_and_read(page, opener, timeout_ms=20000):
    """Joue `opener` (le geste), attend une visionneuse, rend (ce qu'elle montre, erreurs d'aperçu).
    Ce qu'elle montre vaut `{'own': True}` quand la modale ouverte est celle de l'app."""
    page.evaluate(JS_PROBE)
    opener()
    try:
        page.wait_for_selector('#wamaMediaPreviewModal.show, .modal.show', timeout=timeout_ms)
    except Exception:
        return None, page.evaluate('() => window.__previewErrors || []')
    page.wait_for_timeout(800)          # le contenu se construit après l'ouverture
    shown = page.evaluate(JS_SHOWN) or {'own': True}
    return shown, page.evaluate('() => window.__previewErrors || []')


def _verdict(what: str, shown, errors) -> str:
    """'' si la visionneuse montre un contenu sans erreur, sinon ce qui manque."""
    if errors:
        return f"{what} : erreur d'aperçu « {' | '.join(errors)} »"
    if shown is None:
        return f"{what} : aucune visionneuse ne s'ouvre"
    if shown.get('own'):
        return ''
    if not shown.get('parts'):
        return f"{what} : la visionneuse s'ouvre VIDE"
    if shown.get('text', '').startswith(('Erreur', 'Aperçu indisponible')):
        return f"{what} : « {shown['text']} »"
    return ''


def _seen(shown) -> str:
    """Ce que la visionneuse a montré, en clair : la modale PROPRE à l'app, ou le premier
    élément de contenu de la visionneuse commune (balise, sinon classe — un lecteur WaveSurfer)."""
    if shown.get('own'):
        return "modale propre à l'app"
    return shown.get('media') or 'contenu'


def _close(page):
    """Referme la visionneuse ET attend la fin de son fondu : le fond Bootstrap qui reste une
    fraction de seconde intercepte le geste suivant (mesuré le 2026-10-12 : le double-clic sur
    l'aperçu expirait derrière le fond de la visionneuse d'entrée, refermée par Échap).
    ⚠ Et pas PENDANT son ouverture : Bootstrap ignore Échap et `hide()` tant que le fondu d'entrée
    court — un geste qui referme aussitôt ouvert laissait la visionneuse ouverte (2026-10-13)."""
    page.wait_for_timeout(400)
    page.keyboard.press('Escape')
    page.evaluate("""() => document.querySelectorAll('.modal.show').forEach(m => {
        const i = window.bootstrap && bootstrap.Modal.getInstance(m); if (i) i.hide(); })""")
    page.wait_for_function("() => !document.querySelector('.modal.show, .modal-backdrop')",
                           timeout=8000)


def _check_card_navigation(page, card: str, ident, other, faults: list, findings: list):
    """La visionneuse ouverte sur l'entrée de `ident` passe, au clavier, à la card `other` (↑/↓ —
    deux cards au résultat posé), en GARDANT la face regardée ; refermée sur `other`, le volet la
    sélectionne. Mesuré le 2026-10-13 avant le correctif : les flèches ne faisaient rien dans la
    visionneuse, et ↓ déplaçait la sélection du volet DERRIÈRE elle."""
    seq = page.evaluate("""(sel) => { const c = document.querySelector(sel), P = window.WamaMediaPreview;
        return c && P && P.cardSequence ? P.cardSequence(c).map(e => e.dataset.id) : null; }""",
                        card.format(ident))
    if not seq or ident not in seq or other not in seq:
        faults.append(f"navigation : #{ident} et #{other} absentes de la séquence de la visionneuse ({seq})")
        return
    i, j = seq.index(ident), seq.index(other)
    key = 'ArrowDown' if j > i else 'ArrowUp'
    link = page.locator(card.format(ident) + ' .preview-media-link[data-preview-url]').first
    if link.count():
        opener = lambda: link.click(timeout=6000)             # noqa: E731
    else:
        preview = page.locator(card.format(ident) + ' .wama-card-preview').first
        opener = lambda: preview.dblclick(timeout=6000)       # noqa: E731
    shown, errors = _open_and_read(page, opener)
    if shown is None or shown.get('own') or errors:
        _close(page)
        return                       # l'ouverture elle-même est jugée par les gestes ci-dessus
    before = page.evaluate(JS_NAV_STATE) or {}
    for _ in range(abs(j - i)):
        page.keyboard.press(key)
        page.wait_for_timeout(250)
    want = f'{j + 1} / {len(seq)}'
    try:
        page.wait_for_function(
            """(w) => { const m = document.querySelector('#wamaMediaPreviewModal.show');
                const c = m && m.querySelector('.wama-preview-counter');
                const t = c ? c.textContent.trim() : '';
                return t === w || t.startsWith(w + ' ·'); }""", arg=want, timeout=8000)
    except Exception:
        faults.append(f"navigation : {key} ne mène pas à la card #{other} (vu {page.evaluate(JS_NAV_STATE)})")
        _close(page)
        return
    after = page.evaluate(JS_NAV_STATE) or {}
    if before.get('face') and after.get('face') != before.get('face'):
        faults.append(f"navigation : la face « {before['face']} » n'est pas gardée (« {after.get('face')} »)")
    _close(page)
    try:
        page.wait_for_function(
            "(id) => !!document.querySelector('[data-id=\"' + id + '\"].inspector-selected')",
            arg=str(other), timeout=6000)
    except Exception:
        faults.append(f"navigation : refermée sur la card #{other}, le volet ne la sélectionne pas")
        return
    # Les flèches DU VOLET (visionneuse fermée) : la sélection repart vers `ident` et l'aperçu du
    # volet est REFAIT (marqué avant, il doit avoir été remplacé) — l'autre lecture du défaut.
    back = 'ArrowUp' if key == 'ArrowDown' else 'ArrowDown'
    page.evaluate("() => { const h = document.getElementById('preview-container');"
                  " if (h && h.firstElementChild) h.firstElementChild.dataset.navProbe = 'old'; }")
    page.keyboard.press(back)
    try:
        page.wait_for_function(
            """([id, pos]) => { const sel = document.querySelector('.inspector-selected[data-id]');
                const h = document.getElementById('preview-container');
                return sel && sel.dataset.id === id && h && !h.querySelector('[data-nav-probe]')
                    && h.children.length > 0; }""",
            arg=[str(seq[j - 1 if back == 'ArrowUp' else j + 1]), j], timeout=8000)
    except Exception:
        faults.append(f"volet : {back} ne sélectionne pas la card voisine ou ne refait pas son aperçu")
        return
    findings.append(f"navigation #{ident} → #{other} ({key}, face « {before.get('face') or '—'} » "
                    f"gardée), volet resynchronisé, {back} du volet refait son aperçu")


def check_app_preview(app: str, url_path: str):
    """Entrée puis sortie d'une card, ouvertes comme le fait l'utilisateur. (ok, détail)."""
    from playwright.sync_api import sync_playwright

    from wama.common.sandbox import twins_with_copied_views
    from wama.common.services.nightly_tests import SkipScenario
    from wama.common.utils.preview_registry import PreviewRegistry

    if PreviewRegistry.get_model(app) is None:
        raise SkipScenario("aucun modèle d'élément déclaré (PreviewRegistry) — rien à prévisualiser")
    if app in twins_with_copied_views():
        # Même règle que les contrats génériques : une COPIE figée ne suit pas le code réel.
        raise SkipScenario("jumelle aux vues COPIÉES (`sandbox.twins_with_copied_views`) — ses "
                           "gabarits datent de la copie, le geste mesure le code réel")
    url = f"{BASE_URL.rstrip('/')}{url_path}"
    token = _test_session_key(app)
    if not token:
        raise SkipScenario("aucun compte de test disponible (wama_nightly_test / wama_ui_smoke_v3)")
    card = '.wama-card[data-id="{}"]:not(.is-batch)'
    witness = witness2 = None
    detail = ''
    with _garde_de_montage(app, 'preview') as cleaned:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                context = browser.new_context(viewport={'width': 1600, 'height': 1000})
                context.add_cookies(_cookie(token))
                page = context.new_page()
                js_errors = []
                page.on('pageerror', lambda e: js_errors.append(str(e)[:160]))
                resp = page.goto(url, wait_until='networkidle', timeout=PAGE_TIMEOUT_MS)
                wrong_page = _exiger_la_page(page, resp, url)
                if wrong_page:
                    return wrong_page
                page.wait_for_timeout(1200)
                before = set(page.evaluate(IDS_CARDS_JS))
                _monter_un_lot(page, app, n=2)
                page.goto(url, wait_until='networkidle', timeout=PAGE_TIMEOUT_MS)
                new_ids = [i for i in page.evaluate(IDS_CARDS_JS) if i not in before]
                if not new_ids:
                    raise SkipScenario("aucun élément créé par le montage — rien à prévisualiser")
                ident = new_ids[0]
                posed, witness = _in_plain_thread(_store_a_witness_result, app, ident)
                if posed is None:
                    raise SkipScenario(f"élément #{ident} : {witness}")
                # Le second élément a aussi son résultat : la visionneuse passe de l'un à l'autre.
                other = new_ids[1] if len(new_ids) > 1 else None
                if other:
                    _posed, witness2 = _in_plain_thread(_store_a_witness_result, app, other)
                page.goto(url, wait_until='networkidle', timeout=PAGE_TIMEOUT_MS)
                page.wait_for_timeout(1500)
                page.evaluate("() => document.querySelectorAll('.batch-group .collapse')"
                              ".forEach(c => c.classList.add('show'))")
                findings, faults = [posed], []
                if page.evaluate("(sel) => !!document.querySelector(sel + '.wcv3--batch-child')",
                                 card.format(ident)):
                    findings.append('card fille de lot')
                entry_opened = False

                # ── ENTRÉE : le nom d'entrée de la card ─────────────────────────────────
                link = page.locator(card.format(ident) + ' .preview-media-link[data-preview-url]').first
                if link.count():
                    link.scroll_into_view_if_needed(timeout=3000)
                    shown, errors = _open_and_read(page, lambda: link.click(timeout=6000))
                    fault = _verdict('entrée', shown, errors)
                    if fault:
                        faults.append(fault)
                    else:
                        entry_opened = not shown.get('own')
                        findings.append(f"entrée → {_seen(shown)}")
                        # Le NOM d'entrée ouvre la face Entrée — pas la face par défaut d'un élément
                        # terminé, la Sortie (relevé par Fabien sur le Describer le 2026-10-13 : cinq
                        # cards ne demandaient pas `?side=input`, et ce geste ne regardait pas la face).
                        face = (page.evaluate(JS_NAV_STATE) or {}).get('face', '')
                        if entry_opened and 'Entrée' in shown.get('sides', []) and face != 'Entrée':
                            faults.append(f"entrée : le nom d'entrée ouvre la face « {face} », pas l'Entrée")
                        if entry_opened:
                            _check_sides_layout(page, 'entrée', faults)
                        # La bascule de la VISIONNEUSE vers la face Sortie (ses propres faces).
                        if 'Sortie' in (shown or {}).get('sides', []):
                            page.evaluate(JS_PROBE)
                            page.locator('#wamaMediaPreviewModal .wama-modal-sides button',
                                         has_text='Sortie').first.click(timeout=4000)
                            page.wait_for_timeout(1500)
                            fault = _verdict('bascule vers la Sortie dans la visionneuse',
                                             page.evaluate(JS_SHOWN),
                                             page.evaluate('() => window.__previewErrors || []'))
                            if fault:
                                faults.append(fault)
                            else:
                                findings.append('bascule Entrée → Sortie')
                    _close(page)
                elif _in_plain_thread(_entry_declared, app):
                    faults.append("la card n'offre AUCUN accès à son entrée (`.preview-media-link`) "
                                  "alors que la spec en déclare une")
                else:
                    findings.append("pas d'entrée déclarée (spec) — rien à ouvrir")

                # ── SORTIE : l'aperçu de la card ────────────────────────────────────────
                # `.wama-card-preview` SEUL porte le geste : `data-preview-url` n'est requis que
                # pour l'overlay commun — une app qui intercepte `wama:card-expand` ouvre sa
                # propre modale sans lui (transcriber, contrat de `media-preview.js`).
                preview = page.locator(card.format(ident) + ' .wama-card-preview').first
                if not preview.count():
                    # Fille de lot comprise : l'enhancer l'en privait jusqu'au 2026-10-12.
                    faults.append("résultat posé, mais la card n'a aucun aperçu `.wama-card-preview`")
                else:
                    try:
                        page.wait_for_function(
                            "(sel) => { const e = document.querySelector(sel); if (!e) return false;"
                            " const r = e.getBoundingClientRect(); return r.height > 4 && r.width > 4; }",
                            arg=card.format(ident) + ' .wama-card-preview', timeout=15000)
                    except Exception:
                        faults.append("aperçu de la card JAMAIS hydraté (hauteur nulle)")
                    else:
                        preview.scroll_into_view_if_needed(timeout=3000)
                        shown, errors = _open_and_read(page, lambda: preview.dblclick(timeout=6000))
                        fault = _verdict('sortie', shown, errors)
                        if not fault and not shown.get('own') and entry_opened \
                                and 'Entrée' not in shown.get('sides', []):
                            # L'entrée s'ouvre (ci-dessus), la visionneuse de l'élément doit donc
                            # porter sa face Entrée : sans elle, on ne voit que la sortie.
                            fault = "sortie : la visionneuse s'ouvre SANS sa face Entrée"
                        if fault:
                            faults.append(fault)
                        elif shown.get('own'):
                            findings.append("⚠ sortie → modale propre à l'app (sans les faces "
                                            "Entrée | Sortie de la visionneuse commune)")
                        else:
                            findings.append(f"sortie → {_seen(shown)}")
                            _check_sides_layout(page, 'sortie', faults)
                            _check_contrast(page, 'visionneuse', faults, findings,
                                            context='#wamaMediaPreviewModal')
                        _close(page)

                # ── VOLET : l'aperçu de la card sélectionnée s'agrandit par son bouton ──────
                _check_panel_expand(page, card.format(ident), faults, findings)
                # La file HABITÉE et le volet de la card sélectionnée : les états que la page vide
                # de `common.contrast` ne montre pas (2026-10-16).
                _check_contrast(page, 'file et volet', faults, findings)

                # ── NAVIGATION : d'une card à l'autre, la face gardée, le volet resynchronisé ──
                if other:
                    _check_card_navigation(page, card, ident, other, faults, findings)
                if js_errors:
                    faults.append(f"JS en erreur : {' | '.join(js_errors)}")
                if faults:
                    return False, f"élément #{ident} : " + ' ; '.join(faults)
                detail = f"élément #{ident} : " + ' ; '.join(findings)
            except SkipScenario:
                raise
            except Exception as exc:
                if 'Timeout' in type(exc).__name__ and 'goto' in str(exc):
                    raise SkipScenario(_motif_skip(exc))
                raise
            finally:
                browser.close()
                for path in (witness, witness2):
                    if path and os.path.isfile(str(path)):
                        os.remove(path)
    if cleaned:
        detail += f" ; {_total_nettoye(cleaned)} objet(s) de montage nettoyé(s)"
    return True, detail


#: Les natures de fichier que la visionneuse rend différemment — chacune pose ses onglets au-dessus d'elle.
LAYOUT_CASES = (('image', 'w.png', 'image/png'), ('vidéo', 'w.mp4', 'video/mp4'),
                ('audio', 'w.wav', 'audio/wav'), ('pdf', 'w.pdf', 'application/pdf'),
                ('texte', None, 'text/plain'))
LAYOUT_VIEWPORTS = ((1600, 1000), (1280, 700))
_LAYOUT_SIDES = {'has_input': True, 'has_output': True, 'comparable': True,
                 'faces': [{'key': 'detect', 'label': 'Détection', 'icon': 'fa-eye'}]}
#: Une adresse d'élément que le test SERT lui-même (Comparer y demande ses deux faces).
_LAYOUT_ITEM = '/common/preview/none/0/'


def _layout_witnesses(folder: str):
    """Les fichiers témoins de la matrice — de vraies tailles (une image 1×1 ne dit rien d'une
    mise en page) ; la géométrie d'un `<video>` ne dépend pas de son contenu."""
    from fpdf import FPDF
    from PIL import Image
    os.makedirs(folder, exist_ok=True)
    Image.new('RGB', (640, 360), (40, 90, 160)).save(os.path.join(folder, 'w.png'))
    with open(os.path.join(folder, 'w.wav'), 'wb') as out:
        out.write(_wav_silence(2.0))
    with open(os.path.join(folder, 'w.mp4'), 'wb') as out:
        out.write(b'')
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font('Helvetica', size=14)
    pdf.cell(0, 10, 'Temoin de mise en page')
    pdf.output(os.path.join(folder, 'w.pdf'))


def check_preview_layout():
    """La bascule des faces de la visionneuse a SA place pour chaque nature de fichier (image,
    vidéo, audio, PDF, texte, et Comparer), visionneuse à sa taille et à tout l'écran, sur deux
    tailles d'écran. Pilote la visionneuse COMMUNE directement (`showPreviewModal`) : aucun
    élément monté, aucune tâche. (ok, détail)."""
    import json
    import shutil

    from django.conf import settings
    from playwright.sync_api import sync_playwright

    from wama.common.services.nightly_tests import SkipScenario

    apps = list(discoverable_apps())
    token = _test_session_key(apps[0][0]) if apps else None
    if not token:
        raise SkipScenario("aucun compte de test disponible (wama_nightly_test / wama_ui_smoke_v3)")
    folder = os.path.join(str(settings.MEDIA_ROOT), 'smoke_preview_layout')
    base = settings.MEDIA_URL + 'smoke_preview_layout/'
    _in_plain_thread(_layout_witnesses, folder)
    # Une SÉQUENCE de deux éléments : les flèches de navigation s'affichent, leur place se mesure.
    opened = """([data, sides, item]) => { const face = Object.assign({}, data,
        {name: 'témoin', side: 'output', sides: sides, _baseUrl: item});
        window.showPreviewModalWithNav(face, [face, face], 0); }"""
    faults, measured, arrows = [], 0, 0
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                for width, height in LAYOUT_VIEWPORTS:
                    context = browser.new_context(viewport={'width': width, 'height': height})
                    context.add_cookies(_cookie(token))
                    page = context.new_page()
                    js_errors = []
                    page.on('pageerror', lambda e: js_errors.append(str(e)[:160]))
                    page.route(f'**{_LAYOUT_ITEM}**', lambda route: route.fulfill(
                        content_type='application/json', body=json.dumps(
                            {'url': base + 'w.png', 'mime_type': 'image/png', 'name': 'témoin',
                             'side': 'input' if 'side=input' in route.request.url else 'output',
                             'sides': _LAYOUT_SIDES})))
                    page.goto(f"{BASE_URL.rstrip('/')}{apps[0][1]}", wait_until='networkidle',
                              timeout=PAGE_TIMEOUT_MS)
                    screen = f'{width}×{height}'
                    for name, file_name, mime in LAYOUT_CASES:
                        data = ({'url': base + file_name, 'mime_type': mime} if file_name
                                else {'content': 'Ligne de texte\n' * 80, 'mime_type': mime})
                        page.evaluate(opened, [data, _LAYOUT_SIDES, _LAYOUT_ITEM])
                        page.wait_for_selector('#wamaMediaPreviewModal.show', timeout=8000)
                        for full in (False, True):
                            page.evaluate(JS_FULL, full)
                            page.wait_for_timeout(600)
                            layout = page.evaluate(JS_SIDES_LAYOUT)
                            fault = sides_layout_fault(
                                layout, f"{name}, {'tout l’écran' if full else 'modale'}, {screen}",
                                must_fill=full and name in ('image', 'vidéo'))
                            measured += 1
                            # Une séquence est ouverte : sans flèche affichée, leur place n'est
                            # pas mesurée — le contrôle passerait à vide.
                            if layout and not layout.get('navs'):
                                fault = fault or f"{name}, {screen} : aucune flèche de navigation affichée"
                            arrows += bool(layout and layout.get('navs'))
                            if fault:
                                faults.append(fault)
                        page.evaluate(JS_FULL, False)
                    # COMPARER : ses deux faces sont servies par la route ci-dessus.
                    for full in (False, True):
                        page.evaluate(JS_FULL, full)
                        page.locator('#wamaMediaPreviewModal .wama-modal-sides button',
                                     has_text='Comparer').first.click(timeout=4000)
                        page.wait_for_selector('#wamaMediaPreviewModal .wama-modal-compare',
                                               timeout=8000)
                        page.wait_for_timeout(600)
                        fault = sides_layout_fault(
                            page.evaluate(JS_SIDES_LAYOUT),
                            f"comparer, {'tout l’écran' if full else 'modale'}, {screen}")
                        measured += 1
                        if fault:
                            faults.append(fault)
                    page.evaluate(JS_FULL, False)
                    _close(page)
                    if js_errors:
                        faults.append(f"{screen} : JS en erreur : {' | '.join(js_errors)}")
                    context.close()
            finally:
                browser.close()
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    if faults:
        return False, ' ; '.join(faults)
    return True, (f"{measured} mises en page mesurées ({len(LAYOUT_CASES)} natures + Comparer, "
                  f"modale et tout l'écran, {len(LAYOUT_VIEWPORTS)} tailles d'écran) : la bascule "
                  f"est au-dessus de l'aperçu, sans le recouvrir ; les flèches ({arrows} mesures) "
                  "ne le recouvrent pas")


#: L'état de la visionneuse que lisent les gestes de navigation : le fichier montré (titre), le
#: compteur (« 2 / 3 · fichier 1 / 4 »), la face active de la bascule, Comparer affiché ou non.
JS_NAV_STATE = """() => {
    const m = document.querySelector('#wamaMediaPreviewModal.show');
    if (!m) return null;
    const active = m.querySelector('.wama-modal-sides .is-active');
    const counter = m.querySelector('.wama-preview-counter');
    return {title: m.querySelector('.modal-title').textContent.trim(),
            counter: counter && counter.style.display !== 'none' ? counter.textContent.trim() : '',
            face: active ? active.textContent.trim() : '',
            compare: !!m.querySelector('.wama-modal-compare')};
}"""

#: Trois éléments FICTIFS servis par la page elle-même (`page.route`), la sortie du premier en
#: TROIS fichiers et celle du troisième en deux — la sortie multiple d'une génération d'images.
_NAV_FILES = {1: ['o1a', 'o1b', 'o1c'], 2: ['o2'], 3: ['o3a', 'o3b']}
_NAV_SIDES = {'has_input': True, 'has_output': True, 'comparable': True}
_NAV_ITEM = '/common/preview/none/'

#: Les cards fictives, dans un ONGLET actif (la séquence d'une card est celle de son onglet : les
#: cards réelles de la page n'y entrent pas). Leur aperçu est hydraté par la brique commune.
JS_NAV_CARDS = """([ids, item]) => {
    const pane = document.createElement('div');
    pane.className = 'tab-pane active';
    pane.id = 'wamaNavProbe';
    ids.forEach(id => {
        const c = document.createElement('div');
        c.className = 'wama-card';
        c.dataset.id = 'nav' + id;
        c.dataset.status = 'SUCCESS';
        c.innerHTML = `<a href="#" class="preview-media-link" data-preview-url="${item}${id}/?side=input">entrée ${id}</a>`
            + `<div class="wama-card-preview" style="min-height:60px" data-preview-url="${item}${id}/?side=output"`
            + ` data-card-preview="${item}${id}/?side=output"></div>`;
        pane.appendChild(c);
    });
    document.body.prepend(pane);
}"""


def _nav_payload(url: str, base: str) -> dict:
    """La face que sert `page.route` pour un élément fictif : l'entrée, ou la sortie (multiple)."""
    import re
    ident = int(re.search(r'/none/(\d+)/', url).group(1))
    if 'side=input' in url:
        return {'url': f'{base}i{ident}.png', 'mime_type': 'image/png', 'name': f'i{ident}.png',
                'side': 'input', 'sides': _NAV_SIDES}
    names = _NAV_FILES[ident]
    files = [{'url': f'{base}{n}.png', 'mime_type': 'image/png', 'name': f'{n}.png'} for n in names]
    face = dict(files[0], side='output', sides=_NAV_SIDES)
    if len(files) > 1:
        face.update(name=f'{len(files)} fichiers', files=files)
    return face


def _nav_witnesses(folder: str):
    from PIL import Image
    os.makedirs(folder, exist_ok=True)
    names = [n for group in _NAV_FILES.values() for n in group] + [f'i{i}' for i in _NAV_FILES]
    for k, name in enumerate(names):
        Image.new('RGB', (320, 180), (30 + 20 * k, 90, 160)).save(os.path.join(folder, f'{name}.png'))


def _session_user_folder(token: str, sub: str) -> str:
    """Un dossier du gestionnaire de fichiers du compte de la session (`users/<id>/temp/<sub>`)."""
    from importlib import import_module

    from django.conf import settings
    store = import_module(settings.SESSION_ENGINE).SessionStore(session_key=token)
    folder = os.path.join(str(settings.MEDIA_ROOT), 'users', str(store.get('_auth_user_id')), 'temp', sub)
    return folder


def _expect(page, title: str, counter: str = None, face: str = None, compare: bool = None,
            timeout_ms: int = 8000):
    """Attend que la visionneuse montre `title` (et le compteur, la face, Comparer demandés) ;
    rend '' ou ce qu'elle montre à la place."""
    want = {'title': title, 'counter': counter, 'face': face, 'compare': compare}
    try:
        page.wait_for_function(
            """(w) => { const m = document.querySelector('#wamaMediaPreviewModal.show');
                if (!m) return false;
                const c = m.querySelector('.wama-preview-counter');
                const a = m.querySelector('.wama-modal-sides .is-active');
                return m.querySelector('.modal-title').textContent.trim() === w.title
                    && (w.counter == null || (c && c.style.display !== 'none' ? c.textContent.trim() : '') === w.counter)
                    && (w.face == null || (a ? a.textContent.trim() : '') === w.face)
                    && (w.compare == null || !!m.querySelector('.wama-modal-compare') === w.compare)
                    // Comparer : les médias AFFICHÉS sont ceux que nomme le titre (« réf ↔ sortie »).
                    && (w.compare !== true || (() => {
                        const [ref, out] = w.title.split(' ↔ ');
                        const base = m.querySelector('.wama-compare-base');
                        const top = m.querySelector('.wama-compare-top img, .wama-compare-top video');
                        return base && top && base.src.includes(ref) && top.src.includes(out); })()); }""",
            arg=want, timeout=timeout_ms)
        return ''
    except Exception:
        return f"attendu {', '.join(f'{k}={v!r}' for k, v in want.items() if v is not None)} — " \
               f"vu {page.evaluate(JS_NAV_STATE)}"


def check_preview_navigation():
    """La navigation de la visionneuse, geste par geste, sur la brique COMMUNE (`media-preview.js`) :
    les fichiers d'un élément puis l'élément voisin (←/→, boutons ‹ ›), d'élément en élément (↑/↓),
    la face regardée gardée d'une card à l'autre (Entrée, Comparer), à tout l'écran, la vignette
    d'une grille ouverte sur SON fichier ; les fichiers d'un dossier du gestionnaire de fichiers ;
    une galerie et sa surcouche plein écran ; et aucune flèche détournée d'une visionneuse à
    l'autre. Éléments fictifs servis par la page (`page.route`), aucun traitement. (ok, détail)."""
    import json
    import shutil

    from django.conf import settings
    from playwright.sync_api import sync_playwright

    from wama.common.services.nightly_tests import SkipScenario

    apps = list(discoverable_apps())
    token = _test_session_key(apps[0][0]) if apps else None
    if not token:
        raise SkipScenario("aucun compte de test disponible (wama_nightly_test / wama_ui_smoke_v3)")
    folder = os.path.join(str(settings.MEDIA_ROOT), 'smoke_preview_nav')
    base = settings.MEDIA_URL + 'smoke_preview_nav/'
    fm_folder = _in_plain_thread(_session_user_folder, token, 'smoke_preview_nav')
    _in_plain_thread(_nav_witnesses, folder)
    os.makedirs(fm_folder, exist_ok=True)
    for i in range(4):
        shutil.copyfile(os.path.join(folder, 'o1a.png'), os.path.join(fm_folder, f'f{i}.png'))
    faults, steps = [], 0

    def check(fault, what):
        nonlocal steps
        steps += 1
        if fault:
            faults.append(f"{what} : {fault}")

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                context = browser.new_context(viewport={'width': 1600, 'height': 1000})
                context.add_cookies(_cookie(token))
                page = context.new_page()
                js_errors = []
                page.on('pageerror', lambda e: js_errors.append(str(e)[:160]))
                page.route(f'**{_NAV_ITEM}**', lambda route: route.fulfill(
                    content_type='application/json', body=json.dumps(_nav_payload(route.request.url, base))))
                page.goto(f"{BASE_URL.rstrip('/')}{apps[0][1]}", wait_until='networkidle',
                          timeout=PAGE_TIMEOUT_MS)
                page.evaluate(JS_NAV_CARDS, [list(_NAV_FILES), _NAV_ITEM])
                page.wait_for_selector('#wamaNavProbe .wama-preview-tile', timeout=8000)
                keys = page.keyboard
                modal = '#wamaMediaPreviewModal'

                def gesture(what, action, *expected, **kw):
                    """Un geste puis ce que la visionneuse doit montrer ; une panne du geste lui-même
                    (élément absent, visionneuse fermée) est un DÉFAUT nommé, jamais une exception."""
                    try:
                        action()
                    except Exception as exc:
                        check(f"geste impossible ({type(exc).__name__} : {str(exc).splitlines()[0][:120]})", what)
                        return
                    check(_expect(page, *expected, **kw) if expected else '', what)

                def press(key):
                    return lambda: keys.press(key)

                def click(selector, text=None, nth=0):
                    loc = page.locator(selector, has_text=text) if text else page.locator(selector)
                    return lambda: loc.nth(nth).click(timeout=4000)

                def dblclick(selector):
                    return lambda: page.locator(selector).first.dblclick(timeout=4000)

                def close():
                    try:
                        _close(page)
                    except Exception:
                        check('la visionneuse ne se referme pas', 'fermeture')
                        page.evaluate("() => document.querySelectorAll('.modal.show').forEach(m => "
                                      "bootstrap.Modal.getOrCreateInstance(m).hide())")
                        page.wait_for_timeout(600)

                card1 = '#wamaNavProbe .wama-card[data-id="nav1"]'
                # ── CARDS : fichiers puis card voisine, d'une card à l'autre ──────────────────
                gesture("ouverture d'une card (double-clic sur son aperçu)",
                        dblclick(card1 + ' .wama-card-preview small'), 'o1a.png', '1 / 3 · fichier 1 / 3', 'Sortie')
                for title, counter in (('o1b.png', '1 / 3 · fichier 2 / 3'), ('o1c.png', '1 / 3 · fichier 3 / 3'),
                                       ('o2.png', '2 / 3'), ('o3a.png', '3 / 3 · fichier 1 / 2')):
                    gesture(f'→ vers {title}', press('ArrowRight'), title, counter)
                gesture('← vers la card précédente', press('ArrowLeft'), 'o2.png', '2 / 3')
                gesture('← arrive sur le DERNIER fichier de la card précédente', press('ArrowLeft'),
                        'o1c.png', '1 / 3 · fichier 3 / 3')
                gesture('↓ saute à la card suivante', press('ArrowDown'), 'o2.png', '2 / 3')
                gesture('↓', press('ArrowDown'))
                gesture('↓ puis ↑', press('ArrowUp'), 'o2.png', '2 / 3')
                # ── la FACE regardée est gardée d'une card à l'autre ──────────────────────────
                gesture('bascule vers la face Entrée', click(modal + ' .wama-modal-sides button', 'Entrée'),
                        'i2.png', '2 / 3', 'Entrée')
                gesture('la face Entrée gardée à la card suivante', press('ArrowDown'), 'i3.png', '3 / 3', 'Entrée')
                gesture('bouton ‹', click(modal + ' .wama-preview-nav-prev'), 'i2.png', '2 / 3', 'Entrée')
                # ── à TOUT L'ÉCRAN (la modale agrandie) ───────────────────────────────────────
                page.evaluate(JS_FULL, True)
                gesture('bouton › à tout l’écran', click(modal + ' .wama-preview-nav-next'), 'i3.png', '3 / 3', 'Entrée')
                page.evaluate(JS_FULL, False)
                # ── COMPARER suit la navigation : le titre nomme les DEUX fichiers confrontés, une
                #    sortie multiple se compare fichier par fichier (2026-10-13) ────────────────
                gesture('Comparer', click(modal + ' .wama-modal-sides button', 'Comparer'),
                        'i3.png ↔ o3a.png', '3 / 3 · fichier 1 / 2', 'Comparer', compare=True)
                gesture('Comparer gardé à la card précédente', press('ArrowUp'),
                        'i2.png ↔ o2.png', '2 / 3', 'Comparer', compare=True)
                gesture('Comparer : ← arrive sur la DERNIÈRE image de la card précédente', press('ArrowLeft'),
                        'i1.png ↔ o1c.png', '1 / 3 · fichier 3 / 3', 'Comparer', compare=True)
                gesture('Comparer : ← parcourt les images sans quitter Comparer', press('ArrowLeft'),
                        'i1.png ↔ o1b.png', '1 / 3 · fichier 2 / 3', 'Comparer', compare=True)
                gesture('Comparer : →', press('ArrowRight'),
                        'i1.png ↔ o1c.png', '1 / 3 · fichier 3 / 3', 'Comparer', compare=True)
                gesture('Comparer : → après la dernière image, la card suivante', press('ArrowRight'),
                        'i2.png ↔ o2.png', '2 / 3', 'Comparer', compare=True)
                close()
                # ── la VIGNETTE d'une grille ouvre la visionneuse sur SON fichier ────────────
                gesture('clic sur la 2ᵉ vignette', click(card1 + ' .wama-preview-tile', nth=1),
                        'o1b.png', '1 / 3 · fichier 2 / 3', 'Sortie')
                gesture('→ depuis la vignette', press('ArrowRight'), 'o1c.png', '1 / 3 · fichier 3 / 3')
                gesture('Comparer confronte l’image MONTRÉE (la 3ᵉ)',
                        click(modal + ' .wama-modal-sides button', 'Comparer'),
                        'i1.png ↔ o1c.png', '1 / 3 · fichier 3 / 3', 'Comparer', compare=True)
                gesture('de Comparer à la Sortie : la même image', click(modal + ' .wama-modal-sides button', 'Sortie'),
                        'o1c.png', '1 / 3 · fichier 3 / 3', 'Sortie', compare=False)
                close()

                # ── GESTIONNAIRE DE FICHIERS : les fichiers du dossier ─────────────────────────
                opened = page.evaluate("""() => new Promise(res => {
                    const t = window.$ && $('#filemanager-tree').jstree && $('#filemanager-tree').jstree(true);
                    if (!t) return res(false);
                    t.open_node('section_user', () => t.open_node('temp', () => {
                        const f = (t.get_node('temp').children || []).find(id => /smoke_preview_nav/.test(id));
                        if (!f) return res(false);
                        t.open_node(f, () => res(true)); })); })""")
                if not opened:
                    faults.append("gestionnaire de fichiers : le dossier témoin n'apparaît pas dans l'arbre")
                else:
                    gesture('gestionnaire : ouverture',
                            lambda: page.locator('#filemanager-tree a.jstree-anchor', has_text='f0.png')
                            .first.dblclick(timeout=4000), 'f0.png', '1 / 4')
                    gesture('gestionnaire : →', press('ArrowRight'), 'f1.png', '2 / 4')
                    gesture('gestionnaire : ↓', press('ArrowDown'), 'f2.png', '3 / 4')
                    gesture('gestionnaire : bouton ›', click(modal + ' .wama-preview-nav-next'), 'f3.png', '4 / 4')
                    gesture('gestionnaire : ←', press('ArrowLeft'), 'f2.png', '3 / 4')
                    close()
                    # Une flèche dans la visionneuse d'une CARD ne montre plus un fichier du dossier.
                    gesture('card rouverte après le gestionnaire', dblclick(card1 + ' .wama-card-preview small'),
                            'o1a.png', '1 / 3 · fichier 1 / 3')
                    gesture('aucune flèche détournée vers le gestionnaire', press('ArrowRight'),
                            'o1b.png', '1 / 3 · fichier 2 / 3')
                    close()

                # ── GALERIE (liste en main, médiathèque) et sa SURCOUCHE plein écran ─────────
                gesture('galerie : ouverture', lambda: page.evaluate(
                    """(b) => window.showPreviewModalWithNav(
                        {url: b + 'o2.png', name: 'g1', mime_type: 'image/png'},
                        ['o2', 'o3a', 'o3b'].map((n, i) => ({url: b + n + '.png', name: 'g' + (i + 1),
                                                           mime_type: 'image/png'})), 0)""", base), 'g1', '1 / 3')
                gesture('galerie : →', press('ArrowRight'), 'g2', '2 / 3')
                gesture('galerie : surcouche plein écran', click(modal + ' .preview-fullscreen-btn'))
                try:
                    keys.press('ArrowRight')
                    page.wait_for_function("""() => { const o = document.getElementById('wamaFullscreenOverlay');
                        return o && /o3b\\.png/.test(o.querySelector('img').src)
                            && o.querySelector('.wama-preview-counter').textContent.trim() === '3 / 3'; }""",
                                           timeout=5000)
                    check('', 'surcouche plein écran : →')
                    keys.press('Escape')
                    page.wait_for_function("() => !document.getElementById('wamaFullscreenOverlay')", timeout=4000)
                except Exception:
                    check('la surcouche ne suit pas la flèche (ou ne se ferme pas à Échap)', 'surcouche plein écran')
                    page.evaluate("() => window.closeWamaFullscreen && window.closeWamaFullscreen()")
                close()
                if js_errors:
                    faults.append(f"JS en erreur : {' | '.join(js_errors)}")
                context.close()
            finally:
                browser.close()
    finally:
        shutil.rmtree(folder, ignore_errors=True)
        shutil.rmtree(fm_folder, ignore_errors=True)
    if faults:
        return False, f"{steps} gestes : " + ' ; '.join(faults)
    return True, (f"{steps} gestes de navigation : fichiers d'un élément puis card voisine (←/→, "
                  "boutons), d'une card à l'autre (↑/↓), face gardée (Entrée, Comparer), tout l'écran, "
                  "vignette, gestionnaire de fichiers, galerie et sa surcouche — aucune flèche détournée")


#: L'élément FICTIF « en cours » du geste de la face Pendant, servi par la page (`page.route`).
_DURING_ITEM = '/common/preview/during_probe/1/'
_DURING_FRAMES = ('p1', 'p2', 'p3')

JS_DURING_CARD = """(item) => {
    const pane = document.createElement('div');
    pane.className = 'tab-pane active';
    pane.id = 'wamaDuringProbe';
    // Au centre, au premier plan : les volets fixes de la page ne la recouvrent pas.
    pane.style.cssText = 'position:fixed;left:45%;top:45%;z-index:1040;background:#fff;padding:8px;';
    // L'hôte d'attente que chaque card pose (`data-card-during`, 2026-10-20) : la CARD suit la
    // face Pendant comme la visionneuse.
    pane.innerHTML = `<div class="wama-card" data-id="during1" data-status="RUNNING">`
        + `<a href="#" class="preview-media-link" data-preview-url="${item}">en cours</a>`
        + `<div id="wamaDuringHost" data-card-during="${item}" data-preview-mode="excerpt"></div></div>`;
    document.body.prepend(pane);
}"""


def _during_payload(url: str, base: str, state: dict) -> dict:
    """Ce que sert l'aperçu commun d'un élément qui calcule : sa face Pendant CHANGE à chaque
    tour (un nouveau partiel), puis, l'élément terminé, sa Sortie."""
    running = state['running']
    sides = {'has_input': True, 'has_output': not running, 'during_capable': True,
             'has_during': running}
    if 'side=during' in url and running:
        state['turns'] += 1
        name = _DURING_FRAMES[state['turns'] % len(_DURING_FRAMES)]
        return {'url': f'{base}{name}.png', 'mime_type': 'image/png', 'name': f'pendant {name}',
                'side': 'during', 'partial': True, 'sides': sides}
    if 'side=output' in url and not running:
        return {'url': f'{base}o.png', 'mime_type': 'image/png', 'name': 'o.png', 'side': 'output',
                'sides': sides}
    return {'url': f'{base}i.png', 'mime_type': 'image/png', 'name': 'i.png', 'side': 'input',
            'sides': sides}


def _during_witnesses(folder: str):
    from PIL import Image
    os.makedirs(folder, exist_ok=True)
    for k, name in enumerate(_DURING_FRAMES + ('i', 'o')):
        Image.new('RGB', (320, 180), (40 + 40 * k, 120, 90)).save(os.path.join(folder, f'{name}.png'))


def check_preview_during():
    """La face PENDANT dans la visionneuse, de bout en bout dans le navigateur (2026-10-20 :
    « dans Composer, la preview est censée se charger au fur et à mesure »). Un élément fictif EN
    COURS : sa CARD montre déjà ce qui se construit, sans geste (l'hôte `data-card-during`, suivi
    par `followCard` — 2026-10-20) ; ouvert, la visionneuse le montre (onglet Pendant) ; chaque nouveau
    partiel la met à jour sans geste ; l'élément terminé, elle passe d'elle-même à sa Sortie.
    Le suiveur commun (`followDuring`) et sa reprise de lecture sont tenus en V8
    (`tests_cap_from_js`) ; ce geste tient le câblage dans une vraie page. (ok, détail)."""
    import json
    import shutil

    from django.conf import settings
    from playwright.sync_api import sync_playwright

    from wama.common.services.nightly_tests import SkipScenario

    apps = list(discoverable_apps())
    token = _test_session_key(apps[0][0]) if apps else None
    if not token:
        raise SkipScenario("aucun compte de test disponible (wama_nightly_test / wama_ui_smoke_v3)")
    folder = os.path.join(str(settings.MEDIA_ROOT), 'smoke_preview_during')
    base = settings.MEDIA_URL + 'smoke_preview_during/'
    _in_plain_thread(_during_witnesses, folder)
    state = {'running': True, 'turns': 0}
    faults, seen = [], []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                context = browser.new_context(viewport={'width': 1400, 'height': 900})
                context.add_cookies(_cookie(token))
                page = context.new_page()
                js_errors = []
                page.on('pageerror', lambda e: js_errors.append(str(e)[:160]))
                page.route(f'**{_DURING_ITEM}**', lambda route: route.fulfill(
                    content_type='application/json',
                    body=json.dumps(_during_payload(route.request.url, base, state))))
                page.goto(f"{BASE_URL.rstrip('/')}{apps[0][1]}", wait_until='networkidle',
                          timeout=PAGE_TIMEOUT_MS)
                page.evaluate(JS_DURING_CARD, _DURING_ITEM)
                # La CARD elle-même montre ce qui se construit, sans geste (suiveur de card).
                card_js = """() => { const h = document.getElementById('wamaDuringHost');
                    const img = h && h.querySelector('img');
                    return {src: img ? img.src : '', card: !!(h && h.classList.contains('wama-card-preview'))}; }"""
                try:
                    page.wait_for_function(
                        "() => { const h = document.getElementById('wamaDuringHost');"
                        " const img = h && h.querySelector('img');"
                        " return !!(img && img.src.indexOf('/smoke_preview_during/p') >= 0); }",
                        timeout=8000)
                    if not page.evaluate(card_js)['card']:
                        faults.append("la card montre la face Pendant mais son hôte n'a pas le geste commun")
                except Exception:
                    faults.append(f"la card en cours ne montre pas sa face Pendant (vu {page.evaluate(card_js)})")
                page.locator('#wamaDuringProbe .preview-media-link').first.click(timeout=4000)
                state_js = """() => { const m = document.querySelector('#wamaMediaPreviewModal.show');
                    if (!m) return null; const a = m.querySelector('.wama-modal-sides .is-active');
                    const img = m.querySelector('.preview-container img');
                    return {title: m.querySelector('.modal-title').textContent.trim(),
                            face: a ? a.textContent.trim() : '', src: img ? img.src : ''}; }"""
                try:
                    page.wait_for_function(
                        "() => { const m = document.querySelector('#wamaMediaPreviewModal.show');"
                        " const a = m && m.querySelector('.wama-modal-sides .is-active');"
                        " return a && a.textContent.trim() === 'Pendant'; }", timeout=8000)
                    seen.append(page.evaluate(state_js)['title'])
                except Exception:
                    faults.append(f"ouverture d'un élément en cours : la visionneuse ne montre pas sa face "
                                  f"Pendant (vu {page.evaluate(state_js)})")
                if not faults:
                    try:
                        page.wait_for_function(
                            """(first) => { const m = document.querySelector('#wamaMediaPreviewModal.show');
                                const t = m && m.querySelector('.modal-title').textContent.trim();
                                return t && t !== first && t.indexOf('pendant ') === 0; }""",
                            arg=seen[0], timeout=8000)
                        now = page.evaluate(state_js)
                        seen.append(now['title'])
                        if now['face'] != 'Pendant' or '/smoke_preview_during/p' not in now['src']:
                            faults.append(f"partiel suivant : la visionneuse a quitté la face Pendant ({now})")
                    except Exception:
                        faults.append(f"le partiel suivant n'est pas montré sans geste (vu {page.evaluate(state_js)})")
                    # L'élément se termine : partiels retirés, card terminée.
                    state['running'] = False
                    page.evaluate("() => document.querySelector('#wamaDuringProbe .wama-card')"
                                  ".setAttribute('data-status', 'SUCCESS')")
                    try:
                        page.wait_for_function(
                            """() => { const m = document.querySelector('#wamaMediaPreviewModal.show');
                                const a = m && m.querySelector('.wama-modal-sides .is-active');
                                return a && a.textContent.trim() === 'Sortie'
                                    && m.querySelector('.modal-title').textContent.trim() === 'o.png'; }""",
                            timeout=8000)
                    except Exception:
                        faults.append(f"l'élément terminé, la visionneuse ne passe pas à sa Sortie "
                                      f"(vu {page.evaluate(state_js)})")
                _close(page)
                if js_errors:
                    faults.append(f"JS en erreur : {' | '.join(js_errors)}")
                context.close()
            finally:
                browser.close()
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    if faults:
        return False, ' ; '.join(faults)
    return True, (f"face Pendant montrée par la CARD en cours, puis suivie en direct dans la "
                  f"visionneuse ({' → '.join(seen)}, {state['turns']} tours servis), puis la Sortie "
                  "d'elle-même à la fin")


def register_preview_scenarios():
    """Enregistre un scénario `<app>.preview` par app disposant d'un index, la matrice de mise
    en page de la visionneuse (`common.preview_layout`) et ses gestes de navigation
    (`common.preview_navigation`) — aucun GPU."""
    from wama.common.services.nightly_tests import register

    register(
        id="common.preview_layout", app="common", stage="ui",
        description=("Visionneuse : la bascule des faces (Entrée | … | Sortie) est AU-DESSUS de l'aperçu, "
                     "sans le recouvrir, pour chaque nature de fichier (image, vidéo, audio, PDF, "
                     "texte, Comparer), à sa taille et à tout l'écran, sur deux tailles d'écran ; "
                     "les flèches de navigation ne le recouvrent pas non plus"),
        run=lambda ctx: check_preview_layout(),
        timeout_s=240, vram_gb=0.0,
    )
    register(
        id="common.preview_navigation", app="common", stage="ui",
        description=("Visionneuse : ←/→ parcourent les fichiers d'un élément puis passent à la card "
                     "voisine, ↑/↓ sautent de card en card, la face regardée est gardée ; idem au "
                     "gestionnaire de fichiers et dans une galerie (surcouche plein écran comprise), "
                     "sans flèche détournée d'une visionneuse à l'autre"),
        run=lambda ctx: check_preview_navigation(),
        timeout_s=240, vram_gb=0.0,
    )
    register(
        id="common.preview_during", app="common", stage="ui",
        description=("Visionneuse : un élément EN COURS s'ouvre sur sa face Pendant, chaque nouveau "
                     "partiel s'y affiche sans geste, et l'élément terminé elle passe d'elle-même à "
                     "sa Sortie — élément fictif servi par la page, aucun traitement"),
        run=lambda ctx: check_preview_during(),
        timeout_s=180, vram_gb=0.0,
    )

    for label, path in discoverable_apps():
        register(
            id=f"{label}.preview", app=label, stage="ui",
            description=(f"Aperçu {label} : le nom d'entrée de la card ouvre son entrée (puis la "
                         f"Sortie par la bascule), l'aperçu de la card ouvre sa sortie — résultat "
                         f"posé en base, aucun traitement"),
            run=(lambda p=path, a=label: (lambda ctx: check_app_preview(a, p)))(),
            timeout_s=240, vram_gb=0.0,
        )
