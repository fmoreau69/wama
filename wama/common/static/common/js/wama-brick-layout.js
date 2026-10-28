/**
 * wama-brick-layout.js — la DISPOSITION d'une page de briques : où chaque brique se pose, ce que
 * l'utilisateur en fait, ce qui se garde par compte. Sortie le 2026-10-28 du noyau des surfaces
 * (`surfaces/wama-surface.js`, où elle vivait depuis le 2026-10-10) pour que les pages d'apps la
 * montent SANS le noyau d'édition — leur volet devient une zone de briques (`WAMA_VOLETS §3-ter`,
 * étape ②). Déplacée telle quelle : aucun geste n'a changé.
 *
 * Ce qu'elle fait, et elle seule — une page ou une brique n'en réécrit rien :
 *   • la GRILLE (gridstack) : chaque brique est un élément déplaçable par son titre et
 *     redimensionnable ; la disposition se garde PAR COMPTE (route `layout`, 2026-10-21 — le
 *     stockage du navigateur ne sert plus qu'en secours) et se réinitialise à celle que la page
 *     déclare. Elle se FIGE (`setFrozen`) : la grille ne bouge plus et les panneaux prennent un
 *     habit fini ; une page jamais disposée s'ouvre FIGÉE (pour tous depuis le 2026-10-21,
 *     décision de Fabien). Deux ZONES : la grille du centre et la COLONNE du volet droit
 *     (`panelRoot`, `zone='panel'`), où l'on réordonne et règle la hauteur ; une brique passe de
 *     l'une à l'autre en la glissant, sans être remontée.
 *     Sous 768 px de fenêtre, les panneaux s'empilent sur une colonne (rien n'est alors gardé) ;
 *   • GARDER à l'écran (2026-10-26) : des briques EMPILÉES en un seul panneau (`stacks`, la tête
 *     d'abord — affichage seul, chaque brique garde son code et son état) et un panneau ÉPINGLÉ à
 *     un bord de la fenêtre (`docked` : haut, bas, gauche, droite), le centre défilant entre les
 *     bords ; tous deux gardés avec la disposition du compte. Depuis le 2026-10-27, un seul CADRE
 *     fixe borné par l'en-tête, le pied et les volets, des LIGNES de panneaux côte à côte à
 *     chaque bord (`docked` : `{bord: [[panneau, …]]}`, `WamaBrickLayout.docks`), et le
 *     GLISSER-DÉPOSER vers les bords.
 *
 * Ce qu'elle ne fait pas : MONTER une brique (la page la monte, par `mount(rec)`), ni rien savoir
 * de ce que la page édite, de son bus ou de son enregistrement.
 *
 * Le VOLET d'une page d'app (2026-10-28, `wama-panel-layout.js`) n'a pas de grille au centre : il
 * passe la seule colonne (`panelRoot`, sans `root`) et l'endroit du cadre des bords (`frameHost`).
 * Un panneau dont le contenu se RETIRE — l'aperçu masqué tant que rien n'est sélectionné — sort
 * de sa zone sans laisser de trou et y revient à sa place (`setShown`) : ce n'est pas un geste,
 * rien ne se garde.
 *
 * Usage :
 *     var layout = WamaBrickLayout.create({
 *         root, page, panelRoot,   // la grille, l'élément qui porte `.is-frozen`, la colonne du volet
 *         frameHost,               // où poser le cadre des bords (défaut : à côté de la grille)
 *         slots,                   // les emplacements DÉCLARÉS : [{id, x, y, w, h, zone?}]
 *         columns, maxRows, dockEdges,     // ce que le serveur applique — jamais recopié ici
 *         layout,                  // la disposition gardée : {slots, frozen, stored, stacks, docked}
 *         url, key,                // la route qui la garde ; la clé du secours du navigateur
 *         defOf(slot),             // ce que la brique déclare : `dockable`, `rowWidth`
 *         titleOf(slot, def),      // le titre de son panneau
 *         mount(rec),              // monte la brique dans `rec.body` ; ses outils dans `rec.head`,
 *                                  // `rec.hasTools` s'il y en a
 *         emit(name, payload),     // `resize`, `layout` (`{frozen}`)
 *     });
 *     layout.build();              // pose les cadres, monte les briques, épingle
 *     layout.frozen(); layout.setFrozen(on); layout.reset(); layout.help;
 *     layout.setShown(id, on);     // le contenu d'une brique s'est retiré / est revenu
 */
(function (global) {
    'use strict';

    var CELL_HEIGHT = 46;
    /** px de fenêtre sous lesquels les panneaux s'empilent sur une colonne (rien ne se garde). */
    var NARROW = 768;

    function readLayout(key) {
        try { return JSON.parse(localStorage.getItem(key) || 'null'); } catch (e) { return null; }
    }
    function writeLayout(key, value) {
        try {
            if (value) localStorage.setItem(key, JSON.stringify(value));
            else localStorage.removeItem(key);
        } catch (e) { /* stockage indisponible : la disposition déclarée reste */ }
    }

    /** Les poids d'une pile (`[{id, h}]`) ramenés à `rows` rangées : chaque brique garde sa part
     *  de la hauteur du panneau (au moins une rangée) — ce qu'elle retrouve détachée, ce qu'elle
     *  apporte à une autre pile. Pure (testée en V8). */
    function scaleWeights(list, rows) {
        var total = list.reduce(function (s, e) { return s + (e.h > 0 ? e.h : 1); }, 0) || 1;
        return list.map(function (e) {
            return { id: e.id, h: Math.max(1, Math.round((e.h > 0 ? e.h : 1) * rows / total)) };
        });
    }

    /** L'ÉPINGLAGE en LIGNES (2026-10-27, Fabien : un petit élément « se placerait à côté, collé
     *  au transport ») : `{bord: [[panneau, …], …]}` — en haut et en bas des lignes de panneaux
     *  côte à côte, à gauche et à droite des colonnes (`surfaces._clean_docked`). Chaque fonction
     *  rend un NOUVEL objet. Pures (testées en V8). */
    var Docks = {
        /** Le bord d'un panneau, '' s'il n'est pas épinglé. */
        edgeOf: function (docked, key) {
            for (var edge in docked || {}) {
                if (docked[edge].some(function (row) { return row.indexOf(key) >= 0; })) return edge;
            }
            return '';
        },
        /** Le panneau retiré de son bord ; une ligne vidée disparaît. */
        without: function (docked, key) {
            var out = {};
            Object.keys(docked || {}).forEach(function (edge) {
                var rows = docked[edge].map(function (row) {
                    return row.filter(function (id) { return id !== key; });
                }).filter(function (row) { return row.length; });
                if (rows.length) out[edge] = rows;
            });
            return out;
        },
        /** La tête d'une pile a changé : son épinglage la suit, à la même place. */
        renamed: function (docked, from, to) {
            var out = {};
            Object.keys(docked || {}).forEach(function (edge) {
                out[edge] = docked[edge].map(function (row) {
                    return row.map(function (id) { return id === from ? to : id; });
                });
            });
            return out;
        },
        /** Épingle un panneau : à CÔTÉ de `beside` (dans sa ligne, juste après — juste avant si
         *  `before`), sinon sur une ligne neuve au bord EXTÉRIEUR — le plus près du bord de la
         *  fenêtre. */
        put: function (docked, key, edge, beside, before) {
            var out = Docks.without(docked, key);
            var rows = out[edge] = out[edge] || [];
            for (var i = 0; beside && i < rows.length; i++) {
                var at = rows[i].indexOf(beside);
                if (at >= 0) { rows[i].splice(before ? at : at + 1, 0, key); return out; }
            }
            if (edge === 'bottom' || edge === 'right') rows.push([key]); else rows.unshift([key]);
            return out;
        },
        /** Deux panneaux dans la même ligne ? */
        together: function (docked, a, b) {
            var edge = Docks.edgeOf(docked, a);
            return !!edge && docked[edge].some(function (row) {
                return row.indexOf(a) >= 0 && row.indexOf(b) >= 0;
            });
        },
    };

    function create(opts) {
        var App = global.WamaApp || {};
        var root = opts.root || null;
        var slots = opts.slots || [];
        var emit = opts.emit || function () {};

        // ── Grille ────────────────────────────────────────────────────────────────────────
        var COLUMNS = opts.columns || 12;
        // Le plafond de lignes et les bords d'épinglage sont ceux que le serveur applique
        // (`surfaces.MAX_LAYOUT_ROWS`, `DOCK_EDGES`), passés par la page — jamais recopiés ici.
        var MAX_ROWS = opts.maxRows || Infinity;
        var layout = opts.layout || { slots: null, frozen: true, stored: false };
        // La COLONNE du volet (2026-10-21, décision de Fabien) : une seconde zone, d'une colonne —
        // on y réordonne, on y règle la hauteur, une brique passe d'une zone à l'autre en la
        // glissant. Absente (page sans volet), tout reste dans la grille. Sans grille (le volet
        // d'une page d'app, 2026-10-28), tout est dans la colonne.
        var panelRoot = opts.panelRoot || null;
        var page = opts.page || root || panelRoot;
        var grid = root ? global.GridStack.init({
            column: COLUMNS, cellHeight: CELL_HEIGHT, margin: 6, float: false,
            handle: '.wama-brick-head', resizable: { handles: 'e, se, s, sw, w' },
            staticGrid: !!layout.frozen, acceptWidgets: !!panelRoot,
            // Téléphone : une colonne, les panneaux dans l'ordre de la grille (option de gridstack).
            columnOpts: { breakpointForWindow: true, breakpoints: [{ w: NARROW, c: 1 }], layout: 'list' },
        }, root) : null;
        var panel = panelRoot ? global.GridStack.init({
            column: 1, cellHeight: CELL_HEIGHT, margin: 6, float: false, minRow: 2,
            handle: '.wama-brick-head', resizable: { handles: 's' },
            staticGrid: !!layout.frozen, acceptWidgets: true,
        }, panelRoot) : null;
        var zones = [grid, panel].filter(Boolean);
        function showFrozen(on) {
            page.classList.toggle('is-frozen', on);
            if (panelRoot) panelRoot.classList.toggle('is-frozen', on);
        }
        showFrozen(!!layout.frozen);
        /** La zone d'une place : celle qu'elle porte (gardée), sinon celle que l'emplacement
         *  déclare ; une place gardée sans zone date d'avant la colonne : la grille. */
        function zoneOf(slot, place) {
            var zone = place === slot ? (slot.zone || 'grid') : ((place && place.zone) || 'grid');
            return (zone === 'panel' && panel) || !grid ? 'panel' : 'grid';
        }
        function gridOf(zone) { return zone === 'panel' ? panel : grid; }
        function placeIn(zone, place) {
            return zone === 'panel' ? { x: 0, y: place.y, w: 1, h: place.h }
                                    : { x: place.x, y: place.y, w: place.w, h: place.h };
        }
        // Une disposition gardée par ce navigateur AVANT la garde par compte est reprise une fois.
        var migrated = !layout.stored && readLayout(opts.key);
        if (migrated) layout.slots = migrated;
        var saved = layout.slots || {};

        // Le titre (la poignée `handle`) existe AVANT que gridstack ne prenne l'élément :
        // gridstack cherche ses poignées une seule fois, à `makeWidget`, et faute d'en trouver
        // rend TOUTE la brique déplaçable — un glisser dans l'image (redimensionner une zone)
        // devenait, après quelques pixels, un déplacement de la brique (relevé par Fabien,
        // 2026-10-13). D'où l'élément construit à la main plutôt que `addWidget`.
        //
        // La SECTION (titre + corps) est ce qu'une brique apporte dans un panneau : seule, elle
        // remplit le sien ; EMPILÉE, elle passe dans le panneau du groupe — le même élément, la
        // brique n'est jamais remontée. Deux temps : `build` pose les cadres (et reforme les piles
        // gardées), `mountBrick` monte les briques une fois tout attaché à la page.
        var frames = {};                    // emplacement → {slot, def, el, section, head, body, brick}
        function build(slot, placed) {
            var place = saved[slot.id] || slot;
            var zone = zoneOf(slot, place);
            var el = document.createElement('div');
            el.className = 'grid-stack-item';
            var content = document.createElement('div');
            content.className = 'grid-stack-item-content';
            el.appendChild(content);
            var def = opts.defOf ? opts.defOf(slot) || {} : {};
            var section = document.createElement('div');
            section.className = 'wama-brick-section';
            section.dataset.slot = slot.id;
            var head = document.createElement('div');
            head.className = 'wama-brick-head';
            var title = document.createElement('span');
            title.className = 'wama-brick-title';
            title.textContent = opts.titleOf ? opts.titleOf(slot, def) : (def.title || slot.id);
            head.appendChild(title);
            var body = document.createElement('div');
            body.className = 'wama-brick-body';
            section.appendChild(head);
            section.appendChild(body);
            content.appendChild(section);
            var rec = { slot: slot, def: def, el: el, section: section, head: head, body: body,
                        brick: {}, zone: zone, place: placeIn(zone, place) };
            frames[slot.id] = rec;
            if (placed) putSolo(slot.id, rec.place, gridOf(zone));
            return rec;
        }

        /** La page monte la brique (`opts.mount`), la disposition pose ses outils de titre. */
        function mountBrick(rec) {
            if (opts.mount) opts.mount(rec);
            layoutTools(rec);
            return rec;
        }

        // ── EMPILER des briques en UN panneau (2026-10-26, Fabien : « empiler/imbriquer des
        // briques pour les compacter en une seule, uniquement en affichage » — le transport, la
        // ligne de temps et l'écriture à la lecture, qu'on fixe ensemble). Chaque brique garde son
        // code et son état ; seul son CADRE change. Gardé par compte (`stacks` : `{tête: [{id, h}]}`,
        // `surfaces.clean_layout`) ; la tête donne au panneau sa place et son épinglage. Un geste de
        // DISPOSITION : il se fait disposition modifiable, comme déplacer ou redimensionner.
        layout.stacks = layout.stacks || {};
        layout.docked = layout.docked || {};
        var shells = {};                    // tête → l'élément du panneau d'une pile

        function groupOf(id) {
            for (var key in layout.stacks) {
                if (layout.stacks[key].some(function (e) { return e.id === id; })) return key;
            }
            return null;
        }
        /** Les panneaux de la page : une brique seule, ou la tête d'une pile. */
        function containers() {
            return slots.map(function (s) { return s.id; }).filter(function (id) {
                if (!frames[id]) return false;
                var key = groupOf(id);
                return !key || key === id;
            });
        }
        function containerEl(key) { return shells[key] || frames[key].el; }
        // Un panneau ÉPINGLÉ quitte la grille — la page se referme derrière lui — et y retrouve SA
        // place quand on le désépingle : elle est gardée ici, et dans la disposition du compte.
        var dockPlaces = {};                // panneau → {x, y, w, h, grid}
        // Un panneau dont le contenu s'est RETIRÉ (`setShown`) sort de sa zone, comme épinglé, et y
        // revient à SA place : la grille se referme derrière lui, rien ne se garde.
        var hiddenPlaces = {};              // panneau → {x, y, w, h, grid}
        /** La place d'un panneau dans sa zone, qu'il y soit ou qu'il en soit sorti, épinglé ou
         *  retiré. */
        function placeOf(key) {
            if (dockPlaces[key]) return dockPlaces[key];
            if (hiddenPlaces[key]) return hiddenPlaces[key];
            var node = containerEl(key).gridstackNode;
            return node ? { x: node.x, y: node.y, w: node.w, h: node.h, grid: node.grid } : null;
        }
        function titleOf(id) { return frames[id].head.querySelector('.wama-brick-title').textContent; }
        function labelOf(key) {
            return (layout.stacks[key] || [{ id: key }]).map(function (e) { return titleOf(e.id); })
                .join(' + ');
        }
        /** La place d'une zone : la colonne du volet n'a qu'une colonne. */
        function fit(at, g) {
            return g === panel ? { x: 0, y: at.y, w: 1, h: at.h }
                               : { x: at.x, y: at.y, w: Math.min(at.w, COLUMNS), h: at.h };
        }
        function putSolo(id, at, g) {
            var rec = frames[id];
            rec.section.style.flexGrow = '';
            rec.el.querySelector('.grid-stack-item-content').appendChild(rec.section);
            rec.el.dataset.panel = id;
            g.el.appendChild(rec.el);
            var place = fit(at, g);
            place.id = id;
            g.makeWidget(rec.el, place);
        }
        function buildShell(list, at, g) {
            var el = document.createElement('div');
            el.className = 'grid-stack-item wama-brick-stack-shell';
            el.dataset.panel = list[0].id;
            var content = document.createElement('div');
            content.className = 'grid-stack-item-content';
            list.forEach(function (entry) {
                var section = frames[entry.id].section;
                section.style.flexGrow = String(entry.h);     // son poids dans la hauteur du panneau
                content.appendChild(section);
            });
            el.appendChild(content);
            g.el.appendChild(el);
            var place = fit(at, g);
            place.id = list[0].id;
            g.makeWidget(el, place);
            shells[list[0].id] = el;
            return el;
        }
        /** Retire un panneau de sa zone (sans détruire ses briques) : rend sa place et sa zone. */
        function take(key) {
            var el = containerEl(key), node = el.gridstackNode, place = placeOf(key);
            var g = (place && place.grid) || zones[0];
            var at = place ? { x: place.x, y: place.y, w: place.w, h: place.h } : { x: 0, y: 0, w: 4, h: 4 };
            if (node && node.grid) node.grid.removeWidget(el, false, false);
            if (el.parentNode) el.parentNode.removeChild(el);
            clearDock(el);
            el.hidden = false;
            delete shells[key];
            delete dockPlaces[key];
            delete hiddenPlaces[key];
            return { at: at, grid: g };
        }
        /** Ses briques et leur poids, ramenés à sa hauteur actuelle (un panneau a pu être retaillé). */
        function entriesOf(key) {
            var place = placeOf(key), rows = place ? place.h : 1;
            var list = layout.stacks[key];
            if (!list) return [{ id: key, h: rows }];
            return scaleWeights(list, rows);
        }

        function restack(fn) {
            if (layout.frozen) return;
            resetting = true;
            try { fn(); } finally { resetting = false; }
            if (onFullGrid()) layout.slots = layoutNow();
            syncLayoutTools();
            syncShown();
            applyDocks();
            persistLayout();
        }
        /** Le panneau `other` (brique ou pile) rejoint celui de `own`, sous ses briques — à la place
         *  `at` de `own` quand on la donne (celle qu'il avait quand un glisser l'a visé, avant que
         *  la grille ne l'écarte), sinon à sa place du moment. */
        function join(own, other, at) {
            restack(function () {
                var a = entriesOf(own), b = entriesOf(other);
                var ta = take(own), tb = take(other);
                delete layout.stacks[own]; delete layout.stacks[other];
                layout.docked = Docks.without(layout.docked, other);
                var list = a.concat(b);
                layout.stacks[list[0].id] = list;
                var where = at && at.grid === ta.grid ? at : ta.at;
                buildShell(list, { x: where.x, y: where.y, w: ta.at.w,
                                   h: Math.min(ta.at.h + tb.at.h, MAX_ROWS) }, ta.grid);
            });
        }
        /** Monte ou descend une brique dans sa pile ; la tête peut changer, son épinglage la suit. */
        function moveInStack(id, delta) {
            restack(function () {
                var key = groupOf(id), list = entriesOf(key);
                var i = list.findIndex(function (e) { return e.id === id; }), j = i + delta;
                if (j < 0 || j >= list.length) return;
                var moved = list[i]; list[i] = list[j]; list[j] = moved;
                var t = take(key);
                delete layout.stacks[key];
                layout.stacks[list[0].id] = list;
                layout.docked = Docks.renamed(layout.docked, key, list[0].id);
                buildShell(list, t.at, t.grid);
            });
        }
        /** Sort une brique de sa pile : elle reprend sa hauteur, juste sous le panneau. */
        function detach(id) {
            restack(function () {
                var key = groupOf(id), list = entriesOf(key);
                var gone = list.filter(function (e) { return e.id === id; })[0];
                var rest = list.filter(function (e) { return e.id !== id; });
                var t = take(key);
                delete layout.stacks[key];
                layout.docked = Docks.renamed(layout.docked, key, rest[0].id);
                var restH = Math.max(1, t.at.h - gone.h);
                var at = { x: t.at.x, y: t.at.y, w: t.at.w, h: restH };
                if (rest.length > 1) {
                    layout.stacks[rest[0].id] = rest;
                    buildShell(rest, at, t.grid);
                } else {
                    putSolo(rest[0].id, at, t.grid);
                }
                putSolo(id, { x: t.at.x, y: t.at.y + restH, w: t.at.w, h: gone.h }, t.grid);
            });
        }
        /** Défait toutes les piles, chaque brique à sa hauteur (« Disposition par défaut »). */
        function dissolveAll() {
            Object.keys(layout.stacks).forEach(function (key) {
                var list = entriesOf(key), t = take(key), y = t.at.y;
                list.forEach(function (e) {
                    putSolo(e.id, { x: t.at.x, y: y, w: t.at.w, h: e.h }, t.grid);
                    y += e.h;
                });
            });
            layout.stacks = {};
        }

        // ── GARDER un panneau à l'écran : ÉPINGLÉ à un bord de la fenêtre (2026-10-26, demande de
        // Fabien : « locker le transport […] pour qu'il ne défile pas avec la page », puis le jour
        // même : à gauche et à droite aussi, une colonne fixe pendant que le centre défile). Une
        // bande en haut ou en bas, une colonne à gauche ou à droite ; plusieurs panneaux sur un
        // même bord se rangent l'un après l'autre. Jamais « sur place » au milieu de la page : on
        // choisit un BORD. Gardé avec la disposition (`docked`) : une préférence de LECTURE, valable
        // aussi en lecture seule et disposition figée — pour une brique qui le DÉCLARE (`dockable`,
        // le transport) ou un panneau déjà épinglé ; disposition modifiable, pour tout panneau.
        var DOCK_CHOICES = [
            ['top', 'fa-arrow-up', 'En haut de la fenêtre'],
            ['bottom', 'fa-arrow-down', 'En bas de la fenêtre'],
            ['left', 'fa-arrow-left', 'À gauche — une colonne fixe'],
            ['right', 'fa-arrow-right', 'À droite — une colonne fixe'],
            ['', 'fa-arrows-up-down', 'Dans la page — défile avec elle'],
        ].filter(function (c) {
            return !c[0] || !opts.dockEdges || opts.dockEdges.indexOf(c[0]) >= 0;
        });
        var DOCK_SAID = { top: 'Épinglé en haut de la fenêtre', bottom: 'Épinglé en bas de la fenêtre',
                          left: 'Épinglé à gauche', right: 'Épinglé à droite' };
        var SIDES = ['left', 'right'];

        // Le CADRE des bords (2026-10-27, Fabien : « une garde permanente pour ne jamais avoir
        // d'élément masqué par le header ou le pied de page », et de même pour les volets). UN
        // seul élément fixe, borné par l'en-tête, le pied et les deux volets — les marges que lit
        // la frontière des volets (`wama-panel-toggle.css`) ; un panneau épinglé est DÉPLACÉ dans
        // la région de son bord, comme il passe de la grille à la colonne du volet. Rien ne se
        // place panneau par panneau : rien ne peut passer sous l'en-tête, le pied ou un volet.
        var dockFrame = document.createElement('div');
        dockFrame.className = 'wama-dock-frame';
        var regions = {};
        ['top', 'left', 'right', 'bottom'].forEach(function (edge) {
            var region = document.createElement('div');
            region.className = 'wama-dock-region';
            region.dataset.edge = edge;
            dockFrame.appendChild(region);
            regions[edge] = region;
        });
        (opts.frameHost || (page === root ? root.parentNode : page)).appendChild(dockFrame);
        // La page s'écarte de ce que chaque bord occupe — relu quand une région change de taille
        // (une bande plafonnée à la hauteur de la fenêtre, une colonne bornée par sa largeur).
        if (global.ResizeObserver) {
            var watcher = new global.ResizeObserver(function () { dockMargins(); });
            Object.keys(regions).forEach(function (edge) { watcher.observe(regions[edge]); });
        }

        function toolButton(icon, title, fn) {
            var b = document.createElement('button');
            b.type = 'button';
            b.className = 'btn btn-xs';
            b.title = title;
            b.setAttribute('aria-label', title);
            b.innerHTML = '<i class="fas ' + icon + '"></i>';
            b.addEventListener('mousedown', function (e) { e.stopPropagation(); });
            b.addEventListener('click', function (e) { e.stopPropagation(); fn(b); });
            return b;
        }
        function openMenu(btn, entries, title) {
            var r = btn.getBoundingClientRect();
            if (global.WamaCardMenu) global.WamaCardMenu.ouvrir(r.left, r.bottom + 4, entries, title);
        }

        function layoutTools(rec) {
            var box = document.createElement('span');
            box.className = 'wama-brick-stack-tools';
            rec.head.appendChild(box);
            rec.stackTools = box;
            if (rec.def.dockable === false) return;
            rec.dockBtn = toolButton('fa-thumbtack', '', function (b) { openDockMenu(rec.slot.id, b); });
            rec.dockBtn.classList.add('wama-brick-dock');
            rec.head.appendChild(rec.dockBtn);
        }

        function redock(docked) {
            layout.docked = docked;
            applyDocks();
            syncLayoutTools();
            persistLayout();
        }
        function openDockMenu(key, btn) {
            var current = Docks.edgeOf(layout.docked, key);
            var narrow = !onFullGrid();
            var entries = DOCK_CHOICES.map(function (c) {
                return {
                    icone: 'fas ' + (c[0] === current ? 'fa-check' : c[1]), libelle: c[2],
                    desactive: c[0] === current || (narrow && SIDES.indexOf(c[0]) >= 0),
                    agir: function () {
                        redock(c[0] ? Docks.put(layout.docked, key, c[0])
                                    : Docks.without(layout.docked, key));
                    },
                };
            });
            // À CÔTÉ d'un panneau déjà épinglé (2026-10-27) : dans sa ligne — une bande en haut ou
            // en bas, sa colonne à gauche ou à droite.
            containers().forEach(function (other) {
                var edge = Docks.edgeOf(layout.docked, other);
                if (other === key || !edge || !shownOf(other) || (narrow && SIDES.indexOf(edge) >= 0)) return;
                entries.push({
                    icone: 'fas fa-table-columns',
                    libelle: (SIDES.indexOf(edge) >= 0 ? 'Dans la colonne de « ' : 'À côté de « ')
                        + labelOf(other) + ' »',
                    desactive: Docks.together(layout.docked, key, other),
                    agir: function () { redock(Docks.put(layout.docked, key, edge, other)); },
                });
            });
            openMenu(btn, entries, 'Garder ce panneau à l’écran');
        }

        function openStackMenu(key, btn) {
            var others = containers().filter(function (k) { return k !== key && shownOf(k); });
            openMenu(btn, others.length ? others.map(function (k) {
                return { icone: 'fas fa-layer-group', libelle: labelOf(k),
                         agir: function () { join(key, k); } };
            }) : [{ vide: true, libelle: 'Aucun autre panneau sur la page' }],
            'Empiler dans ce panneau');
        }

        // ── Un panneau dont le contenu se RETIRE (2026-10-28, le volet des pages d'apps : l'aperçu
        // est masqué tant que rien n'est sélectionné, les infos aussi) ne laisse pas de trou : il
        // sort de sa zone — la grille se referme — et y revient à SA place. Épinglé, il se cache
        // dans sa ligne. Une pile reste tant qu'une de ses briques a quelque chose à montrer. Ce
        // n'est pas un geste de l'utilisateur : rien ne se garde.
        /** Le panneau `key` (brique seule ou pile) a-t-il quelque chose à montrer ? */
        function shownOf(key) {
            return (layout.stacks[key] || [{ id: key }]).some(function (e) {
                return !frames[e.id].section.hidden;
            });
        }
        // Retiré, il reste DANS la page, garé à l'abri des zones : la page qui l'a masqué le
        // retrouve par son identifiant pour le montrer de nouveau (l'inspecteur, `getElementById`).
        var parking = document.createElement('div');
        parking.className = 'wama-brick-parking';
        parking.hidden = true;
        dockFrame.parentNode.appendChild(parking);
        /** Le RANG d'un panneau dans sa zone : sa rangée dans la disposition gardée, sinon dans la
         *  déclarée, puis l'ordre de déclaration — ce qui ne bouge pas quand un panneau se retire. */
        function rankOf(key) {
            var place = (layout.slots && layout.slots[key]) || frames[key].slot;
            return [place.y, slots.indexOf(frames[key].slot)];
        }
        function before(a, b) { return a[0] < b[0] || (a[0] === b[0] && a[1] < b[1]); }
        /** La rangée où un panneau retiré revient : à la place du premier panneau montré qui le SUIT
         *  dans sa colonne (la grille écarte ce dernier), sinon sous le dernier. L'ordre ne dépend
         *  donc pas de l'ordre dans lequel la page montre ses sections (l'aperçu, puis les infos). */
        function backAt(key, place) {
            var mine = rankOf(key), next = null, end = 0;
            place.grid.getGridItems().forEach(function (item) {
                var n = item.gridstackNode;
                if (!n || !frames[n.id] || n.x >= place.x + place.w || n.x + n.w <= place.x) return;
                if (before(mine, rankOf(n.id))) next = next === null ? n.y : Math.min(next, n.y);
                else end = Math.max(end, n.y + n.h);
            });
            return next === null ? end : next;
        }
        /** Range chaque panneau selon ce qu'il montre ; rend vrai si l'un a changé de place. */
        function syncShown() {
            var was = resetting, moved = false;
            resetting = true;               // la grille qui se referme n'est pas un geste à garder
            try {
                containers().forEach(function (key) {
                    var el = containerEl(key), on = shownOf(key);
                    if (dockPlaces[key]) { el.hidden = !on; return; }
                    el.hidden = false;
                    if (!on && !hiddenPlaces[key]) {
                        var node = el.gridstackNode;
                        if (!node || !node.grid) return;
                        hiddenPlaces[key] = { x: node.x, y: node.y, w: node.w, h: node.h, grid: node.grid };
                        node.grid.removeWidget(el, false, false);
                        parking.appendChild(el);
                        moved = true;
                    } else if (on && hiddenPlaces[key]) {
                        var place = hiddenPlaces[key], at = fit(place, place.grid);
                        at.y = backAt(key, place);
                        delete hiddenPlaces[key];
                        at.id = key;
                        place.grid.el.appendChild(el);
                        place.grid.makeWidget(el, at);
                        // Une place occupée, la grille pose le nouveau venu DESSOUS : on l'y remonte,
                        // et c'est alors l'occupant qu'elle écarte.
                        if (el.gridstackNode && el.gridstackNode.y > at.y) place.grid.update(el, { y: at.y });
                        moved = true;
                    }
                });
            } finally { resetting = was; }
            return moved;
        }
        /** Le contenu de la brique `id` s'est retiré (`on` faux) ou est revenu. */
        function setShown(id, on) {
            var rec = frames[id];
            if (!rec || rec.section.hidden === !on) return;
            rec.section.hidden = !on;
            syncShown();
            applyDocks();                   // revenu, un panneau épinglé regagne son bord
        }

        /** Les outils de disposition de chaque titre, d'après les piles et les épinglages. */
        function syncLayoutTools() {
            Object.keys(frames).forEach(function (id) {
                var rec = frames[id], key = groupOf(id), list = key ? layout.stacks[key] : null;
                var i = list ? list.findIndex(function (e) { return e.id === id; }) : 0;
                var box = rec.stackTools;
                if (!box) return;
                box.innerHTML = '';
                if (list && i > 0) box.appendChild(toolButton('fa-chevron-up', 'Monter dans le panneau',
                    function () { moveInStack(id, -1); }));
                if (list && i < list.length - 1) box.appendChild(toolButton('fa-chevron-down',
                    'Descendre dans le panneau', function () { moveInStack(id, 1); }));
                if (list) box.appendChild(toolButton('fa-object-ungroup', 'Détacher du panneau',
                    function () { detach(id); }));
                if (i === 0) box.appendChild(toolButton('fa-layer-group',
                    'Empiler un autre panneau dans celui-ci (une seule bande, fixée ensemble)',
                    function (b) { openStackMenu(key || id, b); }));
                // L'épingle : sur la tête du panneau seulement — c'est le panneau qui s'épingle.
                var dockable = (list || [{ id: id }]).some(function (e) { return frames[e.id].def.dockable; });
                var edge = i === 0 ? Docks.edgeOf(layout.docked, key || id) : '';
                if (rec.dockBtn) {
                    rec.dockBtn.hidden = i !== 0;
                    rec.dockBtn.classList.toggle('active', !!edge);
                    rec.dockBtn.classList.toggle('is-optional', !dockable && !edge);
                    rec.dockBtn.title = (edge ? DOCK_SAID[edge] + ' — ' : '') + 'Garder ce panneau à l’écran…';
                    rec.dockBtn.setAttribute('aria-pressed', edge ? 'true' : 'false');
                }
                rec.head.classList.toggle('has-tools', !!rec.hasTools
                    || !!(rec.dockBtn && i === 0 && (dockable || edge)));
            });
        }

        /** Pose les cadres — les piles gardées reformées, une brique dans une seule —, puis monte
         *  les briques dans l'ordre déclaré, chacune déjà attachée à la page où qu'elle soit. */
        function buildAll() {
            var known = {}, inGroup = {}, groups = {};
            slots.forEach(function (s) { known[s.id] = true; });
            Object.keys(layout.stacks || {}).forEach(function (key) {
                var list = (layout.stacks[key] || []).filter(function (e) {
                    return known[e.id] && !inGroup[e.id];
                });
                if (list.length < 2) return;
                list.forEach(function (e) { inGroup[e.id] = true; });
                groups[list[0].id] = list;
            });
            layout.stacks = groups;
            slots.forEach(function (slot) { build(slot, !inGroup[slot.id]); });
            Object.keys(groups).forEach(function (key) {
                buildShell(groups[key], frames[key].place, gridOf(frames[key].zone));
            });
            slots.forEach(function (slot) { mountBrick(frames[slot.id]); });
        }
        var LAYOUT_HELP = 'Épingle : garder un panneau au bord de la fenêtre (haut, bas, gauche, '
            + 'droite) — disposition modifiable : empiler des panneaux en un seul (calques), les '
            + 'monter, les descendre, les détacher';

        function clearDock(el) {
            el.classList.remove('is-docked', 'is-fit');
            DOCK_CHOICES.forEach(function (c) { if (c[0]) el.classList.remove('is-docked-' + c[0]); });
            el.style.removeProperty('--wama-fit-width');
            delete el.dataset.docked;
        }
        /** La taille d'un panneau épinglé se LIT dans sa place de grille — rangées × hauteur de
         *  cellule (une bande), colonnes × largeur de colonne (une colonne) —, jamais mesurée sur
         *  l'élément : reconstruit à l'instant (« Détacher », « Empiler », rechargement), il n'a pas
         *  encore sa hauteur, et la mesure rendait une cellule (46 px) — la bande s'écrasait sur le
         *  pied (relevé par Fabien le 2026-10-27, reproduit sur le live). */
        function dockSize(place, edge) {
            return SIDES.indexOf(edge) >= 0 ? Math.round(place.w * place.grid.cellWidth())
                                            : place.h * CELL_HEIGHT;
        }
        /** La largeur qu'un panneau prend dans une ligne de bande quand il la PARTAGE : celle que
         *  ses briques déclarent (`rowWidth` — l'écriture à la lecture, un menu, à côté du
         *  transport), si toutes la déclarent ; sinon il partage la ligne avec les autres. */
        function fitWidthOf(key) {
            var widths = (layout.stacks[key] || [{ id: key }]).map(function (e) {
                return frames[e.id].def.rowWidth || '';
            });
            if (!widths.every(Boolean)) return '';
            return widths.length === 1 ? widths[0] : 'max(' + widths.join(', ') + ')';
        }
        /** Pose chaque panneau épinglé dans sa LIGNE, au bord gardé (`docked`), dans l'ordre gardé.
         *  Une ligne prend la taille de son PREMIER panneau (2026-10-28, Fabien : la taille du plus
         *  grand laissait un vide sous le transport quand l'écriture à la lecture, plus haute, se
         *  posait à côté) : ce qu'on pose « à côté » s'aligne sur ce qui était là. La poignée de la
         *  ligne la retaille sur place (`resizeRow`). Une colonne n'a pas sa place sur une fenêtre
         *  de téléphone : le panneau y reste dans la page. */
        function applyDocks() {
            var narrow = !onFullGrid();
            var was = resetting;
            var placed = {};                // panneau → le bord qu'il occupe
            resetting = true;               // la page qui se referme n'est pas un geste à garder
            try {
                containers().forEach(function (key) {
                    var el = containerEl(key);
                    var edge = Docks.edgeOf(layout.docked, key);
                    if (narrow && SIDES.indexOf(edge) >= 0) edge = '';
                    if (!edge) { undock(key, el); return; }
                    var node = el.gridstackNode;
                    if (!dockPlaces[key] && node && node.grid) {
                        dockPlaces[key] = { x: node.x, y: node.y, w: node.w, h: node.h, grid: node.grid };
                        node.grid.removeWidget(el, false, false);
                    }
                    if (!dockPlaces[key]) return;   // hors de toute zone : rien à épingler
                    var fit = SIDES.indexOf(edge) < 0 ? fitWidthOf(key) : '';
                    el.classList.toggle('is-fit', !!fit);
                    if (fit) el.style.setProperty('--wama-fit-width', fit);
                    else el.style.removeProperty('--wama-fit-width');
                    el.dataset.docked = edge;
                    el.classList.add('is-docked');
                    DOCK_CHOICES.forEach(function (c) {
                        if (c[0]) el.classList.toggle('is-docked-' + c[0], c[0] === edge);
                    });
                    placed[key] = edge;
                });
                Object.keys(regions).forEach(function (edge) {
                    var region = regions[edge], rows = [];
                    (layout.docked[edge] || []).forEach(function (ids) {
                        var row = document.createElement('div'), head = '', count = 0;
                        row.className = 'wama-dock-row';
                        ids.forEach(function (key) {
                            if (placed[key] !== edge) return;
                            row.appendChild(containerEl(key));
                            head = head || key;
                            count += 1;
                        });
                        if (!head) return;
                        row.dataset.head = head;
                        // Partagée : un panneau qui déclare sa largeur (`rowWidth`) la prend ; seul,
                        // il remplit la ligne.
                        row.classList.toggle('is-shared', count > 1);
                        row.style.setProperty('--wama-row-size', dockSize(dockPlaces[head], edge) + 'px');
                        // La POIGNÉE, au bord intérieur de la ligne (côté page) : on la tire pour
                        // retailler la ligne sur place (2026-10-28).
                        var grip = document.createElement('div');
                        grip.className = 'wama-dock-resize';
                        grip.title = 'Glisser pour retailler';
                        row.appendChild(grip);
                        rows.push(row);
                    });
                    while (region.firstChild) region.removeChild(region.firstChild);
                    rows.forEach(function (row) { region.appendChild(row); });
                });
            } finally { resetting = was; }
            dockMargins();
            emit('resize');
        }
        /** Désépinglé : le panneau retrouve SA place dans sa zone (gridstack écarte les autres). */
        function undock(key, el) {
            var place = dockPlaces[key];
            clearDock(el);
            if (!place) return;
            delete dockPlaces[key];
            var at = fit(place, place.grid);
            at.id = key;
            place.grid.el.appendChild(el);
            place.grid.makeWidget(el, at);
        }
        /** Tous les panneaux épinglés rendus à la grille (avant de la réordonner). */
        function undockAll() {
            Object.keys(dockPlaces).forEach(function (key) { undock(key, containerEl(key)); });
        }
        /** Ce que chaque bord occupe — la taille de sa RÉGION, où les panneaux se rangent l'un
         *  après l'autre : la page s'en écarte. Posé sur le corps : la colonne du volet le lit aussi. */
        function dockMargins() {
            Object.keys(regions).forEach(function (edge) {
                var region = regions[edge];
                var used = SIDES.indexOf(edge) >= 0 ? region.offsetWidth : region.offsetHeight;
                document.body.style.setProperty('--wama-dock-' + edge, used + 'px');
            });
        }
        global.addEventListener('resize', function () { if (Object.keys(frames).length) applyDocks(); });

        /** RETAILLER une ligne épinglée sur place (2026-10-28, Fabien : un panneau épinglé ne se
         *  retaillait qu'en le rendant à la page). La taille suit le pointeur pendant le geste ; au
         *  lâcher elle s'aligne sur la grille (rangées pour une bande, colonnes pour une colonne) et
         *  se garde dans la place du PREMIER panneau de la ligne — la même source que sa taille
         *  (`dockSize`), et celle qu'il retrouve rendu à la page. */
        function resizeRow(row, px) {
            var key = row.dataset.head, place = dockPlaces[key];
            if (!place) return;
            if (SIDES.indexOf(Docks.edgeOf(layout.docked, key)) >= 0) {
                var columns = place.grid === panel ? 1 : COLUMNS;
                place.w = Math.max(1, Math.min(columns - place.x, Math.round(px / place.grid.cellWidth())));
            } else {
                place.h = Math.max(1, Math.min(MAX_ROWS, Math.round(px / CELL_HEIGHT)));
            }
            if (onFullGrid()) layout.slots = layoutNow();
            applyDocks();
            persistLayout();
        }
        if (global.WamaGestures) {
            global.WamaGestures.track(dockFrame, {
                touchAction: false, threshold: 2,
                start: function (ev) {
                    var grip = !layout.frozen && ev.target.closest('.wama-dock-resize');
                    if (!grip) return false;
                    var row = grip.parentNode, edge = Docks.edgeOf(layout.docked, row.dataset.head);
                    var side = SIDES.indexOf(edge) >= 0;
                    // Le sens du geste : une bande du BAS grandit vers le haut, une colonne de
                    // DROITE vers la gauche.
                    var sign = (edge === 'bottom' || edge === 'right') ? -1 : 1;
                    return { row: row, side: side, sign: sign,
                             from: side ? row.offsetWidth : row.offsetHeight, px: null };
                },
                move: function (ev, c, d) {
                    c.px = Math.max(CELL_HEIGHT, c.from + c.sign * (c.side ? d.dx : d.dy));
                    c.row.style.setProperty('--wama-row-size', c.px + 'px');
                    dockMargins();
                },
                end: function (ev, c, how) {
                    if (how.moved && !how.cancelled && c.px != null) resizeRow(c.row, c.px);
                    else applyDocks();
                },
            });
        }

        // ── GLISSER-DÉPOSER vers les bords (2026-10-27, Fabien : « par simple drag&drop aux
        // extrémités de la zone centrale, on visualise directement si l'élément va se fixer […]
        // et de même pour l'empilement, avec la possibilité d'empiler aussi latéralement »).
        // Pendant qu'on glisse un panneau — de la page (le glisser de gridstack) ou déjà épinglé
        // (par son titre, `WamaGestures.track`) —, les bords de la zone centrale s'éclairent ;
        // au-dessus d'un panneau épinglé, son centre EMPILE, ses côtés posent À CÔTÉ ; lâché
        // ailleurs, un panneau épinglé revient dans la page. Les MÊMES gestes que les menus
        // (`Docks.put`, `join`) : le glisser n'est qu'un autre chemin vers eux. Dans la page,
        // rien ne change — la grille magnétique garde la main. Tout se dessine DANS le cadre :
        // un repère ne passe pas plus sous l'en-tête qu'un panneau.
        var EDGE_ZONE = 56;                 // px : la bande d'un bord qui épingle
        var EDGE_FIRST = 16;                // px : au plus près du bord, le bord l'emporte sur un panneau
        var dropZones = {};
        Object.keys(regions).forEach(function (edge) {
            var zone = document.createElement('div');
            zone.className = 'wama-dock-zone';
            zone.dataset.edge = edge;
            dockFrame.appendChild(zone);
            dropZones[edge] = zone;
        });
        var dropHint = document.createElement('div');
        dropHint.className = 'wama-dock-hint';
        var dropChip = document.createElement('div');
        dropChip.className = 'wama-dock-chip';
        dockFrame.appendChild(dropHint);
        dockFrame.appendChild(dropChip);
        var dropping = null;                // {key, fromDock, target}

        function pointIn(r, x, y) { return x >= r.left && x <= r.right && y >= r.top && y <= r.bottom; }
        function edgeAllowed(edge) {
            return DOCK_CHOICES.some(function (c) { return c[0] === edge; })
                && !(SIDES.indexOf(edge) >= 0 && !onFullGrid());
        }
        /** Ce qu'un lâcher ferait en (x, y) : `{kind: 'edge' | 'stack' | 'beside', …, rect, said}`,
         *  ou null (dans la page). Les rectangles sont relatifs au cadre. */
        function dropTarget(x, y, key) {
            var f = dockFrame.getBoundingClientRect();
            if (x < f.left || x > f.right || y < f.top || y > f.bottom) return null;
            var dist = { top: y - f.top, bottom: f.bottom - y, left: x - f.left, right: f.right - x };
            var near = '';
            Object.keys(dist).forEach(function (edge) {
                if (edgeAllowed(edge) && dist[edge] <= EDGE_ZONE && (!near || dist[edge] < dist[near])) near = edge;
            });
            function edgeTarget() {
                return { kind: 'edge', edge: near, said: DOCK_SAID[near].replace('Épinglé', 'Épingler') };
            }
            if (near && dist[near] <= EDGE_FIRST) return edgeTarget();
            var items = dockFrame.querySelectorAll('.wama-dock-row > .grid-stack-item');
            for (var i = 0; i < items.length; i++) {
                var el = items[i], other = el.dataset.panel, r = el.getBoundingClientRect();
                if (!pointIn(r, x, y)) continue;
                // Relâché sur lui-même : il reste où il est (un titre à peine bougé ne désépingle pas).
                if (other === key) return { kind: 'stay', said: labelOf(key) };
                var column = SIDES.indexOf(el.dataset.docked) >= 0;
                var t = column ? (y - r.top) / r.height : (x - r.left) / r.width;
                var box = { left: r.left - f.left, top: r.top - f.top, width: r.width, height: r.height };
                if (t > 0.3 && t < 0.7) {
                    return { kind: 'stack', other: other, rect: box,
                             said: 'Empiler dans « ' + labelOf(other) + ' »' };
                }
                var before = t <= 0.3;
                if (column) {
                    box.height /= 2;
                    if (!before) box.top += box.height;
                } else {
                    box.width /= 2;
                    if (!before) box.left += box.width;
                }
                return { kind: 'beside', other: other, edge: el.dataset.docked, before: before, rect: box,
                         said: 'À côté de « ' + labelOf(other) + ' »' };
            }
            var title = pageTitleUnder(x, y, key);
            if (title) {
                var tr = title.rect;
                var tl = Math.max(0, tr.left - f.left), tt = Math.max(0, tr.top - f.top);
                return { kind: 'stack', other: title.key, page: true,
                         rect: { left: tl, top: tt, width: Math.min(tr.right - f.left, f.width) - tl,
                                 height: Math.min(tr.bottom - f.top, f.height) - tt },
                         said: 'Empiler dans « ' + labelOf(title.key) + ' »' };
            }
            return near ? edgeTarget() : null;
        }
        /** Le TITRE d'un panneau de la PAGE sous le pointeur (2026-10-28, Fabien : empiler dans la
         *  page d'un glisser, puis épingler la pile d'un seul geste). Le titre et non le corps : la
         *  grille écarte le panneau qu'on survole, son corps se déroberait sous le pointeur. */
        function pageTitles(key) {
            var out = [];
            zones.forEach(function (g) {
                g.getGridItems().forEach(function (item) {
                    var other = item.dataset.panel;
                    if (!other || other === key || item.classList.contains('ui-draggable-dragging')) return;
                    item.querySelectorAll('.wama-brick-head').forEach(function (head) {
                        out.push({ key: other, head: head, rect: head.getBoundingClientRect() });
                    });
                });
            });
            return out;
        }
        function pageTitleUnder(x, y, key) {
            var live = pageTitles(key);
            for (var i = 0; i < live.length; i++) if (pointIn(live[i].rect, x, y)) return live[i];
            // …ou là où le titre ÉTAIT au début du geste (`dropping.titles`) : c'est là que
            // l'utilisateur vise, et la grille a pu écarter le panneau entre-temps. Le repère se
            // dessine sur le titre RÉEL.
            var then = (dropping && dropping.titles) || [];
            for (var j = 0; j < then.length; j++) {
                if (then[j].key !== key && pointIn(then[j].rect, x, y)) {
                    return { key: then[j].key, rect: then[j].head.getBoundingClientRect() };
                }
            }
            return null;
        }
        // px : une cible saisie sur un titre de la page le RESTE tant que le pointeur ne s'en
        // éloigne pas davantage — la grille déplace le panneau visé pendant qu'on le survole.
        var STACK_HOLD = 24;
        function showDrop(x, y) {
            var t = dropping.target;
            Object.keys(dropZones).forEach(function (edge) {
                dropZones[edge].classList.toggle('is-off', !edgeAllowed(edge));
                dropZones[edge].classList.toggle('is-active', !!t && t.kind === 'edge' && t.edge === edge);
            });
            dropHint.classList.toggle('is-shown', !!(t && t.rect));
            if (t && t.rect) {
                dropHint.style.left = t.rect.left + 'px';
                dropHint.style.top = t.rect.top + 'px';
                dropHint.style.width = t.rect.width + 'px';
                dropHint.style.height = t.rect.height + 'px';
            }
            var f = dockFrame.getBoundingClientRect();
            dropChip.textContent = t ? t.said : (dropping.fromDock ? 'Remettre dans la page' : labelOf(dropping.key));
            // En haut à gauche du pointeur — le panneau glissé, saisi par son titre, s'étend vers la
            // droite et le bas —, et toujours DANS le cadre.
            var w = dropChip.offsetWidth, h = dropChip.offsetHeight, gap = 12;
            var left = x - f.left - w - gap, top = y - f.top - h - gap;
            if (left < 0) left = x - f.left + gap;
            if (top < 0) top = y - f.top + gap;
            dropChip.style.left = Math.max(0, Math.min(left, f.width - w)) + 'px';
            dropChip.style.top = Math.max(0, Math.min(top, f.height - h)) + 'px';
        }
        function startDrop(key, fromDock) {
            if (layout.frozen || !key) return;
            dropping = { key: key, fromDock: fromDock, target: null, titles: pageTitles(key),
                         places: {} };
            // La place de chaque panneau de la page AU DÉBUT du geste : une pile s'y posera.
            dropping.titles.forEach(function (t) {
                if (!dropping.places[t.key]) dropping.places[t.key] = placeOf(t.key);
            });
            dockFrame.classList.add('is-dropping');
        }
        function moveDrop(x, y) {
            if (!dropping) return;
            var t = dropTarget(x, y, dropping.key), lock = dropping.lock;
            if (t && t.page) {
                // La place de la cible au moment où on la SAISIT : la pile s'y posera, pas là où la
                // grille l'aura poussée pendant le survol.
                t.place = dropping.places[t.other] || placeOf(t.other);
                dropping.lock = { x: x, y: y, target: t };
            } else if (!t && lock && Math.hypot(x - lock.x, y - lock.y) <= STACK_HOLD) {
                t = lock.target;
            } else {
                dropping.lock = null;
            }
            dropping.target = t;
            showDrop(x, y);
        }
        function endDrop() {
            var d = dropping;
            dropping = null;
            dockFrame.classList.remove('is-dropping');
            if (!d) return;
            var t = d.target;
            if (!t) { if (d.fromDock) redock(Docks.without(layout.docked, d.key)); return; }
            if (t.kind === 'stay') return;
            if (t.kind === 'stack') join(t.other, d.key, t.place);
            else if (t.kind === 'beside') redock(Docks.put(layout.docked, d.key, t.edge, t.other, t.before));
            else redock(Docks.put(layout.docked, d.key, t.edge));
        }
        // Un panneau de la PAGE : gridstack mène le glisser (`dragstart` / `dragstop`) ; le
        // pointeur se suit au geste commun — l'événement `drag` de gridstack ne part qu'aux
        // changements de cellule (mesuré : arrêté à 200 px du bord visé, la page ne pouvant
        // monter plus haut). La page a fini de bouger quand il se pose : le lâcher s'applique
        // juste après.
        zones.forEach(function (g) {
            g.on('dragstart', function (e, el) { startDrop(el && el.dataset.panel, false); });
            g.on('dragstop', function () { setTimeout(endDrop, 0); });
            if (global.WamaGestures) {
                global.WamaGestures.track(g.el, {
                    touchAction: false, threshold: 0,
                    start: function (ev) {
                        return !layout.frozen && ev.target.closest('.wama-brick-head') ? {} : false;
                    },
                    move: function (ev) { if (dropping && !dropping.fromDock) moveDrop(ev.clientX, ev.clientY); },
                });
            }
        });
        // Un panneau ÉPINGLÉ : par son titre (ni ses boutons ni ses champs), au geste commun.
        if (global.WamaGestures) {
            global.WamaGestures.track(dockFrame, {
                touchAction: false, threshold: 6,
                start: function (ev) {
                    if (layout.frozen || ev.target.closest('button, select, input, textarea, a')) return false;
                    var head = ev.target.closest('.wama-brick-head');
                    var el = head && head.closest('.wama-dock-row > .grid-stack-item');
                    return el ? { el: el } : false;
                },
                move: function (ev, c) {
                    if (!dropping) { startDrop(c.el.dataset.panel, true); c.el.classList.add('is-dragging'); }
                    moveDrop(ev.clientX, ev.clientY);
                },
                end: function (ev, c, how) {
                    c.el.classList.remove('is-dragging');
                    if (how.cancelled) { dropping = null; dockFrame.classList.remove('is-dropping'); return; }
                    if (how.moved) endDrop();
                },
            });
        }

        function layoutNow() {
            var out = {};
            zones.forEach(function (g) {
                var zone = g === panel ? 'panel' : 'grid';
                g.getGridItems().forEach(function (el) {
                    var n = el.gridstackNode;
                    if (n && n.id) out[n.id] = { x: n.x, y: n.y, w: n.w, h: n.h, zone: zone };
                });
            });
            // Un panneau épinglé ou retiré a quitté la grille, pas la disposition : sa place reste
            // la sienne.
            [dockPlaces, hiddenPlaces].forEach(function (away) {
                Object.keys(away).forEach(function (key) {
                    var p = away[key];
                    out[key] = { x: p.x, y: p.y, w: p.w, h: p.h, zone: p.grid === panel ? 'panel' : 'grid' };
                });
            });
            return out;
        }

        // La disposition part au serveur une fois le geste posé (un glisser émet plusieurs
        // `change`) ; refusée ou injoignable, elle reste dans ce navigateur, en secours.
        var persistTimer = null;
        function persistLayout() {
            clearTimeout(persistTimer);
            persistTimer = setTimeout(function () {
                if (!opts.url) { writeLayout(opts.key, layout.slots); return; }
                App.csrfFetch(opts.url, App.csrfToken(), {
                    method: 'POST', headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ slots: layout.slots, frozen: !!layout.frozen,
                                           docked: layout.docked || {},
                                           stacks: layout.stacks || {} }),
                }).then(App.jsonOrExplain).then(function (res) {
                    if (res && res.error) throw new Error(res.error);
                    writeLayout(opts.key, null);
                }).catch(function () { writeLayout(opts.key, layout.slots); });
            }, 300);
        }
        if (migrated) persistLayout();

        /** Sur une colonne (téléphone), la grille n'est qu'un empilement : rien ne se garde. Sans
         *  grille (le volet seul), c'est la largeur de la fenêtre qui le dit. */
        function onFullGrid() {
            return grid ? grid.getColumn() === COLUMNS : global.innerWidth >= NARROW;
        }

        // Le montage des briques ajoute leurs éléments aux zones (`added`) : ce n'est pas un geste.
        var resetting = false, building = false;
        function resetLayout() {
            if (layout.frozen || !onFullGrid()) return;
            layout.slots = null;                 // la disposition DÉCLARÉE, qui suit la page
            resetting = true;
            restoreHidden();                     // un panneau retiré se range aussi, puis se retire
            undockAll();                         // chacun reprend place dans la grille, pour s'y ranger
            dissolveAll();                       // une pile est un geste de disposition : défaite
            zones.forEach(function (g) { g.batchUpdate(); });
            slots.forEach(function (slot) {
                var m = frames[slot.id];
                if (!m) return;
                var zone = zoneOf(slot, slot), target = gridOf(zone), at = placeIn(zone, slot);
                var from = m.el.gridstackNode && m.el.gridstackNode.grid;
                if (from && from !== target) {
                    // Rendue à sa zone déclarée : le même élément change de grille, la brique
                    // montée ne se remonte pas.
                    from.removeWidget(m.el, false, false);
                    target.el.appendChild(m.el);
                    at.id = slot.id;
                    target.makeWidget(m.el, at);
                } else {
                    target.update(m.el, at);
                }
            });
            zones.forEach(function (g) { g.batchUpdate(false); });
            resetting = false;
            syncLayoutTools();
            syncShown();
            applyDocks();
            persistLayout();
        }
        /** Tous les panneaux retirés rendus à leur zone (avant de la réordonner). */
        function restoreHidden() {
            Object.keys(hiddenPlaces).forEach(function (key) {
                var el = containerEl(key), place = hiddenPlaces[key], at = fit(place, place.grid);
                delete hiddenPlaces[key];
                at.id = key;
                place.grid.el.appendChild(el);
                place.grid.makeWidget(el, at);
            });
        }

        /** FIGER : la grille ne bouge plus, les panneaux perdent leur habit d'atelier (CSS
         *  `.is-frozen`) ; le titre d'un panneau qui porte des outils reste, en bande discrète. */
        function setFrozen(on) {
            layout.frozen = !!on;
            zones.forEach(function (g) { g.setStatic(layout.frozen); });
            showFrozen(layout.frozen);
            applyDocks();                        // rendue modifiable, un panneau épinglé reste immobile
            persistLayout();
            emit('layout', { frozen: layout.frozen });
            emit('resize');
        }

        // Un geste posé dans l'une des deux zones — y compris une brique glissée de l'une à
        // l'autre (`added` / `removed`) — garde la disposition ENTIÈRE, les deux zones ensemble.
        // ⚠ Nommé `layoutChanged` : dans le noyau des surfaces, où ce code a vécu, `changed` est le
        // geste de VALEUR — une seconde déclaration le remplaçait dans toute la fonction (vécu le
        // 2026-10-21 : la parité de l'éditeur l'a vu).
        function layoutChanged() {
            if (resetting || building || !onFullGrid()) return;
            layout.slots = layoutNow();
            persistLayout();
        }
        zones.forEach(function (g) {
            g.on('change added removed', layoutChanged);
            g.on('resizestop', function () { emit('resize'); });
            g.on('added', function () { emit('resize'); });      // la brique a changé de largeur
        });
        // Une brique venue du volet arrive dans la grille avec la largeur de la colonne (1) : on lui
        // donne celle de la colonne de droite d'une surface (un tiers), qu'on retaille ensuite.
        var FROM_PANEL_W = Math.round(COLUMNS / 3);
        if (panel && grid) {
            panel.on('removed', function (e, items) {
                (items || []).forEach(function (n) { if (n.el) n.el.dataset.fromPanel = '1'; });
            });
            grid.on('added', function (e, items) {
                if (building || resetting) return;
                (items || []).forEach(function (n) {
                    if (!n.el || !n.el.dataset.fromPanel) return;
                    delete n.el.dataset.fromPanel;
                    if (n.w < FROM_PANEL_W) grid.update(n.el, { w: FROM_PANEL_W });
                });
            });
        }
        global.addEventListener('resize', function () { emit('resize'); });

        return {
            /** Pose les cadres, monte les briques (`opts.mount`), reforme piles et épinglages. */
            build: function () {
                building = true;
                try { buildAll(); }
                finally { building = false; }
                syncLayoutTools();
                applyDocks();
            },
            /** La disposition est-elle figée ? Une préférence du LECTEUR : vaut aussi en lecture seule. */
            frozen: function () { return !!layout.frozen; },
            setFrozen: setFrozen,
            /** « Disposition par défaut » : celle que la page déclare (l'épinglage reste). */
            reset: resetLayout,
            /** Les gestes de disposition, pour l'aide de la page. */
            help: LAYOUT_HELP,
            /** Le contenu de la brique `id` s'est retiré ou est revenu : son panneau suit. */
            setShown: setShown,
        };
    }

    global.WamaBrickLayout = { create: create, docks: Docks, scaleWeights: scaleWeights };
})(window);
