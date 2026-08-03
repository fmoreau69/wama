/**
 * Anonymizer — import de médias (port 2026-08-03).
 *
 * La zone d'import est la card d'entrée COMMUNE `_new_item_card` (drag&drop + URL +
 * batch + médiathèque) : ids `dropZoneAnonymizer` / `fileupload` / `anonUrlInput` /
 * `anonUrlSubmit`. L'upload passe par jQuery-file-upload (séquentiel + modale de
 * progression) vers IndexView.post ; en fin d'import les fichiers déposés ensemble
 * sont consolidés en UN batch, puis la page recharge (file re-rendue serveur).
 */
$(function () {
  const cfg = window.WAMA_ANON || {};

  // Consolidation des fichiers uploadés ensemble en UN batch (débouncé).
  let _anonUploadedIds = [];
  let _anonUploadTimer = null;
  function _finalizeAnonUpload() {
    const ids = _anonUploadedIds.slice();
    _anonUploadedIds = [];
    const done = () => location.reload();
    if (ids.length > 1) {
      fetch('/anonymizer/batch/consolidate/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': cfg.csrfToken },
        body: JSON.stringify({ ids }),
      }).then(done).catch(done);
    } else {
      done();
    }
  }

  // Initialize modal once and reuse the instance
  let progressModal = null;
  const modalElement = document.getElementById('modal-progress');

  if (modalElement) {
    progressModal = new bootstrap.Modal(modalElement, {
      backdrop: 'static',
      keyboard: false,
      focus: true
    });

    modalElement.addEventListener('hide.bs.modal', function () {
      const focusedElement = modalElement.querySelector(':focus');
      if (focusedElement) {
        focusedElement.blur();
      }
    });
    modalElement.addEventListener('hidden.bs.modal', function () {
      modalElement.setAttribute('aria-hidden', 'true');
    });
    modalElement.addEventListener('shown.bs.modal', function () {
      modalElement.setAttribute('aria-hidden', 'false');
    });
  }

  // Drag & drop : la card d'entrée commune gère l'apparence ; on branche l'upload.
  const dropZone = document.getElementById('dropZoneAnonymizer');
  const fileInput = document.getElementById('fileupload');

  if (dropZone && fileInput) {
    dropZone.addEventListener('click', function (e) {
      if (!e.target.closest('button')) {
        fileInput.click();
      }
    });

    ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
      dropZone.addEventListener(eventName, preventDefaults, false);
      document.body.addEventListener(eventName, preventDefaults, false);
    });

    function preventDefaults(e) {
      e.preventDefault();
      e.stopPropagation();
    }

    ['dragenter', 'dragover'].forEach(eventName => {
      dropZone.addEventListener(eventName, () => dropZone.classList.add('drag-over'), false);
    });
    ['dragleave', 'drop'].forEach(eventName => {
      dropZone.addEventListener(eventName, () => dropZone.classList.remove('drag-over'), false);
    });

    dropZone.addEventListener('drop', function (e) {
      const dt = e.dataTransfer;
      if (dt.files.length > 0) {
        $(fileInput).fileupload('add', { files: dt.files });
      }
    });
  }

  // Upload des fichiers (endpoint et CSRF via config — l'input commun n'a pas de data-url)
  $("#fileupload").fileupload({
    url: cfg.uploadUrl,
    dataType: 'json',
    sequentialUploads: true,

    // Inclut le format/qualité de sortie choisis dans le panneau (Phase 3 élargie)
    formData: function () {
      const fmt = (document.getElementById('output_format') || {}).value || 'original';
      const qual = (document.getElementById('output_quality') || {}).value || 'balanced';
      return [
        { name: 'csrfmiddlewaretoken', value: cfg.csrfToken },
        { name: 'output_format', value: fmt },
        { name: 'output_quality', value: qual },
      ];
    },

    start: function () {
      if (progressModal) {
        progressModal.show();
        $("#modal-progress .progress-bar").css({ width: "0%" }).text("0%").attr('aria-valuenow', 0);
      }
    },

    stop: function () {
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
        // Collecte des ids pour consolidation en batch (upload multi-fichiers)
        medias.forEach(function (m) { if (m.id) _anonUploadedIds.push(m.id); });
        if (window.WamaFM) WamaFM.uploaded();  // fichier ajouté → refresh filemanager

        if (data.result.errors && data.result.errors.length) {
          console.warn("Erreurs lors de l'ajout de médias :", data.result.errors);
        }
      } else {
        const error = data.result?.error || "Le fichier n'est pas valide ou une erreur est survenue.";
        WamaApp.toast(error, 'error');
      }

      // Consolidation débouncée puis reload : un seul batch si plusieurs fichiers ensemble.
      clearTimeout(_anonUploadTimer);
      _anonUploadTimer = setTimeout(_finalizeAnonUpload, 600);
    },

    fail: function (e, data) {
      WamaApp.toast("Échec du téléchargement : " + (data.errorThrown || "erreur inconnue"), 'error');
      if (progressModal) {
        progressModal.hide();
      }
    }
  });

  // Import par URL (champ de la card d'entrée commune)
  function submitUrlImport() {
    const input = document.getElementById('anonUrlInput');
    const mediaUrl = input ? input.value.trim() : '';
    if (!mediaUrl) {
      WamaApp.toast("Veuillez entrer une URL de média.", 'warning');
      return;
    }
    if (progressModal) progressModal.show();

    const _fmt = (document.getElementById('output_format') || {}).value || 'original';
    const _qual = (document.getElementById('output_quality') || {}).value || 'balanced';
    $.ajax({
      type: 'POST',
      url: cfg.uploadUrl,
      data: {
        csrfmiddlewaretoken: cfg.csrfToken,
        media_url: mediaUrl,
        output_format: _fmt,
        output_quality: _qual,
      },
      dataType: 'json',
      success: function (data) {
        if (data.success && data.media) {
          if (window.WamaFM) WamaFM.uploaded();
          location.reload();
        } else {
          WamaApp.toast(data.error || "Le téléchargement a échoué.", 'error');
        }
      },
      error: function (xhr) {
        let msg = "Une erreur s'est produite";
        try { msg = JSON.parse(xhr.responseText).error || msg; } catch (e) {}
        WamaApp.toast("Erreur téléchargement URL : " + msg, 'error');
      },
      complete: function () {
        if (progressModal) progressModal.hide();
        if (input) input.value = '';
      }
    });
  }

  const urlSubmit = document.getElementById('anonUrlSubmit');
  if (urlSubmit) {
    urlSubmit.addEventListener('click', function (e) {
      e.preventDefault();
      submitUrlImport();
    });
  }
  const urlInput = document.getElementById('anonUrlInput');
  if (urlInput) {
    urlInput.addEventListener('keydown', function (e) {
      if (e.key === 'Enter') {
        e.preventDefault();
        submitUrlImport();
      }
    });
  }
});
