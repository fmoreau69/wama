/**
 * WAMA — ENVOYER VERS : la sortie d'une card devient l'entrée d'une autre app. Brique COMMUNE.
 *
 * Cadre (Fabien, 2026-09-08) : « la sortie qu'on envoie en entrée d'une autre app, dans l'idée de
 * faire du chaînage progressif, sans forcément devoir passer par le studio ».
 *
 * DEUX APPELS, ET AUCUN DISPATCH NOUVEAU :
 *   ① `/common/api/envoyer-vers/<surface>/<pk>/` (GET) — RÉSOLVEUR : les chemins de sortie
 *      déclarés, les apps éligibles, et l'endpoint qui reçoit — `…/<surface>/lot/<pk>/` pour un
 *      LOT (2026-10-14) : les sorties de tous ses éléments, même réponse ;
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
            // Le DOMAINE qui a reçu (dit par le serveur, `app_modes.arrival_domain`) : la page de
            // l'app s'ouvrira sur lui. Un envoi qui en remplit plusieurs ne change rien au choix.
            var domains = received.map(function (res) { return res.domain || ''; })
                .filter(function (d, i, all) { return all.indexOf(d) === i; });
            if (domains.length === 1 && domains[0] && global.WamaApp && WamaApp.rememberDomain) {
                WamaApp.rememberDomain(app, domains[0]);
            }
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

    // ── Les apps qui reçoivent par DÉSIGNATION (2026-11-17) ─────────────────────────────────
    // Une app SANS PAGE peut déclarer qu'elle reçoit des fichiers désignés
    // (`register_pageless_tool(receives_designations=True)` — l'assistant, devenu une app) : le
    // serveur l'offre avec `designate: true`, et la page lui LIVRE les chemins sans rien importer,
    // par l'événement du glisser depuis l'arbre (`filemanager:designate`) sur la cible qu'elle
    // déclare (`data-fm-designate="<app>"`). Aucune app n'est nommée ici.

    function designationTarget(app) {
        return document.querySelector('[data-fm-designate="' + app + '"]');
    }

    function designer(app, paths, libelle) {
        var target = designationTarget(app);
        if (!target) { dire(libelle + ' n’est pas sur cette page', 'warning'); return null; }
        target.dispatchEvent(new CustomEvent('filemanager:designate', {
            detail: { files: paths.map(function (p) {
                return { path: p, name: String(p).split('/').pop() };
            }) },
        }));
        dire(paths.length + ' élément(s) confié(s) à ' + libelle, 'success');
        return { designated: paths };
    }

    /** UNE livraison pour toute entrée de menu : importer chez l'app, ou lui désigner. */
    function deliver(endpoint, charge, dest) {
        if (dest.designate) {
            return designer(dest.app, Array.isArray(charge) ? charge : [charge.folder], dest.libelle);
        }
        return envoyer(endpoint, charge, dest.app, dest.libelle);
    }

    /** Ce que CETTE page sait livrer : une app qui reçoit par désignation n'est offerte que si sa
     *  cible y est (ce qu'on n'offre pas ne peut pas décevoir). */
    function deliverable(dests) {
        return (dests || []).filter(function (d) { return !d.designate || !!designationTarget(d.app); });
    }

    /**
     * Rend les `formats` d'une card ou d'un lot LATE-BINDING (`renderUrl`, `api_send_rendered`),
     * puis livre les fichiers rendus à `dest` — par l'import de toujours, ou par désignation
     * (2026-11-03).
     */
    function renderAndSend(renderUrl, formats, dest) {
        return fetch(renderUrl, {
            method: 'POST', credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf() },
            body: JSON.stringify({ formats: formats }),
        }).then(function (r) {
            return r.json().catch(function () { return {}; }).then(function (d) {
                if (!r.ok || !d.chemins) throw new Error((d && d.error) || ('HTTP ' + r.status));
                return deliver(d.endpoint, d.chemins, dest);
            });
        }).catch(function (err) {
            dire('Envoi impossible — ' + err.message, 'error');
            return null;
        });
    }

    /**
     * Les entrées d'une card ou d'un lot LATE-BINDING (transcriber, describer, reader) : son
     * fichier n'existe qu'une fois rendu dans le format du ⬇. Une entrée par app, dont le
     * sous-menu offre chaque format qu'elle prend — PDF ou DOCX gardent la mise en forme, TXT le
     * texte brut — puis tous ensemble (« les deux »).
     */
    function formatEntries(d, renderUrl) {
        var byApp = {}, order = [];
        (d.formats || []).forEach(function (f) {
            deliverable(f.destinations).forEach(function (dest) {
                if (!byApp[dest.app]) { byApp[dest.app] = { dest: dest, formats: [] }; order.push(dest.app); }
                byApp[dest.app].formats.push(f);
            });
        });
        return order.map(function (app) {
            var dest = byApp[app].dest, formats = byApp[app].formats;
            var send = function (values) {
                return function () { renderAndSend(renderUrl, values, dest); };
            };
            var sub = formats.map(function (f) {
                return { icone: f.icon || 'fas fa-file', libelle: f.label, agir: send([f.format]) };
            });
            if (formats.length > 1) {
                sub.push({ separateur: true });
                sub.push({ icone: 'fas fa-layer-group',
                           libelle: formats.map(function (f) { return f.label; }).join(' + '),
                           agir: send(formats.map(function (f) { return f.format; })) });
            }
            return { icone: dest.icone || 'fas fa-cube', libelle: dest.libelle, sous: sub };
        });
    }

    /** Sous-menu pour des CHEMINS (fichier seul ou sélection) — résolu au serveur. */
    function entreesPourChemins(chemins) {
        return resoudreChemins({ paths: chemins }).then(function (d) {
            var total = (d.chemins || []).length;
            return deliverable(d.destinations).map(function (dest) {
                var acceptes = dest.acceptes || d.chemins;
                return {
                    icone: dest.icone || 'fas fa-cube',
                    // Sélection : le NOMBRE de fichiers que l'app prend est dit dans le libellé —
                    // c'est ce qui rend un envoi partiel annoncé plutôt que silencieux.
                    libelle: total > 1
                        ? dest.libelle + ' (' + acceptes.length + '/' + total + ' fichiers)'
                        : dest.libelle,
                    agir: function () { deliver(d.endpoint, acceptes, dest); },
                };
            });
        });
    }

    /** Sous-menu pour un DOSSIER entier — l'expansion et le filtre d'extensions sont à l'import. */
    function entreesPourDossier(dossier) {
        return resoudreChemins({ folder: dossier }).then(function (d) {
            return deliverable(d.destinations).map(function (dest) {
                return {
                    icone: dest.icone || 'fas fa-cube',
                    libelle: dest.libelle,
                    agir: function () { deliver(d.endpoint, { folder: d.folder }, dest); },
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
            if (d && d.formats && d.formats.length) {
                return formatEntries(d, '/common/api/envoyer-vers/' + encodeURIComponent(c.surface)
                                        + '/' + encodeURIComponent(c.pk) + '/rendu/');
            }
            if (!d || !d.chemins || !d.chemins.length) return [];
            return deliverable(d.destinations).map(function (dest) {
                return {
                    icone: dest.icone || 'fas fa-cube',
                    libelle: dest.libelle,
                    agir: function () { deliver(d.endpoint, d.chemins, dest); },
                };
            });
        });
    }

    /** Résout les sorties d'un LOT — celles de tous ses éléments (`api_send_batch_to`). */
    function resolveBatch(surface, pk) {
        return fetch('/common/api/envoyer-vers/' + encodeURIComponent(surface) + '/lot/'
                     + encodeURIComponent(pk) + '/', { credentials: 'same-origin' })
            .then(function (r) {
                if (!r.ok) throw new Error('HTTP ' + r.status);
                return r.json();
            });
    }

    /**
     * « Envoyer le lot vers… » (2026-10-14) — les entrées pour la card MÈRE d'un lot.
     *
     * Les sorties de tous les éléments partent en UN envoi : l'import les range en lot chez la
     * destination. Partiel ANNONCÉ, comme une sélection de l'arbre : une app qui ne prend qu'une
     * partie des fichiers le dit dans son libellé. Les éléments sans résultat ne partent pas,
     * et le sous-menu le DIT sous les destinations. Coordonnées du lot = celles du partage
     * (`WamaShare.coordonneesDuLot` : pk sur l'enveloppe, surface lue sur une fille).
     */
    function entriesForBatch(card) {
        var c = (global.WamaShare && WamaShare.coordonneesDuLot) ? WamaShare.coordonneesDuLot(card) : null;
        if (!c) return Promise.resolve([]);
        return resolveBatch(c.surface, c.pk).then(function (d) {
            var paths = (d && d.chemins) || [];
            var rendered = !paths.length && d && d.formats && d.formats.length;
            if (!paths.length && !rendered) {
                return [{ vide: true, libelle: 'Aucun résultat dans ce lot pour l’instant' }];
            }
            var entries = rendered
                ? formatEntries(d, '/common/api/envoyer-vers/' + encodeURIComponent(c.surface)
                                   + '/lot/' + encodeURIComponent(c.pk) + '/rendu/')
                : deliverable(d.destinations).map(function (dest) {
                var accepted = dest.acceptes || paths;
                return {
                    icone: dest.icone || 'fas fa-cube',
                    libelle: accepted.length < paths.length
                        ? dest.libelle + ' (' + accepted.length + '/' + paths.length + ' fichiers)'
                        : dest.libelle,
                    agir: function () { deliver(d.endpoint, accepted, dest); },
                };
            });
            var missing = d.without_output || 0;
            if (entries.length && missing) {
                entries.push({ separateur: true });
                entries.push({ vide: true, libelle: missing + ' élément' + (missing > 1 ? 's' : '')
                               + ' sans résultat — non envoyé' + (missing > 1 ? 's' : '') });
            }
            return entries;
        });
    }

    global.WamaSendTo = { entrees: entrees, coordonnees: coordonnees,
                          resoudre: resoudre, envoyer: envoyer, deliver: deliver,
                          resoudreChemins: resoudreChemins,
                          entreesPourChemins: entreesPourChemins,
                          entreesPourDossier: entreesPourDossier,
                          resolveBatch: resolveBatch, entriesForBatch: entriesForBatch,
                          formatEntries: formatEntries, renderAndSend: renderAndSend };
})(window);
