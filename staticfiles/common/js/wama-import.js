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
 *     folderInputId:  'converterFolderInput',       // optionnel : <input webkitdirectory>
 *     batch:          window._batchImport,          // instance WamaBatchImport (optionnel)
 *     batchScope:     'single' | 'each',            // défaut 'single' : lot testé si fichier SEUL
 *     consolidateUrl: APP.urls.consolidate,         // optionnel : regroupe N dépôts en lot
 *     consolidateField: 'ids',                      // 'job_ids' pour le contrat historique
 *     multiple:       false,                        // true : N fichiers en UNE requête (champ `files`)
 *     fieldName:      'file',                       // nom du champ POST (défaut : file / files)
 *     beforeFile:     function (file) { … },        // optionnel : rendre false = fichier écarté
 *     extraFields:    function (fd, file) { … },    // optionnel : champs POST supplémentaires
 *     afterImport:    function (ids, reponses) {…}, // défaut : rechargement de la page
 *   });
 *
 * Réponse d'upload acceptée : `{id}` / `{job_id}` / `{pk}` (scalaire), ou une LISTE —
 * `{ids:[…]}`, `{created:[{id}…]}`, `{added:[{id}…]}` (reader, anonymizer).
 *
 * Évolutions du 2026-09-05 (ROUTE « Portage F2 ») — chacune répond à un comportement qu'une
 * app en place a DÉJÀ et que la brique ne savait pas faire ; les DÉFAUTS sont inchangés, le
 * gabarit généré se comporte exactement comme avant.
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

    /**
     * Identifiants d'une réponse — scalaire à la racine OU LISTE (2026-09-05, ROUTE
     * « Portage F2 » évolution 1). Deux apps en place répondent une liste : reader
     * `{created:[…], multi}` (N fichiers en une requête) et anonymizer `{added:[…]}`. Avec la
     * lecture scalaire seule, `ids` restait VIDE et `handleFiles` sortait sans reload ni
     * message — le mode de panne le plus silencieux qui soit, précisément celui que l'en-tête
     * de cette brique dit vouloir éviter. Éléments de liste : objets à id, ou scalaires.
     */
    function identifiants(data) {
      if (!data || typeof data !== 'object') return [];
      var un = identifiant(data);
      if (un != null) return [un];
      var liste = data.ids || data.created || data.added || data.items;
      if (!Array.isArray(liste)) return [];
      return liste.map(function (x) { return (x && typeof x === 'object') ? identifiant(x) : x; })
                  .filter(function (v) { return v != null && v !== ''; });
    }

    /**
     * Envoie UN fichier, ou TOUS (`cfg.multiple` : une seule requête, champ répété — reader
     * poste `files` × N et son serveur groupe le lot lui-même, évolution 2). Rend
     * `{ids, data}` ; `ids` vide si erreur (déjà signalée).
     */
    async function envoyer(fichiers) {
      var fd = new FormData();
      var champ = cfg.fieldName || (cfg.multiple ? 'files' : 'file');
      fichiers.forEach(function (f) { fd.append(champ, f); });
      if (typeof cfg.extraFields === 'function') cfg.extraFields(fd, fichiers[0], fichiers);
      try {
        var resp = await poster(cfg.uploadUrl, fd);
        var data = {};
        try { data = await resp.json(); } catch (e) { data = {}; }
        if (!resp.ok || data.error) {
          signaler('Import : ' + (data.error || resp.statusText || 'échec'));
          return { ids: [], data: data };
        }
        if (global.WamaFM && WamaFM.uploaded) WamaFM.uploaded();
        return { ids: identifiants(data), data: data };
      } catch (err) {
        signaler('Import : ' + (err && err.message ? err.message : 'erreur réseau'));
        return { ids: [], data: null };
      }
    }

    /**
     * Point d'entrée UNIQUE, quelle que soit la provenance : glisser-déposer (explorateur
     * ou médiathèque), sélecteur de fichiers, ou appel direct d'une app.
     */
    async function handleFiles(files) {
      files = Array.prototype.slice.call(files || []);
      if (!files.length) return;

      // Un fichier peut être un descripteur de LOT : la décision appartient au formalisme
      // commun (structure du contenu), pas à cette brique. Portée DÉCLARÉE (évolution 6) :
      //   'single' (défaut) — seulement quand un fichier est déposé SEUL (le gabarit généré) ;
      //   'each'            — chaque fichier est testé, les lots reconnus sortent de l'envoi
      //                       (enhancer, synthesizer font ainsi aujourd'hui).
      if (cfg.batch && cfg.batch.detectAndHandle) {
        if ((cfg.batchScope || 'single') === 'each') {
          var restants = [];
          for (var b = 0; b < files.length; b++) {
            if (!(await cfg.batch.detectAndHandle(files[b]))) restants.push(files[b]);
          }
          files = restants;
          if (!files.length) return;
        } else if (files.length === 1) {
          if (await cfg.batch.detectAndHandle(files[0])) return;
        }
      }

      // Refus AVANT envoi (évolution 3) : `beforeFile(file) → false` écarte le fichier — 4 apps
      // refusent une extension ou exigent un réglage avant d'envoyer (converter, enhancer audio,
      // imager, avatarizer). `extraFields` ne pouvait pas annuler ; ce hook le peut. Il dit
      // lui-même pourquoi (toast) : la brique ne signale pas un refus qu'elle n'a pas décidé.
      if (typeof cfg.beforeFile === 'function') {
        var gardes = [];
        for (var g = 0; g < files.length; g++) {
          if ((await cfg.beforeFile(files[g])) !== false) gardes.push(files[g]);
        }
        files = gardes;
        if (!files.length) return;
      }

      var ids = [], reponses = [];
      if (cfg.multiple) {
        var r = await envoyer(files);
        ids = r.ids; reponses.push(r.data);
      } else {
        for (var i = 0; i < files.length; i++) {
          var ri = await envoyer([files[i]]);
          ids = ids.concat(ri.ids); reponses.push(ri.data);
        }
      }
      if (!ids.length) return;

      // Regroupement en lot(s) — l'app le déclare ; sans URL, les cards restent unitaires.
      //
      // ⚠ DEUX contrats coexistent, et se tromper ne PLANTE PAS : le regroupement répond
      // simplement `{"consolidated": false}` et les cards restent isolées, sans message.
      //   • fabrique commune (`queue_manipulation`) → lit `ids`  ← le défaut, car c'est elle
      //     qu'utilise toute app générée ;
      //   • vue propre au converter (`views.py:605`) → lit `job_ids`.
      // Mesuré le 2026-08-22 : j'avais repris `job_ids` de converter.js, donc la voie
      // « plusieurs fichiers » créait bien les cards mais ne les groupait jamais.
      // Une app au contrat historique passe `consolidateField: 'job_ids'`.
      if (cfg.consolidateUrl && ids.length > 1) {
        var fd = new FormData();
        var champ = cfg.consolidateField || 'ids';
        ids.forEach(function (id) { fd.append(champ, id); });
        try { await poster(cfg.consolidateUrl, fd); } catch (e) { /* non bloquant */ }
      }

      // `afterImport(ids, reponses)` (évolution 7) : 5 apps insèrent la card dans le DOM au
      // lieu de recharger — elles ont besoin de la RÉPONSE, pas seulement de l'id.
      if (typeof cfg.afterImport === 'function') cfg.afterImport(ids, reponses);
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
            if (!e.dataTransfer) return;
            // IMPORT = UN SEUL GESTE (décision Fabien 05/09, CARD_DESIGN §11.11 B bis) :
            // fichier(s) ET dossier(s), dépôt ET clic. La brique GLOBALE WamaFolderImport
            // traverse un drop mêlant les deux (récursif) et rend une liste plate ; sans
            // elle, repli sur `dataTransfer.files`. ⚠ Jusqu'au 05/09 cette brique ne lisait
            // que `files` : un DOSSIER déposé sur une app générée n'était pas traversé —
            // alors que 9 apps en place le faisaient chacune dans leur handler. Câbler le
            // parc sur la brique sans ce maillon aurait RÉGRESSÉ le drop de dossier.
            if (global.WamaFolderImport && global.WamaFolderImport.collect) {
              global.WamaFolderImport.collect(e.dataTransfer).then(function (liste) {
                var files = global.WamaFolderImport.files(liste);
                if (files.length) handleFiles(files);
              });
            } else if (e.dataTransfer.files && e.dataTransfer.files.length) {
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

      // Sélecteur de DOSSIER (`<input webkitdirectory>`, `folder_input_id` de la card) :
      // l'autre moitié du même geste, par le clic. Déclaré par l'app (`folderInputId`) —
      // ce câblage vivait dans le gabarit GÉNÉRÉ, hors brique, donc absent de toute app
      // qui adopterait la brique sans passer par le générateur.
      var fdi = el(cfg.folderInputId);
      if (fdi && fdi.dataset.wamaImportBound !== '1') {
        fdi.dataset.wamaImportBound = '1';
        fdi.addEventListener('change', function () {
          if (!this.files || !this.files.length) return;
          var files = global.WamaFolderImport
            ? global.WamaFolderImport.files(global.WamaFolderImport.fromInput(this.files))
            : Array.prototype.slice.call(this.files);
          if (files.length) handleFiles(files);
          this.value = '';
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

  // ⚠ Les helpers « chemin serveur → File → input » (drag depuis l'explorateur, montages)
  // vivent dans wama-app-base.js (`WamaApp.filesFromServerPaths` / `injectFiles`) : ce
  // fichier-ci n'est chargé que par les apps GÉNÉRÉES, l'explorateur est sur toutes les pages.

  global.WamaImport = WamaImport;
})(window);
