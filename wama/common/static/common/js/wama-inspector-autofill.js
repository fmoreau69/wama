/*
 * WAMA — Inspector autofill
 * =========================================================================
 * Génère le contenu du volet droit (#wama-right-panel) à partir des
 * MÉTADONNÉES d'un élément (app, modèle, item de file…) et d'un SCHÉMA
 * déclaratif. Philosophie WAMA : le rendu est générique et homogène entre
 * toutes les apps ; seule la *spécificité* (quels champs, quelles actions)
 * est déclarée — a minima — par l'app.
 *
 * Couplé à wama-inspector.js (sélection/clic/highlight/banner) :
 *   WamaInspector.init({ ..., renderItemActions: function (host, card) {
 *       const data = lookup(card.dataset.id);
 *       host.innerHTML = WamaAutofill.renderSections(data, DETAIL_SCHEMA);
 *       const a = WamaAutofill.renderActions(data, ACTION_SCHEMA);
 *       actionsHost.innerHTML = a.html; a.wire(actionsHost);
 *   }});
 *
 * Charger AVANT le script de l'app, et inclure wama-inspector-autofill.css.
 * -------------------------------------------------------------------------
 *
 * SCHÉMA DE SECTIONS (renderSections) — tableau ordonné de descripteurs :
 *   { badges: d => ['<span class="badge ...">…</span>', …] }
 *   { description: 'field' | d => 'texte' }
 *   { section: 'Titre', rows: [
 *        { k: 'Libellé', field: 'vram_gb', suffix: ' Go' },
 *        { k: 'Clé', field: 'model_key', code: true },
 *        { k: 'Téléchargé', field: 'is_downloaded', badge: true },
 *        { k: 'Calculé', get: d => d.a + d.b },
 *        { k: 'Statique', value: 'foo' },
 *     ], hideIfEmpty: true }            // section masquée si toutes lignes vides
 *   { section: 'Capacités', kv: 'capabilities' }   // dict -> lignes clé/valeur
 *   { section: 'Chemin local', code: 'local_path' }
 *
 * Toute valeur null/undefined/'' fait disparaître la ligne (et la section si
 * toutes ses lignes sont vides). Les sections badges/description/kv/code se
 * masquent d'elles-mêmes quand la donnée est absente.
 *
 * SCHÉMA D'ACTIONS (renderActions) — tableau de boutons/liens :
 *   { label, icon, cls, when: d => bool,
 *     href: d => 'https://…',        // -> rendu <a target=_blank>
 *     onClick: (d, ev) => { … } }     // -> rendu <button>, handler câblé par wire()
 *   { expand: d => [descripteurs…] }  // N boutons dynamiques (ex. 1 par format)
 *
 * Une ligne peut aussi porter render: (raw, data) => 'HTML' pour combiner
 * plusieurs champs (ex. « format actuel → préféré »).
 */
(function (global) {
    'use strict';

    function esc(s) {
        return String(s == null ? '' : s)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    function isEmpty(v) {
        return v === null || v === undefined || v === '' ||
            (Array.isArray(v) && v.length === 0);
    }

    // Résout la valeur brute d'un descripteur de ligne/champ.
    function resolve(data, spec) {
        if (typeof spec.get === 'function') return spec.get(data);
        if (spec.field !== undefined) return data ? data[spec.field] : undefined;
        if (spec.value !== undefined) return spec.value;
        return undefined;
    }

    function boolBadge(v) {
        return v
            ? '<span class="badge bg-success">oui</span>'
            : '<span class="badge bg-secondary">non</span>';
    }

    // Formate une valeur brute en HTML selon le descripteur. '' si vide.
    function formatValue(raw, spec, data) {
        if (spec.badge) return boolBadge(!!raw);
        if (isEmpty(raw)) return '';
        let v = raw;
        if (Array.isArray(v)) v = v.join(', ');
        if (typeof spec.render === 'function') return spec.render(raw, data);  // HTML libre (échappement à la charge de l'app)
        if (spec.code) return '<code>' + esc(v) + '</code>';
        return esc(v) + (spec.suffix ? esc(spec.suffix) : '');
    }

    function rowHtml(k, vHtml) {
        return '<div class="wai-row"><span class="wai-k">' + esc(k) +
            '</span><span class="wai-v">' + vHtml + '</span></div>';
    }

    // Rend un dict en lignes clé/valeur (valeurs objet -> JSON compact).
    function kvRows(obj) {
        if (!obj || typeof obj !== 'object') return '';
        return Object.keys(obj).map(function (k) {
            let val = obj[k];
            if (val && typeof val === 'object') val = JSON.stringify(val);
            if (isEmpty(val)) return '';
            return rowHtml(k, esc(val));
        }).join('');
    }

    function sectionTitle(t) {
        return '<div class="wai-section-title">' + esc(t) + '</div>';
    }

    function renderSections(data, sections) {
        if (!Array.isArray(sections)) return '';
        let html = '';
        sections.forEach(function (sec) {
            // Badges
            if (sec.badges) {
                const arr = sec.badges(data) || [];
                if (arr.length) html += '<div class="wai-badges">' + arr.join('') + '</div>';
                return;
            }
            // Description
            if (sec.description !== undefined) {
                const d = typeof sec.description === 'function'
                    ? sec.description(data) : (data ? data[sec.description] : '');
                if (!isEmpty(d)) html += '<p class="wai-desc">' + esc(d) + '</p>';
                return;
            }
            // Dict clé/valeur
            if (sec.kv !== undefined) {
                const rows = kvRows(data ? data[sec.kv] : null);
                if (rows) html += (sec.section ? sectionTitle(sec.section) : '') + rows;
                return;
            }
            // Bloc code
            if (sec.code !== undefined) {
                const val = data ? data[sec.code] : '';
                if (!isEmpty(val)) {
                    html += (sec.section ? sectionTitle(sec.section) : '') +
                        '<code class="wai-code">' + esc(val) + '</code>';
                }
                return;
            }
            // Lignes
            if (Array.isArray(sec.rows)) {
                const rows = sec.rows.map(function (r) {
                    const vHtml = formatValue(resolve(data, r), r, data);
                    return vHtml === '' ? '' : rowHtml(r.k, vHtml);
                }).join('');
                const hideIfEmpty = sec.hideIfEmpty !== false;
                if (!rows && hideIfEmpty) return;
                html += (sec.section ? sectionTitle(sec.section) : '') + rows;
            }
        });
        return html;
    }

    function actionId(i) { return 'wai-act-' + i; }

    // Construit le HTML des actions + un câbleur de handlers (onClick).
    // Un descripteur peut être statique, ou { expand: d => [descripteurs…] }
    // pour produire N boutons dynamiques (ex. une conversion par format cible).
    function renderActions(data, actions, opts) {
        opts = opts || {};
        let flat = [];
        (actions || []).forEach(function (a) {
            if (typeof a.expand === 'function') flat = flat.concat(a.expand(data) || []);
            else flat.push(a);
        });
        const items = flat.filter(function (a) {
            return !a.when || a.when(data);
        });
        if (!items.length) {
            return { html: '<span class="wai-empty">' + esc(opts.emptyText || 'Aucune action disponible') + '</span>', wire: function () {} };
        }
        const html = '<div class="wai-actions">' + items.map(function (a, i) {
            const icon = a.icon ? '<i class="' + esc(a.icon) + ' me-1"></i>' : '';
            const cls = a.cls || 'btn btn-sm btn-outline-secondary';
            if (a.href) {
                return '<a href="' + esc(a.href(data)) + '" target="_blank" rel="noopener" class="' +
                    esc(cls) + '">' + icon + esc(a.label) + '</a>';
            }
            return '<button type="button" class="' + esc(cls) + '" data-wai="' + actionId(i) + '">' +
                icon + esc(a.label) + '</button>';
        }).join('') + '</div>';

        function wire(scope) {
            if (!scope) return;
            items.forEach(function (a, i) {
                if (!a.onClick) return;
                const el = scope.querySelector('[data-wai="' + actionId(i) + '"]');
                if (el) el.addEventListener('click', function (ev) { a.onClick(data, ev); });
            });
        }
        return { html: html, wire: wire };
    }

    global.WamaAutofill = {
        renderSections: renderSections,
        renderActions: renderActions,
        esc: esc,
        boolBadge: boolBadge,
    };
})(window);
