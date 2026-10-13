/**
 * Brique `surface_actions` — les gestes de la SURFACE elle-même (chantier SURFACES, 2026-10-10).
 *
 * Annuler / rétablir : les boutons portent les classes de l'historique COMMUN (`.wama-undo`,
 * `.wama-redo`) — `wama-history.js` les branche et les grise lui-même, comme dans le
 * transcriber et le studio ; Ctrl+Z / Ctrl+Maj+Z valent partout sur la page.
 * Enregistrer : le champ déclaré par la surface, validé par le serveur.
 * Appliquer : enregistre puis rejoue le process que la modification a périmé (`reruns`).
 * Disposition : rend à chaque brique la place que la surface déclare.
 * Aide : les gestes que chaque brique montée DÉCLARE (`help`, lu par `ctx.helps()`) — jamais ceux
 * d'une brique écrits ici (l'aide de l'image y figurait en dur : fausse sur une page de texte).
 */
(function (global) {
    'use strict';

    function mount(body, ctx) {
        var reruns = ctx.config.surface.reruns;
        body.classList.add('wama-brick-actions');
        body.innerHTML =
            '<div class="wama-actions-row">' +
            '  <button type="button" class="btn btn-sm btn-outline-secondary wama-undo" title="Annuler (Ctrl+Z)"><i class="fas fa-rotate-left"></i></button>' +
            '  <button type="button" class="btn btn-sm btn-outline-secondary wama-redo" title="Rétablir (Ctrl+Maj+Z)"><i class="fas fa-rotate-right"></i></button>' +
            '  <button type="button" class="btn btn-sm btn-outline-primary" data-act="save" title="Enregistrer les corrections"><i class="fas fa-floppy-disk"></i> Enregistrer</button>' +
            '</div>' +
            (reruns ? '<button type="button" class="btn btn-sm btn-success w-100" data-act="apply" title="Enregistrer puis relancer « ' + reruns + ' »"><i class="fas fa-play"></i> Appliquer</button>' : '') +
            '<button type="button" class="btn btn-sm btn-link text-secondary" data-act="layout" title="Rendre à chaque panneau sa place d\'origine"><i class="fas fa-table-cells-large"></i> Disposition par défaut</button>' +
            '<div class="wama-actions-help"></div>';
        var helpEl = body.querySelector('.wama-actions-help');

        body.addEventListener('click', function (ev) {
            var b = ev.target.closest('[data-act]');
            if (!b) return;
            if (b.dataset.act === 'save') ctx.save();
            else if (b.dataset.act === 'apply') ctx.apply();
            else if (b.dataset.act === 'layout') ctx.resetLayout();
        });

        function refresh() {
            var dirty = ctx.dirty();
            body.querySelectorAll('[data-act="save"]').forEach(function (b) {
                b.disabled = !ctx.canEdit || !dirty;
            });
            body.querySelectorAll('[data-act="apply"]').forEach(function (b) {
                b.disabled = !ctx.canEdit;
            });
            ctx.history.syncButtons();
            // Lue à chaque rafraîchissement : les briques placées APRÈS celle-ci sur la grille
            // sont montées plus tard que son `mount`.
            helpEl.textContent = ctx.helps().join(' — ');
        }
        refresh();
        return { refresh: refresh };
    }

    global.WamaSurface.registerBrick('surface_actions', { title: 'Actions', mount: mount });
})(window);
