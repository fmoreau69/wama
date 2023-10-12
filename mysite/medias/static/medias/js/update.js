///// Update global settings values /////
$(document).ready(function() {
  $("#SwitchCheck_blur_faces, #SwitchCheck_blur_plates, #customRange_blur_ratio, #customRange_rounded_edges, #customRange_roi_enlargement, #customRange_detection_threshold, #SwitchCheck_show_preview, #SwitchCheck_show_boxes, #SwitchCheck_show_labels, #SwitchCheck_show_conf")
  .on("input change", function() {
    var inputId = $(this).attr("id");
    if (inputId.includes('SwitchCheck')) {
        var inputValue = $(this).prop("checked");
        } else if (inputId.includes('customRange')) {
        var inputValue = $(this).val();
        }
    submitValues(inputId, inputValue);
  });

  function submitValues(inputId, inputValue) {
    $.ajax({
      type: "POST",
      url: "/medias/update_options/",
      data: {
        input_id: inputId,
        input_value: inputValue,
        csrfmiddlewaretoken: $("input[name=csrfmiddlewaretoken]").val(),
      },
      success: function(res) {
        console.log(res);
        $("#global_settings_container")[0].innerHTML = res['render'];
      },
      error: function(xhr, textStatus, errorThrown) {
        console.error("AJAX error : " + errorThrown);
      },
    });
  }
});

///// Show or Hide global settings /////
$(document).ready(function () {
  $("#button_show_gs").click(function {
    $.ajax({
      type: "POST",
      url: "/medias/show_gs/",
      data: {
        input_id: inputId,
        input_value: inputValue,
        csrfmiddlewaretoken: $("input[name=csrfmiddlewaretoken]").val(),
      },
      success: function(res) {
        console.log(res);
        $("#collapseGlobalSettings")[0].innerHTML = res['render'];
      },
      error: function(xhr, textStatus, errorThrown) {
        console.error("AJAX error : " + errorThrown);
      },
    });
//    var subpageContainer = $("#global_settings_container");
//    subpageContainer.load("global_settings.html");
});
});
