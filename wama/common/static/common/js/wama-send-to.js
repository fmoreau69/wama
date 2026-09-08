/**
 * WAMA — ENVOYER VERS : la sortie d'une card devient l'entrée d'une autre app. Brique COMMUNE.
 *
 * Cadre (Fabien, 2026-09-08) : « la sortie qu'on envoie en entrée d'une autre app, dans l'idée de
 * faire du chaînage progressif, sans forcément devoir passer par le studio ».
 *
 * DEUX APPELS, ET AUCUN DISPATCH NOUVEAU :
 *   ① `/common/api/envoyer-vers/<surface>/<pk>/` (GET) — RÉSOLVEUR : les chemins de sortie
 *      déclarés, les apps éligibles, et l'endpoint qui reçoit ;
 *   ② cet endpoint, `filemanager:api_import` — celui qui sert DÉJÀ « Envoyer vers… » depuis le
 *      gestionnaire de fichiers (critère de grille `filemanager_import` 10/10, scénario nocturne
 *      `<app>.send_to`). On ne réimplémente donc ni l'import ni ses gardes : il revalide
 *      `is_path_allowed` et l'accès à l'app côté serveur.
 *
 * ⚠ L'URL de l'endpoint est RENDUE par le résolveur, pas écrite ici : une brique commune n'a pas
 * à connaître les routes d'une autre app, et un changement de route ne la casse pas.
 *
 * ⚠ Les destinations sont DÉRIVÉES côté serveur (importeur + extension déclarée + accès), jamais
 * listées. C'est la leçon du Geste 14 : le menu du gestionnaire de fichiers a offert pendant des
 * semaines trois apps que le serveur refusait. Ici, une liste vide s'AFFICHE (« aucune app ne
 * prend ce format ») au lieu d'ouvrir un sous-menu creux.
 */
(function (global) {
    'use strict';

    function csrf() {
        var m = document.cookie.match(/csrftoken=([^;]+)/);
        return m ? m[1] : '';
    }

    function dire(msg, type) {
        if (global.WamaApp && WamaApp.toast) { WamaApp.toast(msg, type || 'info'); return; }
        if (type === 'error') alert(msg);
    }

    /** Surface + pk d'une card — MÊME contrat que le partage (`data-preview-url`). */
    function coordonnees(card) {
        if (global.WamaShare && WamaShare.coordonnees) return WamaShare.coordonnees(card);
        return null;
    }

    function resoudre(surface, pk) {
        return fetch('/common/api/envoyer-vers/' + encodeURIComponent(surface) + '/'
                     + encodeURIComponent(pk) + '/', { credentials: 'same-origin' })
            .then(function (r) {
                if (!r.ok) throw new Error('HTTP ' + r.status);
                return r.json();
            });
    }

    function envoyer(endpoint, chemins, app, libelle) {
        return fetch(endpoint, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf() },
            credentials: 'same-origin',
            // `paths` (pluriel) : l'endpoint le gère depuis toujours, et une génération d'imager
            // rend N images. Envoyer le premier fichier seul serait un chaînage tronqué.
            body: JSON.stringify({ paths: chemins, app: app }),
        }).then(function (r) {
            return r.json().catch(function () { return { success: r.ok }; })
                .then(function (d) {
                    if (!r.ok) {
                        // Le statut ne se perd pas : sans ça un refus se raconterait comme un
                        // succès (même règle que le glisser-déposer et le partage).
                        throw new Error((d && (d.error || d.reason)) || ('HTTP ' + r.status));
                    }
                    return d;
                });
        }).then(function (d) {
            var n = (d && (d.imported || d.count)) || chemins.length;
            dire(n + ' fichier(s) envoyé(s) vers ' + libelle, 'success');
            return d;
        }).catch(function (err) {
            dire('Envoi impossible — ' + err.message, 'error');
            throw err;
        });
    }

    /**
     * Les entrées de sous-menu pour cette card — résolues au SERVEUR, au moment du clic.
     *
     * Rend une promesse : le menu s'ouvre avant, sur « Recherche… ». Une card sans sortie ou
     * dont le format n'intéresse personne rend une liste VIDE, que le menu affiche comme telle.
     */
    function entrees(card) {
        var c = coordonnees(card);
        if (!c) return Promise.resolve([]);
        return resoudre(c.surface, c.pk).then(function (d) {
            if (!d || !d.chemins || !d.chemins.length) return [];
            return (d.destinations || []).map(function (dest) {
                return {
                    icone: dest.icone || 'fas fa-cube',
                    libelle: dest.libelle,
                    agir: function () {
                        envoyer(d.endpoint, d.chemins, dest.app, dest.libelle);
                    },
                };
            });
        });
    }

    global.WamaSendTo = { entrees: entrees, coordonnees: coordonnees,
                          resoudre: resoudre, envoyer: envoyer };
})(window);
