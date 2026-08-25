/**
 * WamaPromptEnrich — champ prompt à DEUX ÉTATS (le mien / l'enrichi).
 *
 * Pourquoi un seul champ et pas deux : deux champs éditables = deux sources de vérité. Si
 * l'utilisateur modifie l'original après enrichissement, l'enrichi devient périmé en silence et
 * plus rien ne dit lequel part au modèle. Ici le champ contient TOUJOURS ce qui sera envoyé ;
 * l'original reste consultable (lecture seule) et récupérable en un clic.
 *
 * Contrat de données (aligné sur common/utils/app_metadata.py) :
 *   - `original`  = ce que l'utilisateur a tapé (champ `prompt` en base, jamais écrasé) ;
 *   - `processed` = l'enrichi (`prompt_processed`), vide si aucun enrichissement ;
 *   - l'état courant est exposé sur le champ via `data-prompt-state` = "user" | "processed",
 *     que le formulaire poste pour que le serveur sache DANS QUEL CHAMP écrire l'édition.
 *
 * Transparence : la barre d'état n'apparaît QUE s'il y a quelque chose à dire (règle
 * WAMA_LLM.md — silence si le prompt est parti tel quel).
 *
 * Usage :
 *   WamaPromptEnrich.attach('#id_prompt', {
 *       app: 'imager', domain: 'image', csrf: token,
 *       original: '...', processed: '...', keywords: ['clair-obscur']
 *   });
 */
(function (global) {
    'use strict';

    var ENDPOINT = '/common/api/enrich-prompt/';
    var _byField = [];

    function esc(s) {
        var d = document.createElement('div');
        d.textContent = s == null ? '' : String(s);
        return d.innerHTML;
    }

    function Ctrl(field, cfg) {
        this.field = field;
        this.cfg = cfg || {};
        this.original = cfg.original != null ? cfg.original : field.value;
        this.processed = cfg.processed || '';
        this.keywords = cfg.keywords || [];
        this._build();
        this.render();
    }

    Ctrl.prototype._build = function () {
        var bar = document.createElement('div');
        bar.className = 'wama-prompt-enrich small mt-1';
        var panel = document.createElement('pre');
        panel.className = 'wama-prompt-enrich-original small text-white-50 border border-secondary '
                        + 'rounded p-2 mt-1 mb-0';
        panel.style.whiteSpace = 'pre-wrap';
        panel.style.display = 'none';
        this.field.insertAdjacentElement('afterend', panel);
        this.field.insertAdjacentElement('afterend', bar);
        this.bar = bar;
        this.panel = panel;

        var self = this;
        bar.addEventListener('click', function (e) {
            var a = e.target.closest('[data-act]');
            if (!a) return;
            e.preventDefault();
            var act = a.getAttribute('data-act');
            if (act === 'show') self.toggleOriginal();
            else if (act === 'revert') self.revert();
            else if (act === 'redo') self.enrich();
        });

        // Édition manuelle : l'utilisateur reprend la main sur le texte affiché.
        this.field.addEventListener('input', function () {
            if (self.state() === 'processed') self.processed = self.field.value;
            else self.original = self.field.value;
            self._autosize();
        });
    };

    /** État courant : "processed" si un enrichi est en place, sinon "user". */
    Ctrl.prototype.state = function () {
        return this.processed && this.processed.trim() ? 'processed' : 'user';
    };

    /**
     * Le champ s'adapte à ce qu'il contient.
     * Un prompt enrichi fait 5 à 10 fois la longueur de l'original : à hauteur fixe,
     * l'utilisateur ne voit qu'un tiers de ce qui va réellement partir au modèle — ce qui vide
     * de son sens le fait de le lui montrer. Plafonné pour ne pas pousser la page.
     */
    Ctrl.prototype._autosize = function () {
        var f = this.field;
        if (!f || f.tagName !== 'TEXTAREA') return;
        f.style.height = 'auto';
        f.style.height = Math.min(f.scrollHeight, 320) + 'px';
        f.style.overflowY = f.scrollHeight > 320 ? 'auto' : 'hidden';
    };

    Ctrl.prototype.render = function () {
        var st = this.state();
        this.field.dataset.promptState = st;
        this.field.value = st === 'processed' ? this.processed : this.original;
        this._autosize();

        if (st !== 'processed') {           // rien à dire → silence complet
            this.bar.innerHTML = '';
            this.panel.style.display = 'none';
            return;
        }
        this.bar.innerHTML =
            '<span class="text-warning">&#10024; Enrichi</span>'
            + ' <span class="text-white-50">&middot;</span>'
            + ' <a href="#" data-act="show" class="text-info">voir mon prompt</a>'
            + ' <span class="text-white-50">&middot;</span>'
            + ' <a href="#" data-act="revert" class="text-info">revenir au mien</a>'
            + ' <span class="text-white-50">&middot;</span>'
            + ' <a href="#" data-act="redo" class="text-info">&#8635; ré-enrichir</a>';
        this.panel.innerHTML = esc(this.original);
    };

    Ctrl.prototype.toggleOriginal = function () {
        var hidden = this.panel.style.display === 'none';
        this.panel.style.display = hidden ? 'block' : 'none';
        var link = this.bar.querySelector('[data-act="show"]');
        if (link) link.textContent = hidden ? 'masquer mon prompt' : 'voir mon prompt';
    };

    /** Retour au prompt de l'utilisateur : l'enrichi est abandonné (et le serveur le videra). */
    Ctrl.prototype.revert = function () {
        this.processed = '';
        this.render();
        this.field.focus();
        if (this.cfg.onChange) this.cfg.onChange(this.snapshot());
    };

    /** Pose un enrichi (retour du bouton ✨ ou d'un ré-enrichissement). */
    Ctrl.prototype.setProcessed = function (text) {
        this.processed = text || '';
        this.render();
        if (window.WamaPromptChips) WamaPromptChips.refreshFor(this.field);
        if (this.cfg.onChange) this.cfg.onChange(this.snapshot());
    };

    Ctrl.prototype.enrich = function () {
        var self = this;
        var link = this.bar.querySelector('[data-act="redo"]');
        if (link) link.textContent = '…';
        // Ré-enrichir part TOUJOURS du prompt de l'utilisateur, jamais de l'enrichi précédent :
        // enrichir un enrichi empile les couches de style et finit par noyer le sujet.
        var kws = (window.WamaPromptChips ? WamaPromptChips.activeFor(this.field) : null)
                  || this.keywords;
        fetch(this.cfg.endpoint || ENDPOINT, {
            method: 'POST',
            headers: {'Content-Type': 'application/json', 'X-CSRFToken': this.cfg.csrf},
            body: JSON.stringify({
                prompt: this.original, app: this.cfg.app,
                domain: this.cfg.domain, keywords: kws
            })
        })
        .then(function (r) { return r.json(); })
        .then(function (d) {
            if (d.enhanced) self.setProcessed(d.enhanced);
            else self.render();
        })
        .catch(function () { self.render(); });
    };

    Ctrl.prototype.snapshot = function () {
        return {state: this.state(), original: this.original, processed: this.processed};
    };

    global.WamaPromptEnrich = {
        attach: function (field, cfg) {
            if (typeof field === 'string') field = document.querySelector(field);
            if (!field) return null;
            var existing = this.get(field);
            if (existing) {                       // ré-attache (modale rouverte sur un autre item)
                existing.original = cfg.original != null ? cfg.original : field.value;
                existing.processed = cfg.processed || '';
                existing.keywords = cfg.keywords || [];
                existing.cfg = Object.assign(existing.cfg, cfg);
                existing.render();
                return existing;
            }
            var c = new Ctrl(field, cfg || {});
            _byField.push(c);
            return c;
        },

        get: function (field) {
            if (typeof field === 'string') field = document.querySelector(field);
            for (var i = 0; i < _byField.length; i++) {
                if (_byField[i].field === field) return _byField[i];
            }
            return null;
        },

        /** Pose un enrichi sur un champ déjà attaché (utilisé par le bouton ✨ des apps). */
        setProcessed: function (field, text) {
            var c = this.get(field);
            if (c) c.setProcessed(text);
            return c;
        },
    };
})(window);
