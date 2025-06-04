$(function () {

  // Déclenche l'ouverture du sélecteur de fichiers
  $(".js-upload-medias").click(function () {
    $("#fileupload").click();
  });

  // Gestion de l'upload des fichiers
  $("#fileupload").fileupload({
    dataType: 'json',
    sequentialUploads: true,

    start: function () {
      $("#modal-progress").modal("show");
      $(".progress-bar").css({ width: "0%" }).text("0%");
    },

    stop: function () {
      $("#modal-progress").modal("hide");
    },

    progressall: function (e, data) {
      const progress = parseInt((data.loaded / data.total) * 100, 10);
      const strProgress = progress + "%";
      $(".progress-bar").css({ "width": strProgress }).text(strProgress);
    },

    done: function (e, data) {
      if (data.result && data.result.is_valid) {
        $("#gallery tbody").prepend(
          `<tr><td><a href="${data.result.url}">${data.result.name}</a></td></tr>`
        );
      } else {
        alert("Le fichier n'est pas valide ou une erreur est survenue.");
      }
    },

    fail: function (e, data) {
      alert("Échec du téléchargement : " + (data.errorThrown || "erreur inconnue"));
    }

  }).bind('fileuploaddone', function () {
    $.ajax({
      type: 'GET',
      url: '/medias/refresh/',
      data: { template_name: 'content' },
      success: function (res) {
        if (res.render) {
          $("#main_container").html(res.render);
        }
      },
      error: function () {
        console.warn("Échec du rafraîchissement du contenu.");
      }
    });
  });

  // Gestion de l'envoi d'une URL de média (via formulaire)
  $("#media-url-form").submit(function (e) {
    e.preventDefault();

    const $form = $(this);
    const mediaUrl = $form.find("input[name='media_url']").val();

    if (!mediaUrl) {
      alert("Veuillez entrer une URL de média.");
      return;
    }

    $("#modal-progress").modal("show");

    $.ajax({
      type: 'POST',
      url: $form.attr("action"),
      data: $form.serialize(),
      dataType: 'json',
      success: function (data) {
        if (data.is_valid) {
          $("#gallery tbody").prepend(
            `<tr><td><a href="${data.url}">${data.name}</a></td></tr>`
          );
        } else {
          alert("Le téléchargement a échoué.");
        }
      },
      error: function (xhr) {
        alert("Erreur : " + (xhr.responseText || "Une erreur s'est produite"));
      },
      complete: function () {
        $("#modal-progress").modal("hide");
        $form[0].reset();
      }
    });
  });

});
