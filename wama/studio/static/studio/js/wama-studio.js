/*
 * WamaStudio — canvas du studio : éditeur en graphe d'un PIPELINE (corrigé le 2026-09-15).
 * Nœuds de tous types (métadonnées + ports typés via /studio/api/nodes/) : entrées
 * (Texte / Médiathèque / Jeu de données), apps, fonctions du catalogue (`function:<clé>`,
 * depuis le 2026-09-09) et sortie. Ports typés : ENTRÉE = input_types (vert), SORTIE =
 * output_types (bleu). Une connexion n'est valide que si output_types(source) ∩
 * input_types(cible) ≠ ∅ → « typage par connexion ».
 * Persistance (pipelines sauvegardés) et EXÉCUTION RÉELLE (moteur topologique côté serveur,
 * `studio/tasks.py`) livrées depuis le 2026-07-11 — l'ancienne mention « pas d'exécution »
 * et « la file = méta-app dégénérée à 1 app » sont PÉRIMÉES.
 *
 * Volontairement minimal et autonome (vanilla + SVG). Décidé le 2026-09-15 (vocabulaire
 * process / pipeline / nœud / card → WAMA_APP_GENERATION_ROUTE.md §10.6) — ✅ livré le 03/10 :
 * « Catalogue » en sections repliables avec les pipelines, ajout par glisser-déposer (le clic
 * retiré le 2026-10-07), six états communs ; ⏳ reste le type de nœud `pipeline`.
 * Navigation du canvas (2026-10-07) : glisser le fond = défiler, molette = zoomer.
 */
(function (global) {
    'use strict';

    var canvas, world, svg, hint, paletteList, zoomLabel;
    var apps = {};
    var savedPipelines = [], declaredPipelines = [];   // la section « Pipelines » du catalogue

    // Les nœuds INTÉGRÉS (cards d'entrée et de sortie) arrivent avec le catalogue
    // (`/studio/api/nodes/`, `kind` = 'source' | 'sink'), déclarés par leur monde au registre
    // commun (ROUTE §10.6 3.3bis, R2 — 2026-10-18). Ce fichier les écrivait (`BUILTINS`), avec
    // un « Batch de prompts » que le serveur ne savait pas exécuter, et recopiait la taxonomie
    // des types de donnée dans le jeu de données et la sortie.
    function isBuiltin(a) { return a && (a.kind === 'source' || a.kind === 'sink'); }

    // (Les apps de montage / mixage-mastering restent en ROADMAP — voir STUDIO_VISION.md — et ne sont
    //  PAS exposées ici tant qu'elles ne sont pas réellement développées.)
    var nodes = [];           // {id, app, x, y, el}
    var links = [];           // {id, from, to, path}  (from/to = {nodeId, dot})
    var pending = null;       // {nodeId, dot, types, path}
    var seq = 0;
    var selected = null;      // id du nœud sélectionné (inspecteur)

    function el(tag, cls, html) {
        var e = document.createElement(tag);
        if (cls) e.className = cls;
        if (html != null) e.innerHTML = html;
        return e;
    }
    function svgEl(tag) { return document.createElementNS('http://www.w3.org/2000/svg', tag); }
    function inter(a, b) { return (a || []).some(function (t) { return (b || []).indexOf(t) !== -1; }); }

    // ── Vue : défilement et zoom du canvas (2026-10-07) ─────────────────────
    // Le canvas est une FENÊTRE sur le monde (#studioWorld) : `view` = translation (x, y) en px
    // écran + facteur k. Nœuds, liens et positions sérialisées restent en coordonnées du MONDE —
    // un graphe sauvé avant ce jour s'ouvre tel quel. Gestes (ceux de ComfyUI) : glisser le fond
    // ou bouton du milieu = défiler, molette = zoomer sous le curseur. La vue n'est PAS une
    // mutation du graphe : elle n'entre ni dans l'historique ni dans le brouillon, et se retient
    // à part, par navigateur.
    var view = { x: 0, y: 0, k: 1 };
    var VIEW_KEY = 'wama_studio_view';
    var ZOOM_MIN = 0.2, ZOOM_MAX = 2.5, GRID = 22;

    function applyView(remember) {
        world.style.transform = 'translate(' + view.x + 'px, ' + view.y + 'px) scale(' + view.k + ')';
        // La grille de points suit le monde, sinon le fond « glisse » sous le graphe.
        canvas.style.backgroundSize = (GRID * view.k) + 'px ' + (GRID * view.k) + 'px';
        canvas.style.backgroundPosition = view.x + 'px ' + view.y + 'px';
        if (zoomLabel) zoomLabel.textContent = Math.round(view.k * 100) + ' %';
        if (remember !== false) {
            try { localStorage.setItem(VIEW_KEY, JSON.stringify(view)); } catch (e) { /* non bloquant */ }
        }
    }
    function restoreView() {
        try {
            var v = JSON.parse(localStorage.getItem(VIEW_KEY) || 'null');
            if (v && isFinite(v.x) && isFinite(v.y) && isFinite(v.k) && v.k > 0) {
                view = { x: v.x, y: v.y, k: Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, v.k)) };
                applyView(false);
                return true;
            }
        } catch (e) { /* idem */ }
        return false;
    }
    // Point écran (clientX/Y) → coordonnées du monde.
    function toWorld(clientX, clientY) {
        var c = canvas.getBoundingClientRect();
        return { x: (clientX - c.left - view.x) / view.k, y: (clientY - c.top - view.y) / view.k };
    }
    // Zoome au facteur k en gardant FIXE le point (cx, cy) du canvas (le curseur, ou le centre).
    function zoomAt(k, cx, cy) {
        k = Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, k));
        if (cx == null) { cx = canvas.clientWidth / 2; cy = canvas.clientHeight / 2; }
        var wx = (cx - view.x) / view.k, wy = (cy - view.y) / view.k;
        view = { x: cx - wx * k, y: cy - wy * k, k: k };
        applyView();
    }
    // Cadre tout le graphe dans la fenêtre (sans jamais grossir au-delà de 100 %).
    function fitView() {
        var cw = canvas.clientWidth, ch = canvas.clientHeight;
        if (!cw || !ch) return;
        if (!nodes.length) { view = { x: 0, y: 0, k: 1 }; applyView(); return; }
        var x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
        nodes.forEach(function (n) {
            x0 = Math.min(x0, n.x); y0 = Math.min(y0, n.y);
            x1 = Math.max(x1, n.x + n.el.offsetWidth); y1 = Math.max(y1, n.y + n.el.offsetHeight);
        });
        var pad = 40;
        var k = Math.min(1, (cw - 2 * pad) / Math.max(1, x1 - x0), (ch - 2 * pad) / Math.max(1, y1 - y0));
        k = Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, k));
        view = { x: (cw - (x1 - x0) * k) / 2 - x0 * k, y: (ch - (y1 - y0) * k) / 2 - y0 * k, k: k };
        applyView();
    }

    // Centre d'un point-port en coordonnées du monde, lu dans la MISE EN PAGE (offsets) et non à
    // l'écran : un écart d'arrondi d'1 px écran, divisé par le zoom, valait 4,5 unités à 22 % et
    // restait figé dans le tracé (mesuré au navigateur). Les offsets ignorent aussi les
    // transformations — dont le `scale` d'un port survolé.
    function dotCenter(dot) {
        var x = dot.offsetWidth / 2, y = dot.offsetHeight / 2, e = dot;
        while (e && e !== world) {
            x += e.offsetLeft; y += e.offsetTop;
            e = e.offsetParent;
            if (e && e !== world) { x += e.clientLeft; y += e.clientTop; }   // bordure du parent
        }
        return { x: x, y: y };
    }
    function pathD(p1, p2) {
        var dx = Math.max(40, Math.abs(p2.x - p1.x) / 2);
        return 'M ' + p1.x + ' ' + p1.y + ' C ' + (p1.x + dx) + ' ' + p1.y
            + ' ' + (p2.x - dx) + ' ' + p2.y + ' ' + p2.x + ' ' + p2.y;
    }

    // ── Catalogue (palette) ──────────────────────────────────────────────
    // « Catalogue », en SECTIONS repliables (ROUTE §10.6 5.4, 2026-10-03) : Entrées · Sorties ·
    // Pipelines (les miens + ceux DÉCLARÉS par les apps, qui n'y figuraient pas : ils passaient
    // par le seul sélecteur de la barre) · Apps · Fonctions par catégorie. Pas « Library » : le
    // mot désigne déjà les paquets pip. Un nœud se GLISSE à l'endroit voulu du canvas (drag
    // natif HTML5, type MIME propre) — et SEULEMENT ainsi depuis le 2026-10-07 : la décision du
    // 15/09 disait « glisser-déposer AU LIEU du clic » (STUDIO_VISION, ROUTE §10.6 5.4), le clic
    // qui empilait avait survécu à la livraison du 03/10. Un pipeline, lui, s'OUVRE au clic —
    // c'est un document, pas un nœud — par le même chemin que le sélecteur.
    // Le repli de chaque section est retenu par navigateur (localStorage, tolérant).
    var PALETTE_MIME = 'text/wama-node';

    function paletteItem(id, a, onPick) {
        var item = el('div', 'studio-pal-item');
        item.style.setProperty('--app-c', a.color || '#6ea8fe');
        item.innerHTML = '<i class="' + (a.icon || 'fas fa-cube') + '"></i><span>' + a.label + '</span>';
        // Un process RATTACHÉ à une app porte son app en ÉTIQUETTE (position commune du
        // 2026-10-05, ROUTE §10.6) : la catégorie reste l'axe de la palette, l'app une propriété.
        if (a.kind === 'function' && a.binding === 'app' && a.app) {
            var tag = el('small', 'studio-pal-app', appLabel(a.app));
            item.appendChild(tag);
            item.dataset.fnApp = a.app;
        }
        if (onPick) {
            item.title = a.title || a.label;
            item.addEventListener('click', function () { onPick(id); });
            return item;
        }
        item.title = a.title || ('Glisser sur le canvas pour ajouter « ' + a.label + ' »');
        item.draggable = true;
        item.addEventListener('dragstart', function (e) {
            e.dataTransfer.setData(PALETTE_MIME, id);
            e.dataTransfer.effectAllowed = 'copy';
        });
        // Lâché hors du canvas : le canvas ne voit ni `drop` ni toujours `dragleave`.
        item.addEventListener('dragend', function () { if (canvas) canvas.classList.remove('is-drop-target'); });
        return item;
    }

    function paletteSection(key, label, count) {
        var section = el('details', 'studio-pal-section');
        section.dataset.section = key;
        var remembered = null;
        try { remembered = localStorage.getItem('wama_studio_palette_' + key); } catch (e) {}
        section.open = remembered === null ? true : remembered === 'open';
        section.appendChild(el('summary', 'studio-pal-group',
                               label + (count != null ? ' (' + count + ')' : '')));
        section.addEventListener('toggle', function () {
            try { localStorage.setItem('wama_studio_palette_' + key, section.open ? 'open' : 'closed'); } catch (e) {}
        });
        return section;
    }

    function renderPalette() {
        if (!paletteList) return;
        paletteList.innerHTML = '';
        var sources = Object.keys(apps).filter(function (id) { return apps[id].kind === 'source'; });
        var sinks = Object.keys(apps).filter(function (id) { return apps[id].kind === 'sink'; });
        var appIds = Object.keys(apps).filter(function (id) {
            return apps[id].kind !== 'function' && !isBuiltin(apps[id]);
        });
        var fnIds = Object.keys(apps).filter(function (id) { return apps[id].kind === 'function'; });

        var inputs = paletteSection('inputs', 'Entrées');
        sources.forEach(function (id) { inputs.appendChild(paletteItem(id, apps[id])); });
        paletteList.appendChild(inputs);

        var outputs = paletteSection('outputs', 'Sorties');
        sinks.forEach(function (id) { outputs.appendChild(paletteItem(id, apps[id])); });
        paletteList.appendChild(outputs);

        var pipes = savedPipelines.map(function (p) {
            return { value: String(p.id), label: p.name, icon: 'fas fa-diagram-project', color: '#f7c46c',
                     title: 'Ouvrir « ' + p.name + ' » (' + p.nodes + ' nœuds · ' + p.updated_at + ')' };
        }).concat(declaredPipelines.map(function (p) {
            return { value: 'declared:' + p.key, label: p.name, icon: 'fas fa-diagram-project', color: '#9ad0ec',
                     title: 'Ouvrir le pipeline déclaré par l\'app « ' + p.name
                            + ' » — le sauvegarder en fait une copie personnelle' };
        }));
        var pipelines = paletteSection('pipelines', 'Pipelines', pipes.length);
        if (!pipes.length) pipelines.appendChild(el('div', 'studio-pal-empty', 'Aucun pipeline sauvegardé.'));
        pipes.forEach(function (p) { pipelines.appendChild(paletteItem(p.value, p, openPipeline)); });
        paletteList.appendChild(pipelines);

        var appsSection = paletteSection('apps', 'Apps', appIds.length);
        appIds.forEach(function (id) { appsSection.appendChild(paletteItem(id, apps[id])); });
        paletteList.appendChild(appsSection);

        if (fnIds.length) {
            var functions = paletteSection('functions', 'Fonctions', fnIds.length);
            var filter = functionAppFilter(fnIds);
            if (filter) functions.appendChild(filter);
            var byCategory = {};
            fnIds.forEach(function (id) {
                var c = apps[id].category || 'autres';
                (byCategory[c] = byCategory[c] || []).push(id);
            });
            Object.keys(byCategory).sort().forEach(function (c) {
                var head = el('div', 'studio-pal-subgroup', c);
                head.dataset.subgroup = c;
                functions.appendChild(head);
                byCategory[c].forEach(function (id) {
                    var item = paletteItem(id, apps[id]);
                    item.dataset.subgroup = c;
                    functions.appendChild(item);
                });
            });
            paletteList.appendChild(functions);
            applyFunctionFilter(functions);
        }
    }

    // Libellé d'une app pour l'étiquette d'un process : celui de son nœud d'app s'il existe
    // (le catalogue des apps), sinon sa clé.
    function appLabel(key) {
        return (apps[key] && apps[key].label) || key;
    }

    // FILTRE par app des fonctions (2026-10-05) : « toutes », les fonctions PURES (calcul, sans
    // app), puis une entrée par app qui a des process au catalogue. Retenu par navigateur.
    var FN_FILTER_KEY = 'wama_studio_palette_fn_app';
    function functionAppFilter(fnIds) {
        var owners = {};
        fnIds.forEach(function (id) {
            var a = apps[id];
            if (a.binding === 'app' && a.app) owners[a.app] = appLabel(a.app);
        });
        var keys = Object.keys(owners).sort(function (x, y) { return owners[x].localeCompare(owners[y]); });
        if (!keys.length) return null;
        var select = el('select', 'form-select form-select-sm studio-pal-filter');
        select.title = 'Filtrer les fonctions par app';
        [['', 'Toutes les fonctions'], ['__pure__', 'Calcul (sans app)']]
            .concat(keys.map(function (k) { return [k, 'App : ' + owners[k]]; }))
            .forEach(function (o) {
                var opt = el('option', null, o[1]);
                opt.value = o[0];
                select.appendChild(opt);
            });
        var remembered = '';
        try { remembered = localStorage.getItem(FN_FILTER_KEY) || ''; } catch (e) {}
        select.value = Array.prototype.some.call(select.options, function (o) { return o.value === remembered; })
            ? remembered : '';
        select.addEventListener('change', function () {
            try { localStorage.setItem(FN_FILTER_KEY, select.value); } catch (e) {}
            applyFunctionFilter(select.closest('.studio-pal-section'));
        });
        return select;
    }

    function applyFunctionFilter(section) {
        if (!section) return;
        var select = section.querySelector('.studio-pal-filter');
        var wanted = select ? select.value : '';
        var shown = {};
        section.querySelectorAll('.studio-pal-item').forEach(function (item) {
            var owner = item.dataset.fnApp || '';
            var keep = !wanted || (wanted === '__pure__' ? !owner : owner === wanted);
            item.style.display = keep ? '' : 'none';
            if (keep) shown[item.dataset.subgroup] = true;
        });
        section.querySelectorAll('.studio-pal-subgroup').forEach(function (head) {
            head.style.display = shown[head.dataset.subgroup] ? '' : 'none';
        });
    }

    // ── Nœud ─────────────────────────────────────────────────────────────
    function addNode(appId, opts) {
        opts = opts || {};
        // Un nœud que la palette n'offre pas n'existe que s'il vient d'un graphe ouvert (`loadGraph`
        // a posé sa description dans `unavailable`) : on ne le pose jamais depuis la palette.
        var a = apps[appId] || unavailable[appId];
        if (!a) return null;
        if (hint) hint.style.display = 'none';
        var id = opts.id || ('n' + (++seq));
        var m = /^n(\d+)$/.exec(id);
        if (m) seq = Math.max(seq, parseInt(m[1], 10));
        // Sans position (graphe qui n'en porte pas) : empilé dans le coin VISIBLE de la fenêtre,
        // où qu'on ait défilé. Les graphes sauvés et `body_to_graph` en portent toujours une.
        var stack = (nodes.length % 5) * 30;
        var node = { id: id, app: appId, params: opts.params || {},
                     x: (opts.x != null) ? opts.x : (40 - view.x) / view.k + stack,
                     y: (opts.y != null) ? opts.y : (40 - view.y) / view.k + stack };
        // La DÉCLARATION du process d'un pipeline déclaré (`process`, ROUTE §10.6 3.2) voyage avec
        // le nœud, à part de ses réglages : le canvas la garde telle quelle, ne l'édite jamais.
        if (opts.process) node.process = opts.process;

        var box = el('div', 'studio-node' + (a.planned ? ' is-planned' : '')
            + (a.unavailable ? ' is-unavailable' : ''));
        box.style.left = node.x + 'px';
        box.style.top = node.y + 'px';
        box.style.setProperty('--app-c', a.color || '#6ea8fe');
        box.dataset.node = id;

        var badge = a.planned ? '<span class="studio-node-badge" title="App planifiée — specs à venir">à venir</span>'
            : a.unavailable ? '<span class="studio-node-badge" title="' + esc(a.description) + '">indisponible</span>' : '';
        var head = el('div', 'studio-node-head',
            '<i class="app-ico ' + (a.icon || 'fas fa-cube') + '"></i><span>' + esc(a.label) + '</span>' + badge
            + '<span class="studio-node-del" title="Supprimer">&times;</span>');
        box.appendChild(head);
        // La RAISON, sur le nœud lui-même (décision du 2026-10-19) — lue du serveur par
        // `warnUnavailable`, qui remplace ce texte d'attente dès qu'elle arrive.
        if (a.unavailable) box.appendChild(el('div', 'studio-node-reason', esc(unavailableLabel(a))));

        var ports = el('div', 'studio-ports');
        var inCol = el('div', 'studio-port-col in');
        var outCol = el('div', 'studio-port-col out');
        // Entrées typées (travail / prompt / référence) — plusieurs ports possibles.
        (a.inputs || []).forEach(function (p) {
            inCol.appendChild(portEl('in', p.types, p.label, p.group || 'travail', p.id, p.description));
        });
        // Sortie : types produits (output === false → nœud TERMINAL, pas de port).
        if (a.output !== false) {
            var out = a.output || { label: 'Sortie', types: [] };
            outCol.appendChild(portEl('out', out.types, out.label, 'out', out.id, out.description));
        }
        ports.appendChild(inCol);
        ports.appendChild(outCol);
        box.appendChild(ports);

        world.appendChild(box);
        node.el = box;
        nodes.push(node);

        head.querySelector('.studio-node-del').addEventListener('click', function (e) {
            e.stopPropagation(); removeNode(id);
        });
        makeDraggable(node, head);
        selectNode(id);   // sélectionne le nœud fraîchement ajouté
        persistDraft();
        return node;
    }

    function portEl(side, types, label, group, portId, description) {
        var p = el('div', 'studio-port ' + side);
        var dot = el('span', 'dot');
        dot.dataset.side = side;
        dot.dataset.group = group || '';
        // `port` = l'ID du port (travail/prompt/référence pour une app, la CLÉ du port pour
        // une fonction) : c'est ce que `to_port` sérialise depuis le 2026-09-09 — deux ports
        // d'une fonction partagent souvent le rôle `travail`, le rôle seul ne les distingue pas.
        dot.dataset.port = portId || group || '';
        dot.dataset.types = (types || []).join(',');
        var txt = label ? label : ((types && types.length) ? types.join(' · ') : '—');
        p.appendChild(dot);
        p.appendChild(el('span', 'types', esc(txt)));   // un port peut venir d'un graphe partagé
        // Infobulle : la DESCRIPTION déclarée du port quand il y en a une (fonctions), sinon le
        // libellé. Elle dit ce que le créneau attend — le nom du port et son type ne le disent
        // pas (« track · geo_track » ne prévient pas qu'il faut lat/lon).
        var quoi = (label ? label + ' — ' : '') + ((types && types.length) ? types.join(', ') : '—');
        p.title = description ? quoi + '\n' + description : quoi;
        dot.addEventListener('click', function (e) { e.stopPropagation(); onDot(dot); });
        return p;
    }

    function nodeOf(dot) {
        var box = dot.closest('.studio-node');
        return box ? box.dataset.node : null;
    }

    // ── Connexions ────────────────────────────────────────────────────────
    function onDot(dot) {
        var side = dot.dataset.side;
        if (!pending) {
            if (side !== 'out') return;            // une connexion part d'une SORTIE
            armPending(dot);
        } else {
            if (side !== 'in') { cancelPending(); return; }
            var srcTypes = pending.types;
            var dstTypes = (dot.dataset.types || '').split(',').filter(Boolean);
            if (nodeOf(dot) === pending.nodeId) { cancelPending(); return; }   // pas de boucle sur soi
            if (!inter(srcTypes, dstTypes)) { flashIncompatible(dot); return; } // typage par connexion
            createLink(pending.dot, dot);
            cancelPending();
        }
    }

    function armPending(dot) {
        pending = {
            nodeId: nodeOf(dot), dot: dot,
            types: (dot.dataset.types || '').split(',').filter(Boolean),
            path: svgEl('path'),
        };
        dot.classList.add('is-armed');
        pending.path.setAttribute('class', 'studio-link pending');
        svg.appendChild(pending.path);
        markCompatibility(true);
    }
    function cancelPending() {
        if (!pending) return;
        pending.dot.classList.remove('is-armed');
        if (pending.path && pending.path.parentNode) pending.path.parentNode.removeChild(pending.path);
        markCompatibility(false);
        pending = null;
    }
    function markCompatibility(on) {
        canvas.querySelectorAll('.studio-port.in .dot').forEach(function (d) {
            d.classList.remove('compatible', 'incompatible');
            if (!on) return;
            if (nodeOf(d) === pending.nodeId) return;
            var t = (d.dataset.types || '').split(',').filter(Boolean);
            d.classList.add(inter(pending.types, t) ? 'compatible' : 'incompatible');
        });
    }
    function flashIncompatible(dot) {
        dot.classList.add('incompatible');
        setTimeout(function () { if (pending) markCompatibility(true); else dot.classList.remove('incompatible'); }, 350);
    }

    function createLink(outDot, inDot) {
        var path = svgEl('path');
        path.setAttribute('class', 'studio-link');
        var link = { id: 'l' + (++seq), from: { dot: outDot }, to: { dot: inDot }, path: path };
        path.setAttribute('id', 'linkpath-' + link.id);   // référencé par <mpath> (animation de flux)
        svg.appendChild(path);
        path.addEventListener('click', function () { removeLink(link.id); });
        links.push(link);
        updateLinks();
        updateInspector();   // rafraîchit les compteurs de connexions
        persistDraft();
    }

    function updateLinks() {
        links.forEach(function (l) {
            l.path.setAttribute('d', pathD(dotCenter(l.from.dot), dotCenter(l.to.dot)));
        });
    }

    function removeLink(id) {
        links = links.filter(function (l) {
            if (l.id !== id) return true;
            setLinkFlowing(l, false);
            if (l.path.parentNode) l.path.parentNode.removeChild(l.path);
            return false;
        });
        updateInspector();
        persistDraft();
    }
    function removeNode(id) {
        // retirer les liens touchant ce nœud
        links = links.filter(function (l) {
            if (nodeOf(l.from.dot) === id || nodeOf(l.to.dot) === id) {
                if (l.path.parentNode) l.path.parentNode.removeChild(l.path);
                return false;
            }
            return true;
        });
        nodes = nodes.filter(function (n) {
            if (n.id !== id) return true;
            if (n.el && n.el.parentNode) n.el.parentNode.removeChild(n.el);
            return false;
        });
        if (!nodes.length && hint) hint.style.display = '';
        if (selected === id) { selected = null; }
        updateInspector();
        persistDraft();
    }

    // ── Inspecteur (volet droit, généré par WamaDetails) ──────────────────
    function metaOf(node) { return apps[node.app] || unavailable[node.app] || {}; }
    function countLinks(nodeId, side) {
        return links.filter(function (l) { return nodeOf(l[side].dot) === nodeId; }).length;
    }
    function typeBadge(a) {
        if (a.planned) return '<span class="badge bg-warning text-dark">à venir</span>';
        if (a.unavailable) return '<span class="badge bg-secondary">' + esc(unavailableLabel(a)) + '</span>';
        if (a.kind === 'source') return '<span class="badge bg-success">entrée</span>';
        if (a.kind === 'sink') return '<span class="badge bg-success">sortie</span>';
        if (a.kind === 'function') return '<span class="badge bg-info text-dark">fonction · ' + (a.binding || 'pure') + '</span>';
        return '<span class="badge bg-primary">app</span>';
    }
    function selectNode(id) {
        selected = id;
        canvas.querySelectorAll('.studio-node').forEach(function (b) {
            b.classList.toggle('is-selected', b.dataset.node === id);
        });
        updateInspector();
    }
    function deselect() {
        selected = null;
        canvas.querySelectorAll('.studio-node.is-selected').forEach(function (b) { b.classList.remove('is-selected'); });
        updateInspector();
    }
    function updateInspector() {
        var body = document.getElementById('studioInspectorBody');
        var actionsHost = document.getElementById('studioInspectorActions');
        if (!body) {
            // Hôte disparu = un autre script a réécrit le volet droit (interférence) —
            // on le RECRÉE dans le conteneur commun plutôt que d'échouer en silence.
            var host = document.getElementById('global-settings-container');
            if (global.console && console.warn) {
                console.warn('[WamaStudio] #studioInspectorBody absent — recréé', !!host);
            }
            if (!host) return;
            body = document.createElement('div');
            body.id = 'studioInspectorBody';
            body.className = 'text-muted small';
            host.appendChild(body);
        }
        var node = nodes.find(function (n) { return n.id === selected; });
        if (!node || !global.WamaDetails) {
            if (!global.WamaDetails && global.console && console.warn) {
                console.warn('[WamaStudio] WamaDetails indisponible (wama-inspector-autofill.js non chargé ?)');
            }
            body.innerHTML = '<span class="text-muted small">Sélectionnez un nœud pour voir ses détails.</span>';
            if (actionsHost) actionsHost.innerHTML = '';
            return;
        }
        var a = metaOf(node);
        var data = { label: a.label, app: node.app, description: a.description || '' };
        var schema = [
            { badges: function () { return [typeBadge(a)]; } },
            { description: function (d) { return d.description; } },
            { section: a.label || node.app, rows: [{ k: 'Identifiant', get: function () { return node.app; } }] },
            { section: 'Entrées', rows: (a.inputs && a.inputs.length)
                ? a.inputs.map(function (p) { return { k: p.label || p.id, get: function () { return (p.types || []).join(' · ') || '—'; } }; })
                : [{ k: '—', get: function () { return 'aucune'; } }] },
            { section: 'Sortie', rows: [{ k: (a.output && a.output.label) || 'Sortie',
                get: function () { return ((a.output && a.output.types) || []).join(' · ') || '—'; } }] },
            { section: 'Connexions', rows: [
                { k: 'Entrantes', get: function () { return countLinks(node.id, 'to'); } },
                { k: 'Sortantes', get: function () { return countLinks(node.id, 'from'); } },
            ] },
        ];
        try {
            body.innerHTML = WamaDetails.renderSections(data, schema);
            mountNodeSettings(body, node);
            var acts = WamaDetails.renderActions(data, [
                { label: 'Supprimer le nœud', icon: 'fas fa-trash', cls: 'btn btn-sm btn-outline-danger w-100',
                  onClick: function () { removeNode(node.id); } },
            ]);
            if (actionsHost) { actionsHost.innerHTML = acts.html; if (acts.wire) acts.wire(actionsHost); }
        } catch (err) {
            // JAMAIS avaler : message visible + trace console (recadrage 2026-07-15)
            body.innerHTML = '<span class="text-danger small">Inspecteur en erreur : '
                + (err && err.message ? err.message : err) + '</span>';
            if (actionsHost) actionsHost.innerHTML = '';
            if (global.console && console.error) console.error('[WamaStudio] inspecteur', err);
        }
    }

    // ── Réglages du nœud : le rendu COMMUN (`WamaParams`), depuis le schéma `Param` du nœud ──
    // ROUTE §10.6 point 3.3bis, marche R1 (2026-10-12). Un nœud app, fonction ou intégré expose
    // ses réglages sous la forme que rendent la modale ⚙ d'une card et le volet
    // (`studio/services/node_params.py`) : mêmes champs, mêmes bornes, mêmes conditions, mêmes
    // sources d'options. Ce fichier avait son PROPRE rendu (`renderNodeParams`, 2026-07-11 →
    // 10-12), qui faisait d'un curseur un champ texte et d'un interrupteur un select Oui/Non, et
    // perdait conditions, groupes, aides et bornes — retiré. Contexte `item` : un nœud est un
    // élément, comme celui que règle la modale ⚙.
    // Les schémas arrivent AVEC le catalogue (`/studio/api/nodes/`, clé `schemas` — R2,
    // 2026-10-18) : une route à part arrivait 10 à 15 s plus tard, et d'ici là l'inspecteur ne
    // montrait rien, sans dire pourquoi. Il dit désormais toujours où il en est
    // (`settingsState`) : en chargement, catalogue indisponible, ou nœud sans réglage.
    var nodeSchemas = {};   // nœud -> {params, groups}
    var settingsState = 'loading';   // 'loading' | 'ready' | 'error'

    // L'échappement COMMUN (`wama-app-base.js`, monté sur toutes les pages) — jamais un de plus.
    function esc(s) { return global.WamaApp.escapeHtml(s == null ? '' : String(s)); }
    function nodeTitle(id) {
        var n = nodes.find(function (x) { return x.id === id; });
        return n ? (metaOf(n).label || n.app) : id;
    }
    function typesText(types) {
        return (types || []).length ? types.join(' ou ') : 'inconnue';
    }
    // Les réglages du nœud rendus entre deux couches de ce qu'il reçoit : `context.defaults` (les
    // valeurs ACTUELLES de l'élément d'une étape, comme dans la ⚙ de la card) SOUS `node.params`
    // (ce que le nœud a décidé), `context.values` (nature, texte : FOURNI) AU-DESSUS — un champ
    // fourni par un lien ne se saisit pas, le lien gagne au lancement (`generic_runner.create`).
    // Rien de `context` n'entre dans `node.params` : seul un GESTE l'écrit (`sync`), et un champ
    // fourni est désactivé.
    function renderNodeSettings(host, received, schema, node, context) {
        var ctx = context || {};
        WamaParams.render(host, schema.params, {
            context: 'item', groups: schema.groups || [],
            values: Object.assign({}, ctx.defaults || {}, node.params || {}, ctx.values || {}) });
        var lines = [];
        var ports = metaOf(node).inputs || [];
        Object.keys(ctx.inputs || {}).forEach(function (port) {
            var i = ctx.inputs[port];
            var p = ports.find(function (x) { return x.id === port; });
            lines.push('<i class="fas fa-right-to-bracket me-1"></i>' + esc((p && p.label) || port)
                + ' : ' + esc(typesText(i.types)) + ' — de « ' + esc(nodeTitle(i.from)) + ' »');
        });
        received.innerHTML = lines.join('<br>');
        Object.keys(ctx.provided || {}).forEach(function (field) {
            var how = ctx.provided[field];
            var row = host.querySelector('[data-param-row="' + field + '"]');
            if (!row) return;   // porteur caché (nature) : dit plus haut, dans les entrées reçues
            row.querySelectorAll('input, select, textarea, button').forEach(function (c) { c.disabled = true; });
            var said = how.element != null
                ? 'Porté par l’élément n° ' + how.element
                : (how.at_run ? 'Fourni à l’exécution par « ' : 'Fourni par « ') + nodeTitle(how.node) + ' »';
            row.appendChild(el('div', 'studio-provided small text-body-secondary mt-1',
                '<i class="fas fa-link me-1"></i>' + esc(said)));
        });
    }

    function mountNodeSettings(body, node) {
        var schema = nodeSchemas[node.app];
        var wrap = el('div', 'studio-node-params mt-2 pt-2 border-top border-secondary');
        wrap.appendChild(el('div', 'small text-body-secondary mb-1',
            '<i class="fas fa-sliders-h me-1"></i>Paramètres d’exécution'));
        if (metaOf(node).unavailable) {
            // Ni schéma ni contexte pour un nœud indisponible : ses réglages sont GARDÉS tels quels
            // dans le graphe, sans être affichés — « pas de réglage » serait faux.
            wrap.appendChild(el('div', 'studio-node-params-state text-body-secondary small',
                'Réglages non affichés : nœud indisponible pour ce compte. Ils sont gardés tels quels.'));
            body.appendChild(wrap);
            return;
        }
        if (!schema || !schema.params || !schema.params.length) {
            var said = settingsState === 'loading'
                ? '<span class="text-body-secondary small"><i class="fas fa-spinner fa-spin me-1"></i>Chargement des réglages…</span>'
                : settingsState === 'error'
                    ? '<span class="text-danger small">Réglages indisponibles : le catalogue des nœuds n’a pas pu être chargé.</span>'
                    : '<span class="text-body-secondary small">Ce nœud n’a pas de réglage.</span>';
            wrap.appendChild(el('div', 'studio-node-params-state', said));
            body.appendChild(wrap);
            return;
        }
        if (!global.WamaParams) {
            // JAMAIS muet : un inspecteur sans réglages ne dirait pas pourquoi.
            wrap.appendChild(el('div', 'text-danger small',
                'Réglages indisponibles : wama-params.js n’est pas chargé sur cette page.'));
            body.appendChild(wrap);
            return;
        }
        var received = el('div', 'studio-node-received small text-body-secondary mb-1');
        wrap.appendChild(received);
        var host = el('div', 'wama-params');
        wrap.appendChild(host);
        // Dans le DOM AVANT le rendu : les sources d'options retrouvent leur select par id.
        body.appendChild(wrap);
        renderNodeSettings(host, received, schema, node, null);
        // Ce que REÇOIT le nœud — le graphe porteur de valeurs (2026-10-18, ROUTE §10.6 3.3bis
        // règle 5) : la nature de ce qui lui est branché, le texte d'une saisie, ce que porte
        // l'élément d'une étape. Calculé par le SERVEUR (`graph_flow.node_context`, le parcours du
        // graphe que lit aussi le diagnostic des liens) — jamais recopié ici. Une réponse arrivée
        // après qu'on a changé de nœud est ignorée.
        api('/studio/api/node-context/', {
            method: 'POST', body: JSON.stringify({ graph: serializeGraph(), node: node.id }),
        }).then(function (context) {
            if (selected !== node.id || !host.isConnected) return;
            renderNodeSettings(host, received, schema, node, context);
        }).catch(function (err) {
            received.innerHTML = '<span class="text-danger">Entrées du nœud indisponibles : '
                + esc(err && err.message ? err.message : String(err)) + '</span>';
        });
        // Le graphe n'enregistre que les DÉCISIONS de l'utilisateur (`isGesture`) : la recharge
        // des options d'un select émet aussi un `change`, qui n'est pas un réglage — l'enregistrer
        // remplirait l'historique d'annulation de crans vides à chaque ouverture de l'inspecteur.
        // Le nœud n'enregistre que les réglages DÉCIDÉS — celui que le geste vient de toucher —,
        // jamais l'instantané de tous les champs rendus (ROUTE §10.6 3.3bis, R2, 2026-10-18) :
        // un instantané figeait les DÉFAUTS de l'app au premier geste (un modèle par défaut, un
        // « auto » qui changent ensuite ne s'appliquaient plus jamais à ce nœud). Ce qui n'est pas
        // décidé reste à la cascade de l'app, comme dans la modale ⚙ d'une card. Les autres clés
        // des `params` sont gardées : un réglage déjà décidé, et — jusqu'à ce que la déclaration du
        // process ait sa propre clé — celle d'un pipeline déclaré (`degree`, `watched`…, relevé le
        // 2026-10-13). La ligne du réglage (`data-param-row`) nomme ce qui a été touché, y compris
        // pour un champ composé (le curseur d'intention écrit un champ caché du même nom).
        function decidedName(e) {
            var target = e.target;
            var row = target && target.closest ? target.closest('[data-param-row]') : null;
            if (row) return row.getAttribute('data-param-row');
            return target && target.getAttribute
                ? (target.getAttribute('name') || target.getAttribute('data-param')) : null;
        }
        function sync(e) {
            if (!WamaParams.isGesture(e)) return;
            var name = decidedName(e);
            var values = WamaParams.read(host);
            if (!name || !(name in values)) return;
            node.params = Object.assign({}, node.params || {});
            node.params[name] = values[name];
            // `true` = saisie : la rafale coalesce, sinon « bonjour » coûterait 7 crans.
            persistDraft(e.type === 'input');
        }
        host.addEventListener('input', sync);
        host.addEventListener('change', sync);
    }

    // ── Sérialisation / restauration du graphe ─────────────────────────────
    function serializeGraph() {
        return {
            nodes: nodes.map(function (n) {
                var out = { id: n.id, app: n.app, x: n.x, y: n.y, params: n.params || {} };
                if (n.process) out.process = n.process;
                return out;
            }),
            links: links.map(function (l) {
                return { from: nodeOf(l.from.dot), to: nodeOf(l.to.dot),
                         to_port: l.to.dot.dataset.port || l.to.dot.dataset.group || '' };
            }),
        };
    }

    function clearCanvas() {
        links.slice().forEach(function (l) { removeLink(l.id); });
        nodes.slice().forEach(function (n) { removeNode(n.id); });
    }

    // Un nœud que la palette du compte n'offre pas — app fermée, fonction disparue du catalogue,
    // jumelle d'autrui — est GARDÉ à l'ouverture (2026-10-19, `ROADMAP §16.11` piste 4) : il
    // disparaissait en silence avec ses liens, et enregistrer le pipeline sous le même nom
    // l'effaçait en base. Sa description se lit du GRAPHE seul (ses liens disent ses ports) ; il
    // n'est ni réglable ni lançable (le lancement le refuse en le nommant, `launch.launch_graph`).
    //
    // Sa RAISON — non accessible à ce compte, app non exécutable, inconnu de WAMA — s'affiche SUR
    // le nœud (décision de Fabien, 2026-10-19) : le serveur la donne par la règle du lancement
    // (`palette.unavailable_reason`, route `api/nodes/unavailable/`). Elle se garde par clé pour la
    // page : annuler / rétablir reconstruit le nœud sans la redemander.
    var unavailable = {};   // identifiant de palette -> description, posée par `loadGraph`
    var unavailableReasons = {};   // identifiant de palette -> {code, label, message} du serveur
    var UNAVAILABLE_TEXT = 'Ce nœud n’est pas disponible pour ce compte : inconnu de WAMA, ou app '
        + 'non ouverte à ce compte.';
    var KEPT_TEXT = 'Il est gardé tel quel (réglages et liens) ; le lancement le refuse tant qu’il '
        + 'est dans le graphe.';
    function unavailableText(reason) { return (reason ? reason.message : UNAVAILABLE_TEXT) + ' ' + KEPT_TEXT; }
    function unavailableLabel(a) { return a.reason ? a.reason.label : 'indisponible pour ce compte'; }
    function describeUnavailable(graph) {
        unavailable = {};
        var missing = [];
        (graph.nodes || []).forEach(function (sn) {
            if (!sn || !sn.app || apps[sn.app]) return;
            var a = unavailable[sn.app];
            if (!a) {
                var reason = unavailableReasons[sn.app] || null;
                a = unavailable[sn.app] = { label: sn.app, icon: 'fas fa-ban', unavailable: true,
                    reason: reason, description: unavailableText(reason), inputs: [], output: false };
                missing.push(sn.app);
            }
            (graph.links || []).forEach(function (sl) {
                if (sl.to === sn.id) {
                    var port = sl.to_port || 'travail';
                    if (!a.inputs.some(function (p) { return p.id === port; })) {
                        a.inputs.push({ id: port, group: port, label: port, types: [] });
                    }
                }
                if (sl.from === sn.id) a.output = { label: 'Sortie', types: [] };
            });
        });
        return missing;
    }

    // Rend la liste des nœuds INDISPONIBLES gardés (identifiants de palette) : l'appelant le dit.
    function loadGraph(graph) {
        clearCanvas();
        var missing = describeUnavailable(graph || {});
        var byId = {};
        (graph.nodes || []).forEach(function (sn) {
            var n = addNode(sn.app, sn);
            if (n) byId[sn.id] = n;
        });
        (graph.links || []).forEach(function (sl) {
            var from = byId[sl.from], to = byId[sl.to];
            if (!from || !to) return;
            var outDot = from.el.querySelector('.studio-port-col.out .dot');
            // Par ID de port d'abord ; par rôle ensuite (graphes sauvés avant le 2026-09-09,
            // où `to_port` portait le rôle) ; premier port sinon.
            // `CSS.escape` : le nom du port vient du graphe (partagé, peut-être) — un guillemet
            // y rendait le sélecteur invalide, et l'ouverture entière échouait.
            var port = sl.to_port ? CSS.escape(String(sl.to_port)) : '';
            var inDot = port
                ? (to.el.querySelector('.studio-port-col.in .dot[data-port="' + port + '"]')
                   || to.el.querySelector('.studio-port-col.in .dot[data-group="' + port + '"]'))
                : null;
            if (!inDot) inDot = to.el.querySelector('.studio-port-col.in .dot');
            if (outDot && inDot) createLink(outDot, inDot);
        });
        updateLinks();
        return missing;
    }
    // Pose les raisons reçues sur la description des nœuds gardés ET sur ceux du canevas.
    function explainUnavailable(reasons) {
        Object.keys(reasons || {}).forEach(function (key) {
            var reason = reasons[key];
            unavailableReasons[key] = reason;
            var a = unavailable[key];
            if (!a) return;
            a.reason = reason;
            a.description = unavailableText(reason);
            nodes.forEach(function (n) {
                if (n.app !== key || !n.el) return;
                var line = n.el.querySelector('.studio-node-reason');
                if (line) line.textContent = reason.label;
                var badge = n.el.querySelector('.studio-node-badge');
                if (badge) badge.title = a.description;
            });
        });
    }
    // Demande au serveur POURQUOI les nœuds gardés manquent, la pose sur eux, puis le dit. Sans
    // réponse, le nœud garde « indisponible pour ce compte » : le message part quand même.
    function warnUnavailable(missing) {
        if (!missing || !missing.length) return;
        var asked = unavailable;
        var query = missing.map(function (k) { return 'key=' + encodeURIComponent(k); }).join('&');
        api('/studio/api/nodes/unavailable/?' + query).then(function (d) {
            if (asked !== unavailable) return;   // un autre graphe s'est ouvert entre-temps
            explainUnavailable(d.reasons);
            updateInspector();
        })['catch'](function () { /* raison non lue : le texte d'attente reste */ }).then(function () {
            toast((missing.length > 1 ? missing.length + ' nœuds indisponibles' : 'Un nœud indisponible')
                + ' pour ce compte, gardés tels quels : ' + missing.map(function (k) {
                    var a = asked[k];
                    return '« ' + k + ' »' + (a && a.reason ? ' (' + a.reason.label + ')' : '');
                }).join(', ') + '. Le lancement les refuse tant qu’ils sont dans le graphe.', 'warning');
        });
    }

    // ── Historique annuler / rétablir — brique COMMUNE (common/js/wama-history.js) ──────
    //
    // Le studio avait DÉJÀ les trois pièces d'un historique et n'en gardait qu'un cran :
    // `serializeGraph()` (photographier), `loadGraph()` (restaurer) et un ENTONNOIR unique
    // (`persistDraft()`, appelé en fin des 9 opérations mutantes). Il n'y avait donc rien à
    // inventer — seulement à empiler ce qui était déjà écrasé à chaque fois.
    //
    // `commit()` et non `push()` : l'entonnoir marque APRÈS la mutation (cf. l'en-tête de la
    // brique). C'est ce qui évite de disperser 9 marquages dans ce fichier.
    var history = global.WamaHistory ? global.WamaHistory.create({
        snapshot: serializeGraph,
        restore: loadGraph,
        undoSelector: '.studio-undo', redoSelector: '.studio-redo',
        shortcuts: true,
        burstWindow: 900,   // les champs de PARAMÈTRES sont du texte : une frappe ≠ un cran
    }) : null;

    // ── Brouillon PERSISTANT (localStorage) : le travail en cours survit à la
    //    navigation entre apps, jusqu'à sauvegarde en pipeline ou « Vider le canvas ».
    var DRAFT_KEY = 'wama_studio_draft';

    function persistDraft(fromTyping) {
        // Un cran d'historique par mutation — la brique ignore l'appel pendant une
        // restauration (loadGraph → clearCanvas → removeNode → ici : ré-entrance).
        if (history) history.commit({ burst: !!fromTyping });
        try {
            var nameEl = document.getElementById('studioPipelineName');
            localStorage.setItem(DRAFT_KEY, JSON.stringify({
                graph: serializeGraph(),
                name: nameEl ? nameEl.value : '',
            }));
        } catch (e) { /* stockage privé/plein : non bloquant */ }
    }
    function clearDraft() {
        try { localStorage.removeItem(DRAFT_KEY); } catch (e) { /* idem */ }
    }
    function restoreDraft() {
        try {
            var raw = localStorage.getItem(DRAFT_KEY);
            if (!raw) return;
            var d = JSON.parse(raw);
            if (d && d.graph && d.graph.nodes && d.graph.nodes.length) {
                // Chargement programmatique : on arrive sur la page, il n'y a rien à annuler
                // AVANT. Sans `silence`, la restauration remplirait l'historique de son
                // propre travail (un cran par noeud construit).
                var missing = [];
                if (history) history.silence(function () { missing = loadGraph(d.graph); });
                else missing = loadGraph(d.graph);
                warnUnavailable(missing);
                var nameEl = document.getElementById('studioPipelineName');
                if (nameEl && d.name) nameEl.value = d.name;
                // On retrouve la vue laissée ; à défaut (1re visite), tout le graphe.
                if (!restoreView()) fitView();
            }
        } catch (e) {
            if (global.console && console.warn) console.warn('[WamaStudio] brouillon non restauré :', e && e.message ? e.message : e);
        }
    }

    // ── Persistance (StudioPipeline) ───────────────────────────────────────
    // Jeton CSRF : input caché (posé par {% csrf_token %} du volet) sinon cookie.
    function csrfToken() {
        var el = document.querySelector('[name=csrfmiddlewaretoken]');
        if (el && el.value) return el.value;
        var m = document.cookie.match(/csrftoken=([^;]+)/);
        return m ? m[1] : '';
    }
    function api(url, opts) {
        opts = opts || {};
        // credentials same-origin : garantit l'envoi du cookie de session + csrftoken.
        if (!opts.credentials) opts.credentials = 'same-origin';
        opts.headers = Object.assign({ 'Content-Type': 'application/json' },
            { 'X-CSRFToken': csrfToken() }, opts.headers || {});
        return fetch(url, opts).then(function (r) {
            // Réponse non-JSON (page d'erreur HTML 403/500) → message CLAIR, pas
            // « Unexpected token '<' » (la cause du bug d'enregistrement, 2026-07-15).
            var ct = r.headers.get('content-type') || '';
            if (ct.indexOf('application/json') === -1) {
                if (r.status === 403) throw new Error('Session expirée ou accès refusé (403) — rechargez la page.');
                throw new Error('Réponse inattendue du serveur (HTTP ' + r.status + ').');
            }
            return r.json().then(function (d) {
                if (!r.ok) throw new Error(d.error || ('HTTP ' + r.status));
                return d;
            });
        });
    }
    function toast(msg, kind) {
        if (window.WamaApp && WamaApp.toast) WamaApp.toast(msg, kind || 'info');
    }

    function refreshPipelineList() {
        var sel = document.getElementById('studioLoadSelect');
        if (!sel) return;
        Promise.all([
            api('/studio/api/pipelines/'),
            api('/studio/api/declared-pipelines/')['catch'](function () { return { pipelines: [] }; }),
        ]).then(function (res) {
            sel.innerHTML = '<option value="">Charger un pipeline…</option>';
            var mine = el('optgroup'); mine.label = 'Mes pipelines';
            res[0].pipelines.forEach(function (p) {
                var o = el('option');
                o.value = p.id;
                o.textContent = p.name + ' (' + p.nodes + ' nœuds · ' + p.updated_at + ')';
                mine.appendChild(o);
            });
            if (mine.children.length) sel.appendChild(mine);
            // Pipelines DÉCLARÉS par les apps (registre de code, ex. les passes du cam_analyzer) :
            // s'ouvrent ici pour être VUS ; les sauvegarder en fait un pipeline personnel.
            var declared = el('optgroup'); declared.label = 'Pipelines des apps';
            (res[1].pipelines || []).forEach(function (p) {
                var o = el('option');
                o.value = 'declared:' + p.key;
                o.textContent = p.name;
                declared.appendChild(o);
            });
            if (declared.children.length) sel.appendChild(declared);
            // La section « Pipelines » du catalogue lit les MÊMES listes.
            savedPipelines = res[0].pipelines || [];
            declaredPipelines = res[1].pipelines || [];
            renderPalette();
        })['catch'](function () {});
    }

    function savePipeline() {
        var nameEl = document.getElementById('studioPipelineName');
        var name = nameEl ? nameEl.value.trim() : '';
        if (!name) { toast('Donnez un nom au pipeline avant de sauvegarder.', 'warning'); return; }
        api('/studio/api/pipelines/', { method: 'POST',
            body: JSON.stringify({ name: name, graph: serializeGraph() }) })
            .then(function (d) {
                toast('Pipeline « ' + d.name + ' » sauvegardé.', 'success');
                refreshPipelineList();
            })['catch'](function (e) { toast(e.message, 'error'); });
    }

    function loadSelectedPipeline() {
        var sel = document.getElementById('studioLoadSelect');
        if (sel && sel.value) openPipeline(sel.value);
    }

    // Ouvre un pipeline — `<id>` (le mien) ou `declared:<clé>` (déclaré par une app). Même
    // chemin pour le sélecteur de la barre et la section « Pipelines » du catalogue.
    function openPipeline(value) {
        value = String(value || '');
        if (!value) return;
        var declared = value.indexOf('declared:') === 0;
        var url = declared
            ? '/studio/api/declared-pipelines/' + encodeURIComponent(value.slice('declared:'.length)) + '/'
            : '/studio/api/pipelines/' + value + '/';
        api(url).then(function (d) {
            // Ouvrir un pipeline, c'est changer de DOCUMENT : on ne doit pas pouvoir
            // « annuler » jusqu'au graphe precedent, qui n'a plus rien a voir.
            var missing = [];
            if (history) { history.silence(function () { missing = loadGraph(d.graph); }); history.reset(); }
            else missing = loadGraph(d.graph);
            fitView();   // un autre document : on le montre en entier
            var nameEl = document.getElementById('studioPipelineName');
            if (nameEl) nameEl.value = d.name;
            toast(d.declared
                ? 'Pipeline « ' + d.name + ' » ouvert (déclaré par l\'app) — le sauvegarder en fait une copie personnelle.'
                : 'Pipeline « ' + d.name + ' » chargé.', 'success');
            warnUnavailable(missing);
        })['catch'](function (e) { toast(e.message, 'error'); });
    }

    // ── Exécution (StudioRun) : POST puis polling + coloration des nœuds ──
    var runPoll = null;

    // ── Animation de FLUX sur les câbles (2026-07-17) : un point circule le long d'un
    //    câble tant que le nœud CIBLE est en cours (RUNNING) — la donnée qui entre dans
    //    la card en traitement. Pur SVG (<animateMotion>+<mpath>), aucune dépendance.
    function setLinkFlowing(link, on) {
        if (on) {
            link.path.classList.add('flowing');
            if (link.flowDot) return;
            var dot = svgEl('circle');
            dot.setAttribute('class', 'studio-flow-dot');
            dot.setAttribute('r', '5');
            var motion = svgEl('animateMotion');
            motion.setAttribute('dur', '1.1s');
            motion.setAttribute('repeatCount', 'indefinite');
            motion.setAttribute('rotate', 'auto');
            var mpath = svgEl('mpath');
            var ref = '#' + link.path.getAttribute('id');
            mpath.setAttribute('href', ref);   // SVG2
            mpath.setAttributeNS('http://www.w3.org/1999/xlink', 'xlink:href', ref);  // compat
            motion.appendChild(mpath);
            dot.appendChild(motion);
            svg.appendChild(dot);
            link.flowDot = dot;
        } else {
            link.path.classList.remove('flowing');
            if (link.flowDot && link.flowDot.parentNode) link.flowDot.parentNode.removeChild(link.flowDot);
            link.flowDot = null;
        }
    }
    function clearAllFlows() {
        links.forEach(function (l) { setLinkFlowing(l, false); });
    }
    // Un câble est ACTIF quand son nœud cible est RUNNING (la donnée y transite).
    function updateFlows(nodeStates) {
        nodeStates = nodeStates || {};
        links.forEach(function (l) {
            var target = nodeOf(l.to.dot);
            var st = nodeStates[target] && nodeStates[target].status;
            setLinkFlowing(l, st === 'RUNNING');
        });
    }

    // Les SIX états communs du modèle pipeline (ROUTE §10.6 point 4) — le canvas montre le même
    // vocabulaire que la card : `run-<état>` (pending, awaiting_resources, running, success,
    // failure, stale). Avant, trois seulement ; un nœud en attente de VRAM ou périmé ne se
    // distinguait pas d'un nœud jamais lancé.
    var RUN_STATES = ['PENDING', 'AWAITING_RESOURCES', 'RUNNING', 'SUCCESS', 'FAILURE', 'STALE'];
    var RUN_CLASSES = RUN_STATES.map(function (s) { return 'run-' + s.toLowerCase(); });

    function setNodeRunState(nodeId, status) {
        var n = nodes.filter(function (x) { return x.id === nodeId; })[0];
        if (!n || !n.el) return;
        RUN_CLASSES.forEach(function (c) { n.el.classList.remove(c); });
        if (RUN_STATES.indexOf(status) !== -1) n.el.classList.add('run-' + status.toLowerCase());
    }
    function clearRunStates() {
        nodes.forEach(function (n) {
            if (n.el) RUN_CLASSES.forEach(function (c) { n.el.classList.remove(c); });
        });
        clearAllFlows();
    }
    function setRunStatus(text, cls) {
        var s = document.getElementById('studioRunStatus');
        if (!s) return;
        s.textContent = text || '';
        s.className = 'small ms-2 ' + (cls || 'text-body-secondary');
    }

    function runPipeline() {
        if (runPoll) { toast('Une exécution est déjà en cours.', 'warning'); return; }
        if (!nodes.length) { toast('Le canvas est vide.', 'warning'); return; }
        clearRunStates();
        var btn = document.getElementById('studioRunBtn');
        api('/studio/api/run/', { method: 'POST',
            body: JSON.stringify({ graph: serializeGraph() }) })
            .then(function (d) {
                if (btn) btn.disabled = true;
                setRunStatus('Exécution #' + d.run_id + ' en cours…', 'text-warning');
                runPoll = d.run_id;
                runPoller.start(d.run_id);
            })['catch'](function (e) { toast(e.message, 'error'); });
    }

    // Suivi de l'exécution — boucle COMMUNE `WamaApp.Poller` (2026-10-13 : c'était un `setInterval`
    // local, qui relançait sans attendre la réponse et tournait en onglet caché).
    var runPoller = new WamaApp.Poller({
        urlTemplate: function (runId) { return '/studio/api/run/' + runId + '/'; },
        interval: 2500,
        maxFails: Infinity,
        onError: function () { /* réseau : ignorer ce tour */ },
        onData: function (runId, d) {
            Object.keys(d.node_states || {}).forEach(function (nid) {
                setNodeRunState(nid, d.node_states[nid].status);
            });
            updateFlows(d.node_states);
            if (d.status === 'SUCCESS' || d.status === 'FAILURE') {
                runPoller.stop(runId); runPoll = null;
                clearAllFlows();
                var btn = document.getElementById('studioRunBtn');
                if (btn) btn.disabled = false;
                if (d.status === 'SUCCESS') {
                    setRunStatus('Terminé ✔ (' + (d.processing_display || '') + ')', 'text-success');
                    toast('Pipeline terminé — sorties dans les files des apps.', 'success');
                } else {
                    setRunStatus('Échec : ' + (d.error || ''), 'text-danger');
                    toast('Pipeline en échec : ' + (d.error || ''), 'error');
                }
            }
        },
    });

    // ── Drag d'un nœud ─────────────────────────────────────────────────────
    // Par la brique commune des gestes (`WamaGestures.track`, 2026-10-16) : souris, stylet et
    // doigt passent par le même code. Seuil 0 : le nœud suit dès le premier mouvement, comme
    // avant à la souris ; seul le bouton gauche (le bouton du milieu défile la vue, voir init).
    function makeDraggable(node, handle) {
        WamaGestures.track(handle, {
            threshold: 0,
            start: function (e) {
                if (e.target.closest('.studio-node-del')) return false;
                handle.style.cursor = 'grabbing';
                return { ox: node.x, oy: node.y };
            },
            // Le déplacement écran se divise par le zoom ; plus de butée à 0 : le monde est
            // sans bord depuis que la vue défile.
            // Arrondi : la position finit dans le `layout` du manifeste pipeline, pas de
            // décimales de zoom dans un fichier versionné.
            move: function (e, start, d) {
                node.x = Math.round(start.ox + d.dx / view.k);
                node.y = Math.round(start.oy + d.dy / view.k);
                node.el.style.left = node.x + 'px';
                node.el.style.top = node.y + 'px';
                updateLinks();
            },
            end: function () {
                handle.style.cursor = 'grab';
                persistDraft();   // position du nœud conservée
            },
        });
    }

    // ── Bootstrap ───────────────────────────────────────────────────────────
    function init() {
        canvas = document.getElementById('studioCanvas');
        world = document.getElementById('studioWorld');
        svg = document.getElementById('studioLinks');
        hint = document.getElementById('studioHint');
        paletteList = document.getElementById('studioPaletteList');
        zoomLabel = document.getElementById('studioZoomLabel');
        if (!canvas || !world) return;
        applyView(false);

        // Ligne pendante suit le curseur ; Échap annule.
        canvas.addEventListener('mousemove', function (e) {
            if (!pending) return;
            pending.path.setAttribute('d', pathD(dotCenter(pending.dot), toWorld(e.clientX, e.clientY)));
        });

        // Défilement : glisser le FOND (bouton gauche, ou un doigt), ou n'importe où au bouton du
        // milieu ; PINCER à deux doigts zoome sous les doigts et déplace la vue avec eux. Par la
        // brique commune des gestes (`WamaGestures.track`, 2026-10-16) — le canvas défile LUI-MÊME,
        // la page ne bouge pas dessous (`touch-action: none`, posé par la brique).
        // Un glisser qui a bougé n'est pas un clic : il ne désélectionne pas, n'annule pas un lien.
        var panMoved = false;
        WamaGestures.track(canvas, {
            buttons: [0, 1],
            start: function (e) {
                var onBackground = !e.target.closest('.studio-node, .studio-zoom')
                    && !e.target.classList.contains('studio-link');
                if (!(e.button === 1 || (e.button === 0 && onBackground))) return false;
                return { ox: view.x, oy: view.y };
            },
            move: function (e, start, d) {
                canvas.classList.add('is-panning');
                view.x = start.ox + d.dx; view.y = start.oy + d.dy;
                applyView(false);
            },
            end: function (e, start, info) {
                canvas.classList.remove('is-panning');
                if (info.moved) {
                    applyView();   // retenue une fois, au lâcher
                    panMoved = true;
                    setTimeout(function () { panMoved = false; }, 0);   // le clic suit le relâcher
                }
            },
            pinch: function (p) {
                var c = canvas.getBoundingClientRect();
                view.x += p.dx; view.y += p.dy;
                zoomAt(view.k * p.scale, p.cx - c.left, p.cy - c.top);
            },
        });
        // Zoom à la molette (et au pincement d'un pavé tactile), centré sous le curseur.
        canvas.addEventListener('wheel', function (e) {
            e.preventDefault();
            var c = canvas.getBoundingClientRect();
            var step = e.deltaMode === 1 ? e.deltaY * 16 : e.deltaY;   // lignes → px
            zoomAt(view.k * Math.exp(-step * 0.0015), e.clientX - c.left, e.clientY - c.top);
        }, { passive: false });
        var zoomBar = document.getElementById('studioZoom');
        if (zoomBar) zoomBar.addEventListener('click', function (e) {
            var b = e.target.closest('[data-zoom]');
            if (!b) return;
            var action = b.dataset.zoom;
            if (action === 'in') zoomAt(view.k * 1.2);
            else if (action === 'out') zoomAt(view.k / 1.2);
            else if (action === 'reset') zoomAt(1);
            else if (action === 'fit') fitView();
        });

        // Sélection par DÉLÉGATION (pattern commun des apps, 2026-07-15) : un clic
        // N'IMPORTE OÙ sur la card-nœud la sélectionne et remplit l'inspecteur ;
        // un clic sur le fond (canvas OU calque SVG des liens) désélectionne.
        canvas.addEventListener('click', function (e) {
            if (panMoved) return;   // fin d'un défilement, pas un clic
            if (e.target.closest('.studio-zoom')) return;
            if (pending && !e.target.classList.contains('dot')) { cancelPending(); return; }
            if (e.target.classList.contains('dot')) return;             // ports : gérés par onDot
            if (e.target.closest('.studio-node-del')) return;           // suppression : gérée à part
            var box = e.target.closest('.studio-node');
            if (box) selectNode(box.dataset.node);
            else if (e.target === canvas || e.target === svg || e.target.closest('#studioLinks')) deselect();
        });
        document.addEventListener('keydown', function (e) { if (e.key === 'Escape') cancelPending(); });
        window.addEventListener('resize', updateLinks);

        // Dépôt d'un élément du catalogue À L'ENDROIT voulu (5.4) : seul notre type MIME est
        // accepté — un fichier glissé depuis le bureau n'est pas un nœud.
        // Survol : classe PROPRE au studio — la `.drag-over` globale (filemanager.css) est celle
        // des FICHIERS (fond forcé + « Déposez le fichier ici »), fausse pour un nœud.
        canvas.addEventListener('dragover', function (e) {
            var types = (e.dataTransfer && e.dataTransfer.types) || [];
            if (Array.prototype.indexOf.call(types, PALETTE_MIME) === -1) return;
            e.preventDefault();
            e.dataTransfer.dropEffect = 'copy';
            canvas.classList.add('is-drop-target');
        });
        canvas.addEventListener('dragleave', function (e) {
            if (!canvas.contains(e.relatedTarget)) canvas.classList.remove('is-drop-target');
        });
        canvas.addEventListener('drop', function (e) {
            canvas.classList.remove('is-drop-target');
            var id = e.dataTransfer && e.dataTransfer.getData(PALETTE_MIME);
            if (!id) return;
            e.preventDefault();
            var p = toWorld(e.clientX, e.clientY);
            addNode(id, { x: Math.round(p.x - 20), y: Math.round(p.y - 12) });
        });

        var clear = document.getElementById('studioClear');
        if (clear) clear.addEventListener('click', function () {
            // UN cran pour le geste entier : `commit()` enregistre l'etat d'avant, `silence()`
            // empeche les N suppressions d'en ajouter un chacune. Vider reste donc annulable.
            if (history) {
                history.commit();
                history.silence(function () { nodes.slice().forEach(function (n) { removeNode(n.id); }); });
            } else {
                nodes.slice().forEach(function (n) { removeNode(n.id); });
            }
            clearDraft();   // geste explicite : on repart de zéro
        });

        updateInspector();

        fetch('/studio/api/nodes/')
            .then(function (r) {
                if (!r.ok) throw new Error('HTTP ' + r.status);
                return r.json();
            })
            .then(function (d) {
                apps = d.nodes || {};
                // Les réglages AVANT la palette et le brouillon : un nœud restauré et sélectionné
                // doit trouver son schéma.
                nodeSchemas = d.schemas || {};
                settingsState = 'ready';
                renderPalette();
                restoreDraft();   // le graphe en cours survit à la navigation (2026-07-15)
                if (selected) updateInspector();   // un nœud ouvert avant l'arrivée du catalogue
            })
            .catch(function (err) {
                settingsState = 'error';
                paletteList.innerHTML = '<span class="text-danger">Catalogue indisponible.</span>';
                if (selected) updateInspector();
                if (global.console && console.error) console.error('[WamaStudio] catalogue', err);
            });

        // Persistance + exécution (2026-07-11)
        refreshPipelineList();
        var saveBtn = document.getElementById('studioSaveBtn');
        if (saveBtn) saveBtn.addEventListener('click', savePipeline);
        var loadSel = document.getElementById('studioLoadSelect');
        if (loadSel) loadSel.addEventListener('change', loadSelectedPipeline);
        var runBtn = document.getElementById('studioRunBtn');
        if (runBtn) runBtn.addEventListener('click', runPipeline);
    }

    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
    else init();
})(window);
