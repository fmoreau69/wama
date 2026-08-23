/**
 * Anonymizer — pont AJAX du VOLET DROIT legacy + actions de batch (port 2026-08-03).
 *
 * Reste ici :
 *   • .setting-button (sliders/switches/selects du panneau droit) → update_settings ;
 *   • #clear_all_media_btn (bouton du volet droit — la toolbar a le sien dans queue.js).
 *
 * Parti au port :
 *   • handler de duplication → brique GLOBALE queue-actions.js (double-fire sinon) ;
 *   • .batch-duplicate-btn / .batch-delete-btn → brique commune (2026-08-24) : elle fait
 *     le même confirm + POST + signalement au gestionnaire + rechargement ;
 *   • updateGlobalProgress → brique commune wama-global-progress.js (_global_progress.html) ;
 *   • refreshMediaTable/.ajax-form/expand_area → mécanisme legacy `refresh` supprimé
 *     (card = partial serveur via card_html, structure re-rendue par reload).
 */
$(document).ready(function () {

    function debounce(func, wait) {
        let timeout;
        return function (...args) {
            clearTimeout(timeout);
            timeout = setTimeout(() => func.apply(this, args), wait);
        };
    }

    /* ============================
     * 🔍 Extraction des infos ID (user_setting_* / global_setting_* / media_setting_*_<id>)
     * ============================ */
    function extractSettingName(inputId) {
        const parts = inputId.split('_');
        const setting_type = parts[0] + '_' + parts[1];
        let media_id = null;
        let setting_name;

        if (setting_type === 'media_setting') {
            media_id = parts[parts.length - 1];
            setting_name = parts.slice(2, parts.length - 1).join('_');
        } else {
            setting_name = parts.slice(2).join('_');
        }
        return { setting_type, media_id, setting_name };
    }

    /* ============================
     * 🚀 Envoi AJAX principal
     * ============================ */
    function submitValues(inputId, inputValue) {
        const { setting_type, media_id, setting_name } = extractSettingName(inputId);

        let data = {
            setting_type,
            setting_name,
            input_value: inputValue,
            csrfmiddlewaretoken: $("input[name=csrfmiddlewaretoken]").val(),
        };

        if (media_id) data.media_id = media_id;

        $.ajax({
            type: "POST",
            url: "/anonymizer/update_settings/",
            data,
            success: function (res) {
                if (res.render) {
                    const container = $("#setting_button_container_" + inputId);
                    if (container.length) container.replaceWith(res.render);
                }
            },
            error: function (xhr) {
                console.error("[update.js] update_settings error", xhr.status, xhr.responseText);
            },
        });
    }

    const debouncedSubmit = debounce(submitValues, 250);

    $(document).on("input change", ".setting-button", function () {
        const $el = $(this);
        const inputId = $el.attr("id");
        const inputType = $el.attr("type") || ($el.is('select') ? 'select' : undefined);
        let inputValue;

        if (inputType === "checkbox") {
            inputValue = $el.prop("checked") ? "true" : "false";
        } else {
            inputValue = $el.val();
        }

        // Met à jour le <output> voisin s'il existe (utile pour sliders)
        const $output = $el.next("output");
        if ($output.length) {
            $output.text(inputValue);
        }

        debouncedSubmit(inputId, inputValue);
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
