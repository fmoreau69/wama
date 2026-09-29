/**
 * WamaBatchImport — Common batch import component for all Type A apps.
 *
 * Returns an API object: { detectAndHandle(file) -> bool }
 * Hooks batch bar buttons automatically.
 * Optionally hooks drop zone + file input if dropZoneId/fileInputId are provided
 * (use for new apps; existing apps call detectAndHandle() from their own handleFiles).
 *
 * Usage — new app (auto-hooks events):
 *
 *   window._batchImport = WamaBatchImport({
 *     dropZoneId:      'dropZoneXxx',
 *     fileInputId:     'file-input-id',
 *     batchPreviewUrl: '/app/batch/preview/',
 *     batchCreateUrl:  '/app/batch/create/',
 *     csrfToken:       '{{ csrf_token }}',
 *     afterCreate:     function(data, autoStart) { location.reload(); },
 *   });
 *
 * Usage — existing app (manual integration):
 *
 *   window._batchImport = WamaBatchImport({
 *     batchPreviewUrl: '...',
 *     batchCreateUrl:  '...',
 *     csrfToken:       '...',
 *     formDataBuilder: function(fd) { fd.append('backend', 'auto'); },
 *     afterCreate:     function(data, autoStart) { ... },
 *   });
 *   // In the app's handleFiles():
 *   if (files.length === 1 && window._batchImport.detectAndHandle(files[0])) return;
 *
 * Expected DOM (provided by common/batch_detect_bar.html include):
 *   #batchDetectBar, #batchDetectedCount, #batchDetectPreview,
 *   #batchDetectWarnings, #batchDetectTable, #batchCreateCount,
 *   #batchCreateAndStartBtn, #batchCreateOnlyBtn, #batchPreviewBtn,
 *   #batchCancelBar, #batchCreateProgress
 */

function WamaBatchImport(cfg) {
  'use strict';

  // Default: only plain-text formats can be batch descriptor files.
  // Binary formats (pdf, docx, images, audio, video) are always direct media —
  // they must never be misidentified as batch lists of URLs/paths.
  // Override per-app with cfg.batchExtensions if needed (rare edge case).
  const BATCH_EXTS = cfg.batchExtensions || ['txt', 'md', 'csv'];
  let _file = null;
  let _lastError = '';

  // ── Helpers ────────────────────────────────────────────────────────────────

  // `idBase` (2026-09-08, enhancer AUDIO) : DEUX voies de lot sur une même page exigent deux
  // barres, donc deux jeux d'ids. Les 11 ids de la barre commencent tous par `batch` — la base
  // les remplace (`audioBatch` → `audioBatchDetectBar`…), et `common/batch_detect_bar.html`
  // les rend depuis la même variable (`bid`). Avant, l'enhancer audio recopiait la barre ET
  // sa logique (10 fonctions) faute de cette seule option.
  const ID_BASE = cfg.idBase || 'batch';
  function el(id) { return document.getElementById(ID_BASE + id.slice('batch'.length)); }

  function escHtml(s) {
    return String(s || '').replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  function isBatch(file) {
    const ext = file.name.split('.').pop().toLowerCase();
    if (!BATCH_EXTS.includes(ext)) return false;
    // Additional guard: binary MIME types are never batch descriptors regardless of extension.
    const mime = file.type || '';
    if (mime && !mime.startsWith('text/') && mime !== 'application/octet-stream') return false;
    return true;
  }

  // ── Bar visibility ─────────────────────────────────────────────────────────

  // La barre ANNONCE son ouverture et sa fermeture (2026-09-29) : l'onglet « Lot » de la card
  // v4 bascule dessus quelle que soit la voie qui a apporté le fichier (onglet Lot, dépôt sur
  // le port de travail, texte collé). Événement DOM qui remonte à la card : aucune app à câbler.
  function announce(bar, name, detail) {
    if (bar) bar.dispatchEvent(new CustomEvent(name, { bubbles: true,
      detail: Object.assign({ base: ID_BASE }, detail || {}) }));
  }

  function showBar(count) {
    const bar = el('batchDetectBar');
    const cnt = el('batchDetectedCount');
    const prv = el('batchDetectPreview');
    if (!bar) return;
    if (cnt) cnt.textContent = count;
    if (prv) prv.style.display = 'none';
    bar.style.display = '';
    announce(bar, 'wama:batch-shown', { count: count, name: _file ? _file.name : '' });
  }

  function hideBar() {
    _file = null;
    const bar = el('batchDetectBar');
    const prv = el('batchDetectPreview');
    if (bar) bar.style.display = 'none';
    if (prv) prv.style.display = 'none';
    announce(bar, 'wama:batch-hidden');
  }

  // ── Preview ────────────────────────────────────────────────────────────────

  function defaultBuildRow(item) {
    return `<tr><td class="text-truncate" style="max-width:200px;" title="${escHtml(item.path)}">${escHtml(item.filename || item.path)}</td></tr>`;
  }

  function populatePreview(data) {
    const tbody   = el('batchDetectTable');
    const cntSpan = el('batchCreateCount');
    const warnEl  = el('batchDetectWarnings');
    const prv     = el('batchDetectPreview');
    if (!tbody) return;

    tbody.innerHTML = '';
    const buildRow = cfg.buildRow || defaultBuildRow;
    (data.items || []).forEach(item => {
      tbody.insertAdjacentHTML('beforeend', buildRow(item));
    });

    if (cntSpan) cntSpan.textContent = data.count;
    if (warnEl) {
      if (data.warnings && data.warnings.length) {
        warnEl.textContent = data.warnings.join(' | ');
        warnEl.style.display = '';
      } else {
        warnEl.style.display = 'none';
      }
    }
    if (prv) prv.style.display = '';
  }

  async function doPreview(file) {
    _file = file;
    _lastError = '';
    const fd = new FormData();
    fd.append('batch_file', file);
    fd.append('csrfmiddlewaretoken', cfg.csrfToken);

    let data;
    try {
      const resp = await fetch(cfg.batchPreviewUrl, { method: 'POST', body: fd });
      data = await resp.json();
    } catch (err) {
      console.error('[batch-import.js] preview error', err);
      hideBar();
      return false;
    }

    if (data.error) {
      _file = null;
      _lastError = String(data.error);
      return false;
    }

    if (!data.count) {
      _lastError = (data.warnings || []).join(' · ');
      // Server found 0 valid items — file is not a usable batch descriptor.
      // Fall back to direct media upload (e.g. a PDF OCR document, not a URL list).
      _file = null;
      return false;
    }

    showBar(data.count);
    populatePreview(data);
    return true;
  }

  // ── Create ─────────────────────────────────────────────────────────────────

  async function doCreate(autoStart) {
    if (!_file) return;

    const progress = el('batchCreateProgress');
    const startBtn = el('batchCreateAndStartBtn');
    const addBtn   = el('batchCreateOnlyBtn');

    if (progress) progress.style.display = '';
    if (startBtn) startBtn.disabled = true;
    if (addBtn)   addBtn.disabled   = true;

    const fd = new FormData();
    fd.append('batch_file', _file);
    fd.append('csrfmiddlewaretoken', cfg.csrfToken);
    if (typeof cfg.formDataBuilder === 'function') cfg.formDataBuilder(fd);

    let data;
    try {
      const resp = await fetch(cfg.batchCreateUrl, {
        method: 'POST',
        headers: { 'X-CSRFToken': cfg.csrfToken },
        body: fd,
      });
      data = await resp.json();
    } catch (err) {
      console.error('[batch-import.js] create error', err);
      if (progress) progress.style.display = 'none';
      if (startBtn) startBtn.disabled = false;
      if (addBtn)   addBtn.disabled   = false;
      return;
    }

    if (progress) progress.style.display = 'none';
    if (startBtn) startBtn.disabled = false;
    if (addBtn)   addBtn.disabled   = false;

    if (data.error) {
      alert('Erreur batch : ' + data.error);
      return;
    }

    // ⚠ Un lot REFUSÉ LIGNE À LIGNE répond `success: true` — pas `error`. Les vues renvoient
    // alors `count: 0` et un `warnings[]` qui dit POURQUOI chaque ligne a été écartée
    // (« Échec téléchargement : … », « Introuvable : … », « Type non supporté : … »). Jusqu'ici
    // on refermait la barre et on rechargeait : l'utilisateur voyait la page revenir IDENTIQUE,
    // sans élément et sans un mot — le diagnostic que le serveur venait d'écrire était jeté.
    // Mesuré le 2026-08-27 sur le converter, qui résout la source À LA CRÉATION
    // (`upload_media_from_url`) : toute URL injoignable donnait ce silence. Défaut de la BRIQUE,
    // donc corrigé ici pour les 9 apps et pas dans le converter.
    const motifs = (data.warnings || []).join(' · ');
    if (typeof data.count === 'number' && data.count === 0) {
      const msg = motifs
        ? 'Aucun élément créé — ' + motifs
        : "Aucun élément créé : l'app n'a retenu aucune ligne du fichier.";
      if (window.WamaApp && WamaApp.toast) WamaApp.toast(msg, 'error'); else alert(msg);
      return;  // on LAISSE la barre ouverte : l'utilisateur corrige son fichier et rejoue.
    }
    if (motifs) {
      const msg = 'Créés : ' + data.count + ' — lignes écartées : ' + motifs;
      if (window.WamaApp && WamaApp.toast) WamaApp.toast(msg, 'warning'); else alert(msg);
    }

    hideBar();

    if (typeof cfg.afterCreate === 'function') {
      cfg.afterCreate(data, autoStart);
    } else {
      location.reload();
    }
  }

  // ── Bar buttons ────────────────────────────────────────────────────────────

  function hookBarButtons() {
    el('batchPreviewBtn')?.addEventListener('click', () => {
      if (_file) doPreview(_file);
    });
    el('batchCancelBar')?.addEventListener('click', hideBar);
    el('batchCreateAndStartBtn')?.addEventListener('click', () => doCreate(true));
    el('batchCreateOnlyBtn')?.addEventListener('click',     () => doCreate(false));
  }

  // ── Optional: auto-hook drop zone + file input ─────────────────────────────
  // Used by new apps that don't have their own handleFiles logic.
  // Existing apps call detectAndHandle() from their own handler instead.

  function hookDropZone() {
    const dz = cfg.dropZoneId ? el(cfg.dropZoneId) : null;
    const fi = cfg.fileInputId ? el(cfg.fileInputId) : null;

    if (dz) {
      // Clic = ouvrir le sélecteur (la zone affiche « cliquez pour importer »).
      if (fi) dz.addEventListener('click', () => fi.click());
      dz.addEventListener('dragover', e => e.preventDefault());
      dz.addEventListener('drop', async e => {
        e.preventDefault();
        const files = e.dataTransfer?.files;
        if (files) {
          for (const f of files) {
            if (isBatch(f)) { await doPreview(f); return; }
          }
        }
        // Non-batch: let other drop handlers or the app deal with it
      });
    }

    if (fi) {
      fi.addEventListener('change', async function () {
        if (!this.files || !this.files.length) return;
        for (const f of this.files) {
          if (isBatch(f)) {
            await doPreview(f);
            this.value = '';
            return;
          }
        }
      });
    }
  }

  // ── Public API ─────────────────────────────────────────────────────────────

  /**
   * detectAndHandle(file) — call this from your app's handleFiles() to delegate
   * batch detection. Returns true if the file was identified as a batch file
   * (preview triggered); the caller should then return early.
   */
  async function detectAndHandle(file) {
    if (!isBatch(file)) return false;
    const ok = await doPreview(file);
    return ok !== false;
  }

  /**
   * ingestText(text, filename) — fait passer du texte brut (ex. une URL saisie
   * dans la card d'entrée) par le MÊME pipeline batch qu'un fichier déposé.
   * Le texte est enveloppé dans un File .txt synthétique → parsé par le
   * formalisme batch commun (batch_parsers : URL, prompt, séparateur, csv…) →
   * consolidé en card unité ou batch. Aucune route serveur dédiée.
   * Retourne la promesse de detectAndHandle (true si pris en charge = preview).
   */
  function ingestText(text, filename) {
    const file = new File([text], filename || 'batch.txt', { type: 'text/plain' });
    return detectAndHandle(file);
  }

  /**
   * previewFile(file) — l'utilisateur a DIT que ce fichier est un lot (onglet « Lot » de la
   * card v4, 2026-09-29). C'est la règle 1 de BATCH_FORMAT (« l'intention déclarée prime ») :
   * pas de devinette par extension ni par type MIME, donc un `.pdf`/`.docx` de lot passe
   * (le serveur les lit, `SUPPORTED_BATCH_EXTENSIONS`), et un refus se DIT — alors que la
   * voie implicite (`detectAndHandle`) se tait exprès pour retomber sur l'upload direct.
   */
  async function previewFile(file) {
    if (!file) return false;
    const ok = await doPreview(file);
    if (ok === true) return true;
    const msg = 'Ce fichier n\'a donné aucun élément de lot'
      + (_lastError ? ' — ' + _lastError : ' : aucune ligne reconnue (voir le gabarit de lot).');
    if (window.WamaApp && window.WamaApp.toast) window.WamaApp.toast(msg, 'error'); else alert(msg);
    return false;
  }

  // ── Init ───────────────────────────────────────────────────────────────────

  function init() {
    hookBarButtons();
    if (cfg.dropZoneId || cfg.fileInputId) hookDropZone();
  }

  // ⚠ La brique est le plus souvent INSTANCIÉE DEPUIS un écouteur `DOMContentLoaded` d'app
  // (composer, imager, converter_01…). S'abonner alors à cet événement ne branche RIEN : il a
  // déjà été émis et ne repassera jamais. Défaut MUET — l'aperçu s'ouvrait normalement (il part
  // de `detectAndHandle()`, appelé par l'app), puis « Ajouter » et « Démarrer » ne faisaient
  // rien : aucune requête, aucune erreur console, aucun message. Mesuré sur l'imager le
  // 2026-08-27 en exerçant le geste ; corrigé ICI et pas dans les apps, car c'est la brique qui
  // doit être instanciable à tout moment (le contraire ferait une consigne à répéter 12 fois).
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  const api = { detectAndHandle, ingestText, previewFile };
  // Chaque instance s'INSCRIT sous la base d'ids de sa barre : la card commune la retrouve par
  // `batch_bid`, qu'elle connaît déjà, sans savoir sous quel nom l'app l'a rangée
  // (`_batchImport`, `_batchImportVideo`, `_converterBatchImport`, variable locale…).
  WamaBatchImport.instances[ID_BASE] = api;
  return api;
}
WamaBatchImport.instances = {};
