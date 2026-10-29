/**
 * Brique `surface_actions` — les gestes de la SURFACE elle-même (chantier SURFACES, 2026-10-10).
 *
 * Annuler / rétablir : les boutons portent les classes de l'historique COMMUN (`.wama-undo`,
 * `.wama-redo`) — `wama-history.js` les branche et les grise lui-même, comme dans le
 * transcriber et le studio ; Ctrl+Z / Ctrl+Maj+Z valent partout sur la page.
 * Enregistrer : le champ déclaré par la surface, validé par le serveur.
 * Appliquer : enregistre puis rejoue le process que la modification a périmé (`reruns`).
 *
 * La DISPOSITION (figer, modifier, « Disposition par défaut ») et l'AIDE (raccourcis des briques
 * montées, gestes) ne sont plus ici depuis le 2026-10-29 (décision de Fabien) : elles valent pour
 * toute la page et vivent dans l'en-tête (`wama-page-controls.js`), où une disposition ne peut
 * pas les égarer. Un lien y renvoie.
 */
(function (global) {
    'use strict';

    function esc(t) {
        var d = document.createElement('div'); d.textContent = t == null ? '' : t;
        return d.innerHTML;
    }

    function mount(body, ctx) {
        var reruns = ctx.config.surface.reruns;
        // « Terminer » (2026-10-21, `Surface.finish`) : le geste final d'une correction — un
        // enregistrement marqué fini, dont le serveur tire les conséquences (`Surface.saved`).
        var finish = ctx.config.surface.finish;
        body.classList.add('wama-brick-actions');
        body.innerHTML =
            '<div class="wama-actions-row">' +
            '  <button type="button" class="btn btn-sm btn-outline-secondary wama-undo" title="Annuler"><i class="fas fa-rotate-left"></i></button>' +
            '  <button type="button" class="btn btn-sm btn-outline-secondary wama-redo" title="Rétablir"><i class="fas fa-rotate-right"></i></button>' +
            '  <button type="button" class="btn btn-sm btn-outline-primary" data-act="save" title="Enregistrer les corrections"><i class="fas fa-floppy-disk"></i> Enregistrer</button>' +
            '</div>' +
            (reruns ? '<button type="button" class="btn btn-sm btn-success w-100" data-act="apply" title="Enregistrer puis relancer « ' + reruns + ' »"><i class="fas fa-play"></i> Appliquer</button>' : '') +
            (finish ? '<button type="button" class="btn btn-sm btn-success w-100" data-act="finish" title="Marquer la correction comme terminée"><i class="fas fa-check-double"></i> ' + esc(finish) + '</button>' : '') +
            '<div class="wama-actions-layout">' +
            '  <button type="button" class="btn btn-sm btn-link text-secondary" data-act="help" title="Raccourcis clavier, disposition et gestes de cette page (?)"><i class="fas fa-circle-question"></i> Raccourcis et aide</button>' +
            '</div>';

        body.addEventListener('click', function (ev) {
            var b = ev.target.closest('[data-act]');
            if (!b) return;
            if (b.dataset.act === 'save') ctx.save();
            else if (b.dataset.act === 'apply') ctx.apply();
            else if (b.dataset.act === 'finish') ctx.finish();
            else if (b.dataset.act === 'help' && global.WamaPageControls) global.WamaPageControls.openHelp('keys');
        });

        function refresh() {
            var dirty = ctx.dirty();
            body.querySelectorAll('[data-act="save"]').forEach(function (b) {
                b.disabled = !ctx.canEdit || !dirty;
            });
            // « Appliquer » rejoue le process que le champ PRINCIPAL périme : un autre champ édité
            // (`ctx.target()`, la partition complète du composer) ne le nourrit pas (2026-10-22).
            var other = !!(ctx.target && ctx.target());
            body.querySelectorAll('[data-act="apply"], [data-act="finish"]').forEach(function (b) {
                b.disabled = !ctx.canEdit || (other && b.dataset.act === 'apply');
            });
            ctx.history.syncButtons();
        }
        refresh();
        return { refresh: refresh };
    }

    global.WamaSurface.registerBrick('surface_actions', { title: 'Actions', mount: mount });
})(window);
