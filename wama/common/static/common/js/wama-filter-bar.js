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
 *   • `remote` (2026-10-01, médiathèque) — la page CHARGE ELLE-MÊME sa liste (fetch paginé) :
 *     soumettre un formulaire la rechargerait, filtrer le DOM mentirait (une page sur N). La
 *     barre ne fait alors que DIRE ce qui est demandé : à chaque changement, débouncé, elle
 *     émet `wama:filter-change` (detail = `state()` : `{q, facets, sort}`) ; la page recharge
 *     et écrit son total par `WamaFilterBar.setCount`. Les facettes masquées (`hidden` sur leur
 *     colonne — une facette d'un autre onglet) ne comptent pas.
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

    // RECHERCHE PAR LE CONTENU (2026-10-19, `WAMA_MEMORY §7sexies`) : une requête vectorisée par
    // le serveur coûte un appel au modèle — on attend la fin de la frappe, et deux lettres ne
    // décrivent aucune image.
    var CONTENT_DEBOUNCE_MS = 600;
    var CONTENT_MIN_CHARS = 3;

    /** La clé `surface:pk` de l'élément d'une card — l'adresse de son aperçu commun, lue par la
     *  brique de la preview (`WamaMediaPreview.cardElement`) ; '' sans aperçu. */
    function elementKey(card) {
        var P = global.WamaMediaPreview;
        var el = P && P.cardElement ? P.cardElement(card) : null;
        return el ? el.surface + ':' + el.pk : '';
    }

    /** Les cards d'une entrée de file (card seule, ou card mère et ses filles). */
    function cardsOf(el) {
        return el.matches && el.matches('.wama-card') ? [el] : $$('.wama-card', el);
    }

    function $(sel, racine) { return (racine || document).querySelector(sel); }
    function $$(sel, racine) { return Array.prototype.slice.call((racine || document).querySelectorAll(sel)); }

    /** Texte cherchable d'un élément : `data-f-text` s'il est fourni, sinon son texte rendu. */
    function texteDe(el) {
        var t = el.getAttribute('data-f-text');
        return (t !== null ? t : el.textContent || '').toLowerCase();
    }

    /**
     * Masquage/affichage d'une cible — PAR CLASSE, jamais par `style.display`.
     *
     * ⚠ La brique posait `el.style.display = 'none'` et restaurait `''`. Cette restauration
     * n'est pas neutre : elle SUPPRIME la déclaration `display` de l'attribut `style`. Sur une
     * cible qui en porte une en inline, l'élément ne revient donc pas à son état d'origine.
     * Cas réel qui a imposé le changement (2026-09-08, en préparant la recherche dans la file) :
     * l'entrée unitaire de file porte `style="display:contents"` — indispensable pour que la
     * card se dispose comme si l'enrobage n'existait pas. Filtrer puis vider la recherche
     * l'aurait rendue `div` de bloc, cassant la grille jusqu'au rechargement.
     *
     * Aucun changement de comportement pour les 15 surfaces déjà montées : elles n'ont pas de
     * `display` inline, et la classe produit exactement le même rendu.
     */
    var HORS = 'wama-f-hors-filtre';
    function montrer(el, visible) { el.classList.toggle(HORS, !visible); }
    function estVisible(el) { return !el.classList.contains(HORS); }

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

    /**
     * TRI des éléments filtrés (2026-09-23, demande de Fabien sur le model manager) : le même
     * geste que le filtre, donc la même brique. Chaque élément porte `data-s-<clé>` ; la valeur
     * se compare en NOMBRE si elle en est un, sinon en texte (`localeCompare`, français). Une
     * valeur ABSENTE va toujours en dernier, quel que soit le sens : « inconnu » n'est ni le
     * meilleur ni le pire. Les éléments sont réordonnés DANS leur parent (un groupe garde les
     * siens). `spec` = « clé:asc » ou « clé:desc ».
     */
    function sortElements(elements, spec) {
        var parts = String(spec || '').split(':');
        var key = parts[0], sign = parts[1] === 'desc' ? -1 : 1;
        if (!key) { return; }
        function valueOf(el) {
            var raw = el.getAttribute('data-s-' + key);
            if (raw === null || raw === '') { return null; }
            var n = Number(raw);
            return isNaN(n) ? raw.toLowerCase() : n;
        }
        var byParent = new Map();
        elements.forEach(function (el) {
            if (!el.parentNode) { return; }
            if (!byParent.has(el.parentNode)) { byParent.set(el.parentNode, []); }
            byParent.get(el.parentNode).push(el);
        });
        byParent.forEach(function (list, parent) {
            list.map(function (el, i) { return { el: el, v: valueOf(el), i: i }; })
                .sort(function (a, b) {
                    if (a.v === null || b.v === null) {
                        return (a.v === null) - (b.v === null) || a.i - b.i;
                    }
                    var c = (typeof a.v === 'number' && typeof b.v === 'number')
                        ? a.v - b.v : String(a.v).localeCompare(String(b.v), 'fr');
                    return sign * c || a.i - b.i;
                })
                .forEach(function (entry) { parent.appendChild(entry.el); });
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

        // PORTÉE de la recherche. Par défaut le sélecteur balaie tout le document — ce qui
        // convient aux catalogues (une liste par page) mais serait FAUX sur une file : l'imager
        // et l'enhancer affichent DEUX files sur la même page, et chacune a sa barre. Sans
        // portée, taper dans la barre du haut filtrerait aussi la file du bas.
        //   `data-cible-dans="file-suivante"` — la file gouvernée est le frère SUIVANT de la
        //     barre. Aucune app n'a rien à déclarer : c'est l'invariant de placement tenu par
        //     `tests_queue_toolbar` (la barre est au-dessus de son conteneur, jamais dedans).
        //   `data-cible-dans="<sélecteur>"` — n'importe quel autre élément borne la recherche.
        var racine = null;
        var selRacine = cfg.dans || bar.getAttribute('data-cible-dans');
        if (selRacine === 'file-suivante') {
            racine = bar.nextElementSibling;
        } else if (selRacine) {
            racine = $(selRacine);
        }
        // Une portée DEMANDÉE mais introuvable ne doit pas se replier sur « tout le document » :
        // ce serait filtrer plus large que voulu, en silence. On ne monte rien et on le dit.
        if (selRacine && !racine) {
            console.warn('[WamaFilterBar] portée `' + selRacine + '` introuvable — barre non montée');
            return null;
        }
        var elements = selCible ? $$(selCible, racine || document) : [];
        // CIBLE VIVANTE (2026-09-28, calendrier) : la liste est RE-RENDUE par un composant (le
        // calendrier redessine ses événements à chaque changement de vue), donc la photo prise au
        // montage périme. Les éléments sont alors relus à chaque application, et le composant
        // appelle `WamaFilterBar.refresh(bar)` après chaque rendu. Les facettes d'une telle liste
        // se DÉCLARENT (le DOM est vide au montage), comme en mode server.
        var liveTarget = bar.getAttribute('data-cible-vivante') === '1';

        // RECHERCHE PAR LE CONTENU — barre de FILE seule (`data-content-search-url`, posé par
        // l'enveloppe `file` de `_toolbar.html`). Le filtre texte reste instantané ; quand le
        // serveur répond, une entrée dont une image correspond à la requête est AUSSI montrée
        // (union), et ses cards sont marquées `wama-content-hit`. `content.q` = la requête à
        // laquelle `content.keys` répond : une réponse à une frappe plus ancienne est ignorée.
        var contentUrl = mode === 'client' ? bar.getAttribute('data-content-search-url') : null;
        var content = { q: '', keys: null, timer: null, seq: 0 };
        var note = null;

        // Mode client : les facettes se remplissent de ce qui est réellement affiché.
        if (mode === 'client') {
            selects.forEach(function (s) {
                if (s.options.length <= 1) { derivierOptions(s, elements, s.getAttribute('data-f-facette')); }
            });
        }

        function actif() {
            if (recherche && recherche.value.trim()) { return true; }
            return $$('[data-f-facette]', bar).some(function (s) { return s.value && s.value !== 'all'; });
        }

        function contentHas(card, q) {
            return !!(content.keys && content.q === q && content.keys.has(elementKey(card)));
        }

        function contentMatches(el, q) {
            return !!(content.keys && content.q === q) && cardsOf(el).some(function (c) {
                return contentHas(c, q);
            });
        }

        /** Le mot discret qui dit ce que la recherche par contenu a fait (à côté du champ). */
        function showNote(text, title) {
            if (!note && text && recherche) {
                note = document.createElement('span');
                note.className = 'wama-content-note';
                var group = recherche.closest('.wama-filter-search') || recherche;
                group.insertAdjacentElement('afterend', note);
            }
            if (note) {
                note.textContent = text || '';
                note.title = title || '';
                note.hidden = !text;
            }
        }

        /** Demande au serveur les entrées dont une image répond à `q` (`api_queue_content_search`).
         *  Les cards nommées sont celles de CETTE file ; le serveur ne répond que pour celles que
         *  le compte peut lister, et met en tâche l'indexation de celles qui ne le sont pas. */
        function askContent(q) {
            if (!contentUrl) { return; }
            if (content.timer) { clearTimeout(content.timer); }
            if (q.length < CONTENT_MIN_CHARS) {
                content.seq++;
                content.q = ''; content.keys = null;
                showNote('');
                return;
            }
            if (q === content.q) { return; }
            content.timer = setTimeout(function () {
                if (liveTarget && selCible) { elements = $$(selCible, racine || document); }
                var seen = {}, cards = [];
                elements.forEach(function (el) {
                    cardsOf(el).forEach(function (c) {
                        var key = elementKey(c);
                        if (!key || seen[key]) { return; }
                        seen[key] = true;
                        var cut = key.lastIndexOf(':');
                        cards.push({ surface: key.slice(0, cut), pk: Number(key.slice(cut + 1)) });
                    });
                });
                if (!cards.length) { return; }
                var seq = ++content.seq;
                var app = global.WamaApp;
                var opts = { method: 'POST', headers: { 'Content-Type': 'application/json' },
                             body: JSON.stringify({ q: q, cards: cards }) };
                var call = app && app.csrfFetch
                    ? app.csrfFetch(contentUrl, app.csrfToken ? app.csrfToken() : '', opts)
                    : fetch(contentUrl, opts);
                call.then(function (r) { return r.ok ? r.json() : null; }).then(function (d) {
                    if (!d || seq !== content.seq) { return; }   // une frappe plus récente l'emporte
                    content.q = q;
                    content.keys = new Set((d.hits || []).map(function (h) { return h.surface + ':' + h.pk; }));
                    var parts = [], why = [];
                    if (d.unavailable) {
                        parts.push('contenu : indisponible');
                        why.push("Le modèle qui lit les images ne répond pas : seuls les noms sont cherchés.");
                    } else if (content.keys.size) {
                        parts.push(content.keys.size + ' par l’image');
                        why.push(content.keys.size + ' élément(s) retrouvé(s) par le contenu de leurs images.');
                    }
                    if (d.pending) {
                        parts.push(d.pending + ' à indexer');
                        why.push(d.pending + " élément(s) pas encore indexé(s) : leur indexation est en cours, "
                                 + 'en tâche de fond — relancez la recherche dans un moment.');
                    }
                    showNote(parts.join(' · '), why.join(' '));
                    appliquerClient();
                }).catch(function () { /* la recherche par les noms reste entière */ });
            }, CONTENT_DEBOUNCE_MS);
        }

        function appliquerClient() {
            if (liveTarget && selCible) { elements = $$(selCible, racine || document); }
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
                if (ok && q && texteDe(el).indexOf(q) === -1 && !contentMatches(el, q)) { ok = false; }
                montrer(el, ok);
                if (ok) { visibles++; }
                if (contentUrl) {
                    cardsOf(el).forEach(function (c) {
                        c.classList.toggle('wama-content-hit', !!(q && contentHas(c, q)));
                    });
                }
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
                montrer(g, dedans.some(estVisible));
            });

            if (compteur) {
                compteur.textContent = visibles === elements.length
                    ? elements.length + ' élément' + (elements.length > 1 ? 's' : '')
                    : visibles + ' sur ' + elements.length;
            }
            if (vide) { vide.style.display = (visibles === 0 && elements.length) ? 'block' : 'none'; }
        }

        // Mode `remote` : l'état demandé, relu à chaque fois (une page peut montrer ou masquer
        // des facettes selon son onglet). Une facette dont la colonne est masquée ne compte pas.
        function state() {
            var facets = {};
            $$('[data-f-facette]', bar).forEach(function (s) {
                var col = s.closest('[data-f-nature]');
                if (col && col.hidden) { return; }
                if (s.value && s.value !== 'all') { facets[s.getAttribute('data-f-facette')] = s.value; }
            });
            var sorter = $('[data-f-role="sort"]', bar);
            return { q: recherche ? recherche.value.trim() : '', facets: facets,
                     sort: sorter ? sorter.value : '' };
        }

        function annoncer() {
            bar.dispatchEvent(new CustomEvent('wama:filter-change', { bubbles: true, detail: state() }));
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
            if (mode === 'client') {
                appliquerClient();
                askContent(recherche ? recherche.value.toLowerCase().trim() : '');
                return;
            }
            if (minuteur) { clearTimeout(minuteur); }
            minuteur = setTimeout(mode === 'remote' ? annoncer : soumettre, immediat ? 0 : DEBOUNCE_MS);
        }

        if (mode === 'remote') {
            // DÉLÉGATION : les facettes et le tri sont lus au moment du changement, pas photographiés
            // au montage — la page peut en montrer d'autres selon l'onglet.
            bar.addEventListener('change', function (ev) {
                if (ev.target.matches('[data-f-facette], [data-f-role="sort"]')) { surChangement(true); }
            });
        } else {
            selects.forEach(function (s) {
                s.addEventListener('change', function () { surChangement(true); });
            });
        }
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
        if (reset && mode !== 'server') {
            reset.addEventListener('click', function (ev) {
                ev.preventDefault();
                if (recherche) { recherche.value = ''; }
                $$('[data-f-facette]', bar).forEach(function (s) { s.value = 'all'; });
                surChangement(true);
            });
        }

        // Tri déclaré dans la barre (`<select data-f-role="sort">`, options « clé:sens ») :
        // client seulement — une liste paginée se trie côté serveur.
        var sorter = $('[data-f-role="sort"]', bar);
        if (sorter && mode === 'client') {
            sorter.addEventListener('change', function () { sortElements(elements, sorter.value); });
            if (sorter.value) { sortElements(elements, sorter.value); }
        }

        // État initial : compteur juste et « Réinitialiser » cohérent, sans rien soumettre.
        if (effacer) { effacer.style.display = (recherche && recherche.value) ? '' : 'none'; }
        bar.classList.toggle('is-filtered', actif());
        if (mode === 'client') { appliquerClient(); }

        var api = {
            appliquer: surChangement, elements: elements, state: state,
            // Mode `remote` : la PAGE dit ce qu'elle a chargé (le total vient du serveur).
            setCount: function (text) { if (compteur) { compteur.textContent = text || ''; } },
            // Une recherche posée par la page (clic sur un tag) passe par la barre : le champ
            // affiché et la liste chargée ne divergent jamais.
            setSearch: function (text) {
                if (recherche) { recherche.value = text || ''; }
                surChangement(true);
            },
        };
        mounted.set(bar, api);
        return api;
    }

    /** L'instance d'une barre montée (`init` ou montage automatique), ou null. */
    function get(bar) {
        var element = typeof bar === 'string' ? $(bar) : bar;
        return (element && mounted.get(element)) || null;
    }

    // Barres montées, pour `refresh` : un composant qui re-rend sa liste n'a pas à connaître
    // l'instance, seulement la barre.
    var mounted = new WeakMap();

    /** Ré-applique le filtre d'une barre en mode client — après un re-rendu de sa liste. */
    function refresh(bar) {
        var element = typeof bar === 'string' ? $(bar) : bar;
        var api = element && mounted.get(element);
        if (api && (element.getAttribute('data-mode') || 'client') === 'client') { api.appliquer(true); }
    }

    function autoInit() {
        $$('[data-wama-filter-bar]').forEach(function (bar) {
            if (bar.getAttribute('data-monte') === '1') { return; }
            bar.setAttribute('data-monte', '1');
            init({ bar: bar });
        });
    }

    global.WamaFilterBar = { init: init, autoInit: autoInit, sort: sortElements, refresh: refresh, get: get };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', autoInit);
    } else {
        autoInit();
    }
})(window);
