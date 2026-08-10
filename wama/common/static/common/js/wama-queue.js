/**
 * wama-queue.js — Comportements communs à toutes les files d'attente WAMA
 *
 * Auto-initialisé sur DOMContentLoaded. Opère uniquement sur les éléments
 * portant les attributs data-wama-* correspondants — sans effet de bord
 * sur les pages qui n'ont pas de file d'attente.
 *
 * Convention §9.7 de WAMA_APP_CONVENTIONS.md
 */

(function () {
    'use strict';

    // ── Batch collapse — persistance localStorage ────────────────────────────
    // Multi-batches repliés par défaut. L'état replié/déplié est mémorisé par
    // batch via localStorage (clé : "wama_batch_{app}_{id}").
    //
    // Prérequis template :
    //   - Bloc collapsible : <div class="collapse" id="batchItemsXX"
    //                             data-wama-batch-key="{app}_{id}">
    //   - Bouton toggle    : <div data-bs-toggle="collapse"
    //                             data-bs-target="#batchItemsXX"
    //                             aria-expanded="false">
    function initBatchCollapse() {
        document.querySelectorAll('.collapse[data-wama-batch-key]').forEach(function (collapseEl) {
            const key = 'wama_batch_' + collapseEl.dataset.wamaBatchKey;
            const stored = localStorage.getItem(key);

            // Restaurer l'état sauvegardé (défaut : replié)
            if (stored === 'open') {
                collapseEl.classList.add('show');
                const toggleEl = document.querySelector('[data-bs-target="#' + collapseEl.id + '"]');
                if (toggleEl) toggleEl.setAttribute('aria-expanded', 'true');
            }

            // Sauvegarder à chaque changement d'état
            collapseEl.addEventListener('show.bs.collapse', function () {
                localStorage.setItem(key, 'open');
            });
            collapseEl.addEventListener('hide.bs.collapse', function () {
                localStorage.setItem(key, 'closed');
            });
        });
    }

    // ── Solitaire : UNE pile ouverte à la fois (accordéon) ───────────────────────
    // Quand on ouvre un batch, les autres piles ouvertes se replient. No-op si <2 batchs
    // ou si Bootstrap Collapse indisponible. La persistance localStorage reste cohérente
    // (la fermeture déclenche hide.bs.collapse → 'closed').
    function initOnePileOpen() {
        const all = Array.prototype.slice.call(document.querySelectorAll('.collapse[data-wama-batch-key]'));
        if (all.length < 2 || !window.bootstrap || !bootstrap.Collapse) return;
        all.forEach(function (collapseEl) {
            collapseEl.addEventListener('show.bs.collapse', function () {
                all.forEach(function (other) {
                    if (other !== collapseEl && other.classList.contains('show')) {
                        const inst = bootstrap.Collapse.getInstance(other)
                            || new bootstrap.Collapse(other, { toggle: false });
                        inst.hide();
                    }
                });
            });
        });
    }

    // Files de la page. Plusieurs apps en affichent DEUX (enhancer média+audio, imager
    // image+vidéo) : tout ce qui pilote « la file » doit les traiter TOUTES, sinon le geste
    // ne s'applique qu'à l'onglet visible au moment du clic.
    function allQueues() {
        return Array.prototype.slice.call(
            document.querySelectorAll('.wama-queue-list, .wama-queue-grid'));
    }

    // ── Toggle d'affichage Ligne / Mosaïque (générique) ──────────────────────────
    // Boutons `.wama-layout-btn[data-layout=list|grid]` ; conteneur de file = élément portant
    // `.wama-queue-list`/`.wama-queue-grid`. Persiste sur le profil (endpoint commun). No-op si absent.
    function initLayoutToggle() {
        const btns = Array.prototype.slice.call(document.querySelectorAll('.wama-layout-btn'));
        if (!btns.length) return;
        // TOUTES les files de la page, pas seulement la première : plusieurs apps en ont
        // deux (enhancer média + audio, imager image + vidéo, files scopées par onglet).
        // Avec un `querySelector` singulier, la bascule n'agissait que sur la première et
        // la seconde ne s'alignait qu'au rechargement suivant — mécanisme à moitié vivant,
        // invisible tant qu'on ne regarde pas l'onglet d'à côté.
        const queues = allQueues();
        if (!queues.length) return;
        function csrf() { const m = document.cookie.match(/csrftoken=([^;]+)/); return m ? m[1] : ''; }
        function current() { return queues[0].classList.contains('wama-queue-grid') ? 'grid' : 'list'; }
        function mark() { btns.forEach(function (b) { b.classList.toggle('active', b.dataset.layout === current()); }); }
        function apply(layout) {
            queues.forEach(function (queue) {
                queue.classList.toggle('wama-queue-grid', layout === 'grid');
                queue.classList.toggle('wama-queue-list', layout === 'list');
            });
            mark();
            fetch('/accounts/profile/layout/', {
                method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf() },
                body: JSON.stringify({ card_layout: layout }),
            }).catch(function () {});
        }
        btns.forEach(function (b) { b.addEventListener('click', function () { apply(b.dataset.layout); }); });
        mark();
    }

    // ── DESIGN de card — 3 densités coexistantes (CARD_DESIGN §11.4) ─────────────
    // Le design ne change QUE la mise en page : les 3 densités lisent la même source générée
    // (schéma → chips). D'où un simple attribut sur la file, que 3 feuilles de style
    // interprètent — et surtout aucun rendu conditionnel côté serveur, qui rouvrirait la porte
    // à ce que les designs divergent fonctionnellement.
    function initDesignSelect() {
        // Le design est un réglage de PROFIL (card_design) : comme le toggle Ligne/Mosaïque,
        // il s'applique à TOUTES les files de la page et tous les sélecteurs (un par toolbar,
        // les apps à deux files en incluent deux) se marquent ensemble.
        const sels = Array.prototype.slice.call(document.querySelectorAll('.wama-design-select'));
        const queues = allQueues();
        if (!sels.length || !queues.length) return;

        function csrf() { const m = document.cookie.match(/csrftoken=([^;]+)/); return m ? m[1] : ''; }

        function apply(design, persist) {
            queues.forEach(function (queue) { queue.dataset.cardDesign = design; });
            if (persist === false) return;
            fetch('/accounts/profile/layout/', {
                method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf() },
                body: JSON.stringify({ card_design: design }),
            }).catch(function () {});
            // Les pistes se remesurent : changer de densité change ce que les sections contiennent.
            if (window.WamaCardV3) window.WamaCardV3.measure();
        }

        function mark(design) {
            sels.forEach(function (sel) {
                sel.querySelectorAll('.wama-design-opt').forEach(function (o) {
                    o.classList.toggle('active', o.dataset.value === design);
                });
            });
        }
        sels.forEach(function (sel) {
            sel.querySelectorAll('.wama-design-opt').forEach(function (opt) {
                opt.addEventListener('click', function () {
                    apply(opt.dataset.value, true);
                    mark(opt.dataset.value);
                });
            });
        });
        const initial = sels[0].dataset.design || 'v3';
        mark(initial);
        apply(initial, false);   // état venu du profil : ne pas re-persister
    }

    // ── Modificateur PILE (CARD_DESIGN §11 v3.5) ─────────────────────────────────
    // Orthogonal au layout : c'est un on/off, PAS une 3e disposition — d'où un bouton séparé
    // et un booléen de profil distinct de card_layout. Les cards se compressent selon leur
    // DISTANCE à la card focalisée ; seule celle-ci reste entière.
    //
    // La distance est posée en attribut par le JS plutôt que déduite en CSS : les sélecteurs
    // de fratrie ne portent qu'à un ou deux crans, et la file contient des groupes de lot
    // intercalés — la fratrie DOM ne reflète pas l'ordre visible.
    //
    // Réservé à l'affichage en ligne : pile × mosaïque reste un point ouvert du §11, on ne le
    // tranche pas ici. Le focus lui-même réutilise focusCard() ci-dessous — rien de réinventé.
    function initStackToggle() {
        // Comme layout et design : l'ÉTAT (pile on/off = réglage de profil `card_stacked`) est
        // global à la page — toutes les files basculent ensemble et tous les boutons (un par
        // toolbar, les apps à deux files en incluent deux) se marquent ensemble. Le FOCUS de
        // pile, lui, reste propre à chaque file : `_pileFor()` ferme la machinerie (focusKey,
        // distances, navigation) sur UNE file.
        const btns = Array.prototype.slice.call(document.querySelectorAll('.wama-stack-btn'));
        const queues = allQueues();
        if (!btns.length || !queues.length) return;

        function csrf() { const m = document.cookie.match(/csrftoken=([^;]+)/); return m ? m[1] : ''; }
        function on() { return queues[0].classList.contains('wama-queue-stacked'); }

        const piles = queues.map(_pileFor);

        function apply(state, persist) {
            piles.forEach(function (p) { p.apply(state); });
            btns.forEach(function (b) {
                b.classList.toggle('active', state);
                b.setAttribute('aria-pressed', state ? 'true' : 'false');
            });
            if (persist === false) return;
            fetch('/accounts/profile/layout/', {
                method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf() },
                body: JSON.stringify({ card_stacked: state }),
            }).catch(function () {});
        }

        btns.forEach(function (b) { b.addEventListener('click', function () { apply(!on(), true); }); });

        // false = ne pas re-persister ce qui vient justement du profil.
        if (btns[0].dataset.stacked === '1') apply(true, false);
    }

    // Machinerie de pile d'UNE file — retourne { apply(state) }. Tout l'état est fermé sur
    // `queue` : deux files gardent chacune leur card focalisée.
    function _pileFor(queue) {
        function on() { return queue.classList.contains('wama-queue-stacked'); }

        // Identifiant de la card focalisée — survit au remplacement du nœud par le rendu serveur.
        let focusKey = null;

        // Cards empilables, dans l'ordre DOM — qui est l'ordre de lecture, mère de lot puis ses
        // filles. La card « nouvel élément » n'en fait jamais partie : elle est le point
        // d'entrée, la comprimer priverait du geste de dépôt (§11 : jamais compressée).
        //
        // ⚠ On n'exclut PAS les cards masquées. Une première version filtrait sur la visibilité
        // (offsetParent) : les filles d'un lot REPLIÉ sortaient de la liste, donc la navigation
        // sautait le lot entier et ses cards étaient injoignables au clavier — la pile n'avait
        // plus d'usage. Les cards d'un lot font partie de la file : on les traverse, et c'est le
        // lot qui s'ouvre pour les laisser passer (voir syncBatch).
        function cards() {
            return Array.prototype.slice
                .call(queue.querySelectorAll('.wama-card'))
                .filter(function (c) {
                    return !c.classList.contains('wama-new-item-card') &&
                           !c.classList.contains('wama-new-card');
                });
        }

        function batchOf(card) { return card.closest('.collapse[data-wama-batch-key]'); }

        /**
         * Ouvre le lot de la card focalisée, replie celui qu'on vient de quitter.
         *
         * L'accordéon « une seule pile ouverte » est déjà tenu par initOnePileOpen() : ouvrir
         * ici suffit à refermer les autres, on ne réimplémente pas cette règle. Ne reste que le
         * cas qu'il ne couvre pas : sortir d'un lot pour une card qui n'appartient à aucun lot.
         */
        function syncBatch(card) {
            if (!window.bootstrap || !bootstrap.Collapse) return;
            const target = batchOf(card);
            if (target && !target.classList.contains('show')) {
                bootstrap.Collapse.getOrCreateInstance(target, { toggle: false }).show();
                return;
            }
            if (!target) {
                queue.querySelectorAll('.collapse[data-wama-batch-key].show').forEach(function (el) {
                    bootstrap.Collapse.getOrCreateInstance(el, { toggle: false }).hide();
                });
            }
        }

        /**
         * Pose la distance au focus sur chaque card.
         *
         * La NAVIGATION porte sur toutes les cards (lots repliés compris), mais la COMPRESSION
         * se calcule sur les seules cards visibles : sinon un lot replié de 8 items compterait
         * pour 8 crans, et la card qui le suit serait déjà en lamelle alors qu'elle est
         * visuellement la voisine immédiate. Deux listes, deux rôles.
         */
        function spread() {
            const all = cards();
            if (!all.length) return;
            if (!all.some(function (c) { return c.classList.contains('is-stack-focus'); })) {
                // Le focus a disparu : soit c'est le premier passage, soit la card focalisée
                // vient d'être REMPLACÉE par le rendu serveur (upsertCard remplace le nœud
                // entier, la classe part avec). On le rétablit par son identifiant, sinon la
                // pile se replie sur sa première card à chaque tour de polling — ce qui rendait
                // la navigation inutilisable dès qu'un traitement tournait.
                let back = focusKey && all.find(function (c) { return c.dataset.id === focusKey; });
                if (!back) back = all.find(function (c) { return c.classList.contains('selected'); });
                (back || all[0]).classList.add('is-stack-focus');
            }
            const cur = all.find(function (c) { return c.classList.contains('is-stack-focus'); });
            focusKey = cur && cur.dataset.id ? cur.dataset.id : focusKey;
            const shown = all.filter(function (c) { return c.offsetParent !== null; });
            let focusIdx = shown.findIndex(function (c) { return c.classList.contains('is-stack-focus'); });
            if (focusIdx < 0) focusIdx = 0;
            shown.forEach(function (c, i) {
                // 0 = entière · 1 = 46 px · 2 = 28 px · 3+ = lamelle
                c.dataset.stack = String(Math.min(3, Math.abs(i - focusIdx)));
            });
        }

        function clear() {
            cards().forEach(function (c) {
                c.classList.remove('is-stack-focus');
                delete c.dataset.stack;
            });
        }

        function apply(state) {
            queue.classList.toggle('wama-queue-stacked', state);
            if (state) spread(); else clear();
        }

        // Clic sur une card comprimée = la déplier (elle prend le focus de la pile).
        queue.addEventListener('click', function (ev) {
            if (!on()) return;
            const card = ev.target.closest('.wama-card');
            if (!card || card.classList.contains('is-stack-focus')) return;
            cards().forEach(function (c) { c.classList.remove('is-stack-focus'); });
            card.classList.add('is-stack-focus');
            focusKey = card.dataset.id || focusKey;
            syncBatch(card);
            spread();
        }, true);

        // Flèches ↑/↓ : navigation dans la pile, sans voler le clavier à un champ de saisie.
        document.addEventListener('keydown', function (ev) {
            if (!on() || (ev.key !== 'ArrowUp' && ev.key !== 'ArrowDown')) return;
            // Deux files empilées à la fois (page à onglets) : seule la file VISIBLE répond
            // aux flèches, sinon chaque frappe déplacerait aussi le focus de l'onglet caché.
            if (queue.offsetParent === null) return;
            const t = ev.target;
            if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.isContentEditable)) return;
            const list = cards();
            if (!list.length) return;
            let i = list.findIndex(function (c) { return c.classList.contains('is-stack-focus'); });
            if (i < 0) i = 0;
            const next = Math.max(0, Math.min(list.length - 1, i + (ev.key === 'ArrowDown' ? 1 : -1)));
            if (next === i) return;
            ev.preventDefault();
            list.forEach(function (c) { c.classList.remove('is-stack-focus'); });
            list[next].classList.add('is-stack-focus');
            focusKey = list[next].dataset.id || focusKey;
            // Le lot s'ouvre AVANT le scroll : viser une card encore repliée centrerait sur
            // une hauteur nulle.
            syncBatch(list[next]);
            spread();
            focusCard(list[next], { scroll: 'center' });
        });

        // Les cards sont remplacées entières par le rendu serveur : réattribuer les distances.
        new MutationObserver(function () { if (on()) spread(); })
            .observe(queue, { childList: true, subtree: true });

        return { apply: apply };
    }

    // ── Focus d'une card : scroll centré + halo pulse + (option) sélection ───────
    // Usage commun à l'AJOUT (card unique ou mère de batch) ET à la navigation clavier :
    //   WamaQueue.focusCard('cardId', { scroll:'center', pulse:true, select:true });
    // Évite d'avoir à « chercher » une card qui n'atterrit pas en tête. Le bug « card du haut
    // masquée par un header collant » est traité par `scroll-margin-top` (CSS injecté ci-dessous,
    // surchargeable via --wama-sticky-top sur l'app).
    var _styleInjected = false;
    function injectStyle() {
        if (_styleInjected || document.getElementById('wama-queue-style')) { _styleInjected = true; return; }
        var st = document.createElement('style');
        st.id = 'wama-queue-style';
        st.textContent =
            '@keyframes wama-focus-pulse{0%{box-shadow:0 0 0 0 rgba(13,202,240,.55)}70%{box-shadow:0 0 0 9px rgba(13,202,240,0)}100%{box-shadow:0 0 0 0 rgba(13,202,240,0)}}' +
            '.wama-focus-pulse{animation:wama-focus-pulse 1.2s ease-out 1;border-radius:.7rem}' +
            '[data-wama-card],.synthesis-card,.wama-card,.wama-new-item-card{scroll-margin-top:var(--wama-sticky-top,84px)}';
        document.head.appendChild(st);
        _styleInjected = true;
    }

    function focusCard(idOrEl, opts) {
        opts = opts || {};
        injectStyle();
        var el = (typeof idOrEl === 'string')
            ? (document.getElementById(idOrEl) || document.querySelector(idOrEl))
            : idOrEl;
        if (!el) return null;
        if (opts.scroll !== false) {
            var block = (typeof opts.scroll === 'string') ? opts.scroll : 'center';
            try { el.scrollIntoView({ block: block, behavior: opts.smooth === false ? 'auto' : 'smooth' }); }
            catch (e) { el.scrollIntoView(); }
        }
        if (opts.pulse !== false) {
            el.classList.remove('wama-focus-pulse');
            void el.offsetWidth;               // reflow → rejoue l'animation
            el.classList.add('wama-focus-pulse');
            setTimeout(function () { el.classList.remove('wama-focus-pulse'); }, 1300);
        }
        if (opts.select) {
            // Sélection = clic sur la card (design card-centric : le clic remplit l'inspecteur).
            // Best-effort : sans effet si l'app ne gère pas la sélection.
            try { el.click(); } catch (e) {}
        }
        return el;
    }

    // Reprise après rechargement : une app peut poser sessionStorage['wama_focus_card'] = id avant
    // un reload (cas d'ajout qui recharge la page) ; on met au point la card au chargement suivant.
    function focusFromSession() {
        var id;
        try { id = sessionStorage.getItem('wama_focus_card'); } catch (e) { return; }
        if (!id) return;
        try { sessionStorage.removeItem('wama_focus_card'); } catch (e) {}
        // léger délai : laisser le layout/le prepend de la card « nouveau » se stabiliser
        setTimeout(function () { focusCard(id, { scroll: 'center', pulse: true }); }, 120);
    }

    // ── Init ─────────────────────────────────────────────────────────────────

    function init() { injectStyle(); initBatchCollapse(); initOnePileOpen(); initLayoutToggle(); initDesignSelect(); initStackToggle(); focusFromSession(); }

    // API publique
    window.WamaQueue = window.WamaQueue || {};
    window.WamaQueue.focusCard = focusCard;

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

})();
