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
Une erreur d'aperçu (le toast que lève `media-preview.js`) est un ÉCHEC, jamais un constat.

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
    const parts = box ? Array.from(box.children).filter(e =>
        !e.matches('.wama-preview-nav-btn, .wama-modal-sides, .wama-modal-variants')) : [];
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
    l'aperçu expirait derrière le fond de la visionneuse d'entrée, refermée par Échap)."""
    page.keyboard.press('Escape')
    page.evaluate("""() => document.querySelectorAll('.modal.show').forEach(m => {
        const i = window.bootstrap && bootstrap.Modal.getInstance(m); if (i) i.hide(); })""")
    page.wait_for_function("() => !document.querySelector('.modal.show, .modal-backdrop')",
                           timeout=8000)


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
    witness = None
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
                        _close(page)
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
                if witness and os.path.isfile(str(witness)):
                    os.remove(witness)
    if cleaned:
        detail += f" ; {_total_nettoye(cleaned)} objet(s) de montage nettoyé(s)"
    return True, detail


def register_preview_scenarios():
    """Enregistre un scénario `<app>.preview` par app disposant d'un index — aucun GPU."""
    from wama.common.services.nightly_tests import register

    for label, path in discoverable_apps():
        register(
            id=f"{label}.preview", app=label, stage="ui",
            description=(f"Aperçu {label} : le nom d'entrée de la card ouvre son entrée (puis la "
                         f"Sortie par la bascule), l'aperçu de la card ouvre sa sortie — résultat "
                         f"posé en base, aucun traitement"),
            run=(lambda p=path, a=label: (lambda ctx: check_app_preview(a, p)))(),
            timeout_s=240, vram_gb=0.0,
        )
