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
 *     qui suit EXACTEMENT la même voie (`handleFiles`) qu'un fichier déposé ;
 *   • demande ce que la nature déclare `on_add` (langue, âge, genre d'une voix) et, replié, la
 *     PROVENANCE d'un extrait qui n'est pas de la personne (licence, auteur, page d'origine).
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
    var attrsHost = root.querySelector('[data-library-attrs]');
    var licenseInput = root.querySelector('[data-library-license]');
    var authorInput = root.querySelector('[data-library-author]');
    var sourceInput = root.querySelector('[data-library-source]');

    function esc(s) {
      return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
        return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
      });
    }

    // Ce que la NATURE demande à l'ajout (`Attr.on_add`, 2026-09-30) : un select quand la
    // déclaration nomme ses valeurs (choix, ou libellés — la langue), un champ libre sinon.
    // Rien n'est écrit ici : la déclaration arrive avec la nature (`natures_as_json`, onglets).
    function renderAttributes(n) {
      if (!attrsHost) return;
      var schema = (n && n.attributes) || {};
      var asked = Object.keys(schema).filter(function (k) { return schema[k].on_add; });
      attrsHost.hidden = !asked.length;
      attrsHost.innerHTML = asked.map(function (k) {
        var a = schema[k];
        var values = (a.choices && a.choices.length) ? a.choices : Object.keys(a.labels || {});
        if (values.length) {
          return '<select class="form-select form-select-sm" style="max-width:11rem" data-attr="' + esc(k) + '"'
            + ' title="' + esc(a.description) + '"><option value="">' + esc(a.label) + ' ?</option>'
            + values.map(function (v) {
                return '<option value="' + esc(v) + '">' + esc((a.labels || {})[v] || v) + '</option>';
              }).join('') + '</select>';
        }
        return '<input type="text" class="form-control form-control-sm" style="max-width:11rem" data-attr="'
          + esc(k) + '" placeholder="' + esc(a.label) + '" title="' + esc(a.description) + '">';
      }).join('');
    }

    // ── PROPOSER avant d'ajouter (2026-09-30) ─────────────────────────────────────────────
    // Une nature qui sait ESTIMER des attributs demandés (`on_add` + `estimated` : la langue
    // entendue, le genre de la voix) fait d'abord ÉCOUTER le fichier par le serveur ; les champs
    // restés VIDES se pré-remplissent (marqués « estimé »), la personne corrige, puis ajoute ou
    // ignore. Une valeur qu'elle a choisie elle-même n'est jamais écrasée.
    var pendingBox = root.querySelector('[data-library-pending]');
    var pendingText = root.querySelector('[data-library-pending-text]');
    var confirmBtn = root.querySelector('[data-library-confirm]');
    var skipBtn = root.querySelector('[data-library-skip]');

    if (attrsHost) {
      // Toucher un champ, c'est le faire sien : il n'est plus « estimé » (et reste pour la suite).
      attrsHost.addEventListener('change', function (e) {
        if (e.target && e.target.dataset) delete e.target.dataset.estimated;
        if (e.target && e.target.classList) e.target.classList.remove('border-info');
      });
    }

    function estimable(n) {
      var schema = (n && n.attributes) || {};
      return Object.keys(schema).some(function (k) { return schema[k].on_add && schema[k].estimated; });
    }

    function applyProposals(proposals) {
      var said = [];
      Object.keys(proposals || {}).forEach(function (k) {
        var p = proposals[k];
        var field = attrsHost && attrsHost.querySelector('[data-attr="' + k + '"]');
        if (!field || field.value) return;
        field.value = p.value;
        if (field.value !== String(p.value)) return;            // valeur absente du select
        field.dataset.estimated = '1';
        field.classList.add('border-info');
        said.push(p.label + (p.confidence != null ? ' (' + Math.round(p.confidence * 100) + ' %)' : ''));
      });
      return said;
    }

    function proposeThenConfirm(file) {
      var url = root.getAttribute('data-estimate-url');
      var n = nature();
      if (!url || !pendingBox || !estimable(n)) return Promise.resolve(true);
      pendingBox.hidden = false;
      pendingText.textContent = 'Écoute de « ' + (file.name || 'fichier') + ' »…';
      confirmBtn.disabled = skipBtn.disabled = true;
      var fd = new FormData();
      fd.append('asset_type', opts.getType());
      if (file.designation) fd.append('file__designated', file.designation);
      else fd.append('file', file);
      return fetch(url, { method: 'POST', body: fd, credentials: 'same-origin',
                          headers: { 'X-CSRFToken': opts.csrfToken || cookie('csrftoken') } })
        .then(function (r) { return r.json().catch(function () { return {}; }); })
        .catch(function () { return {}; })
        .then(function (data) {
          var said = applyProposals(data.proposals);
          pendingText.textContent = said.length
            ? 'Proposé d’après l’écoute de « ' + file.name + ' » : ' + said.join(' · ')
              + ' — vérifiez, puis ajoutez.'
            : 'Rien n’a pu être estimé pour « ' + file.name + ' » — renseignez si besoin, puis ajoutez.';
          confirmBtn.disabled = skipBtn.disabled = false;
          return new Promise(function (resolve) {
            function done(ok) {
              confirmBtn.removeEventListener('click', yes);
              skipBtn.removeEventListener('click', no);
              pendingBox.hidden = true;
              if (!ok) clearEstimated();
              resolve(ok);
            }
            function yes() { done(true); }
            function no() { done(false); }
            confirmBtn.addEventListener('click', yes);
            skipBtn.addEventListener('click', no);
          });
        });
    }

    // Une proposition vaut pour UN fichier : après son envoi (ou s'il est ignoré), les champs
    // qu'elle avait remplis se vident, pour que le suivant soit écouté à son tour.
    function clearEstimated() {
      if (!attrsHost) return;
      attrsHost.querySelectorAll('[data-estimated]').forEach(function (el) {
        el.value = '';
        delete el.dataset.estimated;
        el.classList.remove('border-info');
      });
    }

    function statedAttributes() {
      var out = {};
      if (attrsHost) {
        attrsHost.querySelectorAll('[data-attr]').forEach(function (el) {
          if (el.value) out[el.getAttribute('data-attr')] = el.value;
        });
      }
      return out;
    }

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
      renderAttributes(n);
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
        // Ce que la personne DIT du fichier (langue d'une voix…) et sa PROVENANCE : ils valent
        // pour tout le dépôt (plusieurs prises d'une même voix) et restent pour le suivant.
        fd.append('attributes', JSON.stringify(statedAttributes()));
        clearEstimated();
        if (licenseInput && licenseInput.value.trim()) fd.append('license', licenseInput.value.trim());
        if (authorInput && authorInput.value.trim()) fd.append('author', authorInput.value.trim());
        if (sourceInput && sourceInput.value.trim()) fd.append('source_url', sourceInput.value.trim());
      },
      beforeFile:    function (file) {
        var n = nature();
        if (!n) { toast('Choisissez d’abord une nature (onglet) pour y ajouter un fichier.', 'warning'); return false; }
        if (file.designation) return proposeThenConfirm(file);   // le serveur juge le format
        var ext = (file.name || '').split('.').pop().toLowerCase();
        if ((n.extensions || []).indexOf(ext) !== -1) return proposeThenConfirm(file);
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
