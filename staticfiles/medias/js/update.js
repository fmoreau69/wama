$(document).ready(function () {

    /**
     * Ajoute un délai pour limiter le nombre de requêtes
     */
    function debounce(func, wait) {
        let timeout;
        return function (...args) {
            clearTimeout(timeout);
            timeout = setTimeout(() => func.apply(this, args), wait);
        };
    }

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
    const debouncedSubmit = debounce(submitValues, 150);  // 150 ms de délai

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
        debouncedSubmit(inputId, inputValue);
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
                console.log("%c[update.js] ✔ Médias supprimés, rechargement de la page", "color: #4CAF50;");
                window.location.reload();
            },
            error: function (xhr) {
                console.error("%c[update.js] ✖ Erreur clear_all_media", "color: red;", xhr.responseText || "Erreur inconnue");
                alert("Erreur lors de la suppression des médias : " + (xhr.responseText || "Erreur inconnue"));
            },
        });
    });

    /**
     * Gestion des formulaires ajax
     */
    $(document).on("submit", ".ajax-form", function (e) {
        e.preventDefault();

        const $form = $(this);
        const actionUrl = $form.attr("action");
        const method = $form.attr("method") || "POST";
        const targetSelector = $form.data("target") || "#main_container";
        const formData = $form.serialize();

        // console.log("[ajax-form] ▶ Envoi AJAX", { actionUrl, method, targetSelector });

        $.ajax({
            type: method,
            url: actionUrl,
            data: formData,
            success: function (res) {
                if (res.render) {
                    $(targetSelector).html(res.render);
                    attachCollapseEvents();
                    // console.log("[ajax-form] ✔ Contenu mis à jour", { targetSelector });
                } else {
                    console.warn("[ajax-form] ⚠ Réponse inattendue", res);
                }
            },
            error: function (xhr) {
                console.error("[ajax-form] ✖ Erreur AJAX", xhr.responseText || "Erreur inconnue");
                alert("Erreur lors de l'envoi du formulaire : " + (xhr.responseText || "Erreur inconnue"));
            }
        });
    });
    attachCollapseEvents();
});

/**
 * Envoie l'état du bouton (collapse show/hide) au serveur
 * @param {string} buttonId - l'id du collapse
 * @param {number} buttonState - 1 si ouvert, 0 si fermé
 */
function sendButtonState(buttonId, buttonState) {
    // console.log("[update.js] ▶ Sending button state", { buttonId, buttonState });

    $.ajax({
        type: "POST",
        url: "/medias/expand_area/",
        data: {
            button_id: buttonId,
            button_state: buttonState,
            csrfmiddlewaretoken: $("input[name=csrfmiddlewaretoken]").val(),
        },
        success: function (res) {
            // console.log("[update.js] ✔ Button state updated", res);
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

/**
 * Attache les événements Bootstrap collapse aux éléments dynamiquement réinjectés
 */
function attachCollapseEvents() {
    $(".collapse").each(function () {
        const buttonId = $(this).attr("id");
        if (!buttonId.includes('collapseContent')) {
            $(this).off("hidden.bs.collapse shown.bs.collapse");  // évite les doublons
            $(this).on('hidden.bs.collapse', function () {
                sendButtonState(buttonId, 0);
            });
            $(this).on('shown.bs.collapse', function () {
                sendButtonState(buttonId, 1);
            });
        }
    });
}
