/*
 * WamaModes — générateur d'UI domaines→modes (clé de voûte UX, voir MODES_QUEUE_UX.md).
 * Rend, depuis le schéma déclaratif d'une app : onglets DOMAINE (si >1) → switch de MODE →
 * champs d'ENTRÉE typés (prompt/fichier/url) + un slot RÉGLAGES (que l'app remplit).
 * Émet onChange({domain, mode, realtime}) à chaque changement. Métadonnée-driven : zéro code par app.
 *
 * Usage :
 *   WamaModes.fetch('imager').then(schema => {
 *     const wm = WamaModes.create({ container:'#newCardConfig', schema,
 *       onChange: s => { renderAppSettings(s); } });
 *     // ... wm.getState() -> {domain, mode, inputs}
 *   });
 *
 * LE MODE EST UN RÉGLAGE (2026-09-27, `app_modes.mode_param`). Quand le domaine nomme son
 * `mode_param`, le switch tient un champ caché `name=<mode_param>` : l'inspecteur commun le lit
 * et l'applique comme n'importe quel réglage (le mode d'une card s'affiche quand on la
 * sélectionne), la modale et les préférences aussi. Un clic de l'utilisateur émet
 * `wama:user-edit` (l'enregistrement au geste, `WamaInspector` `autoSave`) ; une valeur posée de
 * l'extérieur (inspecteur) met le switch à jour sans rien signaler comme geste. Chaque rendu
 * ANNONCE la valeur du mode par un `change` du champ (non « trusted ») : ce qui en dépend s'aligne,
 * même rempli avant que le switch n'existe. Les éléments
 * `[data-mode-section="<id> <id>…"]` de `sectionsRoot` (défaut : la page) ne sont affichés que
 * pour les modes qu'ils listent — des sections de réglages propres à un mode, sans script d'app.
 */
(function (global) {
    'use strict';

    function esc(s) {
        if (global.WamaApp && WamaApp.escapeHtml) return WamaApp.escapeHtml(s);
        return String(s == null ? '' : s).replace(/[&<>"']/g, function (m) {
            return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[m];
        });
    }

    function renderInput(inp) {
        const id = 'wm-in-' + inp.id;
        const label = esc(inp.label || inp.id);
        if (inp.kind === 'text') {
            return `<div class="wm-field mb-2"><label class="form-label small mb-1" for="${id}">${label}</label>
                <textarea id="${id}" class="form-control form-control-sm" data-input="${inp.id}" rows="2"></textarea></div>`;
        }
        if (inp.kind === 'url') {
            return `<div class="wm-field mb-2"><label class="form-label small mb-1" for="${id}">${label}</label>
                <input id="${id}" type="url" class="form-control form-control-sm" data-input="${inp.id}" placeholder="https://…"></div>`;
        }
        if (inp.kind === 'file') {
            const acc = inp.accept ? ` <span class="text-muted">(${esc(inp.accept)})</span>` : '';
            const multi = inp.multi ? ' multiple' : '';
            const hint = inp.multi ? ' <span class="text-muted small">— plusieurs possibles</span>' : '';
            // Source double : upload OU médiathèque (MediaPicker, filtré par type) — si la brique est là.
            const lib = (typeof window !== 'undefined' && window.MediaPicker && inp.accept)
                ? `<button type="button" class="btn btn-sm btn-outline-secondary wm-lib" data-for="${id}" data-type="${esc(inp.accept)}" title="Depuis la médiathèque">
                       <i class="fas fa-photo-film"></i></button>` : '';
            return `<div class="wm-field mb-2"><label class="form-label small mb-1" for="${id}">${label}${acc}${hint}</label>
                <div class="input-group input-group-sm">
                    <input id="${id}" type="file" class="form-control form-control-sm" data-input="${inp.id}"${multi}>${lib}
                </div>
                <div class="wm-lib-picked small text-success mt-1" data-picked-for="${id}"></div></div>`;
        }
        return '';
    }

    function WamaModes(cfg) {
        this.container = typeof cfg.container === 'string'
            ? document.querySelector(cfg.container) : cfg.container;
        this.schema = cfg.schema || {};
        this.onChange = cfg.onChange || function () {};
        this.domain = cfg.domain || null;
        this.mode = cfg.mode || null;
        // renderInputs=false : rend SEULEMENT les onglets domaine + switch de mode (l'app garde ses
        // propres champs d'entrée). Utile pour piloter une UI existante sans la dupliquer.
        this.renderInputs = cfg.renderInputs !== false;
        // Présentation du switch de mode : couleur Bootstrap (modeVariant ou schéma `domain.variant`,
        // défaut 'secondary') + block (btn-group pleine largeur, comme l'UI Imager d'origine).
        this.modeVariant = cfg.modeVariant || null;
        this.block = !!cfg.block;
        // Label optionnel au-dessus du switch de mode (ex : « Mode de génération »).
        this.modesLabel = cfg.modesLabel || null;
        this.sectionsRoot = cfg.sectionsRoot || document;
        this._bindParamListener();
        this._render();
    }

    // Le param du schéma qui porte le mode du domaine courant ('' sinon).
    WamaModes.prototype._param = function () {
        const dom = this._domains().find(d => d.id === this.domain);
        return (dom && dom.mode_param) || '';
    };

    // Valeur posée de l'EXTÉRIEUR sur le champ caché (inspecteur, préférences) → le switch suit.
    // Délégué sur le conteneur : le champ est recréé à chaque rendu.
    WamaModes.prototype._bindParamListener = function () {
        const self = this;
        if (!this.container) return;
        this.container.addEventListener('change', function (e) {
            const tg = e.target;
            if (!tg || !tg.classList || !tg.classList.contains('wm-param')) return;
            if (tg.value && tg.value !== self.mode) { self.mode = tg.value; self._render(true); }
        });
    };

    // Sections propres à un mode : affichées pour les modes qu'elles listent.
    WamaModes.prototype._applySections = function () {
        // Seulement quand le mode est un RÉGLAGE déclaré : sans `mode_param`, le switch n'est
        // qu'un affichage et ne décide de rien d'autre sur la page.
        if (!this._param()) return;
        const mode = this.mode;
        (this.sectionsRoot || document).querySelectorAll('[data-mode-section]').forEach(el => {
            const modes = (el.dataset.modeSection || '').split(/\s+/).filter(Boolean);
            el.hidden = modes.length > 0 && modes.indexOf(mode) === -1;
        });
    };

    WamaModes.prototype._domains = function () {
        return (this.schema && this.schema.domains) || [];
    };

    WamaModes.prototype._render = function (quiet) {
        const ds = this._domains();
        if (!this.container) return;
        if (!ds.length) { this.container.innerHTML = ''; return; }

        if (!this.domain || !ds.find(d => d.id === this.domain)) this.domain = ds[0].id;
        const dom = ds.find(d => d.id === this.domain);
        const modes = dom.modes || [];
        if (!this.mode || !modes.find(m => m.id === this.mode)) this.mode = (modes[0] || {}).id;
        const mode = modes.find(m => m.id === this.mode) || modes[0] || { inputs: [] };

        let html = '';
        // Onglets DOMAINE = vrais ONGLETS (nav-tabs), conditionnels (seulement si >1 domaine).
        // Le DOMAINE est un onglet (axe supérieur) ; le MODE reste un bouton/pill (dans le domaine).
        if (ds.length > 1) {
            html += '<ul class="wm-domains nav nav-tabs mb-3" role="tablist">';
            ds.forEach(d => {
                html += `<li class="nav-item" role="presentation">
                    <button type="button" class="nav-link ${d.id === this.domain ? 'active' : ''} wm-domain" data-domain="${d.id}" role="tab">
                        ${d.icon ? `<i class="fas ${esc(d.icon)} me-1"></i>` : ''}${esc(d.label)}</button></li>`;
            });
            html += '</ul>';
        }
        // Switch de MODE (si >1 mode dans le domaine)
        if (modes.length > 1) {
            if (this.modesLabel) {
                html += `<label class="form-label text-light">${esc(this.modesLabel)}</label>`;
            }
            // Couleur : priorité au mode (m.variant), sinon override create(), sinon domaine, sinon défaut.
            const domVariant = this.modeVariant || dom.variant || 'secondary';
            const wrapCls = this.block ? 'wm-modes btn-group w-100 flex-wrap mb-2' : 'wm-modes d-flex flex-wrap gap-1 mb-2';
            html += `<div class="${wrapCls}" role="tablist">`;
            modes.forEach(m => {
                const variant = m.variant || domVariant;
                const cls = m.id === this.mode ? `btn-${variant}` : `btn-outline-${variant}`;
                html += `<button type="button" class="btn btn-sm ${cls} wm-mode" data-mode="${m.id}">
                    ${m.icon ? `<i class="fas ${esc(m.icon)} me-1"></i>` : ''}${esc(m.label)}${m.realtime ? ' <i class="fas fa-bolt fa-xs text-warning" title="Temps réel"></i>' : ''}</button>`;
            });
            html += '</div>';
        }
        // Le champ du RÉGLAGE de mode (si le domaine le déclare) : ce que lisent l'inspecteur,
        // les préférences et `WamaParams` (`options_mode`) — jamais les boutons eux-mêmes.
        const param = this._param();
        if (param && modes.length > 1) {
            html += `<input type="hidden" class="wm-param" name="${esc(param)}" data-param="${esc(param)}" value="${esc(this.mode)}">`;
        }
        // ENTRÉES typées du mode (sautées si renderInputs=false : l'app garde les siennes)
        if (this.renderInputs) {
            html += '<div class="wm-inputs">';
            const types = this.schema.input_types || {};
            (mode.inputs || []).forEach(key => {
                const inp = Object.assign({ id: key, label: key, kind: 'text' }, types[key] || {});
                inp.id = key;
                html += renderInput(inp);
            });
            html += '</div>';
            // Slot RÉGLAGES (l'app y injecte ses widgets pour ce mode)
            html += '<div class="wm-settings" data-domain="' + esc(this.domain) + '" data-mode="' + esc(this.mode) + '"></div>';
        }

        this.container.innerHTML = html;
        this._bind();
        this._applySections();
        // La valeur du mode est ANNONCÉE à chaque rendu (le premier compris) : ce qui en dépend —
        // un menu de modèles borné par le mode (`options_mode`) — a pu se remplir avant que le
        // switch n'existe. Un `change` émis par code n'est jamais pris pour un geste
        // (l'enregistrement au geste n'écoute que les événements « trusted » et `wama:user-edit`).
        const field = this.container.querySelector('.wm-param');
        if (field) field.dispatchEvent(new Event('change', { bubbles: true }));
        this.onChange({ domain: this.domain, mode: this.mode, modeDef: mode, realtime: !!mode.realtime,
                        external: !!quiet });
    };

    WamaModes.prototype._bind = function () {
        const self = this;
        this.container.querySelectorAll('.wm-domain').forEach(b => b.addEventListener('click', function () {
            self.domain = this.dataset.domain; self.mode = null; self._render();
        }));
        this.container.querySelectorAll('.wm-mode').forEach(b => b.addEventListener('click', function (e) {
            if (this.dataset.mode === self.mode) return;
            self.mode = this.dataset.mode; self._render();
            // Un GESTE de l'utilisateur (le rendu a déjà annoncé la nouvelle valeur) :
            // l'enregistrement au geste est prévenu.
            const field = self.container.querySelector('.wm-param');
            if (field && e.isTrusted) {
                field.dispatchEvent(new CustomEvent('wama:user-edit', { bubbles: true }));
            }
        }));
        // Bouton « médiathèque » : ouvre MediaPicker (filtré par type), stocke le File choisi.
        this.container.querySelectorAll('.wm-lib').forEach(b => b.addEventListener('click', function () {
            if (!window.MediaPicker) return;
            const target = self.container.querySelector('#' + CSS.escape(this.dataset.for));
            MediaPicker.open({
                type: this.dataset.type,
                onSelect: function (file) {
                    if (!target) return;
                    target._wamaPicked = file;   // File renvoyé par MediaPicker → traité comme un upload
                    const lbl = self.container.querySelector('[data-picked-for="' + target.id + '"]');
                    if (lbl) lbl.textContent = '🗂 ' + (file && file.name ? file.name : 'média sélectionné');
                },
            });
        }));
    };

    WamaModes.prototype.settingsSlot = function () {
        return this.container ? this.container.querySelector('.wm-settings') : null;
    };

    WamaModes.prototype.getState = function () {
        const inputs = {};
        this.container.querySelectorAll('[data-input]').forEach(el => {
            if (el.type === 'file') {
                // Fichier choisi via médiathèque (MediaPicker) > sinon upload natif.
                inputs[el.dataset.input] = el._wamaPicked ? [el._wamaPicked] : el.files;
            } else {
                inputs[el.dataset.input] = el.value;
            }
        });
        return { domain: this.domain, mode: this.mode, inputs: inputs };
    };

    global.WamaModes = {
        create: function (cfg) { return new WamaModes(cfg); },
        fetch: function (app) { return fetch('/common/api/app-modes/' + app + '/').then(r => r.json()); },
    };
})(window);
