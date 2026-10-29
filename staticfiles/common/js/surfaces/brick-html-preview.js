/**
 * Brique `html_preview` — le document RENDU, en lecture seule (chantier SURFACES, 2026-10-13 ;
 * 1ʳᵉ surface : l'aperçu du Writer).
 *
 * Universelle : elle affiche l'URL d'un rôle lu par la surface (option `role`, défaut
 * `preview`) dans le cadre ISOLÉ commun (`WamaMediaPreview.documentFrame` — `<iframe sandbox>`
 * sans permission : ni script ni navigation), celui de l'aperçu en ligne et de la visionneuse. On
 * ne l'édite jamais (ROADMAP §21.5, n°2).
 *
 * Ses libellés d'état (`LABELS`) ne recopient pas `WamaApp.statusLabel` : ils disent ce que l'état
 * veut dire pour LE RENDU (« Périmé — Appliquer le refait »), pas le nom de l'état.
 *
 * Elle dit si le rendu est À JOUR : l'état du process qui le produit (option `process`, défaut
 * le process que la surface rejoue) est lu des lignes d'exécution (`ctx.processes()`, événement
 * `processes`) — périmé après un enregistrement, en cours après « Appliquer », rechargé quand il
 * a fini.
 */
(function (global) {
    'use strict';

    var LABELS = {
        STALE: ['warning', 'Périmé — « Appliquer » le refait'],
        PENDING: ['info', 'Mise en forme demandée…'],
        AWAITING_RESOURCES: ['info', 'En attente de ressources…'],
        RUNNING: ['info', 'Mise en forme en cours…'],
        FAILURE: ['danger', 'Échec du rendu'],
    };

    function mount(body, ctx, options) {
        var role = options.role || 'preview';
        var process = options.process || ctx.config.surface.reruns || '';
        body.classList.add('wama-brick-preview');
        var frame = global.WamaMediaPreview.documentFrame('', {
            referrerPolicy: 'no-referrer', title: 'Aperçu du document' });
        var empty = document.createElement('div');
        empty.className = 'wama-preview-empty';
        body.appendChild(frame);
        body.appendChild(empty);

        var tools = document.createElement('div');
        tools.className = 'wama-brick-tools';
        tools.innerHTML =
            '<span class="wama-preview-state badge"></span>' +
            '<button type="button" class="btn btn-xs" data-act="reload" title="Recharger l\'aperçu"><i class="fas fa-rotate"></i></button>' +
            '<a class="btn btn-xs" data-act="open" target="_blank" rel="noopener" title="Ouvrir dans un onglet"><i class="fas fa-up-right-from-square"></i></a>';
        var badge = tools.querySelector('.wama-preview-state');
        var openLink = tools.querySelector('[data-act="open"]');
        tools.addEventListener('mousedown', function (e) { e.stopPropagation(); });
        tools.addEventListener('click', function (e) {
            if (e.target.closest('[data-act="reload"]')) load();
        });

        var shownState = null;

        function url() { return ctx.reads()[role] || ''; }

        function load() {
            var u = url();
            frame.hidden = !u;
            empty.hidden = !!u;
            openLink.hidden = !u;
            if (!u) {
                empty.textContent = 'Pas encore de rendu.';
                frame.removeAttribute('src');
                return;
            }
            openLink.href = u;
            // Le rendu refait garde son adresse : sans ce jeton, le cadre resservirait l'ancien.
            frame.src = u + (u.indexOf('?') < 0 ? '?' : '&') + 'v=' + Date.now();
        }

        function showState(states) {
            var s = process ? states[process] : '';
            var label = LABELS[s];
            badge.hidden = !label;
            if (label) {
                badge.className = 'wama-preview-state badge text-bg-' + label[0];
                badge.textContent = label[1];
            }
            // Le process vient de finir : le rendu a changé, on le recharge.
            if (s === 'SUCCESS' && shownState && shownState !== 'SUCCESS') load();
            shownState = s;
        }

        ctx.on('processes', showState);
        load();
        showState(ctx.processes());
        return { tools: tools };
    }

    global.WamaSurface.registerBrick('html_preview', { title: 'Aperçu', mount: mount });
})(window);
