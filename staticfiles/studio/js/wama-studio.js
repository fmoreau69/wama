/*
 * WamaStudio — méta-app (squelette).
 * Canvas où chaque nœud = une app (métadonnées + ports typés via /studio/api/nodes/).
 * Ports typés : ENTRÉE = input_types (vert), SORTIE = output_types (bleu).
 * Une connexion n'est valide que si output_types(source) ∩ input_types(cible) ≠ ∅
 * → « typage par connexion ». Pas d'exécution : on valide card + connecteurs sur du réel.
 *
 * Volontairement minimal et autonome (vanilla + SVG). Évolutions prévues :
 *  - ports prompt/référence/url distincts (cf. INPUT_TYPES app_modes),
 *  - réutilisation du composant card pour les éléments qui circulent,
 *  - persistance + exécution (la file = méta-app dégénérée à 1 app).
 */
(function (global) {
    'use strict';

    var canvas, svg, hint, paletteList;
    var apps = {};

    // Nœuds-SOURCE intégrés (pas des apps) : produisent une sortie typée, sans entrée.
    // 1er maillon de la chaîne vidéo : un batch de prompts → port prompt de l'Imager.
    var BUILTINS = {
        text_input: {
            label: 'Texte', icon: 'fas fa-keyboard', color: '#f7c46c',
            description: "Source : un texte / prompt saisi dans les paramètres du nœud (inspecteur).",
            inputs: [], output: { label: 'Texte', types: ['prompt', 'text'] }, builtin: true,
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
            inputs: [{ label: 'Média final', types: ['image', 'video', 'audio', 'document', 'text'], group: 'travail' }],
            output: false, builtin: true,
        },
    };

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

    // ── Palette ──────────────────────────────────────────────────────────
    function paletteItem(id, a) {
        var item = el('div', 'studio-pal-item');
        item.style.setProperty('--app-c', a.color || '#6ea8fe');
        item.innerHTML = '<i class="' + (a.icon || 'fas fa-cube') + '"></i><span>' + a.label + '</span>';
        item.title = 'Ajouter ' + a.label;
        item.addEventListener('click', function () { addNode(id); });
        return item;
    }
    function renderPalette() {
        paletteList.innerHTML = '';
        // Sources (nœuds intégrés)
        paletteList.appendChild(el('div', 'studio-pal-group', 'Sources'));
        Object.keys(BUILTINS).forEach(function (id) { paletteList.appendChild(paletteItem(id, BUILTINS[id])); });
        // Apps (catalogue)
        paletteList.appendChild(el('div', 'studio-pal-group', 'Apps'));
        Object.keys(apps).forEach(function (id) { paletteList.appendChild(paletteItem(id, apps[id])); });
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
            inCol.appendChild(portEl('in', p.types, p.label, p.group || 'travail'));
        });
        // Sortie : types produits (output === false → nœud TERMINAL, pas de port).
        if (a.output !== false) {
            var out = a.output || { label: 'Sortie', types: [] };
            outCol.appendChild(portEl('out', out.types, out.label, 'out'));
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
        return node;
    }

    function portEl(side, types, label, group) {
        var p = el('div', 'studio-port ' + side);
        var dot = el('span', 'dot');
        dot.dataset.side = side;
        dot.dataset.group = group || '';
        dot.dataset.types = (types || []).join(',');
        var txt = label ? label : ((types && types.length) ? types.join(' · ') : '—');
        p.appendChild(dot);
        p.appendChild(el('span', 'types', txt));
        p.title = (label ? label + ' — ' : '') + ((types && types.length) ? types.join(', ') : '—');
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
        svg.appendChild(path);
        var link = { id: 'l' + (++seq), from: { dot: outDot }, to: { dot: inDot }, path: path };
        path.addEventListener('click', function () { removeLink(link.id); });
        links.push(link);
        updateLinks();
        updateInspector();   // rafraîchit les compteurs de connexions
    }

    function updateLinks() {
        links.forEach(function (l) {
            l.path.setAttribute('d', pathD(dotCenter(l.from.dot), dotCenter(l.to.dot)));
        });
    }

    function removeLink(id) {
        links = links.filter(function (l) {
            if (l.id !== id) return true;
            if (l.path.parentNode) l.path.parentNode.removeChild(l.path);
            return false;
        });
        updateInspector();
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
    }

    // ── Inspecteur (volet droit, généré par WamaDetails) ──────────────────
    function metaOf(node) { return apps[node.app] || BUILTINS[node.app] || {}; }
    function countLinks(nodeId, side) {
        return links.filter(function (l) { return nodeOf(l[side].dot) === nodeId; }).length;
    }
    function typeBadge(a) {
        if (a.planned) return '<span class="badge bg-warning text-dark">à venir</span>';
        if (a.builtin) return '<span class="badge bg-success">source</span>';
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
                    if (!window.MediaPicker) { toast('Médiathèque indisponible sur cette page.', 'error'); return; }
                    MediaPicker.open({ type: 'all', onSelect: function (file, asset) {
                        if (!asset) return;
                        var url = asset.file_url || '';
                        node.params.asset_path = url.replace(/^\/?media\//, '');
                        node.params.asset_name_display = asset.name || url.split('/').pop();
                        input.innerHTML = '<i class="fas fa-photo-film me-1"></i>' + node.params.asset_name_display;
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
            input.addEventListener('input', function () { node.params[p.name] = input.value; });
            input.addEventListener('change', function () { node.params[p.name] = input.value; });
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
                         to_port: l.to.dot.dataset.group || '' };
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
            var inDot = sl.to_port
                ? to.el.querySelector('.studio-port-col.in .dot[data-group="' + sl.to_port + '"]')
                : null;
            if (!inDot) inDot = to.el.querySelector('.studio-port-col.in .dot');
            if (outDot && inDot) createLink(outDot, inDot);
        });
        updateLinks();
    }

    // ── Persistance (StudioPipeline) ───────────────────────────────────────
    function api(url, opts) {
        opts = opts || {};
        opts.headers = Object.assign({ 'Content-Type': 'application/json' },
            (window.WamaApp && WamaApp.csrfHeaders) ? WamaApp.csrfHeaders() : {}, opts.headers || {});
        return fetch(url, opts).then(function (r) {
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
        api('/studio/api/pipelines/').then(function (d) {
            sel.innerHTML = '<option value="">Charger un pipeline…</option>';
            d.pipelines.forEach(function (p) {
                var o = el('option');
                o.value = p.id;
                o.textContent = p.name + ' (' + p.nodes + ' nœuds · ' + p.updated_at + ')';
                sel.appendChild(o);
            });
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
        if (!sel || !sel.value) return;
        api('/studio/api/pipelines/' + sel.value + '/').then(function (d) {
            loadGraph(d.graph);
            var nameEl = document.getElementById('studioPipelineName');
            if (nameEl) nameEl.value = d.name;
            toast('Pipeline « ' + d.name + ' » chargé.', 'success');
        })['catch'](function (e) { toast(e.message, 'error'); });
    }

    // ── Exécution (StudioRun) : POST puis polling + coloration des nœuds ──
    var runPoll = null;

    function setNodeRunState(nodeId, status) {
        var n = nodes.filter(function (x) { return x.id === nodeId; })[0];
        if (!n || !n.el) return;
        n.el.classList.remove('run-running', 'run-success', 'run-failure');
        if (status === 'RUNNING') n.el.classList.add('run-running');
        else if (status === 'SUCCESS') n.el.classList.add('run-success');
        else if (status === 'FAILURE') n.el.classList.add('run-failure');
    }
    function clearRunStates() {
        nodes.forEach(function (n) {
            if (n.el) n.el.classList.remove('run-running', 'run-success', 'run-failure');
        });
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
            if (d.status === 'SUCCESS' || d.status === 'FAILURE') {
                clearInterval(runPoll); runPoll = null;
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

        var clear = document.getElementById('studioClear');
        if (clear) clear.addEventListener('click', function () {
            nodes.slice().forEach(function (n) { removeNode(n.id); });
        });

        updateInspector();

        fetch('/studio/api/nodes/')
            .then(function (r) { return r.json(); })
            .then(function (d) { apps = d.nodes || {}; renderPalette(); })
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
