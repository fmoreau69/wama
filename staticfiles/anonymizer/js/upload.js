$(function () {
  // Initialize modal once and reuse the instance
  let progressModal = null;
  const modalElement = document.getElementById('modal-progress');

  if (modalElement) {
    // Create modal instance with proper configuration
    progressModal = new bootstrap.Modal(modalElement, {
      backdrop: 'static',
      keyboard: false,
      focus: true
    });

    // Prevent focus retention on hide
    modalElement.addEventListener('hide.bs.modal', function () {
      // Blur any focused element inside the modal before closing
      const focusedElement = modalElement.querySelector(':focus');
      if (focusedElement) {
        focusedElement.blur();
      }
    });

    // Clean aria-hidden after modal is fully hidden
    modalElement.addEventListener('hidden.bs.modal', function () {
      modalElement.setAttribute('aria-hidden', 'true');
    });

    // Set aria-hidden to false when modal is shown
    modalElement.addEventListener('shown.bs.modal', function () {
      modalElement.setAttribute('aria-hidden', 'false');
    });
  }

  // Ouvre le sélecteur de fichiers
  $(".js-upload-medias").click(function () {
    $("#fileupload").click();
  });

  // Support Drag & Drop pour la zone d'upload
  const dropZone = document.getElementById('dropZoneAnonymizer');
  const fileInput = document.getElementById('fileupload');

  if (dropZone && fileInput) {
    // Click sur la zone = ouvrir le sélecteur
    dropZone.addEventListener('click', function(e) {
      // Ne pas déclencher si on clique sur le bouton (qui a déjà son handler)
      if (!e.target.closest('.js-upload-medias')) {
        fileInput.click();
      }
    });

    // Empêcher le comportement par défaut du navigateur
    ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
      dropZone.addEventListener(eventName, preventDefaults, false);
      document.body.addEventListener(eventName, preventDefaults, false);
    });

    function preventDefaults(e) {
      e.preventDefault();
      e.stopPropagation();
    }

    // Highlight de la zone au survol
    ['dragenter', 'dragover'].forEach(eventName => {
      dropZone.addEventListener(eventName, highlight, false);
    });

    ['dragleave', 'drop'].forEach(eventName => {
      dropZone.addEventListener(eventName, unhighlight, false);
    });

    function highlight() {
      dropZone.classList.add('drag-over');
    }

    function unhighlight() {
      dropZone.classList.remove('drag-over');
    }

    // Gestion du drop
    dropZone.addEventListener('drop', handleDrop, false);

    async function handleDrop(e) {
      // Check if this is a FileManager drop
      if (window.FileManager && window.FileManager.getFileManagerData) {
        const fileData = window.FileManager.getFileManagerData(e);
        if (fileData && fileData.path) {
          // Handle FileManager import
          try {
            const result = await window.FileManager.importToApp(fileData.path, 'anonymizer');
            if (result.imported) {
              // Reload the page to show the new file
              window.location.reload();
            }
          } catch (error) {
            console.error('FileManager import error:', error);
            if (window.FileManager.showToast) {
              window.FileManager.showToast('Erreur d\'import: ' + error.message, 'danger');
            }
          }
          return;
        }
      }

      // Regular file drop
      const dt = e.dataTransfer;
      const files = dt.files;

      if (files.length > 0) {
        // Simuler la sélection de fichiers via l'input
        fileInput.files = files;
        // Déclencher l'événement change pour fileupload
        $(fileInput).trigger('change');
      }
    }
  }

  // Upload des fichiers
  $("#fileupload").fileupload({
    dataType: 'json',
    sequentialUploads: true,

    start: function () {
      // Use the pre-initialized modal instance
      if (progressModal) {
        progressModal.show();
        $("#modal-progress .progress-bar").css({ width: "0%" }).text("0%").attr('aria-valuenow', 0);
      }
    },

    stop: function () {
      // Use the pre-initialized modal instance
      if (progressModal) {
        progressModal.hide();
      }
    },

    progressall: function (e, data) {
      const progress = parseInt((data.loaded / data.total) * 100, 10);
      $("#modal-progress .progress-bar").css({ width: progress + "%" }).text(progress + "%").attr('aria-valuenow', progress);
    },

    done: function (e, data) {
      if (data.result && data.result.success) {
        const medias = data.result.added || (data.result.media ? [data.result.media] : []);

        medias.forEach(function (media) {
          $("#gallery tbody").prepend(
            `<tr><td><button type="button" class="btn btn-link p-0 preview-media-link" data-preview-url="${media.preview_url}">${media.name}</button></td></tr>`
          );
        });

        if (typeof window.initMediaPreview === 'function') {
          window.initMediaPreview();
        }

        if (data.result.errors && data.result.errors.length) {
          console.warn("Erreurs lors de l'ajout de médias :", data.result.errors);
        }
      } else {
        const error = data.result?.error || "Le fichier n'est pas valide ou une erreur est survenue.";
        alert(error);
      }

      // Rafraîchir le contenu après upload et garder Start Process utilisable sans reload
      refreshContent(() => {
        // Optionnel: démarrer le process si l'utilisateur le souhaite (ex: prompt)
        // Ici, on ne démarre pas automatiquement, mais le bouton est prêt
      });
    },

    fail: function (e, data) {
      alert("Échec du téléchargement : " + (data.errorThrown || "erreur inconnue"));
      // Use the pre-initialized modal instance
      if (progressModal) {
        progressModal.hide();
      }
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

    // Use the pre-initialized modal instance
    if (progressModal) {
      progressModal.show();
    }

    $.ajax({
      type: 'POST',
      url: $form.attr("action"),
      data: $form.serialize(),
      dataType: 'json',
      success: function (data) {
        if (data.success && data.media) {
          $("#gallery tbody").prepend(
            `<tr><td><button type="button" class="btn btn-link p-0 preview-media-link" data-preview-url="${data.media.preview_url}">${data.media.name}</button></td></tr>`
          );
          if (typeof window.initMediaPreview === 'function') {
            window.initMediaPreview();
          }
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
        // Use the pre-initialized modal instance
        if (progressModal) {
          progressModal.hide();
        }
        $form[0].reset();
      }
    });
  });

  // Fonction pour rafraîchir le contenu
  function refreshContent(after) {
    // Clean up old modals and backdrops before refreshing
    cleanupModals();

    $.ajax({
      type: 'GET',
      url: '/anonymizer/refresh/',
      data: { template_name: 'content' },
      success: function (res) {
        if (res.render) {
          $("#main_container").html(res.render);

          // Re-initialize modals after content refresh
          reinitializeModals();

          if (typeof attachCollapseEvents === 'function') {
            attachCollapseEvents();
          }
          if (typeof window.initProcessControls === 'function') {
            window.initProcessControls();
          }
          if (typeof window.initMediaPreview === 'function') {
            window.initMediaPreview();
          }
          if (typeof after === 'function') after();
        }
      },
      error: function () {
        console.warn("Échec du rafraîchissement du contenu.");
      }
    });
  }

  // Clean up old modal instances and backdrops
  function cleanupModals() {
    // Find all modals that were moved to body level
    document.querySelectorAll('[id^="modal_classes2blur"]').forEach(function(modal) {
      const bsModal = bootstrap.Modal.getInstance(modal);
      if (bsModal) {
        bsModal.dispose();
      }
      modal.remove();
    });

    // Remove any leftover modal backdrops
    document.querySelectorAll('.modal-backdrop').forEach(function(backdrop) {
      backdrop.remove();
    });

    // Remove modal-open class from body
    document.body.classList.remove('modal-open');
    document.body.style.overflow = '';
    document.body.style.paddingRight = '';
  }

  // Re-initialize modals after content refresh
  function reinitializeModals() {
    // Move all modals that start with "modal_classes2blur" to body level
    document.querySelectorAll('[id^="modal_classes2blur"]').forEach(function(modal) {
      document.body.appendChild(modal);
    });
  }

  // Expose these functions globally for use by other scripts
  window.cleanupModals = cleanupModals;
  window.reinitializeModals = reinitializeModals;
});
