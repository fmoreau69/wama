/*
 * WamaPromptChips — palette de mots-clés cliquables pour enrichir un prompt.
 * Source = bibliothèque médiathèque (tronc commun partagé + perso), endpoint
 * /media-library/api/keywords/. Click sur un chip = insère/retire le mot-clé dans
 * le champ prompt cible. Affordance « + perso » pour ajouter ses propres mots-clés.
 *
 * Usage :
 *   WamaPromptChips.init({
 *     container: '#promptChips',     // où rendre la palette
 *     target:    '#id_prompt',       // <textarea>/<input> prompt à enrichir
 *     domain:    'image',            // optionnel : filtre par domaine
 *   });
 *
 * Métadonnée-driven : aucune liste codée en dur côté app. La bibliothèque vit dans
 * la médiathèque (modèle PromptKeyword), partagée et extensible par utilisateur.
 */
(function (global) {
    'use strict';

    function esc(s) {
        if (global.WamaApp && WamaApp.escapeHtml) return WamaApp.escapeHtml(s);
        return String(s == null ? '' : s).replace(/[&<>"']/g, function (m) {
            return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[m];
        });
    }

    // Variant Bootstrap par catégorie → même esthétique que les boutons d'action des cards
    // (btn-outline-X ; contour+texte, fond seulement à l'état plein). Inconnue → primary.
    var CAT_VARIANTS = {
        quality: 'success',
        style:   'primary',
        light:   'warning',
        mood:    'danger',
        camera:  'info',
        render:  'secondary',
        domain:  'light',    // 'dark' serait invisible sur fond sombre
    };
    function catVariant(cat) { return CAT_VARIANTS[cat] || 'primary'; }

    // Bascule un chip entre contour (outline) et plein, selon son variant Bootstrap.
    function setChipOn(btn, on) {
        var v = btn.dataset.variant || 'primary';
        btn.classList.toggle('btn-' + v, on);
        btn.classList.toggle('btn-outline-' + v, !on);
    }

    function csrf() {
        if (global.WamaApp && WamaApp.csrfHeaders) return WamaApp.csrfHeaders();
        var m = document.cookie.match(/csrftoken=([^;]+)/);
        return { 'X-CSRFToken': m ? m[1] : '' };
    }

    function Chips(cfg) {
        this.container = typeof cfg.container === 'string'
            ? document.querySelector(cfg.container) : cfg.container;
        this.target = typeof cfg.target === 'string'
            ? document.querySelector(cfg.target) : cfg.target;
        this.domain = cfg.domain || '';
        // Mode gestion (médiathèque) : pas de prompt cible — clic chip = no-op, seuls add/del perso comptent.
        this.manage = !!cfg.manage;
        // Callback optionnel(n) appelé avec le nombre total de mots-clés (ex : MAJ d'un badge d'onglet).
        this.onCount = typeof cfg.onCount === 'function' ? cfg.onCount : null;
        // collapsed : palette repliée derrière un en-tête (gain de place sous un prompt). Par défaut
        // repliée SAUF en mode gestion (médiathèque) où tout voir est l'objectif.
        this.collapsed = cfg.collapsed != null ? !!cfg.collapsed : !this.manage;
        this._open = false;        // état d'ouverture de l'accordéon
        this.active = new Set();   // textes de mots-clés actuellement insérés
        if (this.container && (this.target || this.manage)) this._load();
    }

    Chips.prototype._load = function () {
        var self = this;
        var url = '/media-library/api/keywords/' + (this.domain ? '?domain=' + encodeURIComponent(this.domain) : '');
        this.container.innerHTML = '<div class="text-muted small">Chargement des mots-clés…</div>';
        fetch(url, { headers: { 'X-Requested-With': 'XMLHttpRequest' } })
            .then(function (r) {
                if (!r.ok) { throw new Error('HTTP ' + r.status); }
                return r.json();
            })
            .then(function (data) {
                self.cats = data.categories || {};
                var n = Object.keys(self.cats).reduce(function (a, k) { return a + (self.cats[k].items || []).length; }, 0);
                console.debug('[WamaPromptChips]', url, '→', n, 'mot(s)-clé(s)');
                if (self.onCount) self.onCount(n);
                self._render();
            })
            .catch(function (e) {
                console.warn('[WamaPromptChips] échec', url, e && e.message);
                self.container.innerHTML = '<div class="text-danger small">Mots-clés indisponibles ('
                    + esc((e && e.message) || 'erreur') + ').</div>';
            });
    };

    Chips.prototype._render = function () {
        var self = this;
        var keys = Object.keys(this.cats);
        var total = keys.reduce(function (a, k) { return a + (self.cats[k].items || []).length; }, 0);

        // ── Corps de la palette (catégories + ajout perso) ──────────────────────
        var inner = '';
        if (!keys.length) {
            inner += '<div class="text-muted small">Aucun mot-clé.</div>';
        }
        keys.forEach(function (cat) {
            var group = self.cats[cat];
            var v = catVariant(cat);
            inner += '<div class="wpc-cat" data-cat="' + esc(cat) + '">'
                + '<span class="wpc-cat-label">' + esc(group.label) + '</span>'
                + '<span class="wpc-chips">';
            (group.items || []).forEach(function (kw) {
                var on = self.active.has(kw.text);
                var del = kw.shared ? '' :
                    '<span class="wpc-del" data-del="' + kw.id + '" title="Supprimer ce mot-clé perso">&times;</span>';
                // Esthétique des boutons d'action des cards : btn-outline-X (plein quand actif), pill.
                var cls = 'wpc-chip btn btn-sm rounded-pill btn-' + (on ? '' : 'outline-') + v;
                inner += '<button type="button" class="' + cls
                    + '" data-kw="' + esc(kw.text) + '" data-variant="' + v + '"'
                    + (kw.shared ? '' : ' data-perso="1"') + '>'
                    + esc(kw.text) + del + '</button>';
            });
            inner += '</span></div>';
        });
        // Affordance « + perso »
        inner += '<div class="wpc-add input-group input-group-sm mt-1" style="max-width:320px;">'
            + '<select class="form-select form-select-sm wpc-add-cat" style="max-width:120px;">';
        keys.forEach(function (cat) {
            inner += '<option value="' + esc(cat) + '">' + esc(self.cats[cat].label) + '</option>';
        });
        if (!keys.length) {
            ['quality', 'style', 'light', 'mood', 'camera', 'render', 'domain'].forEach(function (c) {
                inner += '<option value="' + c + '">' + c + '</option>';
            });
        }
        inner += '</select>'
            + '<input type="text" class="form-control form-control-sm wpc-add-text" placeholder="mot-clé perso…" maxlength="120">'
            + '<button type="button" class="btn btn-outline-primary wpc-add-btn"><i class="fas fa-plus"></i></button>'
            + '</div>';

        // ── Enveloppe : accordéon replié (par défaut hors mode gestion) ou plein ──
        var html;
        if (this.collapsed) {
            var open = this._open ? ' is-open' : '';
            html = '<div class="wpc wpc-collapsible' + open + '">'
                + '<button type="button" class="wpc-head">'
                + '<i class="fas fa-wand-magic-sparkles me-1"></i>Mots-clés'
                + '<span class="wpc-count">' + total + '</span>'
                + '<i class="fas fa-chevron-down wpc-caret ms-auto"></i></button>'
                + '<div class="wpc-body"' + (this._open ? '' : ' style="display:none"') + '>' + inner + '</div>'
                + '</div>';
        } else {
            html = '<div class="wpc">' + inner + '</div>';
        }
        this.container.innerHTML = html;
        this._syncActive();
        this._bind();
    };

    // Reconstruit l'ensemble actif depuis le contenu réel du prompt (résilient aux édits manuels).
    Chips.prototype._syncActive = function () {
        if (this.manage) return;   // pas de prompt cible en mode gestion
        var txt = (this.target && this.target.value) || '';
        var self = this;
        this.active = new Set();
        this.container.querySelectorAll('.wpc-chip').forEach(function (b) {
            var kw = b.dataset.kw;
            if (kw && txt.indexOf(kw) !== -1) {
                self.active.add(kw);
                setChipOn(b, true);
            }
        });
    };

    Chips.prototype._toggle = function (kw, btn) {
        var val = this.target.value || '';
        if (this.active.has(kw)) {
            // Retirer (gère séparateurs « , kw » / « kw, » / « kw »)
            val = val.replace(new RegExp('\\s*,?\\s*' + kw.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'), 'g'), '');
            val = val.replace(/^\s*,\s*/, '').replace(/\s{2,}/g, ' ').trim();
            this.active.delete(kw);
            setChipOn(btn, false);
        } else {
            val = val.trim();
            val = val ? (val.replace(/,\s*$/, '') + ', ' + kw) : kw;
            this.active.add(kw);
            setChipOn(btn, true);
        }
        this.target.value = val;
        this.target.dispatchEvent(new Event('input', { bubbles: true }));
    };

    Chips.prototype._bind = function () {
        var self = this;
        // Accordéon : en-tête replie/déplie le corps (sans re-fetch).
        var head = this.container.querySelector('.wpc-head');
        if (head) head.addEventListener('click', function () {
            self._open = !self._open;
            var wrap = self.container.querySelector('.wpc-collapsible');
            var body = self.container.querySelector('.wpc-body');
            if (wrap) wrap.classList.toggle('is-open', self._open);
            if (body) body.style.display = self._open ? '' : 'none';
        });
        this.container.querySelectorAll('.wpc-chip').forEach(function (b) {
            b.addEventListener('click', function (e) {
                if (e.target.closest('.wpc-del')) return;  // clic sur la croix géré séparément
                if (self.manage) return;                   // mode gestion : chip non insérable
                self._toggle(this.dataset.kw, this);
            });
        });
        this.container.querySelectorAll('.wpc-del').forEach(function (x) {
            x.addEventListener('click', function (e) {
                e.stopPropagation();
                self._del(this.dataset.del);
            });
        });
        var btn = this.container.querySelector('.wpc-add-btn');
        if (btn) btn.addEventListener('click', function () { self._add(); });
        var inp = this.container.querySelector('.wpc-add-text');
        if (inp) inp.addEventListener('keydown', function (e) {
            if (e.key === 'Enter') { e.preventDefault(); self._add(); }
        });
    };

    Chips.prototype._add = function () {
        var self = this;
        var inp = this.container.querySelector('.wpc-add-text');
        var sel = this.container.querySelector('.wpc-add-cat');
        var text = (inp && inp.value || '').trim();
        if (!text) return;
        var fd = new FormData();
        fd.append('text', text);
        fd.append('category', sel ? sel.value : 'style');
        fetch('/media-library/api/keywords/add/', { method: 'POST', headers: csrf(), body: fd })
            .then(function (r) { return r.json(); })
            .then(function (d) { if (d && d.success) { if (inp) inp.value = ''; self._load(); } });
    };

    Chips.prototype._del = function (id) {
        var self = this;
        fetch('/media-library/api/keywords/' + id + '/delete/', { method: 'POST', headers: csrf() })
            .then(function (r) { return r.json(); })
            .then(function () { self._load(); });
    };

    // Resynchronise les chips si le prompt change ailleurs (ex : enrichissement, reset).
    Chips.prototype.refresh = function () { this._syncActive(); };

    global.WamaPromptChips = {
        init: function (cfg) { return new Chips(cfg); },
    };
})(window);
