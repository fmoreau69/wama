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
 *
 * Mode GESTION (`manage: true`, médiathèque — 2026-10-27, ROADMAP §29) : la liste est celle que
 * le compte VOIT (`?manage=1`), et un clic sur un mot-clé ouvre sa provenance et ses gestes, lus
 * sur ses FAITS (`media_library/keywords.as_dict`) : partager, copier, demander la promotion,
 * rendre système, supprimer. La palette sous un prompt, elle, ne change pas.
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
        var params = [];
        if (this.domain) params.push('domain=' + encodeURIComponent(this.domain));
        if (this.manage) params.push('manage=1');
        var url = '/media-library/api/keywords/' + (params.length ? '?' + params.join('&') : '');
        this.container.innerHTML = '<div class="text-muted small">Chargement des mots-clés…</div>';
        fetch(url, { headers: { 'X-Requested-With': 'XMLHttpRequest' } })
            .then(function (r) {
                if (!r.ok) { throw new Error('HTTP ' + r.status); }
                return r.json();
            })
            .then(function (data) {
                self.cats = data.categories || {};
                // Mode gestion : les portées offertes et les adresses des gestes (serveur).
                self.gestures = self.manage ? {
                    scopes: data.scopes || [], api: data.manage_api || '',
                    promotionApi: data.promotion_api || '', registry: data.registry || '',
                } : null;
                self.byId = {};
                Object.keys(self.cats).forEach(function (k) {
                    (self.cats[k].items || []).forEach(function (kw) { self.byId[kw.id] = kw; });
                });
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
                // `kw.common` : mot-clé du TRONC COMMUN (sans propriétaire) — pas de croix, on
                // ne supprime que les siens. La clé s'appelait `shared` jusqu'au 2026-09-26 ;
                // « partagé » a un autre sens dans WAMA (cf. `PromptKeyword.to_dict`).
                var removable = self.manage ? !!kw.can_delete : !kw.common;
                var del = !removable ? '' :
                    '<span class="wpc-del" data-del="' + kw.id + '" title="Supprimer ce mot-clé perso">&times;</span>';
                // Esthétique des boutons d'action des cards : btn-outline-X (plein quand actif), pill.
                var cls = 'wpc-chip btn btn-sm rounded-pill btn-' + (on ? '' : 'outline-') + v;
                inner += '<button type="button" class="' + cls
                    + '" data-kw="' + esc(kw.text) + '" data-variant="' + v + '" data-id="' + kw.id + '"'
                    + (self.manage && kw.provenance ? ' title="' + esc(kw.provenance) + '"' : '')
                    + (kw.common ? '' : ' data-perso="1"') + '>'
                    + esc(kw.text) + del + '</button>';
            });
            inner += '</span></div>';
            if (self.manage) inner += '<div class="wpc-detail small" data-detail="' + esc(cat) + '"></div>';
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
                if (self.manage) { self._detail(this.dataset.id, this); return; }  // gestion : ses gestes
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

    // Mode gestion : la provenance et les gestes d'UN mot-clé, sous sa catégorie. Les droits sont
    // ceux que dit le serveur (`can_*`) — rien n'est décidé ici.
    Chips.prototype._detail = function (id, chip) {
        var self = this, kw = this.byId[id], g = this.gestures;
        var box = chip.closest('.wpc-cat').nextElementSibling;
        if (!kw || !g || !box) return;
        if (box.dataset.open === String(id)) { box.innerHTML = ''; box.dataset.open = ''; return; }
        var html = '<span class="me-2">' + esc(kw.provenance || '')
            + (kw.scope_label ? ' · ' + esc(kw.scope_label) : '')
            + (kw.promotion_pending ? ' · promotion demandée' : '') + '</span>';
        if (kw.can_share) {
            html += '<select class="form-select form-select-sm d-inline-block w-auto py-0 wpc-scope" aria-label="Portée">';
            g.scopes.forEach(function (o) {
                html += '<option value="' + esc(o.value) + '"' + (o.value === kw.scope ? ' selected' : '')
                    + '>' + esc(o.label) + '</option>';
            });
            html += '</select> <button type="button" class="btn btn-sm btn-outline-secondary py-0" data-act="share">Partager</button> ';
        }
        if (kw.can_copy) html += '<button type="button" class="btn btn-sm btn-outline-secondary py-0" data-act="copy">Copier dans les miens</button> ';
        if (kw.can_request_promotion && g.promotionApi) {
            html += '<button type="button" class="btn btn-sm btn-outline-success py-0" data-promotion-request="'
                + esc(g.promotionApi) + '" data-registry="' + esc(g.registry) + '" data-pk="' + kw.id
                + '">Demander la promotion</button> ';
        }
        if (kw.promotion_request_url) html += '<a class="btn btn-sm btn-outline-secondary py-0" href="' + esc(kw.promotion_request_url) + '">Voir la demande</a> ';
        if (kw.can_promote) html += '<button type="button" class="btn btn-sm btn-outline-success py-0" data-act="promote">Rendre système</button> ';
        box.innerHTML = html;
        box.dataset.open = String(id);
        box.querySelectorAll('[data-act]').forEach(function (b) {
            b.addEventListener('click', function () {
                var act = this.dataset.act;
                if (act === 'promote' && !confirm('Rendre ce mot-clé système ? Il ne sera plus à son auteur.')) return;
                var payload = { action: act, pk: kw.id };
                if (act === 'share') payload.scope = box.querySelector('.wpc-scope').value;
                self._act(payload);
            });
        });
    };

    Chips.prototype._act = function (payload) {
        var self = this, headers = csrf();
        headers['Content-Type'] = 'application/json';
        fetch(this.gestures.api, { method: 'POST', headers: headers, body: JSON.stringify(payload) })
            .then(function (r) { return r.json(); })
            .then(function (d) {
                if (d && d.success) { self._load(); return; }
                var msg = (d && d.error) || 'Échec';
                if (global.WamaApp && WamaApp.toast) WamaApp.toast(msg, 'danger'); else console.warn(msg);
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

    // Registre des instances : permet de retrouver les mots-clés ACTIFS d'un champ prompt
    // depuis l'extérieur (enrichissement ✨) sans que l'app ait à garder la référence.
    var _instances = [];

    global.WamaPromptChips = {
        init: function (cfg) { var c = new Chips(cfg); _instances.push(c); return c; },

        /**
         * Mots-clés actifs d'un champ prompt (élément ou sélecteur) → Array.
         * Ce sont des termes CHOISIS par l'utilisateur, pas de la prose : ils partent en
         * glossaire d'enrichissement pour être préservés VERBATIM (sinon le LLM les
         * reformule et le chip s'éteint tout seul). Cf. common/views.api_enrich_prompt.
         */
        activeFor: function (el) {
            var c = this.instanceFor(el);
            return c ? Array.from(c.active) : [];
        },

        /** Instance pilotant un champ prompt (élément ou sélecteur), ou null. */
        instanceFor: function (el) {
            if (typeof el === 'string') el = document.querySelector(el);
            if (!el) return null;
            for (var i = 0; i < _instances.length; i++) {
                if (_instances[i].target === el) return _instances[i];
            }
            return null;
        },

        /** Resynchronise l'état visuel des chips après un changement externe du champ. */
        refreshFor: function (el) {
            var c = this.instanceFor(el);
            if (c) c.refresh();
        },
    };
})(window);
