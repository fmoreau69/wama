/**
 * Anonymizer — import de médias (port 2026-08-03).
 *
 * La zone d'import est la card d'entrée COMMUNE `_new_item_card` (drag&drop + URL +
 * batch + médiathèque) : ids `dropZoneAnonymizer` / `fileupload` / `anonUrlInput` /
 * `anonUrlSubmit`. L'upload passe par la brique commune WamaImport (portage 2026-09-07,
 * 7ᵉ app en place) : envoi séquentiel AVEC progression (XHR — évolution 8 de la brique,
 * écrite pour cette modale), lot testé sur chaque fichier, consolidation en UN batch quand
 * plusieurs fichiers arrivent ensemble, puis la page recharge (file re-rendue serveur).
 * jQuery-file-upload n'a plus de consommateur ici.
 */
$(function () {
  const cfg = window.WAMA_ANON || {};

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

  // Protège la PAGE : un fichier lâché hors de la zone ne doit pas être ouvert par le
  // navigateur (comportement d'avant, conservé — ce n'est pas de l'import, c'est de la page).
  ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(function (eventName) {
    document.body.addEventListener(eventName, function (e) { e.preventDefault(); e.stopPropagation(); }, false);
  });

  // ── Voie d'import : brique commune WamaImport (wama-import.js) — portage 2026-09-07 ──
  //
  // Ce qui vivait ici — jQuery-file-upload (séquentiel, `paramName:'file'`, `add` déléguant
  // le LOT à la brique batch, `formData`, modale de progression, `done` collectant `added[]`,
  // consolidation débouncée puis reload) — est le contrat de la brique. L'app ne DÉCLARE que :
  //   • `batchScope:'each'` : chaque fichier est testé comme descripteur de lot (un `.txt` de
  //                           lot ne part JAMAIS vers /upload/ — leçon du 27/08) ;
  //   • `extraFields`     : format et qualité de sortie du volet ;
  //   • `afterImport`     : les erreurs PAR LIGNE (`errors[]`) restent lisibles en console,
  //                           puis reload (file re-rendue serveur).
  // La PROGRESSION D'ENVOI est celle de la brique, COMMUNE à toutes les apps (08/09, demande
  // Fabien) : la modale `#modal-progress` que cette app montrait pendant l'upload (héritage
  // jQuery-file-upload, puis hooks `onProgress`/`onSettled` le 07/09) n'est plus utilisée
  // ICI — elle ne sert plus qu'à l'import par URL ci-dessous, chemin propre à l'app.
  // Réponse `{success, added:[{id…}], errors}` : lue par la brique (évolution 1, écrite le
  // 05/09 pour ce contrat). Consolidation `ids` (multipart) → `anonymizer:consolidate`, qui lit
  // par le lecteur commun `ids_from_request` (corrigé le 07/09 : il lisait `request.body`).
  if (typeof window.WamaImport === 'function') {
    window._import = WamaImport({
      uploadUrl:        cfg.uploadUrl,
      consolidateUrl:   cfg.consolidateUrl,
      consolidateField: 'ids',
      csrfToken:        cfg.csrfToken,
      dropZoneId:       'dropZoneAnonymizer',
      fileInputId:      'fileupload',
      folderInputId:    'anonFolderInput',
      batch:            window._batchImport,
      batchScope:       'each',
      extraFields:      function (fd) {
        fd.append('output_format', (document.getElementById('output_format') || {}).value || 'original');
        fd.append('output_quality', (document.getElementById('output_quality') || {}).value || 'balanced');
      },
      afterImport:      function (_ids, reponses) {
        reponses.forEach(function (r) {
          if (r && r.errors && r.errors.length) console.warn("Erreurs lors de l'ajout de médias :", r.errors);
        });
        location.reload();
      },
    });
  } else {
    // Défaut le plus silencieux qui soit (une zone de dépôt que rien n'écoute) → on le DIT.
    WamaApp.toast("Voie d'import non chargée (wama-import.js) — dépôt impossible", 'error');
    console.error('[Anonymizer] WamaImport absent : wama-import.js non chargé par le gabarit');
  }

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
