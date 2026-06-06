/* ===========================================================================
 * WAMA — Notification commune au gestionnaire de fichiers
 * ===========================================================================
 * Centralise le signalement des changements de fichiers vers le filemanager
 * (qui écoute media:uploaded / media:processed / media:deleted et rafraîchit
 * son arborescence, de façon débouncée).
 *
 * Les apps appellent ces helpers plutôt que de dispatcher les events à la main
 * → noms d'events centralisés, comportement homogène (logique d'import unifiée).
 *
 *   WamaFM.uploaded()    → un fichier de travail vient d'être ajouté (input)
 *   WamaFM.processed()   → une sortie vient d'être créée (fin de traitement)
 *   WamaFM.deleted()     → un fichier a été supprimé
 *   WamaFM.refresh()     → forcer un rafraîchissement
 *
 * Filet de sécurité complémentaire : le filemanager poll aussi les mtime
 * (~5 s) et détecte les changements même sans appel explicite.
 * ======================================================================== */
(function () {
    'use strict';
    function emit(name) {
        try { document.dispatchEvent(new CustomEvent(name)); } catch (e) { /* noop */ }
    }
    window.WamaFM = {
        uploaded:  function () { emit('media:uploaded'); },
        processed: function () { emit('media:processed'); },
        deleted:   function () { emit('media:deleted'); },
        refresh:   function () { emit('filemanager:refresh'); },
    };
})();
