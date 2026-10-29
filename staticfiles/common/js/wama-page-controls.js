/**
 * wama-page-controls.js — les CONTRÔLES DE PAGE (2026-10-29, décision de Fabien : « une barre de
 * page », `WAMA_VOLETS §3-ter`).
 *
 * Ce qui vaut pour TOUTE la page vit dans l'en-tête, jamais dans une brique : une brique se
 * déplace, s'empile, part dans une autre fenêtre — le bouton qui défait une mauvaise disposition
 * ne doit pas pouvoir s'y perdre. Deux contrôles :
 *   • le CADENAS (`#wamaLayoutToggle`), montré quand la page offre une disposition : modifier /
 *     figer ; ouverte, un BANDEAU dit les gestes et porte « Disposition par défaut » et « Figer » ;
 *   • l'AIDE de la page (`#wamaPageHelpToggle`, et la touche `?`) : les raccourcis clavier des
 *     briques de CETTE page, lus au registre (`UIBrick.shortcuts`), la disposition et les gestes.
 * Et pour qu'on le DÉCOUVRE sans le deviner : une BULLE au premier passage (une fois par compte,
 * gardé au serveur) ; l'infobulle d'un bouton qu'une touche actionne dit cette touche, lue au
 * registre (`Shortcut.targets`) — jamais écrite à la main dans la brique ; le texte des gestes est
 * celui du serveur (`surfaces.LAYOUT_HELP`), que l'assistant dit aussi.
 *
 * Ce qu'une page apporte, elle le DÉCLARE ici (aucune liste écrite dans ce module) :
 *   WamaPageControls.offerLayout({subject, frozen(), setFrozen(on), reset()});
 *   WamaPageControls.layoutChanged();                 // la disposition a changé d'état
 *   WamaPageControls.addShortcuts(function () { return [{title, items}]; });
 *   WamaPageControls.addHelp(function () { return ['un geste', …]; });
 *   WamaPageControls.openHelp();
 * Les briques de PAGE (la file, l'inspecteur, la visionneuse) viennent du serveur
 * (`volet.page_controls_config`, bloc `wama-page-controls`), chacune avec ce qui dit qu'elle est
 * sur la page (`present`).
 */
(function (global) {
    'use strict';

    var layoutProvider = null;
    var shortcutProviders = [];
    var helpProviders = [];
    var banner = null, modal = null;

    function esc(t) {
        var d = document.createElement('div'); d.textContent = t == null ? '' : t;
        return d.innerHTML;
    }
    function call(fn) { try { return typeof fn === 'function' ? fn() : fn; } catch (e) { return null; } }

    function serverConfig() {
        var source = document.getElementById('wama-page-controls');
        if (!source) return { shortcuts: [] };
        try { return JSON.parse(source.textContent) || { shortcuts: [] }; }
        catch (e) { return { shortcuts: [] }; }
    }
    var config = serverConfig();

    // ── La disposition ───────────────────────────────────────────────────────────────────────
    function isOpen() { return !!layoutProvider && !call(layoutProvider.frozen); }

    function sync() {
        var btn = document.getElementById('wamaLayoutToggle');
        if (btn) {
            var item = btn.closest('[data-page-control]') || btn;
            item.hidden = !layoutProvider;
            var open = isOpen();
            var subject = (layoutProvider && layoutProvider.subject) || 'de la page';
            btn.innerHTML = '<i class="fas ' + (open ? 'fa-lock-open' : 'fa-lock') + '"></i>';
            btn.title = (open ? 'Figer la disposition ' : 'Modifier la disposition ') + subject;
            btn.setAttribute('aria-label', btn.title);
            btn.setAttribute('aria-pressed', open ? 'true' : 'false');
            btn.classList.toggle('active', open);
        }
        showBanner(isOpen());
    }

    function setFrozen(on) {
        if (!layoutProvider) return Promise.resolve();
        return Promise.resolve(layoutProvider.setFrozen(on)).then(sync, function (e) {
            if (global.WamaApp && global.WamaApp.toast) {
                global.WamaApp.toast('Disposition indisponible : ' + (e && e.message || e), 'danger');
            }
        });
    }

    /** Le BANDEAU de la disposition modifiable. Ses issues (« Disposition par défaut », « Figer »)
     *  prennent la place du logo DANS l'en-tête : elles ne recouvrent jamais un panneau — posées
     *  sous l'en-tête, elles masquaient les titres qu'on glisse justement (vu au scénario
     *  `common.surface_stack`). Les gestes s'affichent dessous, en texte qui laisse passer le
     *  pointeur et s'efface de lui-même ; ils restent dans l'aide de la page. */
    var hint = null;
    function showBanner(open) {
        var header = document.querySelector('.wama-header');
        if (header) header.classList.toggle('wama-arranging', open);
        if (!open) {
            if (banner) banner.hidden = true;
            if (hint) hint.hidden = true;
            return;
        }
        var host = document.querySelector('.wama-header-container') || document.body;
        if (!banner) {
            banner = document.createElement('div');
            banner.className = 'wama-layout-banner';
            banner.setAttribute('role', 'status');
            // Compact : le cadenas ouvert (coloré) et les gestes dessous disent déjà le mode — le
            // libellé « Disposition modifiable » ne sert qu'au lecteur d'écran (une barre où il se
            // voyait débordait sur le volet, captures du 29/10).
            banner.innerHTML =
                '<span class="visually-hidden">Disposition modifiable</span>' +
                '<button type="button" class="btn btn-sm btn-outline-secondary" data-page-layout="reset" title="Disposition par défaut">' +
                '<i class="fas fa-table-cells-large me-1"></i><span class="wama-header-label">Par défaut</span></button>' +
                '<button type="button" class="btn btn-sm btn-primary" data-page-layout="freeze" title="Figer la disposition">' +
                '<i class="fas fa-lock me-1"></i><span class="wama-header-label">Figer</span></button>';
            banner.addEventListener('click', function (ev) {
                var b = ev.target.closest('[data-page-layout]');
                if (!b || !layoutProvider) return;
                if (b.dataset.pageLayout === 'reset') layoutProvider.reset();
                else setFrozen(true);
            });
            host.appendChild(banner);
            hint = document.createElement('div');
            hint.className = 'wama-layout-hint';
            hint.setAttribute('aria-hidden', 'true');      // le même texte est dans l'aide de la page
            document.body.appendChild(hint);
        }
        var text = config.layout_help || '';
        banner.title = text;
        banner.hidden = false;
        hint.textContent = text;
        hint.hidden = !text;
        // Rejouer l'effacement à chaque ouverture : la classe retirée puis remise relance l'animation.
        hint.classList.remove('is-fading');
        void hint.offsetWidth;
        hint.classList.add('is-fading');
    }

    // ── Les raccourcis de la page ────────────────────────────────────────────────────────────
    /** Une brique de page est-elle sur la page ? `always` (chargée par la page de base), sinon
     *  un sélecteur que le serveur a dérivé de sa déclaration. */
    function present(group) {
        if (group.present === 'always') return true;
        try { return !!(group.present && document.querySelector(group.present)); }
        catch (e) { return false; }
    }

    function shortcutGroups() {
        var groups = (config.shortcuts || []).filter(present).map(function (g) {
            return { title: g.title, items: g.items };
        });
        shortcutProviders.forEach(function (p) { (call(p) || []).forEach(function (g) { groups.push(g); }); });
        return groups;
    }

    function keysHtml(groups) {
        var mine = config.help_shortcut || {};
        var own = mine.label ? '<div class="wama-keys-group"><b>Cette page</b><ul><li><kbd>' + esc(mine.label) +
            '</kbd> ' + esc(mine.action) + '</li></ul></div>' : '';
        return own + groups.map(function (group) {
            return '<div class="wama-keys-group"><b>' + esc(group.title) + '</b><ul>' +
                (group.items || []).map(function (s) {
                    return '<li title="' + esc(s.where) + '"><kbd>' + esc(s.label) + '</kbd> ' +
                        esc(s.action) + (s.scope === 'field' ? ' <i>(' + esc(s.where) + ')</i>' : '') +
                        '</li>';
                }).join('') + '</ul></div>';
        }).join('');
    }

    // ── L'aide de la page ────────────────────────────────────────────────────────────────────
    function buildModal() {
        modal = document.createElement('div');
        modal.className = 'modal fade wama-page-help';
        modal.id = 'wamaPageHelpModal';
        modal.tabIndex = -1;
        modal.setAttribute('aria-labelledby', 'wamaPageHelpTitle');
        modal.setAttribute('aria-hidden', 'true');
        modal.innerHTML =
            '<div class="modal-dialog modal-lg modal-dialog-scrollable"><div class="modal-content">' +
            '<div class="modal-header"><h5 class="modal-title" id="wamaPageHelpTitle">' +
            '<i class="fas fa-circle-question me-2"></i>Aide de cette page</h5>' +
            '<button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Fermer"></button></div>' +
            '<div class="modal-body">' +
            '<section data-help="keys"><h6><i class="fas fa-keyboard me-1"></i>Raccourcis clavier</h6>' +
            '<div class="wama-help-keys"></div></section>' +
            '<section data-help="layout"><h6><i class="fas fa-table-cells-large me-1"></i>Disposition</h6>' +
            '<p class="wama-help-layout"></p>' +
            '<button type="button" class="btn btn-sm btn-outline-primary" data-page-layout="open">' +
            '<i class="fas fa-lock-open"></i> Modifier la disposition</button></section>' +
            '<section data-help="gestures"><h6><i class="fas fa-hand-pointer me-1"></i>Gestes</h6>' +
            '<ul class="wama-help-gestures"></ul></section>' +
            '</div></div></div>';
        modal.addEventListener('click', function (ev) {
            if (!ev.target.closest('[data-page-layout="open"]')) return;
            hideModal();
            setFrozen(false);
        });
        document.body.appendChild(modal);
    }

    function fillModal() {
        modal.querySelector('.wama-help-keys').innerHTML = keysHtml(shortcutGroups());
        var layoutSection = modal.querySelector('[data-help="layout"]');
        layoutSection.hidden = !layoutProvider;
        if (layoutProvider) {
            modal.querySelector('.wama-help-layout').textContent =
                (config.layout_controls || '') + ' ' + (config.layout_help || '');
            modal.querySelector('[data-page-layout="open"]').hidden = isOpen();
        }
        var gestures = [];
        helpProviders.forEach(function (p) { (call(p) || []).forEach(function (g) { if (g) gestures.push(g); }); });
        modal.querySelector('[data-help="gestures"]').hidden = !gestures.length;
        modal.querySelector('.wama-help-gestures').innerHTML =
            gestures.map(function (g) { return '<li>' + esc(g) + '</li>'; }).join('');
    }

    function hideModal() {
        var Modal = global.bootstrap && global.bootstrap.Modal;
        if (modal && Modal) Modal.getOrCreateInstance(modal).hide();
    }

    function openHelp(section) {
        if (!modal) buildModal();
        fillModal();
        var Modal = global.bootstrap && global.bootstrap.Modal;
        if (Modal) Modal.getOrCreateInstance(modal).show();
        else modal.classList.add('show');
        var target = section && modal.querySelector('[data-help="' + section + '"]');
        if (target) target.scrollIntoView({ block: 'start' });
    }

    // ── La BULLE du premier passage ──────────────────────────────────────────────────────────
    /** Une fois par COMPTE (gardé au serveur, `common:page_hint`), sous le cadenas, sur une page
     *  qui offre une disposition (décision de Fabien, 29/10 : « l'utilisateur ne va pas forcément
     *  comprendre qu'il peut modifier l'interface »). Montrée vaut vue : elle ne revient pas, qu'on
     *  clique ou non — une bulle qui revient à chaque page devient du bruit. */
    var hinted = false;
    function maybeHint() {
        var hintCfg = config.hint;
        if (hinted || !hintCfg || hintCfg.seen || !layoutProvider || isOpen()) return;
        var lock = document.getElementById('wamaLayoutToggle');
        if (!lock || !lock.offsetParent) return;          // barre de téléphone : pas de cadenas
        hinted = true;
        hintCfg.seen = true;
        var helpKey = (config.help_shortcut || {}).label;
        var bubble = document.createElement('div');
        bubble.className = 'wama-page-hint';
        bubble.setAttribute('role', 'dialog');
        bubble.setAttribute('aria-label', 'Réorganiser cette page');
        bubble.innerHTML =
            '<p><b>Cette page se réorganise.</b> Le cadenas rend ses panneaux mobiles : ' +
            'déplacez-les, empilez-les, épinglez-les au bord de la fenêtre.' +
            (helpKey ? ' La touche <kbd>' + esc(helpKey) + '</kbd> liste ses raccourcis clavier.' : '') + '</p>' +
            '<div class="wama-page-hint-actions">' +
            '<button type="button" class="btn btn-sm btn-primary" data-hint="show">Me montrer</button>' +
            '<button type="button" class="btn btn-sm btn-outline-secondary" data-hint="ok">Compris</button></div>';
        var r = lock.getBoundingClientRect();
        bubble.style.left = Math.max(8, r.left + r.width / 2 - 22) + 'px';
        bubble.style.top = (r.bottom + 10) + 'px';
        // Elle ne gêne pas la page : son texte laisse passer le pointeur (seuls ses deux boutons le
        // prennent), et elle s'en va au premier geste ailleurs — un clic, une frappe — ou d'elle-même.
        // Posée au-dessus du haut de la page, elle masquait les outils qu'on venait utiliser (vu au
        // scénario `common.image_keys`).
        // La frappe passe par le clavier commun, en OBSERVATEUR (elle suit sans prendre la touche) :
        // aucune écoute du clavier de toute la page hors du module (`PageKeyListenersTest`).
        var offKeys = null;
        function dismiss() {
            bubble.remove();
            document.removeEventListener('pointerdown', outside, true);
            if (offKeys) { offKeys(); offKeys = null; }
        }
        function outside(ev) { if (!bubble.contains(ev.target)) dismiss(); }
        bubble.addEventListener('click', function (ev) {
            var b = ev.target.closest('[data-hint]');
            if (!b) return;
            dismiss();
            if (b.dataset.hint === 'show') setFrozen(false);
        });
        document.addEventListener('pointerdown', outside, true);
        if (global.WamaKeys) {
            offKeys = global.WamaKeys.register({ owner: 'page_hint', observe: true, handle: dismiss });
        }
        setTimeout(dismiss, 15000);
        document.body.appendChild(bubble);
        var App = global.WamaApp;
        if (App && App.csrfFetch) {
            App.csrfFetch(hintCfg.url, App.csrfToken(), { method: 'POST' }).catch(function () {});
        }
    }

    // ── Les touches dans les INFOBULLES ──────────────────────────────────────────────────────
    /** Le bouton qu'une touche actionne le dit dans son infobulle, lue au registre
     *  (`Shortcut.targets`, des briques de CETTE page) au moment où le pointeur ou le focus
     *  l'atteint — les briques montées tard (une surface) comprises. Une infobulle que la brique
     *  change elle-même reprend sa nouvelle base. */
    function keyTargets() {
        var out = [];
        shortcutGroups().forEach(function (g) {
            (g.items || []).forEach(function (s) { (s.targets || []).forEach(function (t) { out.push(t); }); });
        });
        return out;
    }
    function annotate(ev) {
        var el = ev.target && ev.target.closest ? ev.target.closest('button, a, [role="button"]') : null;
        if (!el) return;
        var labels = [];
        keyTargets().forEach(function (t) {
            try { if (el.matches(t.selector) && labels.indexOf(t.label) < 0) labels.push(t.label); }
            catch (e) { /* un sélecteur invalide ne casse pas la page */ }
        });
        if (!labels.length) return;
        var current = el.getAttribute('title') || '';
        var base = current === el.dataset.wamaKeysTitle ? (el.dataset.wamaTitle || '') : current;
        el.dataset.wamaTitle = base;
        el.title = (base ? base + ' ' : '') + '(' + labels.join(' · ') + ')';
        el.dataset.wamaKeysTitle = el.title;
    }
    document.addEventListener('pointerover', annotate, true);
    document.addEventListener('focusin', annotate, true);

    // ── Branchement ──────────────────────────────────────────────────────────────────────────
    function wire() {
        var lock = document.getElementById('wamaLayoutToggle');
        if (lock) lock.addEventListener('click', function () { setFrozen(isOpen()); });
        var help = document.getElementById('wamaPageHelpToggle');
        if (help) help.addEventListener('click', function () { openHelp('keys'); });
        sync();
        setTimeout(maybeHint, 600);
    }
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', wire);
    else wire();

    // La touche de l'aide (`surfaces.PAGE_HELP_SHORTCUT`, « ? ») l'ouvre partout sur la page — le
    // clavier commun : jamais en saisie ni sous une couche.
    var helpKeyName = ((config.help_shortcut || {}).keys || [])[0];
    if (global.WamaKeys && helpKeyName) {
        global.WamaKeys.register({ owner: 'page_controls', scope: 'page', handle: function (e) {
            if (e.key !== helpKeyName || e.ctrlKey || e.metaKey || e.altKey) return false;
            openHelp('keys');
            return true;
        } });
    }

    global.WamaPageControls = {
        offerLayout: function (provider) { layoutProvider = provider; sync(); setTimeout(maybeHint, 600); },
        layoutChanged: sync,
        addShortcuts: function (fn) { shortcutProviders.push(fn); },
        addHelp: function (fn) { helpProviders.push(fn); },
        openHelp: openHelp,
        /** Les raccourcis que l'aide montrerait maintenant (les scénarios les lisent). */
        shortcutGroups: shortcutGroups,
    };
})(window);
