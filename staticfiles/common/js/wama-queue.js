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

    // ── Init ─────────────────────────────────────────────────────────────────

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initBatchCollapse);
    } else {
        initBatchCollapse();
    }

})();
