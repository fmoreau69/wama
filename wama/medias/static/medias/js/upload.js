$(function () {
  // Ouvre le sélecteur de fichiers
  $(".js-upload-medias").click(function () {
    $("#fileupload").click();
  });

  // Upload des fichiers
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
      $(".progress-bar").css({ width: progress + "%" }).text(progress + "%");
    },

    done: function (e, data) {
      if (data.result && data.result.success) {
        const medias = data.result.added || (data.result.media ? [data.result.media] : []);

        medias.forEach(function (media) {
          $("#gallery tbody").prepend(
            `<tr><td><a href="${media.url}">${media.name}</a></td></tr>`
          );
        });

        if (data.result.errors && data.result.errors.length) {
          console.warn("Erreurs lors de l'ajout de médias :", data.result.errors);
        }
      } else {
        const error = data.result?.error || "Le fichier n'est pas valide ou une erreur est survenue.";
        alert(error);
      }

      // Rafraîchir le contenu après upload
      refreshContent();
    },

    fail: function (e, data) {
      alert("Échec du téléchargement : " + (data.errorThrown || "erreur inconnue"));
      $("#modal-progress").modal("hide");
    }
  });

  // Formulaire d'URL
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
        if (data.success && data.media) {
          $("#gallery tbody").prepend(
            `<tr><td><a href="${data.media.url}">${data.media.name}</a></td></tr>`
          );
        } else {
          const error = data.error || "Le téléchargement a échoué.";
          alert(error);
        }

        // Rafraîchir le contenu après ajout par URL
        refreshContent();
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

  // Fonction pour rafraîchir le contenu
  function refreshContent() {
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
  }
});
