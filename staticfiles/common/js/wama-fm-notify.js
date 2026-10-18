/* ===========================================================================
 * WAMA — Notification commune au gestionnaire de fichiers
 * ===========================================================================
 * Centralise le signalement des changements de fichiers vers le filemanager
 * (qui écoute media:uploaded / media:processed / media:deleted et rafraîchit
 * son arborescence, de façon débouncée).
 *
 * Les BRIQUES COMMUNES appellent ces helpers — une app n'a rien à écrire (2026-10-17) :
 *   WamaFM.uploaded()    → un fichier de travail vient d'être ajouté (`WamaImport`, socle JS)
 *   WamaFM.processed()   → une sortie vient d'être créée : la barre de progression globale
 *                          émet `media:processed` quand le compte des tâches terminées monte
 *                          (`wama-global-progress.js`, montée par les dix apps) — six apps le
 *                          répétaient dans leur propre suivi, doublons retirés ce jour-là
 *   WamaFM.deleted()     → un fichier a été supprimé (`queue-actions.js` : 🗑 d'élément, de lot
 *                          et « Tout effacer » de file — les dix apps y passent depuis le
 *                          2026-10-17, leurs `deleted()` locaux sont retirés avec leurs handlers)
 *   WamaFM.refresh()     → forcer un rafraîchissement
 *   WamaFM.upload(files, csrf) → DÉPOSE des fichiers dans l'espace de l'utilisateur (2026-10-18) :
 *                          `/filemanager/api/upload/`, le geste partagé avec Discord et l'API
 *                          (`enregistrer_fichier_utilisateur`), puis `uploaded()`. Rend la réponse
 *                          (`{uploaded: [{id, name, path, size}]}`). Le glisser-déposer sur le chat
 *                          de l'assistant et la zone « Mes Fichiers » de l'accueil simplifié y
 *                          passent — la seconde l'écrivait à la main.
 * Aucune app n'appelle plus ces helpers elle-même : un nouvel appel dans une app signale un
 * geste écrit à côté d'une brique commune.
 *
 * ⚠ Il n'y a PLUS de filet de sécurité : la surveillance périodique de l'arbre a été retirée
 * le 2026-10-13 (`filemanager.js`). Un événement non émis = un arbre qui ne se met pas à jour.
 * ======================================================================== */
(function () {
    'use strict';
    function emit(name) {
        try { document.dispatchEvent(new CustomEvent(name)); } catch (e) { /* noop */ }
    }
    var UPLOAD_URL = '/filemanager/api/upload/';

    function csrfToken() {
        if (window.WamaApp && window.WamaApp.csrfToken) return window.WamaApp.csrfToken();
        var m = document.cookie.match(/csrftoken=([^;]+)/);
        return m ? m[1] : '';
    }

    function upload(files, csrf) {
        var fd = new FormData();
        (files || []).forEach(function (f) { fd.append('files', f); });
        return fetch(UPLOAD_URL, { method: 'POST', headers: { 'X-CSRFToken': csrf || csrfToken() },
                                   body: fd })
            .then(function (r) {
                return r.json().catch(function () { return { error: 'HTTP ' + r.status }; });
            })
            .then(function (d) {
                if (d && d.uploaded && d.uploaded.length) emit('media:uploaded');
                return d || {};
            });
    }

    window.WamaFM = {
        uploaded:  function () { emit('media:uploaded'); },
        processed: function () { emit('media:processed'); },
        deleted:   function () { emit('media:deleted'); },
        refresh:   function () { emit('filemanager:refresh'); },
        upload:    upload,
    };
})();
