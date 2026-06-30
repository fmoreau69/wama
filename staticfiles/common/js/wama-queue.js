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

    // ── Toggle d'affichage Ligne / Mosaïque (générique) ──────────────────────────
    // Boutons `.wama-layout-btn[data-layout=list|grid]` ; conteneur de file = élément portant
    // `.wama-queue-list`/`.wama-queue-grid`. Persiste sur le profil (endpoint commun). No-op si absent.
    function initLayoutToggle() {
        const btns = Array.prototype.slice.call(document.querySelectorAll('.wama-layout-btn'));
        if (!btns.length) return;
        const queue = document.querySelector('.wama-queue-list, .wama-queue-grid');
        if (!queue) return;
        function csrf() { const m = document.cookie.match(/csrftoken=([^;]+)/); return m ? m[1] : ''; }
        function current() { return queue.classList.contains('wama-queue-grid') ? 'grid' : 'list'; }
        function mark() { btns.forEach(function (b) { b.classList.toggle('active', b.dataset.layout === current()); }); }
        function apply(layout) {
            queue.classList.toggle('wama-queue-grid', layout === 'grid');
            queue.classList.toggle('wama-queue-list', layout === 'list');
            mark();
            fetch('/accounts/profile/layout/', {
                method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf() },
                body: JSON.stringify({ card_layout: layout }),
            }).catch(function () {});
        }
        btns.forEach(function (b) { b.addEventListener('click', function () { apply(b.dataset.layout); }); });
        mark();
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

    function init() { injectStyle(); initBatchCollapse(); initOnePileOpen(); initLayoutToggle(); focusFromSession(); }

    // API publique
    window.WamaQueue = window.WamaQueue || {};
    window.WamaQueue.focusCard = focusCard;

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }

})();
