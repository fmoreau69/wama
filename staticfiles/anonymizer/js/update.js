/**
 * Anonymizer — enregistrement du VOLET DROIT (réglages `.setting-button`).
 *
 * Depuis le 2026-09-27 un réglage changé au volet est ENREGISTRÉ PAR L'INSPECTEUR COMMUN
 * (`autoSave`, queue.js), qui route selon ce qui est inspecté : l'élément, le lot, ou — rien
 * d'inspecté — les défauts de l'utilisateur (brique `user_settings`). Il ne reste ici que
 * l'affichage de la valeur à côté d'un curseur. Avant, chaque champ partait seul vers
 * `update_settings/` et écrivait TOUJOURS les réglages de l'utilisateur, même quand le volet
 * montrait une card : l'élément inspecté ne recevait rien.
 *
 * Parti au port :
 *   • handler de duplication → brique GLOBALE queue-actions.js (double-fire sinon) ;
 *   • .batch-duplicate-btn / .batch-delete-btn → brique commune (2026-08-24) ;
 *   • updateGlobalProgress → brique commune wama-global-progress.js (_global_progress.html) ;
 *   • refreshMediaTable/.ajax-form/expand_area → mécanisme legacy `refresh` supprimé.
 */
$(document).ready(function () {

    $(document).on("input change", ".setting-button", function () {
        const $el = $(this);
        // Met à jour le <output> voisin s'il existe (utile pour sliders)
        const $output = $el.next("output");
        if ($output.length) {
            $output.text($el.attr("type") === "checkbox" ? ($el.prop("checked") ? "true" : "false") : $el.val());
        }
    });

    /* ============================
     * 📦 Actions de batch — PORTÉES à la brique commune (2026-08-24)
     * ============================
     * Les handlers `.batch-duplicate-btn` et `.batch-delete-btn` vivaient ici : POST + reload
     * pour l'un, confirm + POST + `WamaFM.deleted()` + reload pour l'autre. `queue-actions.js`
     * fait EXACTEMENT cela pour les 8 apps — `signalerFichiers: true` étant le nom commun du
     * rafraîchissement du gestionnaire de fichiers. Rien de propre à l'anonymizer ne s'y
     * jouait, donc rien à déclarer : les URLs viennent du partial (`actions_communes=True`).
     * ⚠ Retrait et pose du drapeau dans le MÊME geste — les garder tous deux ferait tirer la
     * brique ET l'app sur le même clic (double POST).
     * ▶ et ⚙ de lot, eux, déclarent une suite : voir `queue.js`.
     */

    // Le « Tout effacer » du volet droit est MORT (2026-08-03) : l'action vit
    // dans la toolbar commune (queue.js, #anon-clear-all-btn).
});
