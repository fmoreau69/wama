/**
 * wama-panel-layout.js — le VOLET d'une page en BRIQUES (2026-10-28, `WAMA_VOLETS §3-ter`,
 * étape ② ; décision de Fabien du 21/10 : « on passe tout WAMA progressivement en briques UI »).
 *
 * Chaque section du volet (assistant, bloc de tête, Aperçu, Infos, Paramètres, Actions) devient un
 * panneau de la disposition COMMUNE (`wama-brick-layout.js`, celle des surfaces) : on la réordonne,
 * on la retaille, on l'empile, on l'épingle à un bord de la zone centrale, et la disposition se
 * garde par compte et par page (`common:panel_layout`). La section est DÉPLACÉE telle quelle dans
 * son panneau — mêmes éléments, mêmes identifiants : l'inspecteur et les apps qui la remplissent
 * n'en savent rien. Ce que la page déclare (les sections, leur ordre et leur hauteur par défaut)
 * vient du serveur (`common/utils/volet.py`, `PANEL_SLOTS`) ; rien n'est recopié ici.
 *
 * Le rendu par défaut ne change pas : tant que le compte n'a rien disposé, le volet reste celui
 * d'avant et la grille n'est pas même chargée ; elle se monte au geste « Modifier la disposition »
 * (le cadenas de l'en-tête, `wama-page-controls.js`). Le contenu d'une brique DÉFILE en elle (la règle de toutes les
 * briques) ; une section que la page masque — l'aperçu tant que rien n'est sélectionné — retire
 * son panneau sans laisser de trou (`setShown`).
 *
 * LE CENTRE (2026-10-28, étape ④) : la card d'entrée, la progression globale, la barre de la file
 * et la file deviennent les briques de la GRILLE du centre, dans la même disposition que le volet
 * — une brique passe de l'une à l'autre en la glissant, comme sur une surface. Elles se trouvent
 * par la marque que leur pièce commune pose (`data-wama-brick`, son domaine
 * `data-wama-brick-domain`) ; un onglet de domaine masqué retire ses briques, son retour les rend
 * à leur rang. La grille se pose à la place de la première, ou sous les onglets.
 */
(function (global) {
    'use strict';

    var source = document.getElementById('wama-panel-layout');
    var me = document.currentScript;
    if (!source || !me) return;
    var config;
    try { config = JSON.parse(source.textContent); } catch (e) { return; }
    var content = document.querySelector('#wama-right-panel .right-panel-content');
    if (!config || !content) return;
    var MARK = '[data-wama-brick]';
    var withCentre = Array.prototype.some.call(document.querySelectorAll(MARK),
        function (el) { return !content.contains(el); });
    var subject = withCentre ? 'de la page' : 'du volet';

    var layout = null;              // la disposition commune, une fois montée

    // ── Les fichiers de la grille, chargés au premier geste (une page disposée les a déjà),
    // par la plomberie commune (`WamaApp.loadScript`, `loadStyle`).
    function loadGrid() {
        var App = global.WamaApp;
        App.loadStyle(me.dataset.gridstackCss);
        App.loadStyle(me.dataset.surfaceCss);
        return App.loadScript(me.dataset.gridstackJs, function () { return !!global.GridStack; })
            .then(function () {
                return App.loadScript(me.dataset.layoutJs, function () { return !!global.WamaBrickLayout; });
            });
    }

    // ── Les sections que la page porte ─────────────────────────────────────────────────────
    function sectionOf(slot) {
        var el = document.getElementById(slot.element);
        if (!el || !content.contains(el)) return null;
        // Le bloc de tête n'est un panneau que s'il porte quelque chose (il est vide par défaut).
        if (slot.id === 'top' && !el.children.length) return null;
        return el;
    }
    /** Une section est montrée tant que la page ne l'a pas masquée (`style.display`, `hidden`). */
    function shown(el) { return el.style.display !== 'none' && !el.hidden; }
    function titleOf(el, slot) {
        var title = el.querySelector('.right-panel-section-title');
        return (title && title.textContent.trim()) || slot.id;
    }

    // ── Les briques du centre ──────────────────────────────────────────────────────────────
    /** L'emplacement déclaré d'une marque : celui de son domaine, sinon celui sans domaine (une
     *  app d'un seul domaine qui le nomme quand même). */
    function centreSlotOf(kind, domain) {
        var exact = null, plain = null;
        config.slots.forEach(function (slot) {
            if (slot.zone !== 'grid' || slot.kind !== kind) return;
            if (slot.domain === domain) exact = slot;
            else if (!slot.domain) plain = slot;
        });
        return exact || plain;
    }
    /** Les briques du centre, dans l'ordre de la page : `{slot, el, pane}`. Une marque sans
     *  domaine (la progression) prend celui d'une brique marquée de son onglet. */
    function centreBricks() {
        var marked = Array.prototype.filter.call(document.querySelectorAll(MARK),
            function (el) { return !content.contains(el); });
        var found = [], taken = {};
        marked.forEach(function (el) {
            var pane = el.closest('.tab-pane');
            var domain = el.dataset.wamaBrickDomain || '';
            if (!domain && pane) {
                marked.some(function (other) {
                    domain = pane.contains(other) && other.dataset.wamaBrickDomain || '';
                    return !!domain;
                });
            }
            var slot = centreSlotOf(el.dataset.wamaBrick, domain);
            if (!slot || taken[slot.id]) return;
            taken[slot.id] = true;
            // Le TITRE posé juste avant une brique (« File d'attente images ») est celui du bloc
            // qu'il introduit : il part avec lui, au lieu de rester seul au-dessus de la grille.
            var prev = el.previousElementSibling;
            var heading = prev && /^H[1-6]$/.test(prev.tagName) ? prev : null;
            found.push({ slot: slot, el: el, pane: pane, heading: heading });
        });
        return found;
    }
    /** Empilées dans l'ordre de LA page (les pages ne rendent pas toutes leurs briques dans le même
     *  ordre), ESPACÉES : une brique `fit` prend ensuite la hauteur de son contenu, et la grille
     *  (sans flottement) remonte chacune sous la précédente. Collées, une brique grandie aurait
     *  chevauché la suivante, et gridstack les aurait permutées (vu à « Disposition par défaut »). */
    var STACK_STEP = 20;
    function stackCentre(bricks) {
        bricks.forEach(function (b, i) {
            b.slot = Object.assign({}, b.slot, { y: i * STACK_STEP });
        });
    }
    /** La barre de file trouve sa file dans son frère SUIVANT (`wama-filter-bar.js`) : chacune
     *  dans sa brique, ce lien se nomme avant de les séparer. */
    function pinToolbarScope(bricks) {
        bricks.forEach(function (b) {
            if (b.slot.kind !== 'toolbar' || b.el.getAttribute('data-cible-dans') !== 'file-suivante') return;
            var next = b.el.nextElementSibling;
            if (next && next.id) b.el.setAttribute('data-cible-dans', '#' + next.id);
        });
    }

    function arrange() {
        if (layout) return Promise.resolve();
        return loadGrid().then(function () {
            if (layout) return;
            var elements = {}, panes = {}, headings = {};
            var slots = config.slots.filter(function (slot) { return !!sectionOf(slot); });
            slots.forEach(function (slot) { elements[slot.id] = sectionOf(slot); });
            var bricks = centreBricks();
            if (!slots.length && !bricks.length) return;
            var column = null, grid = null;
            if (slots.length) {
                var first = elements[slots[0].id];
                column = document.createElement('div');
                column.className = 'grid-stack wama-surface-panel wama-panel-column';
                column.dataset.zone = 'panel';
                first.parentNode.insertBefore(column, first);
            }
            if (bricks.length) {
                stackCentre(bricks);
                pinToolbarScope(bricks);
                var anchor = bricks[0].el, tabs = anchor.closest('.tab-content');
                grid = document.createElement('div');
                grid.className = 'grid-stack wama-surface-grid wama-centre-grid';
                if (tabs) tabs.parentNode.insertBefore(grid, tabs.nextSibling);
                else anchor.parentNode.insertBefore(grid, anchor);
                bricks.forEach(function (b) {
                    elements[b.slot.id] = b.el;
                    panes[b.slot.id] = b.pane;
                    headings[b.slot.id] = b.heading;
                    slots.push(b.slot);
                });
            }
            layout = global.WamaBrickLayout.create({
                root: grid, panelRoot: column, page: grid || column, frameHost: document.body,
                slots: slots, columns: config.columns, maxRows: config.max_rows,
                dockEdges: config.dock_edges,
                layout: config.layout, url: config.url, key: config.key,
                titleOf: function (slot) {
                    return slot.kind ? slot.title : titleOf(elements[slot.id], slot);
                },
                mount: function (rec) {
                    if (!rec.slot.kind) {
                        rec.body.classList.add('wama-panel-body');
                        rec.body.appendChild(elements[rec.slot.id]);
                        return;
                    }
                    // Une enveloppe : c'est elle, marges comprises, que mesure une brique `fit`.
                    var wrap = document.createElement('div');
                    wrap.className = 'wama-centre-body';
                    if (headings[rec.slot.id]) wrap.appendChild(headings[rec.slot.id]);
                    wrap.appendChild(elements[rec.slot.id]);
                    rec.body.appendChild(wrap);
                },
                emit: function (name) { if (name === 'layout') syncTools(); },
            });
            layout.build();
            document.body.classList.add('wama-panel-arranged');
            // La brique suit sa section : masquée par la page — ou son onglet —, son panneau se retire.
            slots.forEach(function (slot) {
                var el = elements[slot.id], pane = panes[slot.id];
                var follow = function () {
                    layout.setShown(slot.id, shown(el) && (!pane || pane.classList.contains('active')));
                };
                follow();
                new MutationObserver(follow)
                    .observe(el, { attributes: true, attributeFilter: ['style', 'hidden'] });
                if (pane) new MutationObserver(follow).observe(pane, { attributes: true, attributeFilter: ['class'] });
            });
            syncTools();
        });
    }

    // ── Le cadenas : celui des CONTRÔLES DE PAGE de l'en-tête (2026-10-29), auquel le volet se
    // déclare — il vivait dans le titre du volet, qu'une disposition peut déplacer.
    function syncTools() {
        if (global.WamaPageControls) global.WamaPageControls.layoutChanged();
    }
    if (global.WamaPageControls) {
        global.WamaPageControls.offerLayout({
            subject: subject,
            frozen: function () { return !layout || layout.frozen(); },
            setFrozen: function (on) {
                if (layout) { layout.setFrozen(on); return; }
                if (on) return;
                return arrange().then(function () { if (layout) layout.setFrozen(false); });
            },
            reset: function () { if (layout) layout.reset(); },
        });
    }

    // Une page déjà disposée par ce compte s'ouvre telle qu'il l'a laissée.
    function start() { if (config.arranged) arrange(); }
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
    else start();

    global.WamaPanelLayout = { arrange: arrange, layout: function () { return layout; } };
})(window);
