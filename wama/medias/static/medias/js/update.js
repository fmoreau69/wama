$(document).ready(function () {

    /* ============================
     * 🕒 Debounce utilitaire
     * ============================ */
    function debounce(func, wait) {
        let timeout;
        return function (...args) {
            clearTimeout(timeout);
            timeout = setTimeout(() => func.apply(this, args), wait);
        };
    }

    /* ============================
     * 🔍 Extraction des infos ID
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
        console.log("%c[update.js] ▶ Sending update", "color:#00BCD4", { inputId, inputValue });

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
            url: "/medias/update_settings/",
            data,
            success: function (res) {
                if (res.success) {
                    console.log("%c[update.js] ✔ Setting updated successfully", "color:#4CAF50", res);
                } else if (res.render) {
                    const container = $("#setting_button_container_" + inputId);
                    container.replaceWith(res.render);
                    console.log("%c[update.js] ✔ DOM re-rendered", "color:#4CAF50");
                } else {
                    console.warn("%c[update.js] ⚠ Unexpected server response", "color:#FFC107", res);
                }
            },
            error: function (xhr) {
                console.error("%c[update.js] ✖ AJAX error", "color:red", {
                    status: xhr.status,
                    response: xhr.responseText
                });
            },
        });
    }

    /* ============================
     * 🎚 Gestion des sliders / switches
     * ============================ */
    const debouncedSubmit = debounce(submitValues, 250);

    $(document).on("input change", ".setting-button", function () {
        const $el = $(this);
        const inputId = $el.attr("id");
        const inputType = $el.attr("type") || ($el.is('select') ? 'select' : undefined);
        let inputValue;

        if (inputType === "checkbox") {
            inputValue = $el.prop("checked") ? "true" : "false";
        } else if (inputType === 'select') {
            inputValue = $el.val();
        } else {
            inputValue = $el.val();
        }

        // Met à jour le <output> voisin s’il existe (utile pour sliders)
        const $output = $el.next("output");
        if ($output.length) {
            $output.text(inputValue);
        }

        console.log("%c[update.js] ✏ Change detected", "color:#2196F3", { inputId, inputValue });
        debouncedSubmit(inputId, inputValue);
    });

    /* ============================
     * 🧹 Bouton "Clear All Media"
     * ============================ */
    $(document).on("click", "#clear_all_media_btn", function (e) {
        e.preventDefault();
        if (!confirm("Voulez-vous vraiment supprimer tous les médias ?")) return;

        console.log("%c[update.js] 🧹 Clearing all media…", "color:purple");

        $.ajax({
            type: "POST",
            url: "/medias/clear_all_media/",
            data: { csrfmiddlewaretoken: $("input[name=csrfmiddlewaretoken]").val() },
            success: function () {
                console.log("%c[update.js] ✔ Médias supprimés", "color:#4CAF50");
                window.location.reload();
            },
            error: function (xhr) {
                console.error("%c[update.js] ✖ Erreur clear_all_media", "color:red", xhr.responseText);
                alert("Erreur lors de la suppression des médias : " + (xhr.responseText || "Erreur inconnue"));
            },
        });
    });

    /* ============================
     * 📦 Gestion des formulaires AJAX
     * ============================ */
    $(document).on("submit", ".ajax-form", function (e) {
        e.preventDefault();

        const $form = $(this);
        const actionUrl = $form.attr("action");
        const method = $form.attr("method") || "POST";
        const targetSelector = $form.data("target") || "#main_container";
        const formData = $form.serialize();

        $.ajax({
            type: method,
            url: actionUrl,
            data: formData,
            success: function (res) {
                if (res.render) {
                    $(targetSelector).html(res.render);
                    attachCollapseEvents();
                    if (typeof window.initProcessControls === 'function') {
                        window.initProcessControls();
                    }
                    if (typeof window.initMediaPreview === 'function') {
                        window.initMediaPreview();
                    }
                    console.log("%c[update.js] ✔ Section reloaded", "color:#4CAF50");
                } else {
                    console.warn("%c[update.js] ⚠ Réponse inattendue", "color:#FFC107", res);
                }
            },
            error: function (xhr) {
                console.error("%c[update.js] ✖ Erreur AJAX formulaire", "color:red", xhr.responseText);
                alert("Erreur lors de l'envoi du formulaire : " + (xhr.responseText || "Erreur inconnue"));
            },
        });
    });

    attachCollapseEvents();
});

/* ============================
 * ⬇️ Collapse state handler
 * ============================ */
function sendButtonState(buttonId, buttonState) {
    $.ajax({
        type: "POST",
        url: "/medias/expand_area/",
        data: {
            button_id: buttonId,
            button_state: buttonState,
            csrfmiddlewaretoken: $("input[name=csrfmiddlewaretoken]").val(),
        },
        success: function () {
            console.log("%c[update.js] ↕ Collapse state saved", "color:#9C27B0", buttonId, buttonState);
        },
        error: function (xhr) {
            console.error("%c[update.js] ✖ AJAX error expand_area", "color:red", xhr.responseText);
        },
    });
}

/* ============================
 * 🔁 Réattache les événements Bootstrap
 * ============================ */
function attachCollapseEvents() {
    $(".collapse").each(function () {
        const buttonId = $(this).attr("id");
        if (!buttonId.includes('collapseContent')) {
            $(this).off("hidden.bs.collapse shown.bs.collapse");
            $(this).on("hidden.bs.collapse", function () { sendButtonState(buttonId, 0); });
            $(this).on("shown.bs.collapse", function () { sendButtonState(buttonId, 1); });
        }
    });
}
