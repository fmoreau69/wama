/**
 * WamaLibraryAdd — le câblage de la card d'AJOUT de la médiathèque (2026-09-30).
 *
 * POURQUOI. La page médiathèque savait ajouter (card d'entrée commune + `WamaImport` → `api_upload`)
 * mais ce câblage vivait DANS son JS ; la fenêtre commune de sélection (`MediaPicker`), ouverte
 * depuis toutes les apps, ne savait que CHOISIR. Pour une voix de clonage, on devait donc quitter
 * l'app, aller sur la page médiathèque, ajouter, revenir, recharger, choisir (constat de Fabien).
 * Le câblage est désormais ICI, une fois ; la page et la fenêtre le déclarent.
 *
 * CE QU'IL FAIT, pour la card `common/_new_item_card_library.html` d'une racine `[data-library-add]` :
 *   • dit ce que la NATURE de l'onglet accepte (attribut `accept`, libellé sous la zone) ;
 *   • envoie les fichiers déposés / choisis / glissés depuis l'arbre par `WamaImport` vers
 *     `api_upload` (le serveur convertit vers le pivot, lit durée et attributs) ;
 *   • montre « Enregistrer » quand la nature est déclarée `recordable` : le micro produit un webm,
 *     qui suit EXACTEMENT la même voie (`handleFiles`) qu'un fichier déposé.
 *
 * Usage :
 *   const add = WamaLibraryAdd.wire({
 *     root:      document.querySelector('[data-library-add="ml"]'),
 *     getType:   () => currentNature,          // '' = aucune nature choisie (onglet « Tous »)
 *     getNature: key => ({label, extensions, recordable}),   // la déclaration `natures_as_json`
 *     csrfToken: '…',                            // défaut : cookie `csrftoken`
 *     toast:     (msg, level) => …,              // défaut : WamaApp.toast
 *     onAdded:   (assets) => …,                  // les assets CRÉÉS (réponse d'`api_upload`)
 *   });
 *   add.refresh();   // après un changement d'onglet
 *
 * `wire` rend une PROMESSE quand `WamaImport` n'est pas encore chargé (fenêtre commune ouverte
 * sur une page sans `_app_scripts.html`) : le script est chargé depuis `data-import-src`.
 */
(function (global) {
  'use strict';

  var MAX_RECORD_SECONDS = 30;

  function cookie(name) {
    var m = document.cookie.match(new RegExp('(?:^|; )' + name + '=([^;]*)'));
    return m ? decodeURIComponent(m[1]) : '';
  }

  function loadScript(src) {
    return new Promise(function (resolve, reject) {
      if (global.WamaImport) { resolve(); return; }
      var s = document.createElement('script');
      s.src = src;
      s.onload = function () { resolve(); };
      s.onerror = function () { reject(new Error('script introuvable : ' + src)); };
      document.head.appendChild(s);
    });
  }

  function stamp() {
    var d = new Date();
    function p(n) { return String(n).padStart(2, '0'); }
    return d.getFullYear() + '-' + p(d.getMonth() + 1) + '-' + p(d.getDate()) + ' ' +
           p(d.getHours()) + 'h' + p(d.getMinutes()) + 'm' + p(d.getSeconds());
  }

  function bind(opts) {
    var root = opts.root;
    var prefix = root.getAttribute('data-library-add');
    var toast = opts.toast || function (msg, level) {
      if (global.WamaApp && WamaApp.toast) WamaApp.toast(msg, level === 'error' ? 'danger' : level);
    };
    var fileInput = root.querySelector('#' + prefix + 'FileInput');
    var hint = root.querySelector('#' + prefix + 'DropZone small');
    var recordZone = root.querySelector('[data-library-record]');
    var recordBtn = root.querySelector('[data-library-record-btn]');
    var recordLabel = root.querySelector('[data-library-record-label]');
    var recordTimer = root.querySelector('[data-library-record-timer]');
    var recordHint = root.querySelector('[data-library-record-hint]');
    var nameInput = root.querySelector('[data-library-name]');

    function nature() {
      var key = opts.getType();
      return key ? (opts.getNature(key) || null) : null;
    }

    function refresh() {
      var n = nature();
      var ext = (n && n.extensions) || [];
      if (fileInput) fileInput.accept = ext.map(function (e) { return '.' + e; }).join(',');
      if (hint) {
        hint.textContent = n
          ? n.label + ' — ' + ext.map(function (e) { return e.toUpperCase(); }).join(', ')
          : 'Choisissez d’abord une nature (onglet) pour y ajouter un fichier.';
      }
      if (recordZone) recordZone.hidden = !(n && n.recordable);
      if (recordHint) recordHint.textContent = n && n.recordable
        ? 'Quelques secondes suffisent pour une voix de clonage (' + MAX_RECORD_SECONDS + ' s max).' : '';
    }

    var api = global.WamaImport({
      uploadUrl:     root.getAttribute('data-upload-url'),
      csrfToken:     opts.csrfToken || cookie('csrftoken'),
      dropZoneId:    prefix + 'DropZone',
      fileInputId:   prefix + 'FileInput',
      folderInputId: prefix + 'FolderInput',
      extraFields:   function (fd) {
        fd.append('asset_type', opts.getType());
        // Le nom saisi vaut pour le PREMIER fichier envoyé, puis se vide : un dépôt de plusieurs
        // fichiers ne les nomme pas tous pareil (le serveur refuserait les suivants, nom pris).
        var name = nameInput ? nameInput.value.trim() : '';
        if (name) { fd.append('name', name); nameInput.value = ''; }
      },
      beforeFile:    function (file) {
        var n = nature();
        if (!n) { toast('Choisissez d’abord une nature (onglet) pour y ajouter un fichier.', 'warning'); return false; }
        if (file.designation) return true;          // le serveur juge (format, provenance)
        var ext = (file.name || '').split('.').pop().toLowerCase();
        if ((n.extensions || []).indexOf(ext) !== -1) return true;
        toast('Format .' + ext + ' non admis ici. Attendu : ' +
              (n.extensions || []).map(function (e) { return e.toUpperCase(); }).join(', '), 'error');
        return false;
      },
      afterImport:   function (ids, responses) {
        var assets = (responses || []).filter(function (r) { return r && r.id; });
        if (typeof opts.onAdded === 'function') opts.onAdded(assets);
      },
    });

    // ── Enregistrer (nature `recordable`) ───────────────────────────────────
    var recorder = null, chunks = [], started = 0, tick = null;

    function stopTimer() {
      if (tick) { clearInterval(tick); tick = null; }
      if (recordTimer) recordTimer.hidden = true;
      if (recordLabel) recordLabel.textContent = 'Enregistrer';
      if (recordBtn) recordBtn.classList.replace('btn-danger', 'btn-outline-info');
    }

    async function startRecording() {
      if (!nature()) { toast('Choisissez d’abord une nature (onglet).', 'warning'); return; }
      var stream;
      try {
        stream = await navigator.mediaDevices.getUserMedia({
          audio: { echoCancellation: true, noiseSuppression: true } });
      } catch (err) {
        toast(err && err.name === 'NotAllowedError'
          ? 'Accès au microphone refusé : autorisez-le dans les réglages du navigateur.'
          : 'Micro indisponible : ' + (err && err.message || err), 'error');
        return;
      }
      chunks = [];
      recorder = new MediaRecorder(stream);
      recorder.ondataavailable = function (e) { if (e.data && e.data.size) chunks.push(e.data); };
      recorder.onstop = function () {
        stream.getTracks().forEach(function (t) { t.stop(); });
        stopTimer();
        var blob = new Blob(chunks, { type: recorder.mimeType || 'audio/webm' });
        recorder = null;
        if (!blob.size) { toast('Enregistrement vide.', 'warning'); return; }
        // Même voie qu'un fichier déposé : le serveur le range dans le pivot de la nature (wav).
        api.handleFiles([new File([blob], 'Enregistrement ' + stamp() + '.webm', { type: 'audio/webm' })]);
      };
      recorder.start();
      started = Date.now();
      if (recordLabel) recordLabel.textContent = 'Arrêter';
      if (recordBtn) recordBtn.classList.replace('btn-outline-info', 'btn-danger');
      if (recordTimer) { recordTimer.hidden = false; recordTimer.textContent = '0 s'; }
      tick = setInterval(function () {
        var s = Math.floor((Date.now() - started) / 1000);
        if (recordTimer) recordTimer.textContent = s + ' s';
        if (s >= MAX_RECORD_SECONDS && recorder && recorder.state === 'recording') recorder.stop();
      }, 250);
    }

    if (recordBtn) {
      recordBtn.addEventListener('click', function () {
        if (recorder && recorder.state === 'recording') recorder.stop();
        else startRecording();
      });
    }

    refresh();
    return { refresh: refresh, handleFiles: api && api.handleFiles };
  }

  function wire(opts) {
    if (!opts || !opts.root) throw new Error('WamaLibraryAdd.wire : racine [data-library-add] requise');
    if (global.WamaImport) return bind(opts);
    return loadScript(opts.root.getAttribute('data-import-src')).then(function () { return bind(opts); });
  }

  global.WamaLibraryAdd = { wire: wire };
})(window);
