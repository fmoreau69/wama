///// Update setting buttons values /////
(function($) {
    $.fn.SettingButtons = function (){
        this.each(function(){
            var self = this;
            function submitValues(inputId, inputValue) {
                $.ajax({
                    type: "POST",
                    url: "/medias/update_settings/",
                    data: {
                        input_id: inputId,
                        input_value: inputValue,
                        csrfmiddlewaretoken: $("input[name=csrfmiddlewaretoken]").val(),
                    },
                    success: function(res) {
                        console.log(inputId, inputValue)
                        $("#setting_button_container_" + inputId)[0].innerHTML = res['render'];
                    },
                    error: function(xhr, textStatus, errorThrown) {
                        console.error("AJAX error : " + errorThrown);
                     },
                })
            }

            $(this).change(function() {
                var inputId = $(this).attr("id");
                if (inputId.includes('switchCheck')) {
                    var inputValue = $(this).prop("checked");
                }
                else if (inputId.includes('customRange')) {
                    var inputValue = $(this).val();
                }
                submitValues(inputId, inputValue);
            });
        });
    };
})(jQuery);

$(document).ready(function() {
    $(".setting-button").SettingButtons();
});
$(document).ajaxComplete(function() {
    $(".setting-button").SettingButtons();
});

///// Update reset buttons /////
(function($) {
    $.fn.ResetButtons = function (){
        this.each(function(){
            var self = this;
        });
    }
})(jQuery);

$(document).ajaxComplete(function() {
    $(".reset-button").ResetButtons();
});

///// Update collapse button shown status /////
function SendButtonState(buttonId, buttonState){
    $.ajax({
        type: "POST",
        url: "/medias/expand_area/",
        data: {
            button_id: buttonId,
            button_state: buttonState,
            csrfmiddlewaretoken: $("input[name=csrfmiddlewaretoken]").val(),
        },
        success: function(res) {
//            console.log(buttonId, buttonState)
        },
        error: function(xhr, textStatus, errorThrown) {
            console.error("AJAX error : " + errorThrown);
        },
    })
}

$(".collapse").each(function(){
    var buttonId = $(this).attr("id");
    if (!buttonId.includes('collapseContent')) {
        $(this).on('hidden.bs.collapse', function () {
          SendButtonState(buttonId, 0);
        });
        $(this).on('shown.bs.collapse', function () {
          SendButtonState(buttonId, 1);
        });
    }
});
