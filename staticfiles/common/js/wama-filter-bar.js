/**
 * WAMA — Barre de filtrage COMMUNE : recherche + facettes, en DIRECT (aucun bouton « Filtrer »).
 *
 * POURQUOI CETTE BRIQUE. Le même geste était écrit TROIS fois — `applyFilters()` du model
 * manager (~50 l. inline), `#fcSearch` du catalogue de fonctions, `#li-q` des licences — deux
 * pages en manquaient (apps, librairies) et le journal en avait ajouté une quatrième, à boutons.
 * Relevé et arbitré par Fabien le 2026-08-20 : une seule barre, réutilisable partout.
 *
 * DEUX MODES, UN SEUL GESTE POUR L'UTILISATEUR
 *   • `client` (défaut) — tous les éléments sont dans le DOM : on montre/masque, c'est instantané.
 *     C'est le cas des catalogues (modèles, apps, licences, librairies, fonctions).
 *   • `server` — la liste est PAGINÉE (journal : 25 sur 207) : filtrer côté client ne filtrerait
 *     que la page courante, donc mentirait. La barre soumet alors son formulaire, débouncée.
 *     Le geste est identique à l'écran ; seul le mécanisme diffère.
 *
 * LES OPTIONS SE DÉRIVENT DU DOM en mode client (`data-f-<facette>`) : une option ne peut pas
 * mentir puisqu'elle vient de ce qui est affiché, et une page n'a rien à déclarer. En mode
 * server, le DOM ne porte qu'une page — les options DOIVENT donc être déclarées côté serveur.
 *
 * MONTAGE : automatique sur `[data-wama-filter-bar]`. Aucune page n'écrit de JS.
 */
(function (global) {
    'use strict';

    var DEBOUNCE_MS = 350;          // frappe au clavier — assez pour ne pas soumettre à chaque touche

    function $(sel, racine) { return (racine || document).querySelector(sel); }
    function $$(sel, racine) { return Array.prototype.slice.call((racine || document).querySelectorAll(sel)); }

    /** Texte cherchable d'un élément : `data-f-text` s'il est fourni, sinon son texte rendu. */
    function texteDe(el) {
        var t = el.getAttribute('data-f-text');
        return (t !== null ? t : el.textContent || '').toLowerCase();
    }

    /** Construit les <option> d'une facette à partir des valeurs PRÉSENTES dans le DOM. */
    function derivierOptions(select, elements, cle) {
        var vues = {};
        elements.forEach(function (el) {
            var v = el.getAttribute('data-f-' + cle);
            if (v) { vues[v] = true; }
        });
        Object.keys(vues).sort().forEach(function (v) {
            var o = document.createElement('option');
            o.value = v;
            o.textContent = v;
            select.appendChild(o);
        });
    }

    function init(cfg) {
        var bar = typeof cfg.bar === 'string' ? $(cfg.bar) : cfg.bar;
        if (!bar) { return null; }

        var mode = cfg.mode || bar.getAttribute('data-mode') || 'client';
        var selCible = cfg.cible || bar.getAttribute('data-cible');
        var recherche = $('[data-f-role="recherche"]', bar);
        var effacer = $('[data-f-role="effacer"]', bar);
        var compteur = $('.wama-filter-count', bar);
        var reset = $('.wama-filter-reset', bar);
        var vide = cfg.vide ? $(cfg.vide) : $('.wama-filter-empty');
        var selects = $$('[data-f-facette]', bar);
        var form = bar.closest('form') || (cfg.form ? $(cfg.form) : null);

        var elements = selCible ? $$(selCible) : [];

        // Mode client : les facettes se remplissent de ce qui est réellement affiché.
        if (mode === 'client') {
            selects.forEach(function (s) {
                if (s.options.length <= 1) { derivierOptions(s, elements, s.getAttribute('data-f-facette')); }
            });
        }

        function actif() {
            if (recherche && recherche.value.trim()) { return true; }
            return selects.some(function (s) { return s.value && s.value !== 'all'; });
        }

        function appliquerClient() {
            var q = recherche ? recherche.value.toLowerCase().trim() : '';
            var visibles = 0;
            elements.forEach(function (el) {
                var ok = true;
                for (var i = 0; i < selects.length && ok; i++) {
                    var s = selects[i], v = s.value;
                    if (v && v !== 'all' && el.getAttribute('data-f-' + s.getAttribute('data-f-facette')) !== v) {
                        ok = false;
                    }
                }
                if (ok && q && texteDe(el).indexOf(q) === -1) { ok = false; }
                el.style.display = ok ? '' : 'none';
                if (ok) { visibles++; }
            });
            // GROUPES — un en-tête de section n'a pas de sens si sa section est vide. Sans ça,
            // filtrer une page groupée (catalogue d'apps par catégorie, frise par mois) laisse
            // des titres qui n'annoncent plus rien : l'utilisateur lit « Créer » au-dessus du
            // vide. Le groupe se déclare par `data-f-groupe` sur le conteneur qui EMBRASSE
            // l'en-tête ET les éléments.
            // ⚠ On ne considère QUE les groupes qui contiennent des éléments DE CETTE barre.
            // Chercher `[data-f-groupe]` dans tout le document sans ce rattachement ferait que,
            // sur une page à deux barres, l'une forcerait la visibilité des groupes de l'autre
            // (leurs éléments ne matchant pas son `cible`, elle les croirait vides d'enjeu).
            // Aucun bug aujourd'hui — une seule page a des groupes — mais c'est un piège posé
            // pour le prochain adoptant, et il ne coûte rien à désamorcer maintenant.
            $$('[data-f-groupe]').forEach(function (g) {
                var dedans = elements.filter(function (e) { return g.contains(e); });
                if (!dedans.length) { return; }          // groupe d'une AUTRE barre : on n'y touche pas
                var visiblesIci = dedans.filter(function (e) { return e.style.display !== 'none'; });
                g.style.display = visiblesIci.length ? '' : 'none';
            });

            if (compteur) {
                compteur.textContent = visibles === elements.length
                    ? elements.length + ' élément' + (elements.length > 1 ? 's' : '')
                    : visibles + ' sur ' + elements.length;
            }
            if (vide) { vide.style.display = (visibles === 0 && elements.length) ? 'block' : 'none'; }
        }

        var minuteur = null;
        function soumettre() {
            if (!form) { return; }
            // Repartir de la 1re page : garder l'offset sur un filtre changé afficherait « 26–50
            // sur 3 », c.-à-d. rien, sans dire pourquoi.
            var off = form.querySelector('[name="offset"]');
            if (off) { off.value = 0; }
            form.submit();
        }

        function surChangement(immediat) {
            if (effacer) { effacer.style.display = (recherche && recherche.value) ? '' : 'none'; }
            bar.classList.toggle('is-filtered', actif());
            if (mode === 'client') { appliquerClient(); return; }
            if (minuteur) { clearTimeout(minuteur); }
            minuteur = setTimeout(soumettre, immediat ? 0 : DEBOUNCE_MS);
        }

        selects.forEach(function (s) {
            s.addEventListener('change', function () { surChangement(true); });
        });
        if (recherche) {
            recherche.addEventListener('input', function () { surChangement(false); });
            // Entrée = « maintenant », sans attendre le debounce. Et on empêche la soumission
            // native, qui doublerait la nôtre.
            recherche.addEventListener('keydown', function (ev) {
                if (ev.key === 'Enter') { ev.preventDefault(); surChangement(true); }
            });
        }
        if (effacer) {
            effacer.addEventListener('click', function () {
                if (recherche) { recherche.value = ''; recherche.focus(); }
                surChangement(true);
            });
        }
        if (reset && mode === 'client') {
            reset.addEventListener('click', function (ev) {
                ev.preventDefault();
                if (recherche) { recherche.value = ''; }
                selects.forEach(function (s) { s.value = 'all'; });
                surChangement(true);
            });
        }

        // État initial : compteur juste et « Réinitialiser » cohérent, sans rien soumettre.
        if (effacer) { effacer.style.display = (recherche && recherche.value) ? '' : 'none'; }
        bar.classList.toggle('is-filtered', actif());
        if (mode === 'client') { appliquerClient(); }

        return { appliquer: surChangement, elements: elements };
    }

    function autoInit() {
        $$('[data-wama-filter-bar]').forEach(function (bar) {
            if (bar.getAttribute('data-monte') === '1') { return; }
            bar.setAttribute('data-monte', '1');
            init({ bar: bar });
        });
    }

    global.WamaFilterBar = { init: init, autoInit: autoInit };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', autoInit);
    } else {
        autoInit();
    }
})(window);
