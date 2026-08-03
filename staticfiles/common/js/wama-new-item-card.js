/**
 * WAMA — Card « Nouvel élément » DÉPLIABLE (brique commune, auto-init).
 *
 * Mécanisme du synthesizer GLOBALISÉ (2026-07-03) : la card d'entrée reste compacte
 * (en-tête + prompt + bouton primaire) et la zone médiane d'import (dropzones, URL,
 * médiathèque, batch, live, référence) se déplie à l'interaction. 1ʳᵉ étape vers la
 * card miniaturisée intégrée à la file (MODES_QUEUE_UX).
 *
 * Contrat template (_new_item_card.html avec collapsible=True) :
 *   racine        [data-wama-nic] [data-nic-primary="<id input primaire>"]
 *   en-tête       [data-nic-toggle]  (clic = déplier/replier)
 *   zone médiane  .collapse#<cardId>Body
 *
 * Dépliage : clic en-tête · focus/saisie de l'entrée primaire · survol drag de fichier.
 * Zéro code par app : auto-init sur DOMContentLoaded.
 */
(function () {
    'use strict';

    function wire(card) {
        // Garde anti-double-init : le script est porté par la brique _new_item_card.html
        // (2026-08-03) ET encore inclus par d'anciens templates d'app — deux exécutions
        // sans garde = deux toggles par clic (la card se refermait instantanément).
        if (card.dataset.nicWired === '1') return;
        card.dataset.nicWired = '1';
        var body = document.getElementById(card.id + 'Body');
        if (!body || typeof bootstrap === 'undefined') return;
        var collapse = bootstrap.Collapse.getOrCreateInstance(body, { toggle: false });

        function open()  { collapse.show(); }
        function toggle() { collapse.toggle(); }

        // Chevron : refléter l'état (classe posée sur la RACINE pour le CSS commun).
        body.addEventListener('show.bs.collapse', function () { card.classList.add('is-deployed'); });
        body.addEventListener('hide.bs.collapse', function () { card.classList.remove('is-deployed'); });
        if (body.classList.contains('show')) card.classList.add('is-deployed');

        var header = card.querySelector('[data-nic-toggle]');
        if (header) header.addEventListener('click', function (e) {
            // Ne pas replier quand le clic vient d'un contrôle interne (futur-proof).
            if (e.target.closest('button, a, input, select, textarea')) return;
            toggle();
        });

        var primary = card.dataset.nicPrimary && document.getElementById(card.dataset.nicPrimary);
        if (primary) {
            primary.addEventListener('focus', open);
            primary.addEventListener('input', open);
        }

        // Dépliage à TOUTE interaction avec la card repliée (2026-08-03, référence composer) :
        // pour les apps à modalité fichier, l'entrée primaire est un input CACHÉ — focus/saisie
        // ne se produisent jamais, et seul l'en-tête dépliait. Un clic n'importe où sur la card
        // repliée la déplie (l'en-tête garde son toggle ; les contrôles visibles restent actifs).
        card.addEventListener('click', function (e) {
            if (card.classList.contains('is-deployed')) return;   // repliée seulement
            if (e.target.closest('[data-nic-toggle]')) return;    // l'en-tête gère déjà le toggle
            open();
        });

        // Drag de fichier au-dessus de la card : révéler les zones de dépôt.
        card.addEventListener('dragover', open);
    }

    document.addEventListener('DOMContentLoaded', function () {
        document.querySelectorAll('[data-wama-nic]').forEach(wire);
    });
})();
