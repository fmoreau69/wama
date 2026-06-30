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
        this._render();
    }

    WamaModes.prototype._domains = function () {
        return (this.schema && this.schema.domains) || [];
    };

    WamaModes.prototype._render = function () {
        const ds = this._domains();
        if (!this.container) return;
        if (!ds.length) { this.container.innerHTML = ''; return; }

        if (!this.domain || !ds.find(d => d.id === this.domain)) this.domain = ds[0].id;
        const dom = ds.find(d => d.id === this.domain);
        const modes = dom.modes || [];
        if (!this.mode || !modes.find(m => m.id === this.mode)) this.mode = (modes[0] || {}).id;
        const mode = modes.find(m => m.id === this.mode) || modes[0] || { inputs: [] };

        let html = '';
        // Onglets DOMAINE (conditionnels : seulement si >1 domaine)
        if (ds.length > 1) {
            html += '<div class="wm-domains btn-group btn-group-sm mb-2" role="tablist">';
            ds.forEach(d => {
                html += `<button type="button" class="btn ${d.id === this.domain ? 'btn-primary' : 'btn-outline-primary'} wm-domain" data-domain="${d.id}">
                    ${d.icon ? `<i class="fas ${esc(d.icon)} me-1"></i>` : ''}${esc(d.label)}</button>`;
            });
            html += '</div>';
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
        this.onChange({ domain: this.domain, mode: this.mode, modeDef: mode, realtime: !!mode.realtime });
    };

    WamaModes.prototype._bind = function () {
        const self = this;
        this.container.querySelectorAll('.wm-domain').forEach(b => b.addEventListener('click', function () {
            self.domain = this.dataset.domain; self.mode = null; self._render();
        }));
        this.container.querySelectorAll('.wm-mode').forEach(b => b.addEventListener('click', function () {
            self.mode = this.dataset.mode; self._render();
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
