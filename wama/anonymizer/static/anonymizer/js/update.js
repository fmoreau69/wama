/**
 * Anonymizer — pont AJAX du VOLET DROIT legacy + actions de batch (port 2026-08-03).
 *
 * Reste ici :
 *   • .setting-button (sliders/switches/selects du panneau droit) → update_settings ;
 *   • .batch-duplicate-btn / .batch-delete-btn (handlers d'app, contrat _batch_card) ;
 *   • #clear_all_media_btn (bouton du volet droit — la toolbar a le sien dans queue.js).
 *
 * Parti au port :
 *   • handler de duplication → brique GLOBALE queue-actions.js (double-fire sinon) ;
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
     * 📦 Actions de batch (contrat _batch_card : handlers d'app .batch-*-btn)
     * ============================ */
    $(document).on("click", ".batch-duplicate-btn", function (e) {
        e.preventDefault();
        const batchId = $(this).data("batch-id");
        $.ajax({
            type: "POST",
            url: `/anonymizer/batch/${batchId}/duplicate/`,
            data: { csrfmiddlewaretoken: $("input[name=csrfmiddlewaretoken]").val() },
            success: function () { window.location.reload(); },
            error: function (xhr) {
                WamaApp.toast("Erreur lors de la duplication du batch : " + (xhr.responseText || "Erreur inconnue"), 'error');
            },
        });
    });

    $(document).on("click", ".batch-delete-btn", function (e) {
        e.preventDefault();
        const batchId = $(this).data("batch-id");
        if (!confirm("Supprimer ce batch et tous ses médias ?")) return;
        $.ajax({
            type: "POST",
            url: `/anonymizer/batch/${batchId}/delete/`,
            data: { csrfmiddlewaretoken: $("input[name=csrfmiddlewaretoken]").val() },
            success: function () {
                if (window.WamaFM) WamaFM.deleted();  // fichiers supprimés → refresh filemanager
                window.location.reload();
            },
            error: function (xhr) {
                WamaApp.toast("Erreur lors de la suppression du batch : " + (xhr.responseText || "Erreur inconnue"), 'error');
            },
        });
    });

    /* ============================
     * 🧹 Bouton "Tout effacer" du volet droit
     * ============================ */
    $(document).on("click", "#clear_all_media_btn", function (e) {
        e.preventDefault();
        if (!confirm("Voulez-vous vraiment supprimer tous les médias ?")) return;

        $.ajax({
            type: "POST",
            url: "/anonymizer/clear_all_media/",
            data: { csrfmiddlewaretoken: $("input[name=csrfmiddlewaretoken]").val() },
            success: function () {
                if (window.WamaFM) WamaFM.deleted();  // fichiers supprimés → refresh filemanager
                window.location.reload();
            },
            error: function (xhr) {
                WamaApp.toast("Erreur lors de la suppression des médias : " + (xhr.responseText || "Erreur inconnue"), 'error');
            },
        });
    });
});
