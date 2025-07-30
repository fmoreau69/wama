$(document).ready(function () {
    /**
     * Envoie la valeur au serveur via AJAX
     * @param {string} inputId - L'ID de l'input (ex: media_setting_blur_ratio_17)
     * @param {string|boolean|number} inputValue - La nouvelle valeur
     */
    function submitValues(inputId, inputValue) {
        console.log("[update.js] ▶ Sending update", { inputId, inputValue });

        const parts = inputId.split('_');
        const setting_type = parts[0] + '_' + parts[1];
        let media_id = null;
        let setting_name = null;

        if (setting_type === 'media_setting') {
            media_id = parts[parts.length - 1];
            setting_name = parts.slice(2, parts.length - 1).join('_');
        } else if (setting_type === 'global_setting') {
            setting_name = parts.slice(2).join('_');
        } else {
            // cas éventuel
            setting_name = parts.slice(2).join('_');
        }

        let data = {
            setting_type: setting_type,
            setting_name: setting_name,
            input_value: inputValue,
            csrfmiddlewaretoken: $("input[name=csrfmiddlewaretoken]").val(),
        };

        if (setting_type === 'media_setting') {
            data.media_id = media_id;
        }

        $.ajax({
            type: "POST",
            url: "/medias/update_settings/",
            data: data,
            success: function (res) {
                if (res.render) {
                    $("#setting_button_container_" + inputId).html(res.render);
                    console.log("[update.js] ✔ Update success", res);
                } else {
                    console.warn("[update.js] ⚠ Unexpected server response", res);
                }
            },
            error: function (xhr, textStatus, errorThrown) {
                console.error("[update.js] ✖ AJAX error", {
                    errorThrown,
                    status: xhr.status,
                    response: xhr.responseText
                });
            },
        });
    }

    /**
     * Surveille tous les inputs dynamiques ayant la classe 'setting-button'
     */
    $(document).on("input change", ".setting-button", function () {
        const $el = $(this);
        const inputId = $el.attr("id");
        const inputType = $el.attr("type");
        let inputValue;

        if (inputType === "checkbox") {
            inputValue = $el.prop("checked") ? "true" : "false";
        } else {
            inputValue = $el.val();
        }

        console.log("%c[update.js] ✏ Trigger change", "color: #2196F3;", { inputId, inputType, inputValue });
        submitValues(inputId, inputValue);
    });

    /**
     * Gestion du bouton "Clear All Media"
     */
    $(document).on("click", "#clear_all_media_btn", function (e) {
        e.preventDefault();
        if (!confirm("Voulez-vous vraiment supprimer tous les médias ?")) {
            return;
        }

        console.log("%c[update.js] 🧹 Envoi clear_all_media", "color: purple;");

        $.ajax({
            type: "POST",
            url: "/medias/clear_all_media/",
            data: {
                csrfmiddlewaretoken: $("input[name=csrfmiddlewaretoken]").val(),
            },
            success: function (res) {
                if (res.render) {
                    $("#main_container").html(res.render);
                    console.log("%c[update.js] ✔ Médias supprimés", "color: #4CAF50;", res);
                } else {
                    console.warn("%c[update.js] ⚠ Réponse inattendue clear_all_media", "color: orange;", res);
                }
            },
            error: function (xhr) {
                console.error("%c[update.js] ✖ Erreur clear_all_media", "color: red;", xhr.responseText || "Erreur inconnue");
                alert("Erreur lors de la suppression des médias : " + (xhr.responseText || "Erreur inconnue"));
            },
        });
    });
});

/**
 * Envoie l'état du bouton (collapse show/hide) au serveur
 * @param {string} buttonId - l'id du collapse
 * @param {number} buttonState - 1 si ouvert, 0 si fermé
 */
function sendButtonState(buttonId, buttonState) {
    console.log("[update.js] ▶ Sending button state", { buttonId, buttonState });

    $.ajax({
        type: "POST",
        url: "/medias/expand_area/",
        data: {
            button_id: buttonId,
            button_state: buttonState,
            csrfmiddlewaretoken: $("input[name=csrfmiddlewaretoken]").val(),
        },
        success: function (res) {
            console.log("[update.js] ✔ Button state updated", res);
        },
        error: function (xhr, textStatus, errorThrown) {
            console.error("[update.js] ✖ AJAX error expand_area", {
                errorThrown,
                status: xhr.status,
                response: xhr.responseText
            });
        },
    });
}

// Attache les événements bootstrap collapse
$(".collapse").each(function () {
    var buttonId = $(this).attr("id");
    if (!buttonId.includes('collapseContent')) {
        $(this).on('hidden.bs.collapse', function () {
            sendButtonState(buttonId, 0);
        });
        $(this).on('shown.bs.collapse', function () {
            sendButtonState(buttonId, 1);
        });
    }
});
