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
 * (le cadenas du titre du volet). Le contenu d'une brique DÉFILE en elle (la règle de toutes les
 * briques) ; une section que la page masque — l'aperçu tant que rien n'est sélectionné — retire
 * son panneau sans laisser de trou (`setShown`).
 */
(function (global) {
    'use strict';

    var source = document.getElementById('wama-panel-layout');
    var me = document.currentScript;
    if (!source || !me) return;
    var config;
    try { config = JSON.parse(source.textContent); } catch (e) { return; }
    var content = document.querySelector('#wama-right-panel .right-panel-content');
    var header = document.querySelector('#wama-right-panel .right-panel-header');
    if (!config || !content) return;

    var layout = null;              // la disposition commune, une fois montée
    var lockBtn = null, resetBtn = null;

    // ── Les fichiers de la grille, chargés au premier geste (une page disposée les a déjà) ──
    function loadStyle(href) {
        if (!href || document.querySelector('link[href="' + href + '"]')) return;
        var link = document.createElement('link');
        link.rel = 'stylesheet';
        link.href = href;
        document.head.appendChild(link);
    }
    function loadScript(src, ready) {
        if (ready()) return Promise.resolve();
        return new Promise(function (resolve, reject) {
            var s = document.createElement('script');
            s.src = src;
            s.onload = resolve;
            s.onerror = function () { reject(new Error(src)); };
            document.body.appendChild(s);
        });
    }
    function loadGrid() {
        loadStyle(me.dataset.gridstackCss);
        loadStyle(me.dataset.surfaceCss);
        return loadScript(me.dataset.gridstackJs, function () { return !!global.GridStack; })
            .then(function () {
                return loadScript(me.dataset.layoutJs, function () { return !!global.WamaBrickLayout; });
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

    function arrange() {
        if (layout) return Promise.resolve();
        return loadGrid().then(function () {
            if (layout) return;
            var slots = config.slots.filter(function (slot) { return !!sectionOf(slot); });
            if (!slots.length) return;
            var first = sectionOf(slots[0]);
            var column = document.createElement('div');
            column.className = 'grid-stack wama-surface-panel wama-panel-column';
            column.dataset.zone = 'panel';
            first.parentNode.insertBefore(column, first);
            var sections = {};
            slots.forEach(function (slot) { sections[slot.id] = sectionOf(slot); });
            layout = global.WamaBrickLayout.create({
                panelRoot: column, page: column, frameHost: document.body,
                slots: slots, maxRows: config.max_rows, dockEdges: config.dock_edges,
                layout: config.layout, url: config.url, key: config.key,
                titleOf: function (slot) { return titleOf(sections[slot.id], slot); },
                mount: function (rec) {
                    rec.body.classList.add('wama-panel-body');
                    rec.body.appendChild(sections[rec.slot.id]);
                },
                emit: function (name) { if (name === 'layout') syncTools(); },
            });
            layout.build();
            document.body.classList.add('wama-panel-arranged');
            // La brique suit sa section : masquée par la page, son panneau se retire.
            slots.forEach(function (slot) {
                var el = sections[slot.id];
                layout.setShown(slot.id, shown(el));
                new MutationObserver(function () { layout.setShown(slot.id, shown(el)); })
                    .observe(el, { attributes: true, attributeFilter: ['style', 'hidden'] });
            });
            syncTools();
        });
    }

    // ── Le cadenas du titre du volet : modifier / figer la disposition, et la remettre ─────
    function button(icon, title, onClick) {
        var b = document.createElement('button');
        b.type = 'button';
        b.className = 'btn btn-sm btn-link text-secondary p-0 ms-2';
        b.innerHTML = '<i class="fas ' + icon + '"></i>';
        b.title = title;
        b.setAttribute('aria-label', title);
        b.addEventListener('click', onClick);
        return b;
    }
    function syncTools() {
        if (!lockBtn) return;
        var open = !!layout && !layout.frozen();
        lockBtn.innerHTML = '<i class="fas ' + (open ? 'fa-lock-open' : 'fa-lock') + '"></i>';
        lockBtn.title = open ? 'Figer la disposition du volet' : 'Modifier la disposition du volet';
        lockBtn.setAttribute('aria-label', lockBtn.title);
        lockBtn.setAttribute('aria-pressed', open ? 'true' : 'false');
        resetBtn.hidden = !open;
    }
    if (header) {
        var tools = document.createElement('span');
        tools.className = 'wama-panel-tools';
        resetBtn = button('fa-table-cells-large', 'Disposition par défaut du volet', function () {
            if (layout) layout.reset();
        });
        lockBtn = button('fa-lock', '', function () {
            if (layout) { layout.setFrozen(!layout.frozen()); return; }
            arrange().then(function () { if (layout) layout.setFrozen(false); })
                .catch(function (e) {
                    if (global.WamaApp && global.WamaApp.toast) {
                        global.WamaApp.toast('Disposition indisponible : ' + e.message, 'danger');
                    }
                });
        });
        tools.appendChild(resetBtn);
        tools.appendChild(lockBtn);
        header.appendChild(tools);
        syncTools();
    }

    // Une page déjà disposée par ce compte s'ouvre telle qu'il l'a laissée.
    function start() { if (config.arranged) arrange(); }
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
    else start();

    global.WamaPanelLayout = { arrange: arrange, layout: function () { return layout; } };
})(window);
