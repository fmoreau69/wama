/**
 * WamaImport — LA voie d'import commune d'une app (2026-08-22).
 *
 * POURQUOI CETTE BRIQUE. Elle manquait, et son absence rendait toute app GÉNÉRÉE incapable
 * de créer la moindre card, en silence : `batch-import.js` sait s'accrocher à la zone de
 * dépôt mais ne traite QUE les fichiers de lot — pour un fichier ordinaire son propre
 * commentaire dit « laissons l'app s'en occuper » (hookDropZone), c'est-à-dire personne.
 * Chaque app écrivait donc son propre `handleFiles` (converter.js, reader.js, index.js…) :
 * la même boucle upload → consolidation → rafraîchissement, réécrite dix fois, et absente
 * de la onzième dès qu'elle est générée.
 *
 * CE QU'ELLE FAIT. Une app DÉCLARE ses URL et les ids de sa zone de dépôt ; elle n'écrit
 * plus de JS d'import. Le lot est délégué à WamaBatchImport (détection structurelle), le
 * reste part vers l'endpoint d'upload de l'app.
 *
 * AGNOSTIQUE DU MONDE (garde-fou demandé par Fabien) : aucune hypothèse « média » ici —
 * ni type MIME, ni extension, ni notion de durée. Une app du monde Data ou Lab peut s'en
 * servir telle quelle. Ce qui est propre au média (détection de type, formats de sortie)
 * reste dans les apps ou dans des briques dédiées.
 *
 * Usage :
 *   window._import = WamaImport({
 *     uploadUrl:      APP.urls.upload,
 *     csrfToken:      APP.csrfToken,
 *     dropZoneId:     'converterDropZone',
 *     fileInputId:    'converterFileInput',
 *     batch:          window._batchImport,          // instance WamaBatchImport (optionnel)
 *     consolidateUrl: APP.urls.consolidate,         // optionnel : regroupe N dépôts en lot
 *     extraFields:    function (fd) { … },          // optionnel : champs POST supplémentaires
 *     afterImport:    function (ids) { … },         // défaut : rechargement de la page
 *   });
 */
(function (global) {
  'use strict';

  function WamaImport(cfg) {
    cfg = cfg || {};

    function el(id) { return id ? document.getElementById(id) : null; }

    function poster(url, fd) {
      if (global.WamaApp && WamaApp.csrfFetch) {
        return WamaApp.csrfFetch(url, cfg.csrfToken, { method: 'POST', body: fd });
      }
      fd.append('csrfmiddlewaretoken', cfg.csrfToken);
      return fetch(url, { method: 'POST', body: fd });
    }

    function signaler(msg, niveau) {
      if (global.WamaApp && WamaApp.toast) WamaApp.toast(msg, niveau || 'error');
      else console.error('[WamaImport]', msg);
    }

    /**
     * Lecture TOLÉRANTE de l'identifiant renvoyé par l'endpoint d'upload.
     *
     * Les vues n'ont jamais eu de contrat commun : converter renvoie `job_id`, le gabarit
     * de génération renvoie `id`, d'autres `pk`. Mesuré le 2026-08-22 : converter.js lisait
     * `data.job_id` là où la vue générée renvoyait `data.id` — l'identifiant sortait
     * `undefined`, la liste restait vide, le rechargement n'avait jamais lieu et AUCUNE card
     * n'apparaissait, sans la moindre erreur. On accepte donc les trois graphies plutôt que
     * de faire dépendre l'affichage d'un nom de clé. La normalisation des vues reste
     * souhaitable — mais elle ne doit plus être ce qui décide si l'utilisateur voit sa card.
     */
    function identifiant(data) {
      if (!data || typeof data !== 'object') return null;
      var v = (data.job_id != null) ? data.job_id
            : (data.id != null) ? data.id
            : (data.pk != null) ? data.pk : null;
      return (v === null || v === '' ) ? null : v;
    }

    /** Envoie UN fichier. Rend son identifiant, ou null (l'erreur est déjà signalée). */
    async function envoyer(file) {
      var fd = new FormData();
      fd.append(cfg.fieldName || 'file', file);
      if (typeof cfg.extraFields === 'function') cfg.extraFields(fd, file);
      try {
        var resp = await poster(cfg.uploadUrl, fd);
        var data = {};
        try { data = await resp.json(); } catch (e) { data = {}; }
        if (!resp.ok || data.error) {
          signaler('Import : ' + (data.error || resp.statusText || 'échec'));
          return null;
        }
        if (global.WamaFM && WamaFM.uploaded) WamaFM.uploaded();
        return identifiant(data);
      } catch (err) {
        signaler('Import : ' + (err && err.message ? err.message : 'erreur réseau'));
        return null;
      }
    }

    /**
     * Point d'entrée UNIQUE, quelle que soit la provenance : glisser-déposer (explorateur
     * ou médiathèque), sélecteur de fichiers, ou appel direct d'une app.
     */
    async function handleFiles(files) {
      files = Array.prototype.slice.call(files || []);
      if (!files.length) return;

      // Un fichier SEUL peut être un descripteur de lot : la décision appartient au
      // formalisme commun (structure du contenu), pas à cette brique.
      if (files.length === 1 && cfg.batch && cfg.batch.detectAndHandle) {
        if (await cfg.batch.detectAndHandle(files[0])) return;
      }

      var ids = [];
      for (var i = 0; i < files.length; i++) {
        var id = await envoyer(files[i]);
        if (id != null) ids.push(id);
      }
      if (!ids.length) return;

      // Regroupement en lot(s) — l'app le déclare ; sans URL, les cards restent unitaires.
      if (cfg.consolidateUrl && ids.length > 1) {
        var fd = new FormData();
        ids.forEach(function (id) { fd.append('job_ids', id); });
        try { await poster(cfg.consolidateUrl, fd); } catch (e) { /* non bloquant */ }
      }

      if (typeof cfg.afterImport === 'function') cfg.afterImport(ids);
      else global.location.reload();
    }

    /** Fait passer du TEXTE (URL collée, liste saisie) par le même chemin qu'un fichier. */
    function ingestText(text, filename) {
      if (cfg.batch && cfg.batch.ingestText) return cfg.batch.ingestText(text, filename);
      return handleFiles([new File([text], filename || 'import.txt', { type: 'text/plain' })]);
    }

    function brancher() {
      var dz = el(cfg.dropZoneId);
      var fi = el(cfg.fileInputId);

      if (dz) {
        // Repères posés sur l'élément : un second branchement (batch-import pose les siens)
        // ne doit pas doubler les envois — la leçon de la double inclusion du 18/08.
        if (dz.dataset.wamaImportBound !== '1') {
          dz.dataset.wamaImportBound = '1';
          if (fi) dz.addEventListener('click', function () { fi.click(); });
          dz.addEventListener('dragover', function (e) {
            e.preventDefault();
            dz.classList.add('dragover');
          });
          dz.addEventListener('dragleave', function () { dz.classList.remove('dragover'); });
          dz.addEventListener('drop', function (e) {
            e.preventDefault();
            dz.classList.remove('dragover');
            if (e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files.length) {
              handleFiles(e.dataTransfer.files);
            }
          });
        }
      }

      if (fi && fi.dataset.wamaImportBound !== '1') {
        fi.dataset.wamaImportBound = '1';
        fi.addEventListener('change', function () {
          if (this.files && this.files.length) {
            handleFiles(this.files);
            this.value = '';           // re-déposer le MÊME fichier doit re-déclencher
          }
        });
      }
    }

    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', brancher);
    } else {
      brancher();
    }

    return { handleFiles: handleFiles, ingestText: ingestText, brancher: brancher };
  }

  global.WamaImport = WamaImport;
})(window);
