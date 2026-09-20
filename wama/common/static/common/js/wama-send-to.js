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

    /**
     * Résout les destinations de CHEMINS du gestionnaire de fichiers (2026-09-14) : le MÊME
     * résolveur serveur que pour une card, entré par `{paths}` ou `{folder}`. L'arbre ne calcule
     * plus rien chez le client.
     */
    function resoudreChemins(corps) {
        return fetch('/common/api/envoyer-vers/chemins/', {
            method: 'POST', credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf() },
            body: JSON.stringify(corps),
        }).then(function (r) {
            if (!r.ok) throw new Error('HTTP ' + r.status);
            return r.json();
        });
    }

    /**
     * Envoie vers `app`. `charge` : une LISTE de chemins, ou `{folder}` pour un dossier entier.
     * Émet `wama:fileimported` par fichier reçu — l'app de destination ouverte met sa file à jour
     * sans rechargement (contrat `WAMA_APP_CONVENTIONS` « Import depuis le filemanager »).
     */
    function envoyer(endpoint, charge, app, libelle) {
        // `paths` (pluriel) : l'endpoint le gère depuis toujours, et une génération d'imager
        // rend N images. Envoyer le premier fichier seul serait un chaînage tronqué.
        var corps = Array.isArray(charge) ? { paths: charge, app: app }
                                          : Object.assign({ app: app }, charge);
        return fetch(endpoint, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf() },
            credentials: 'same-origin',
            body: JSON.stringify(corps),
        }).then(function (r) {
            return r.json().catch(function () { return { success: r.ok }; })
                .then(function (d) {
                    if (!r.ok) {
                        // Le statut ne se perd pas : sans ça un refus se raconterait comme un
                        // succès (même règle que le glisser-déposer et le partage).
                        throw new Error((d && (d.error || d.reason)) || ('HTTP ' + r.status));
                    }
                    // Un fichier SEUL refusé répond 200 `{imported:false, error}` : c'est un échec.
                    if (d && d.imported === false && d.error) throw new Error(d.error);
                    return d;
                });
        }).then(function (d) {
            var refused = (d && d.errors) || [];
            // Rien de reçu. Si le serveur a REFUSÉ des fichiers, c'est SON motif qu'on dit (accès,
            // fichier introuvable…) : « aucun fichier compatible » ne vaut que sans refus
            // (message trompeur relevé à l'audit du 14/09).
            if (d && d.count === 0 && !d.imported) {
                if (refused.length) {
                    dire('Envoi refusé par ' + libelle + ' — ' + (refused[0].error || 'refusé')
                         + (refused.length > 1 ? ' (+' + (refused.length - 1) + ')' : ''), 'error');
                } else {
                    dire((d.message || 'Aucun fichier compatible') + ' — ' + libelle, 'warning');
                }
                return d;
            }
            var received = (d && d.results) || (d && (d.id || d.path) ? [d] : []);
            var n = received.length || (d && d.count) || (Array.isArray(charge) ? charge.length : 0);
            dire(n + ' fichier(s) envoyé(s) vers ' + libelle, 'success');
            // `batch` : les fichiers reçus ENSEMBLE forment un LOT côté serveur (consolidation « par
            // arrivée »). Un écouteur ne doit alors PAS insérer chaque élément comme une card seule —
            // elle apparaîtrait sans sa card de lot — et laisse le repli commun recharger la page.
            // Relevé à l'audit du 14/09 : `reader.js` insérait N cards filles orphelines.
            var inBatch = received.length > 1;
            received.forEach(function (res) {
                document.dispatchEvent(new CustomEvent('wama:fileimported', {
                    detail: Object.assign({ imported: true, app: app }, res, { batch: inBatch }),
                }));
            });
            if (refused.length) {
                dire(refused.length + ' fichier(s) refusé(s) par ' + libelle, 'warning');
            }
            return d;
        }).catch(function (err) {
            // L'échec est DIT à l'utilisateur ; on ne le relance pas. Les appelants (entrées de
            // menu) ne chaînent rien : relancer ne laissait qu'une « Uncaught (in promise) » en
            // console à chaque refus (audit du 14/09).
            dire('Envoi impossible — ' + err.message, 'error');
            return null;
        });
    }

    /** Sous-menu pour des CHEMINS (fichier seul ou sélection) — résolu au serveur. */
    function entreesPourChemins(chemins) {
        return resoudreChemins({ paths: chemins }).then(function (d) {
            var total = (d.chemins || []).length;
            return (d.destinations || []).map(function (dest) {
                var acceptes = dest.acceptes || d.chemins;
                return {
                    icone: dest.icone || 'fas fa-cube',
                    // Sélection : le NOMBRE de fichiers que l'app prend est dit dans le libellé —
                    // c'est ce qui rend un envoi partiel annoncé plutôt que silencieux.
                    libelle: total > 1
                        ? dest.libelle + ' (' + acceptes.length + '/' + total + ' fichiers)'
                        : dest.libelle,
                    agir: function () { envoyer(d.endpoint, acceptes, dest.app, dest.libelle); },
                };
            });
        });
    }

    /** Sous-menu pour un DOSSIER entier — l'expansion et le filtre d'extensions sont à l'import. */
    function entreesPourDossier(dossier) {
        return resoudreChemins({ folder: dossier }).then(function (d) {
            return (d.destinations || []).map(function (dest) {
                return {
                    icone: dest.icone || 'fas fa-cube',
                    libelle: dest.libelle,
                    agir: function () { envoyer(d.endpoint, { folder: d.folder }, dest.app, dest.libelle); },
                };
            });
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
                          resoudre: resoudre, envoyer: envoyer,
                          resoudreChemins: resoudreChemins,
                          entreesPourChemins: entreesPourChemins,
                          entreesPourDossier: entreesPourDossier };
})(window);
