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
 * Volontairement minimal et autonome (vanilla + SVG). Décidé le 2026-09-15, non implémenté
 * (vocabulaire process / pipeline / nœud / card → WAMA_APP_GENERATION_ROUTE.md §10.6) :
 *  - ajout d'un nœud au CLIC aujourd'hui (empilé) → glisser-déposer à l'endroit voulu,
 *  - palette « Apps » → « Catalogue » en sections repliables, pipelines sauvegardés inclus,
 *  - type de nœud `pipeline` (un pipeline enregistré réutilisé comme nœud),
 *  - états d'exécution alignés sur le vocabulaire commun (5 états JOB_* + STALE).
 */
(function (global) {
    'use strict';

    var canvas, svg, hint, paletteList;
    var apps = {};
    var savedPipelines = [], declaredPipelines = [];   // la section « Pipelines » du catalogue

    // Nœuds-SOURCE intégrés (pas des apps) : produisent une sortie typée, sans entrée.
    // 1er maillon de la chaîne vidéo : un batch de prompts → port prompt de l'Imager.
    var BUILTINS = {
        text_input: {
            label: 'Texte', icon: 'fas fa-keyboard', color: '#f7c46c',
            description: "Source : un texte / prompt saisi dans les paramètres du nœud (inspecteur).",
            inputs: [], output: { label: 'Texte', types: ['prompt'] }, builtin: true,
        },
        prompt_batch: {
            label: 'Batch de prompts', icon: 'fas fa-list-ul', color: '#c4a7fb',
            description: "Source : une liste de prompts à envoyer à une app génératrice (ex. Imager vidéo).",
            inputs: [], output: { label: 'Prompts', types: ['prompt'] }, builtin: true,
        },
        media_import: {
            label: 'Médias importés', icon: 'fas fa-photo-film', color: '#6ee7a8',
            description: "Source : vos médias existants (image/vidéo/audio) injectés dans le pipeline.",
            inputs: [], output: { label: 'Médias', types: ['image', 'video', 'audio'] }, builtin: true,
        },
        studio_output: {
            label: 'Sortie', icon: 'fas fa-flag-checkered', color: '#e78fb3',
            description: "Range le résultat final dans la MÉDIATHÈQUE (nom + type configurables dans l'inspecteur).",
            inputs: [{ label: 'Média final', types: ['image', 'video', 'audio', 'document', 'dataset', '3d'], group: 'travail' }],
            output: false, builtin: true,
        },
    };
    // Nœud-source « Jeu de données » (D13) : ses types de sortie sont LA taxonomie Data servie
    // par /studio/api/nodes/ (`data_types`) — jamais recopiée ici. Posé à la réception.
    function installDatasetSource(dataTypes) {
        if (!dataTypes || !dataTypes.length) return;
        BUILTINS.dataset_input = {
            label: 'Jeu de données', icon: 'fas fa-table', color: '#9ad0ec',
            description: "Source : un fichier tabulaire (CSV) de la médiathèque lu comme donnée TYPÉE (type choisi dans l'inspecteur) → entrée d'un nœud fonction.",
            inputs: [], output: { label: 'Données', types: dataTypes }, builtin: true,
        };
        // La Sortie accepte aussi une donnée typée (écrite en CSV, rangée en document).
        var sink = BUILTINS.studio_output.inputs[0];
        dataTypes.forEach(function (t) { if (sink.types.indexOf(t) === -1) sink.types.push(t); });
    }

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

    // Centre d'un point-port en coordonnées canvas.
    function dotCenter(dot) {
        var c = canvas.getBoundingClientRect();
        var r = dot.getBoundingClientRect();
        return { x: r.left + r.width / 2 - c.left, y: r.top + r.height / 2 - c.top };
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
    // mot désigne déjà les paquets pip. Un nœud s'ajoute au CLIC (comme avant, empilé) ou se
    // GLISSE à l'endroit voulu du canvas (drag natif HTML5, type MIME propre) ; un pipeline
    // s'OUVRE — c'est un document, pas un nœud — par le même chemin que le sélecteur.
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
        item.title = a.title || ('Ajouter ' + a.label + ' (clic, ou glisser sur le canvas)');
        item.addEventListener('click', function () { (onPick || addNode)(id); });
        if (!onPick) {
            item.draggable = true;
            item.addEventListener('dragstart', function (e) {
                e.dataTransfer.setData(PALETTE_MIME, id);
                e.dataTransfer.effectAllowed = 'copy';
            });
        }
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
        var sources = Object.keys(BUILTINS).filter(function (id) { return BUILTINS[id].output !== false; });
        var sinks = Object.keys(BUILTINS).filter(function (id) { return BUILTINS[id].output === false; });
        var appIds = Object.keys(apps).filter(function (id) { return apps[id].kind !== 'function'; });
        var fnIds = Object.keys(apps).filter(function (id) { return apps[id].kind === 'function'; });

        var inputs = paletteSection('inputs', 'Entrées');
        sources.forEach(function (id) { inputs.appendChild(paletteItem(id, BUILTINS[id])); });
        paletteList.appendChild(inputs);

        var outputs = paletteSection('outputs', 'Sorties');
        sinks.forEach(function (id) { outputs.appendChild(paletteItem(id, BUILTINS[id])); });
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
        var a = apps[appId] || BUILTINS[appId];
        if (!a) return null;
        if (hint) hint.style.display = 'none';
        var id = opts.id || ('n' + (++seq));
        var m = /^n(\d+)$/.exec(id);
        if (m) seq = Math.max(seq, parseInt(m[1], 10));
        var node = { id: id, app: appId, params: opts.params || {},
                     x: (opts.x != null) ? opts.x : 40 + (nodes.length % 5) * 30,
                     y: (opts.y != null) ? opts.y : 40 + (nodes.length % 5) * 30 };

        var box = el('div', 'studio-node' + (a.planned ? ' is-planned' : ''));
        box.style.left = node.x + 'px';
        box.style.top = node.y + 'px';
        box.style.setProperty('--app-c', a.color || '#6ea8fe');
        box.dataset.node = id;

        var badge = a.planned ? '<span class="studio-node-badge" title="App planifiée — specs à venir">à venir</span>' : '';
        var head = el('div', 'studio-node-head',
            '<i class="app-ico ' + (a.icon || 'fas fa-cube') + '"></i><span>' + a.label + '</span>' + badge
            + '<span class="studio-node-del" title="Supprimer">&times;</span>');
        box.appendChild(head);

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

        canvas.appendChild(box);
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
        p.appendChild(el('span', 'types', txt));
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
    function metaOf(node) { return apps[node.app] || BUILTINS[node.app] || {}; }
    function countLinks(nodeId, side) {
        return links.filter(function (l) { return nodeOf(l[side].dot) === nodeId; }).length;
    }
    function typeBadge(a) {
        if (a.planned) return '<span class="badge bg-warning text-dark">à venir</span>';
        if (a.builtin) return '<span class="badge bg-success">source</span>';
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
            renderNodeParams(body, node);
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

    // ── Params d'exécution du nœud (métadonnée-driven : params_spec des runners) ──
    var paramsSpecs = {};   // app -> spec[], servi par /studio/api/run-options/
    var runOptions = {};    // listes dynamiques (ex. avatar_gallery)

    function renderNodeParams(body, node) {
        var spec = paramsSpecs[node.app];
        if (!spec || !spec.length) return;
        node.params = node.params || {};
        var wrap = el('div', 'studio-node-params mt-2 pt-2 border-top border-secondary');
        wrap.appendChild(el('div', 'small text-white-50 mb-1',
            '<i class="fas fa-sliders-h me-1"></i>Paramètres d’exécution'));
        spec.forEach(function (p) {
            var field = el('div', 'mb-2');
            field.appendChild(el('label', 'form-label small text-white-50 mb-0', p.label));
            var input;
            if (p.type === 'textarea') {
                input = el('textarea', 'form-control form-control-sm bg-dark text-light border-secondary');
                input.rows = 3;
                input.placeholder = p.placeholder || '';
            } else if (p.type === 'select') {
                input = el('select', 'form-select form-select-sm bg-dark text-light border-secondary');
                var opts = p.options || runOptions[p.options_source] || [];
                opts.forEach(function (o) {
                    var op = el('option');
                    if (o && typeof o === 'object') { op.value = o.value; op.textContent = o.label || o.value; }
                    else { op.value = o; op.textContent = o; }
                    input.appendChild(op);
                });
            } else if (p.type === 'media_picker') {
                // Bouton Médiathèque (MediaPicker commun) → stocke le chemin + la catégorie du média.
                input = el('button', 'btn btn-sm btn-outline-info w-100');
                input.type = 'button';
                var chosen = node.params.asset_name_display || '';
                input.innerHTML = '<i class="fas fa-photo-film me-1"></i>' +
                    (chosen ? chosen : 'Choisir dans la médiathèque…');
                input.addEventListener('click', function () {
                    // const MediaPicker au top-level = binding lexical global, PAS window.MediaPicker
                    var MP = (typeof MediaPicker !== 'undefined') ? MediaPicker : global.MediaPicker;
                    if (!MP) { toast('Médiathèque indisponible sur cette page.', 'error'); return; }
                    MP.open({ type: 'all', onSelect: function (file, asset) {
                        if (!asset) return;
                        var url = asset.file_url || '';
                        node.params.asset_path = url.replace(/^\/?media\//, '');
                        node.params.asset_name_display = asset.name || url.split('/').pop();
                        input.innerHTML = '<i class="fas fa-photo-film me-1"></i>' + node.params.asset_name_display;
                        persistDraft();
                    } });
                });
                field.appendChild(input);
                wrap.appendChild(field);
                return;   // pas de câblage value/input générique pour ce type
            } else {
                input = el('input', 'form-control form-control-sm bg-dark text-light border-secondary');
            }
            input.value = node.params[p.name] != null ? node.params[p.name] : (p['default'] || '');
            if (input.value && !node.params[p.name]) node.params[p.name] = input.value;
            // `true` = saisie : la rafale coalesce, sinon « bonjour » coûterait 7 crans.
            input.addEventListener('input', function () { node.params[p.name] = input.value; persistDraft(true); });
            input.addEventListener('change', function () { node.params[p.name] = input.value; persistDraft(); });
            field.appendChild(input);
            wrap.appendChild(field);
        });
        body.appendChild(wrap);
    }

    // ── Sérialisation / restauration du graphe ─────────────────────────────
    function serializeGraph() {
        return {
            nodes: nodes.map(function (n) {
                return { id: n.id, app: n.app, x: n.x, y: n.y, params: n.params || {} };
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

    function loadGraph(graph) {
        clearCanvas();
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
            var inDot = sl.to_port
                ? (to.el.querySelector('.studio-port-col.in .dot[data-port="' + sl.to_port + '"]')
                   || to.el.querySelector('.studio-port-col.in .dot[data-group="' + sl.to_port + '"]'))
                : null;
            if (!inDot) inDot = to.el.querySelector('.studio-port-col.in .dot');
            if (outDot && inDot) createLink(outDot, inDot);
        });
        updateLinks();
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
                if (history) history.silence(function () { loadGraph(d.graph); });
                else loadGraph(d.graph);
                var nameEl = document.getElementById('studioPipelineName');
                if (nameEl && d.name) nameEl.value = d.name;
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
            if (history) { history.silence(function () { loadGraph(d.graph); }); history.reset(); }
            else loadGraph(d.graph);
            var nameEl = document.getElementById('studioPipelineName');
            if (nameEl) nameEl.value = d.name;
            toast(d.declared
                ? 'Pipeline « ' + d.name + ' » ouvert (déclaré par l\'app) — le sauvegarder en fait une copie personnelle.'
                : 'Pipeline « ' + d.name + ' » chargé.', 'success');
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
        s.className = 'small ms-2 ' + (cls || 'text-white-50');
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
                runPoll = setInterval(function () { pollRun(d.run_id, btn); }, 2500);
            })['catch'](function (e) { toast(e.message, 'error'); });
    }

    function pollRun(runId, btn) {
        api('/studio/api/run/' + runId + '/').then(function (d) {
            Object.keys(d.node_states || {}).forEach(function (nid) {
                setNodeRunState(nid, d.node_states[nid].status);
            });
            updateFlows(d.node_states);
            if (d.status === 'SUCCESS' || d.status === 'FAILURE') {
                clearInterval(runPoll); runPoll = null;
                clearAllFlows();
                if (btn) btn.disabled = false;
                if (d.status === 'SUCCESS') {
                    setRunStatus('Terminé ✔ (' + (d.processing_display || '') + ')', 'text-success');
                    toast('Pipeline terminé — sorties dans les files des apps.', 'success');
                } else {
                    setRunStatus('Échec : ' + (d.error || ''), 'text-danger');
                    toast('Pipeline en échec : ' + (d.error || ''), 'error');
                }
            }
        })['catch'](function () {});
    }

    // ── Drag d'un nœud ─────────────────────────────────────────────────────
    function makeDraggable(node, handle) {
        handle.addEventListener('mousedown', function (e) {
            if (e.target.closest('.studio-node-del')) return;
            e.preventDefault();
            // ── Drag d'abord (les listeners DOIVENT être posés quoi qu'il arrive) ──
            var startX = e.clientX, startY = e.clientY, ox = node.x, oy = node.y;
            handle.style.cursor = 'grabbing';
            function move(ev) {
                node.x = Math.max(0, ox + (ev.clientX - startX));
                node.y = Math.max(0, oy + (ev.clientY - startY));
                node.el.style.left = node.x + 'px';
                node.el.style.top = node.y + 'px';
                updateLinks();
            }
            function up() {
                document.removeEventListener('mousemove', move);
                document.removeEventListener('mouseup', up);
                handle.style.cursor = 'grab';
                persistDraft();   // position du nœud conservée
            }
            document.addEventListener('mousemove', move);
            document.addEventListener('mouseup', up);
        });
    }

    // ── Bootstrap ───────────────────────────────────────────────────────────
    function init() {
        canvas = document.getElementById('studioCanvas');
        svg = document.getElementById('studioLinks');
        hint = document.getElementById('studioHint');
        paletteList = document.getElementById('studioPaletteList');
        if (!canvas) return;

        // Ligne pendante suit le curseur ; Échap annule.
        canvas.addEventListener('mousemove', function (e) {
            if (!pending) return;
            var c = canvas.getBoundingClientRect();
            pending.path.setAttribute('d', pathD(dotCenter(pending.dot),
                { x: e.clientX - c.left, y: e.clientY - c.top }));
        });
        // Sélection par DÉLÉGATION (pattern commun des apps, 2026-07-15) : un clic
        // N'IMPORTE OÙ sur la card-nœud la sélectionne et remplit l'inspecteur ;
        // un clic sur le fond (canvas OU calque SVG des liens) désélectionne.
        canvas.addEventListener('click', function (e) {
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
        canvas.addEventListener('dragover', function (e) {
            var types = (e.dataTransfer && e.dataTransfer.types) || [];
            if (Array.prototype.indexOf.call(types, PALETTE_MIME) === -1) return;
            e.preventDefault();
            e.dataTransfer.dropEffect = 'copy';
        });
        canvas.addEventListener('drop', function (e) {
            var id = e.dataTransfer && e.dataTransfer.getData(PALETTE_MIME);
            if (!id) return;
            e.preventDefault();
            var c = canvas.getBoundingClientRect();
            addNode(id, { x: Math.max(0, e.clientX - c.left - 20), y: Math.max(0, e.clientY - c.top - 12) });
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
            .then(function (r) { return r.json(); })
            .then(function (d) {
                apps = d.nodes || {};
                installDatasetSource(d.data_types);
                renderPalette();
                restoreDraft();   // le graphe en cours survit à la navigation (2026-07-15)
            })
            .catch(function () { paletteList.innerHTML = '<span class="text-danger">Catalogue indisponible.</span>'; });

        // Persistance + exécution (2026-07-11)
        api('/studio/api/run-options/').then(function (d) {
            paramsSpecs = d.params_specs || {};
            runOptions = d.options || {};
        })['catch'](function () {});
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
