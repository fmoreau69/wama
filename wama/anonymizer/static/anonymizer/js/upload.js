/**
 * Anonymizer — import de médias (port 2026-08-03).
 *
 * La zone d'import est la card d'entrée COMMUNE `_new_item_card` (drag&drop + URL +
 * batch + médiathèque) : ids `dropZoneAnonymizer` / `fileupload` / `anonUrlInput` /
 * `anonUrlSubmit`. L'upload passe par la brique commune WamaImport (portage 2026-09-07,
 * 7ᵉ app en place) : envoi séquentiel avec la barre de progression COMMUNE, lot testé sur
 * chaque fichier, consolidation en UN batch quand plusieurs fichiers arrivent ensemble, puis
 * la page recharge (file re-rendue serveur). L'URL passe par le formalisme de lot commun
 * (08/09). jQuery-file-upload et la modale `#modal-progress` n'ont plus de consommateur.
 */
$(function () {
  const cfg = window.WAMA_ANON || {};

  // (La modale `#modal-progress` a disparu le 08/09 : la progression d'envoi est la barre
  // commune de la brique, l'import par URL passe par le formalisme de lot — plus rien à montrer.)

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
  // Fabien) : la modale `#modal-progress` (héritage jQuery-file-upload, puis hooks
  // `onProgress`/`onSettled` le 07/09) est RETIRÉE du gabarit.
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

  // Import par URL : le FORMALISME COMMUN, comme les 6 autres apps portées (08/09, Fabien :
  // « l'import par URL n'est pas propre aux apps, c'est le portage qui n'était pas terminé »).
  // L'URL = un lot d'UNE ligne → même parseur (`batch_parsers`) → `batch_create` la stocke en
  // `source_url` (régime PARESSEUX, `WAMA_INGEST` sur `Media`) et `ensure_local_input` la
  // télécharge AU LANCEMENT de la tâche. L'ancien `$.ajax` maison postait `media_url` à la vue
  // d'upload, qui téléchargeait À L'IMPORT derrière une modale bloquante — la seule app du parc
  // à le faire (`MEDIA_STORAGE_TIERING §8.3`). `initUrlImport` (commun) porte champ, bouton,
  // touche Entrée, spinner, vidage et erreurs ; le format/qualité de sortie viennent du
  // `formDataBuilder` du lot (gabarit), comme pour un fichier de lot.
  if (window.WamaApp && WamaApp.initUrlImport) {
    WamaApp.initUrlImport({
      inputId: 'anonUrlInput',
      buttonId: 'anonUrlSubmit',
      onEmpty: function () { WamaApp.toast("Veuillez entrer une URL de média.", 'warning'); },
      onSubmit: function (url) {
        if (!window._batchImport) throw new Error("Import batch non initialisé");
        return window._batchImport.ingestText(url + '\n', 'url.txt');
      },
    });
  }
});
