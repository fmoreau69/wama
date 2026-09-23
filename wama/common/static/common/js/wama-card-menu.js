/**
 * WAMA — MENU CONTEXTUEL de card / de lot, et DÉBORDEMENT « … » de la rangée d'actions.
 *
 * Décidé avec Fabien le 2026-09-08. Deux surfaces, UN seul constructeur d'entrées :
 *
 *   • le bouton « … » de la rangée = le DÉBORDEMENT SEUL. La rangée montre les 6 actions
 *     nominales (bouton édition compris) ; au-delà, tout passe dans le « … ». Rangée + « … »
 *     = la liste complète, sans rien de dupliqué.
 *   • le CLIC DROIT = la liste COMPLÈTE (les 6 visibles comprises) plus les actions de
 *     sélection multiple. C'est la surface de découverte, et celle qui agit sur N cards.
 *
 * D'OÙ VIENNENT LES ENTRÉES (modèle « hybride », option 1 retenue par Fabien — l'option 2, un
 * registre pour TOUT, est la direction à terme, pas ce commit) :
 *
 *   ① les actions EXISTANTES sont lues sur le `.btn-group-actions` de la card. C'est le contrat
 *     que `WamaInspector.cloneActions` utilise déjà depuis des mois : aucune hypothèse sur les
 *     fonctions ou les ids de l'app, et le clic est PROXIFIÉ vers le vrai bouton, donc déjà
 *     câblé. Zéro ligne par app, zéro gabarit touché.
 *   ② les actions TRANSVERSES (sortir du lot, ajouter à un lot, former un lot) sont DÉCLARÉES :
 *     elles n'existent dans aucune rangée, et leurs URLs sont déjà posées sur le conteneur de
 *     file par `{% queue_dnd_attrs %}`. Une route absente n'émet pas son attribut, donc
 *     l'entrée n'apparaît pas — même contrat de non-collision que le glisser-déposer :
 *     *ce qui n'est pas déclaré n'existe pas.*
 *
 * ⚠ POURQUOI PAS UN MENU TIERS. Celui du gestionnaire de fichiers était le `vakata-context` de
 * jsTree, rhabillé par des `!important` — il ne pouvait pas s'uniformiser parce que ce n'était
 * pas un composant WAMA. ✅ Migré le 2026-09-14 : l'arbre a quitté le plugin `contextmenu` de
 * jsTree et ouvre CE menu par `WamaCardMenu.ouvrir` (`filemanager.js:bindContextMenu`).
 *
 * Montage AUTOMATIQUE sur les files `[data-wama-dnd]`. Aucune page n'écrit de JS. Toute autre
 * surface (l'arbre de fichiers) appelle `ouvrir(x, y, entrees, titre)` avec ses propres entrées
 * — et, depuis le 2026-09-18, obtient les gestes d'ÉLÉMENT (Partager…, Ajouter à la
 * médiathèque…, Ajouter au RAG) par `entreesPourChemin(chemin, nom)` : le serveur dit de quel
 * élément le fichier est la SORTIE, et les entrées sont EXACTEMENT celles de la card.
 */
(function (global) {
    'use strict';

    //: Nombre d'actions NOMINALES dans la rangée, bouton édition compris (décision Fabien,
    //: 2026-09-08). Au-delà, le surplus part dans le « … ». Mesuré le même jour : aucune card
    //: du parc n'atteint ce seuil aujourd'hui (la plus fournie en a 5), donc le « … » n'apparaît
    //: que là où des actions TRANSVERSES s'ajoutent — l'apparence du parc ne change pas.
    var NOMINAL = 6;

    var SEL_CARD = '.wama-card[data-id]';
    //: La card MÈRE d'un lot ne porte PAS `data-id` (`_batch_card.html` : son pk est sur
    //: l'enveloppe `.batch-group`). Jusqu'au 2026-09-23 le menu ne montait que sur SEL_CARD : les
    //: gestes de LOT prévus ici (« Partager le lot… ») n'avaient donc AUCUNE surface — ni clic
    //: droit ni « … » sur la mère, constaté au navigateur en posant « Référence du lot… ».
    var SEL_MOTHER = '.wama-card.is-batch';
    var SEL_ANY_CARD = SEL_CARD + ', ' + SEL_MOTHER;
    var CLASSE_MASQUE = 'wama-cm-debord';        // bouton de rangée passé au débordement

    function $$(sel, racine) {
        return Array.prototype.slice.call((racine || document).querySelectorAll(sel));
    }

    function echapper(s) {
        return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
            return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
        });
    }

    // ── Lecture d'une action EXISTANTE (①) ───────────────────────────────────────────────
    //
    // On lit ce que le bouton MONTRE, pas ce que l'app pense : l'icône telle quelle, et le
    // libellé dans l'ordre `title` → `.wama-btn-label` → texte. Le `title` d'abord parce que
    // c'est la seule source présente sur TOUTES les cards (les rangées de card n'ont pas de
    // libellé texte, seulement des icônes + infobulle).
    function entreeDepuisBouton(el) {
        var icone = el.querySelector('i');
        var libelle = el.getAttribute('title')
            || (el.querySelector('.wama-btn-label') || {}).textContent
            || el.textContent || '';
        libelle = libelle.trim();
        if (!libelle) return null;               // un bouton sans nom ne se met pas dans un menu
        return {
            icone: icone ? icone.className : 'fas fa-circle',
            libelle: libelle,
            danger: /btn-outline-danger|btn-danger/.test(el.className),
            desactive: !!el.disabled,
            // PROXY : on ne rejoue pas l'action, on clique le VRAI bouton, déjà câblé.
            agir: function () { el.click(); },
        };
    }

    function actionsDeLaRangee(card) {
        var rangee = card.querySelector('.btn-group-actions');
        if (!rangee) return [];
        // Les enfants DIRECTS interactifs : un `.dropdown` compte pour UN (son bouton), et les
        // entrées de son menu ne sont pas des actions de card.
        //
        // ⚠ Le bouton « … » est EXCLU. Il vit dans la rangée (c'est sa place), donc il se
        // relisait comme une action : le clic droit affichait une entrée « Plus d'actions » qui
        // n'aurait fait qu'ouvrir un menu depuis un menu. Mesuré à la 1ʳᵉ sonde du 2026-09-08.
        // *Une brique qui écrit dans le DOM qu'elle relit doit s'exclure elle-même.*
        return $$(':scope > button, :scope > a, :scope > .dropdown > button, ' +
                  ':scope > .btn-group > a, :scope > .btn-group > button', rangee)
            .filter(function (el) { return !el.classList.contains('wama-cm-plus'); })
            .map(entreeDepuisBouton)
            .filter(Boolean);
    }

    // ── Actions TRANSVERSES déclarées (②) ────────────────────────────────────────────────
    function file(card) { return card.closest('[data-wama-dnd]'); }
    function lotDe(card) { return card.closest('.batch-group'); }

    function csrf() {
        var m = document.cookie.match(/csrftoken=([^;]+)/);
        return m ? m[1] : '';
    }

    function avecPk(gabarit, pk) {
        if (global.WamaApp && WamaApp.getUrl) return WamaApp.getUrl(gabarit, pk);
        return (gabarit || '').replace('/0/', '/' + pk + '/');
    }

    function poster(url, champs) {
        var fd = new FormData();
        Object.keys(champs || {}).forEach(function (k) { fd.append(k, champs[k]); });
        return fetch(url, { method: 'POST', headers: { 'X-CSRFToken': csrf() }, body: fd })
            .then(function (r) {
                return r.json().catch(function () { return { success: r.ok }; })
                    .then(function (d) {
                        // Même règle que `wama-queue-dnd.js` : le STATUT ne se perd pas. Un 404
                        // rend une page HTML, donc un objet sans clé métier — sans ça le geste
                        // se féliciterait de son échec (défaut vécu le 2026-09-08).
                        if (!r.ok && d && typeof d === 'object') {
                            d.success = false;
                            if (d.reason === undefined) d.reason = 'le serveur a répondu ' + r.status;
                        }
                        return d;
                    });
            });
    }

    function dire(msg, type) {
        if (global.WamaApp && WamaApp.toast) { WamaApp.toast(msg, type || 'info'); return; }
        if (type === 'error') alert(msg);
    }

    /**
     * Cards actuellement sélectionnées. LA sélection de WAMA est unique (cf. `wama-queue-dnd` :
     * la brique annonce `wama:selection-change`, l'inspecteur rend) — on ne s'en fabrique pas
     * une seconde.
     *
     * ⚠ `WamaQueueDnd.selectedCards()` rend des **identifiants**, pas des éléments, malgré son
     * nom (relevé au code le 2026-09-08). On passe par l'API publique quand même — c'est elle
     * la source — et on absorbe les deux formes : le jour où le nom sera réparé, ce code
     * continuera de marcher.
     */
    function selection(q) {
        var racine = q || document;
        var brut = (global.WamaQueueDnd && WamaQueueDnd.selectedCards)
            ? WamaQueueDnd.selectedCards(racine) : null;
        if (!brut || !brut.length) return [];
        return brut.map(function (x) {
            if (x && x.nodeType === 1) return x;
            return racine.querySelector(SEL_CARD.replace('[data-id]', '[data-id="' + x + '"]'));
        }).filter(Boolean);
    }

    /**
     * Range la sortie d'un élément dans la médiathèque, sous le rôle CHOISI (2026-09-11).
     * Passe par la route COMMUNE — une seule pour toutes les apps, la brique lit le résultat au
     * schéma canonique. Aucune connaissance d'app ici, donc rien à ajouter par app.
     */
    function urlMediatheque(co) {
        return '/media-library/api/export/' + encodeURIComponent(co.surface)
            + '/' + encodeURIComponent(co.pk) + '/';
    }

    /**
     * Retire de la médiathèque ce qui y a été rangé depuis cet élément, sous ce rôle (2026-09-14).
     * MÊME route que le rangement (`action=remove`) : un geste et son inverse ne divergent pas.
     * Seule la COPIE rangée disparaît — la sortie de l'app reste intacte, et la confirmation le dit.
     */
    /**
     * Un CHOIX du sous-menu médiathèque = `{asset_type, format}` — un RÔLE (app early-binding :
     * le fichier est déjà rendu) ou un FORMAT rendu à la demande (app late-binding : le master
     * est un texte, l'asset un document). Le serveur décrit chaque clé (`choices`) ; le menu
     * n'a rien à savoir de l'archétype de l'app.
     */
    function champsDuChoix(choix) {
        return { asset_type: (choix && choix.asset_type) || '',
                 output_format: (choix && choix.format) || '' };
    }

    function retirerDeMediatheque(co, choix, nom) {
        if (!window.confirm('Retirer « ' + (nom || 'cet asset') + ' » de la médiathèque ?\n'
                            + 'Le résultat de l\'application n\'est pas touché.')) return;
        var champs = champsDuChoix(choix);
        champs.action = 'remove';
        poster(urlMediatheque(co), champs).then(function (res) {
            if (res && res.success) dire('Retiré de la médiathèque : ' + (nom || ''), 'ok');
            else dire('Retrait impossible — ' + ((res && res.error) || 'refusé'), 'error');
        });
    }

    function rangerEnMediatheque(co, choix) {
        var url = urlMediatheque(co);
        poster(url, champsDuChoix(choix)).then(function (res) {
            if (res && res.success) dire('Ajouté à la médiathèque : ' + (res.name || ''), 'ok');
            // Le motif du refus est DIT : « précisez le rôle », « existe déjà »… Un geste qui
            // échoue en silence se re-tente à l'identique.
            else dire('Ajout impossible — ' + ((res && res.error) || 'refusé'), 'error');
        });
    }

    /**
     * Indexe l'élément au RAG. MÊME endpoint que le bouton de l'inspecteur
     * (`wama-inspector.js:405`) — deux surfaces, un seul geste : si elles divergeaient, on
     * déboguerait deux chemins pour la même promesse.
     * Le NIVEAU n'est pas demandé ici non plus : il vient du défaut de profil (décision du
     * 21/08 — le changer reste possible depuis « Mon RAG », où l'on voit ce qu'on a partagé).
     */
    function ajouterAuRag(co) {
        poster('/common/api/rag/ajouter/', { app: co.surface, pk: co.pk }).then(function (res) {
            if (res && res.erreur) { dire('RAG — ' + res.erreur, 'error'); return; }
            if (!res || res.fragments == null) { dire('RAG — échec', 'error'); return; }
            // « en attente de vectorisation » est DIT, pas tu : sans embedding le document ne
            // remonte pas encore au rappel sémantique (mêmes mots que l'inspecteur, exprès).
            dire(res.fragments + ' fragment' + (res.fragments > 1 ? 's' : '')
                + ' au RAG · ' + (res.niveau || '') + ' · en attente de vectorisation', 'ok');
        });
    }

    // ── Les gestes d'ÉLÉMENT, pour des coordonnées `{surface, pk}` ─────────────────────
    //
    // Sortis d'`actionsTransverses` le 2026-09-18 (demande de Fabien : « on ne duplique pas le
    // code, on le réutilise ») pour que l'ARBRE DE FICHIERS les offre sur un fichier qui est la
    // SORTIE d'un élément — sans réécrire une ligne. Deux surfaces, UNE liste d'entrées, donc un
    // seul endroit où elle peut dériver ; et les mêmes endpoints serveur (partage, route commune
    // de la médiathèque, RAG), donc les mêmes refus.

    /** « Partager… » d'un ÉLÉMENT (pas d'un lot — le lot est le cas propre à la card). */
    function entreePartager(co, nom) {
        if (!global.WamaShare) return null;
        return {
            icone: 'fas fa-share-nodes', libelle: 'Partager…',
            agir: function () { WamaShare.ouvrir(co.surface, co.pk, nom, 'element'); },
        };
    }

    /**
     * Les DEUX « sorties complémentaires » (décision Fabien, 2026-09-11) : ranger dans la
     * MÉDIATHÈQUE et ajouter au RAG — deux façons de garder une sortie. Elles vont dans le « … »
     * et PAS dans la rangée : celle-ci est figée à cinq actions par les conventions
     * (`[⚙][▶][⬇][⧉][🗑]`), et l'arbitrage du 2026-09-08 dit déjà que « les sorties manquantes
     * vont dans les "..." ».
     *
     * ⚠ « Ajouter au RAG » EXISTAIT DÉJÀ, mais seulement dans l'inspecteur, dans sa section
     * RAG (`wama-inspector.js:374`). Il fallait donc ouvrir le volet pour le trouver. Les
     * deux surfaces coexistent volontairement — c'est le MÊME endpoint, et l'inspecteur
     * garde l'avantage de dire l'état (« 3 fragments · en attente de vectorisation »).
     */
    function entreesGarder(co) {
        return [
            // MÉDIATHÈQUE — sous-menu des CHOIX, chargé à l'ouverture : des RÔLES (app
            // early-binding — le serveur ne rend que les rôles admissibles pour l'extension, et
            // UN SEUL quand l'app déclare ce qu'elle produit, 2026-09-18) ou des FORMATS (app
            // late-binding — ceux du bouton ⬇, rendus à la demande, 2026-09-18). On ne propose
            // donc jamais ce que le serveur refuserait.
            // ÉTAT PERSISTÉ (2026-09-14, demande de Fabien) : le serveur rend aussi les clés sous
            // lesquelles la sortie est DÉJÀ rangée (provenance de l'asset). Celles-là portent une
            // COCHE, et leur clic RETIRE l'asset — sans aller dans la médiathèque.
            {
                icone: 'fas fa-photo-film', libelle: 'Ajouter à la médiathèque…',
                sous: [{ chargement: true }],
                videLibelle: 'Rien à ranger (pas encore de résultat)',
                charger: function () {
                    return fetch(urlMediatheque(co), { credentials: 'same-origin' })
                        .then(function (r) { return r.json(); })
                        .then(function (d) {
                            var deja = d.in_library || {};
                            var choix = d.choices || {};
                            var cles = (d.candidates || []).slice();
                            // Une clé déjà rangée reste retirable même si le résultat a changé de
                            // format depuis : on ne la fait pas disparaître du menu.
                            Object.keys(deja).forEach(function (k) {
                                if (cles.indexOf(k) === -1) cles.push(k);
                            });
                            return cles.map(function (cle) {
                                var libelle = (d.labels || {})[cle] || cle;
                                // Repli : un serveur sans `choices` décrit des rôles (contrat d'avant).
                                var c = choix[cle] || { asset_type: cle, format: '' };
                                if (deja[cle]) {
                                    return {
                                        icone: 'fas fa-check wama-cm-coche', libelle: libelle,
                                        agir: function () { retirerDeMediatheque(co, c, deja[cle].name); },
                                    };
                                }
                                return {
                                    icone: 'fas fa-plus', libelle: libelle,
                                    agir: function () { rangerEnMediatheque(co, c); },
                                };
                            });
                        });
                },
            },
            {
                icone: 'fas fa-book-open-reader', libelle: 'Ajouter au RAG',
                agir: function () { ajouterAuRag(co); },
            },
        ];
    }

    /**
     * TOUS les gestes d'élément pour des coordonnées — Partager…, Ajouter à la médiathèque…,
     * Ajouter au RAG — dans l'ordre du menu de card. C'est ce que l'arbre de fichiers consomme
     * (« Envoyer vers… », lui, y existe déjà par chemin, résolu au serveur). `nom` : ce que la
     * modale de partage affiche.
     */
    function entreesPourElement(co, nom) {
        return [entreePartager(co, nom)].filter(Boolean).concat(entreesGarder(co));
    }

    /**
     * Les gestes d'élément pour un CHEMIN de `media/` (2026-09-18) : le serveur dit de quel
     * élément ce fichier est la SORTIE (`/common/api/element-pour-chemin/`, inverse du résolveur
     * « Envoyer vers »), puis ce sont exactement les entrées ci-dessus. Un fichier qui n'est la
     * sortie de rien (dépôt temporaire, entrée d'app, montage) rend une liste VIDE — l'entrée
     * différée disparaît alors du menu, elle n'affiche pas un vide.
     */
    function entreesPourChemin(chemin, nom) {
        return fetch('/common/api/element-pour-chemin/?path=' + encodeURIComponent(chemin),
                     { credentials: 'same-origin' })
            .then(function (r) { return r.ok ? r.json() : null; })
            .then(function (d) {
                if (!d || !d.surface || !d.pk) return [];
                return entreesPourElement({ surface: d.surface, pk: String(d.pk) }, nom);
            })
            .catch(function () { return []; });
    }

    // ── Résultat de référence (port `reference_result`) ──────────────────────────────────
    //
    // Une route COMMUNE pour toutes les surfaces évaluables : l'URL émise vise un élément au
    // pk 0, on y substitue la nature (`element` | `lot`) et le pk. Le serveur mesure au moment
    // de la pose et rend la mesure — elle est DITE tout de suite, la page se recharge ensuite
    // pour que la card (onglet) et la card mère (ligne de comparaison) la montrent.
    function referenceTarget(card) {
        if (card.classList.contains('is-batch')) {
            var lot = lotDe(card);
            return lot && lot.dataset.batchId ? { nature: 'lot', pk: lot.dataset.batchId } : null;
        }
        return card.dataset.id ? { nature: 'element', pk: card.dataset.id } : null;
    }

    function referenceUrl(base, target) {
        return base.replace(/element\/0\/$/, target.nature + '/' + target.pk + '/');
    }

    function referenceSaid(res) {
        var primary = res && res.item && res.item.metrics && res.item.metrics[0];
        if (primary && primary.value != null) {
            return 'Référence posée · ' + primary.metric.toUpperCase() + ' '
                + (primary.value * 100).toFixed(1) + ' %';
        }
        if (res && res.batch) {
            return 'Référence posée sur ' + res.targets + ' élément' + (res.targets > 1 ? 's' : '')
                + ' · ' + res.measured + ' mesuré' + (res.measured > 1 ? 's' : '');
        }
        return 'Référence posée — la mesure suivra le résultat';
    }

    function chooseReference(card, d) {
        var target = referenceTarget(card);
        if (!target) return;
        var input = document.createElement('input');
        input.type = 'file';
        if (d.resultReferenceAccept) input.accept = d.resultReferenceAccept;
        input.addEventListener('change', function () {
            if (!input.files || !input.files[0]) return;
            poster(referenceUrl(d.resultReferenceUrl, target), { file: input.files[0] })
                .then(function (res) {
                    if (!res || res.ok === false) {
                        dire('Référence refusée — ' + ((res && (res.reason || res.error)) || 'échec'),
                             'error');
                        return;
                    }
                    dire(referenceSaid(res), 'ok');
                    setTimeout(function () { location.reload(); }, 900);
                });
        });
        input.click();
    }

    function removeReference(card, d) {
        var target = referenceTarget(card);
        if (!target) return;
        poster(referenceUrl(d.resultReferenceUrl, target), { action: 'remove' }).then(function (res) {
            if (!res || res.ok === false) { dire('Retrait impossible', 'error'); return; }
            if (!res.removed) { dire('Aucune référence à retirer', 'info'); return; }
            dire('Référence retirée', 'ok');
            setTimeout(function () { location.reload(); }, 600);
        });
    }

    function referenceEntry(card, d) {
        var lot = card.classList.contains('is-batch');
        return {
            icone: 'fas fa-scale-balanced',
            libelle: lot ? 'Référence du lot…' : 'Résultat de référence…',
            sous: [
                { icone: 'fas fa-file-import', libelle: lot ? 'Joindre (à tout le lot)…' : 'Joindre…',
                  agir: function () { chooseReference(card, d); } },
                { icone: 'fas fa-xmark', libelle: 'Retirer', danger: true,
                  agir: function () { removeReference(card, d); } },
            ],
        };
    }

    function actionsTransverses(card, cibles) {
        var q = file(card);
        if (!q) return [];
        var d = q.dataset;
        var entrees = [];
        // Les gestes d'ÉLÉMENT (sortir du lot, ajouter à un lot) ne valent pas pour la MÈRE : elle
        // n'a pas de `data-id`, ils posteraient `undefined`. Elle a ses gestes de lot, plus bas.
        var estLot = card.classList.contains('is-batch');
        var dansUnLot = estLot ? [] : cibles.filter(lotDe);

        if (d.dndRemoveUrl && dansUnLot.length) {
            entrees.push({
                icone: 'fas fa-object-ungroup', libelle: dansUnLot.length > 1
                    ? 'Sortir du lot (' + dansUnLot.length + ')' : 'Sortir du lot',
                agir: function () {
                    // Séquentiel : chaque sortie recalcule le lot d'origine (et peut le vider).
                    dansUnLot.reduce(function (p, c) {
                        return p.then(function (motif) {
                            if (motif) return motif;
                            return poster(avecPk(d.dndRemoveUrl, c.dataset.id), {})
                                .then(function (res) {
                                    return (res && (res.success === false || res.unwrapped === false))
                                        ? (res.reason || 'refusé') : null;
                                });
                        });
                    }, Promise.resolve(null)).then(function (motif) {
                        if (motif) dire('Sortie du lot impossible — ' + motif, 'error');
                        else location.reload();
                    });
                },
            });
        }

        if (d.dndMergeUrl && cibles.length > 1) {
            entrees.push({
                icone: 'fas fa-layer-group', libelle: 'Former un lot (' + cibles.length + ')',
                agir: function () {
                    // `ids` répété : la fabrique commune lit JSON ET champ répété
                    // (`queue_manipulation.ids_from_request`), vérifié au code.
                    var fd = new FormData();
                    cibles.forEach(function (c) { fd.append('ids', c.dataset.id); });
                    fetch(d.dndMergeUrl, {
                        method: 'POST', headers: { 'X-CSRFToken': csrf() }, body: fd,
                    }).then(function (r) {
                        return r.json().catch(function () { return { success: r.ok }; })
                            .then(function (res) {
                                if (res && res.consolidated) { location.reload(); return; }
                                dire('Lot impossible — ' + (res && res.reason
                                    ? res.reason : 'ces éléments ne peuvent pas cohabiter'), 'error');
                            });
                    });
                },
            });
        }

        // PARTAGER — la premiere des « sorties complementaires » (arbitrage Fabien 2026-09-08 :
        // « les sorties manquantes vont dans les "..." »). L'entree n'apparait que si la card
        // porte ses coordonnees (`data-preview-url` → surface + pk, present sur les 10 gabarits
        // du parc, mesure) : une app non portee ne se voit rien proposer, plutot que d'ouvrir
        // une modale qui echouerait.
        // ⚠ UNE card a la fois : partager N elements exigerait N portees a la fois, ce qui n'est
        // pas la meme decision. On ne l'offre donc pas en selection multiple.
        // ⚠ DEUX CIBLES, et c'est ce sur quoi on a CLIQUÉ qui décide (question de Fabien :
        // « est-ce que le partage fonctionne pour les batch ? » — il ne fonctionnait pas) :
        //   • card MÈRE de lot  → on partage LE LOT (et le serveur descend à ses éléments) ;
        //   • card unitaire ou FILLE → on partage cet élément (le serveur remonte à son lot).
        // La mère ne porte pas `data-preview-url` (`_batch_card.html`, mesuré) : sa surface est
        // lue sur une card fille, son pk sur l'enveloppe `.batch-group`.
        if (cibles.length === 1 && global.WamaShare) {
            var estMere = card.classList.contains('is-batch');
            var dispo = estMere ? WamaShare.coordonneesDuLot(card) : WamaShare.coordonnees(card);
            var nom = (card.textContent || '').trim().slice(0, 70);
            if (dispo && estMere) {
                entrees.push({
                    icone: 'fas fa-share-nodes', libelle: 'Partager le lot…',
                    agir: function () { WamaShare.ouvrirPourLot(card, nom); },
                });
            } else if (dispo) {
                // L'entrée COMMUNE (celle de l'arbre aussi) : mêmes coordonnées, même modale.
                entrees.push(entreePartager(dispo, nom));
            }
        }

        // ENVOYER VERS — la sortie de cette card devient l'entrée d'une autre app : le
        // chaînage progressif, sans passer par le studio (cadre Fabien 2026-09-08).
        //
        // ⚠ L'entrée est posée SANS savoir encore s'il y a des destinations : les connaître
        // exige un appel serveur, et un menu ne doit pas attendre le réseau pour s'ouvrir. Le
        // sous-menu se remplit au clic et DIT ce qu'il a trouvé — y compris « aucune app ne
        // prend ce format », qui est une réponse, pas un vide. La condition dure, elle, est
        // qu'il faut une SORTIE : une card sans résultat n'a rien à envoyer.
        if (cibles.length === 1 && !card.classList.contains('is-batch')
                && global.WamaSendTo && WamaSendTo.coordonnees(card)) {
            entrees.push({
                icone: 'fas fa-share-from-square', libelle: 'Envoyer vers…',
                sous: [{ chargement: true }],
                charger: function () { return WamaSendTo.entrees(card); },
            });
        }

        // ── LES DEUX « SORTIES COMPLÉMENTAIRES » : médiathèque + RAG (`entreesGarder`) ───────
        // Une card UNITAIRE qui porte ses coordonnées. Le bloc lui-même vit plus haut, partagé
        // avec l'arbre de fichiers (2026-09-18).
        if (cibles.length === 1 && !card.classList.contains('is-batch')
                && global.WamaShare && WamaShare.coordonnees(card)) {
            entrees.push.apply(entrees, entreesGarder(WamaShare.coordonnees(card)));
        }

        // RÉSULTAT DE RÉFÉRENCE — le port `reference_result` (2026-09-23, WAMA_QUALITE Q6).
        // Offert SEULEMENT quand la file porte `data-result-reference-url`, que le serveur n'émet
        // que pour une surface ÉVALUABLE (`queue_dnd_attrs`). Sur la card MÈRE, la référence va
        // au LOT (le serveur la pose sur chacun de ses éléments, un seul fichier).
        if (d.resultReferenceUrl && cibles.length === 1) {
            entrees.push(referenceEntry(card, d));
        }

        // « Ajouter à un lot » — n'a de sens que s'il EXISTE un lot d'accueil autre que le sien.
        if (d.dndMoveUrl && !estLot) {
            var lots = $$('.batch-group[data-batch-id]', q).filter(function (g) {
                return !cibles.some(function (c) { return lotDe(c) === g; });
            });
            if (lots.length) {
                entrees.push({
                    icone: 'fas fa-folder-plus', libelle: 'Ajouter à un lot',
                    // Sous-entrées : un lot d'accueil par entrée. C'est ce qui évite le
                    // déplacement à la souris que Fabien voulait contourner.
                    sous: lots.map(function (g) {
                        var titre = (g.querySelector('.wama-card') || {}).textContent || '';
                        return {
                            icone: 'fas fa-layer-group',
                            libelle: 'Lot #' + g.dataset.batchId
                                + (titre.trim() ? ' — ' + titre.trim().slice(0, 28) : ''),
                            agir: function () {
                                cibles.reduce(function (p, c) {
                                    return p.then(function (motif) {
                                        if (motif) return motif;
                                        return poster(avecPk(d.dndMoveUrl, c.dataset.id),
                                                      { batch_id: g.dataset.batchId })
                                            .then(function (res) {
                                                return (res && (res.success === false || res.moved === false))
                                                    ? (res.reason || 'refusé') : null;
                                            });
                                    });
                                }, Promise.resolve(null)).then(function (motif) {
                                    if (motif) dire('Déplacement impossible — ' + motif, 'error');
                                    else location.reload();
                                });
                            },
                        };
                    }),
                });
            }
        }
        return entrees;
    }

    // ── Rendu du menu ────────────────────────────────────────────────────────────────────
    //
    // Une PILE de menus : [racine, sous-menu, sous-sous-menu…]. Un sous-menu s'ouvre À CÔTÉ de
    // son parent, qui RESTE ouvert (retour de Fabien, 2026-09-14 : le sous-menu s'ouvrait au
    // clic et REMPLAÇAIT son parent — « il apparaît après fermeture du menu contextuel »). Il
    // s'ouvre au SURVOL, après un court délai d'intention, et aussi au CLIC (tactile, clavier).
    var pile = [];
    var minuteur = null;
    //: L'élément focalisé AVANT l'ouverture du menu — Échap lui rend le focus (clavier, 2026-09-14).
    var retourFocus = null;
    //: Délai d'intention au survol (ms) : rejoindre un sous-menu en diagonale fait traverser
    //: une entrée voisine, qui ne doit pas basculer sur SON sous-menu au passage.
    var DELAI_SURVOL = 140;

    /** Referme les menus à partir de ce niveau (0 = tout) et éteint l'entrée qui les portait. */
    function fermerDepuis(niveau) {
        clearTimeout(minuteur);
        pile.splice(niveau).forEach(function (m) {
            if (m.parentNode) m.parentNode.removeChild(m);
        });
        var parent = pile[niveau - 1];
        if (parent) {
            $$('.wama-cm-ouvert', parent).forEach(function (b) { b.classList.remove('wama-cm-ouvert'); });
        }
    }

    function fermer() { fermerDepuis(0); }

    function dansUnMenu(noeud) {
        return pile.some(function (m) { return m.contains(noeud); });
    }

    function ligne(e, i) {
        if (e.separateur) return '<li class="wama-cm-sep" role="separator"></li>';
        if (e.chargement) {
            return '<li><span class="wama-cm-item wama-cm-attente">'
                + '<i class="fas fa-spinner fa-spin"></i><span>Recherche…</span></span></li>';
        }
        if (e.vide) {
            return '<li><span class="wama-cm-item wama-cm-attente">'
                + '<i class="fas fa-circle-info"></i><span>' + echapper(e.libelle)
                + '</span></span></li>';
        }
        return '<li><button type="button" class="wama-cm-item'
            + (e.danger ? ' wama-cm-danger' : '')
            + (e.sous ? ' wama-cm-parent' : '') + '"'
            + (e.desactive ? ' disabled' : '') + ' data-i="' + i + '">'
            + '<i class="' + echapper(e.icone) + '"></i>'
            + '<span>' + echapper(e.libelle) + '</span>'
            + (e.sous ? '<i class="fas fa-chevron-right wama-cm-fleche"></i>' : '')
            + '</button></li>';
    }

    /** Crée l'élément d'un menu de ce niveau, sur `document.body`, et l'inscrit dans la pile. */
    function creer(niveau) {
        var el = document.createElement('div');
        el.className = 'wama-card-menu' + (niveau ? ' wama-cm-sous' : '');
        el.setAttribute('role', 'menu');
        // Focalisable SANS entrer dans l'ordre de tabulation : c'est ce qui rend les flèches
        // utilisables dès l'ouverture, avant qu'aucune entrée n'ait le focus (2026-09-14).
        el.tabIndex = -1;
        document.body.appendChild(el);
        // Arriver dans un menu annule la bascule qu'a pu programmer l'entrée traversée en chemin.
        el.addEventListener('mouseenter', function () { clearTimeout(minuteur); });
        pile[niveau] = el;
        return el;
    }

    /**
     * Ouvre un menu aux coordonnées données. `entrees` peut contenir des `sous`.
     *
     * Le menu est posé sur `document.body` et non dans la card : une card peut vivre dans un
     * conteneur à `overflow` (la file en mosaïque, le `.collapse` d'un lot), qui rognerait le
     * menu. C'est le défaut classique des menus contextuels — on ne l'introduit pas.
     */
    function ouvrir(x, y, entrees, titre) {
        // L'élément qui avait le focus AVANT le menu : Échap le lui rend (on ne perd pas sa place).
        if (!pile.length) retourFocus = document.activeElement;
        fermer();
        if (!entrees.length) return;
        var el = creer(0);
        el._wamaAncre = { x: x, y: y };      // relu si une entrée différée change la taille
        remplir(el, entrees, titre, 0);
        placerRacine(el);
        el.focus({ preventScroll: true });
        return el;
    }

    /**
     * Placement du menu RACINE à son ancre : corrigé APRÈS insertion, quand la taille réelle
     * est connue — un menu dimensionné à l'aveugle sort de l'écran en bas de page. Rejoué quand
     * une entrée différée le remplit (sa hauteur change).
     */
    function placerRacine(el) {
        var a = el._wamaAncre || { x: 0, y: 0 };
        var r = el.getBoundingClientRect();
        el.style.left = Math.max(8, Math.min(a.x, window.innerWidth - r.width - 8)) + 'px';
        el.style.top = Math.max(8, Math.min(a.y, window.innerHeight - r.height - 8)) + 'px';
    }

    /**
     * ENTRÉE DIFFÉRÉE au niveau du menu lui-même (2026-09-18) : `{chargement: true, charger}`.
     *
     * Même contrat que le sous-menu différé, un cran plus haut : le menu s'ouvre TOUT DE SUITE
     * sur « Recherche… » à la place de l'entrée, et quand `charger()` rend ses entrées elles
     * REMPLACENT la ligne d'attente — aucune si la liste est vide (l'entrée disparaît, avec le
     * séparateur qui la précédait si plus rien ne le suit). Né pour l'arbre de fichiers : savoir
     * si un fichier est la SORTIE d'un élément exige un appel serveur, et un menu ne doit pas
     * attendre le réseau pour s'ouvrir.
     *
     * ⚠ Le FOCUS survit au remplissage : le re-rendu détruit les boutons, on rend le focus à
     * l'entrée qui l'avait (les objets d'entrée sont conservés, seul le DOM change).
     */
    function chargerDifferee(el, entrees, e, titre, niveau) {
        if (e._wamaLancee) return;            // un re-rendu ne relance pas un appel en vol
        e._wamaLancee = true;
        Promise.resolve().then(function () { return e.charger(); }).then(function (obtenues) {
            return obtenues || [];
        }, function () {
            return [];
        }).then(function (obtenues) {
            if (pile[niveau] !== el) return;          // le menu a été refermé entre-temps
            var i = entrees.indexOf(e);
            if (i === -1) return;
            var args = [i, 1].concat(obtenues);
            entrees.splice.apply(entrees, args);
            if (!obtenues.length) {
                // Un séparateur qui ne sépare plus rien (fin de liste, ou deux d'affilée) s'en va.
                var j = i - 1;
                if (j >= 0 && entrees[j] && entrees[j].separateur
                        && (i >= entrees.length || (entrees[i] && entrees[i].separateur))) {
                    entrees.splice(j, 1);
                }
            }
            var active = document.activeElement;
            var entreeActive = active && el.contains(active) ? active._wamaEntree : null;
            var menuAvaitLeFocus = active === el;
            remplir(el, entrees, titre, niveau);
            if (niveau === 0) placerRacine(el);
            else if (el._wamaDepuis) placerSous(el, el._wamaDepuis);
            if (entreeActive) {
                var b = $$('.wama-cm-item', el).filter(function (x) { return x._wamaEntree === entreeActive; })[0];
                if (b) b.focus({ preventScroll: true });
                else el.focus({ preventScroll: true });
            } else if (menuAvaitLeFocus || (active && !document.contains(active))) {
                el.focus({ preventScroll: true });
            }
        });
    }

    /**
     * Place un sous-menu contre le BORD de son menu parent — à droite, ou à gauche s'il n'y a pas
     * la place —, à hauteur de l'entrée qui le porte. Ancré sur le bord du MENU et non sur celui
     * de l'entrée : sinon il chevauche la marge intérieure du parent (5 px mesurés le 2026-09-14).
     */
    function placerSous(el, bouton) {
        var rb = bouton.getBoundingClientRect();
        var rp = (bouton.closest('.wama-card-menu') || bouton).getBoundingClientRect();
        var r = el.getBoundingClientRect();
        var x = rp.right + 2;
        if (x + r.width > window.innerWidth - 8) x = rp.left - r.width - 2;
        el.style.left = Math.max(8, x) + 'px';
        el.style.top = Math.max(8, Math.min(rb.top - 6, window.innerHeight - r.height - 8)) + 'px';
    }

    /** Les entrées ACTIONNABLES d'un menu (ni séparateur, ni « Recherche… », ni désactivée). */
    function entreesActives(menu) {
        return $$('button.wama-cm-item', menu).filter(function (b) { return !b.disabled; });
    }

    function premiereEntree(menu) {
        var b = entreesActives(menu)[0];
        (b || menu).focus({ preventScroll: true });
    }

    /**
     * Ouvre, au niveau donné, le sous-menu de l'entrée `e` portée par `bouton`.
     * `parClavier` : le focus ENTRE dans le sous-menu (→, Entrée) — à la souris il reste où il est.
     */
    function ouvrirSous(bouton, e, niveau, parClavier) {
        clearTimeout(minuteur);
        if (pile[niveau] && pile[niveau]._wamaDepuis === bouton) {       // déjà le sien
            if (parClavier) premiereEntree(pile[niveau]);
            return;
        }
        fermerDepuis(niveau);
        bouton.classList.add('wama-cm-ouvert');
        var el = creer(niveau);
        el._wamaDepuis = bouton;
        remplir(el, e.sous, null, niveau);
        placerSous(el, bouton);
        if (parClavier) premiereEntree(el);

        // SOUS-MENU DIFFÉRÉ : `charger()` rend une promesse d'entrées. Le sous-menu s'ouvre TOUT
        // DE SUITE sur « Recherche… » puis se remplit — un menu qui attend le réseau avant de
        // s'afficher se lit comme un geste perdu.
        if (typeof e.charger !== 'function') return;
        e.charger().then(function (entrees) {
            // Le sous-menu a pu être refermé (ou remplacé) entre-temps : on ne réécrit que CELUI
            // qu'on a ouvert.
            if (pile[niveau] !== el) return;
            var avaitLeFocus = el.contains(document.activeElement);
            // ⚠ Le message de vide était FIGÉ à « Aucune app ne prend ce format » — le
            // vocabulaire d'UN appelant (« Envoyer vers… ») dans la brique commune. Dès le 2ᵉ
            // sous-menu (médiathèque, 2026-09-11) il devenait faux. L'appelant le dit désormais ;
            // le repli garde l'existant intact.
            var liste = entrees && entrees.length ? entrees
                : [{ vide: true, libelle: e.videLibelle || "Aucune app ne prend ce format" }];
            remplir(el, liste, null, niveau);
            placerSous(el, bouton);          // la taille a changé : on replace
            // Le focus était sur « Recherche… » (ouverture au clavier) : il passe à la 1ʳᵉ entrée
            // réelle, sinon le rendu l'aurait détruit avec l'ancien contenu.
            if (avaitLeFocus) premiereEntree(el);
        }).catch(function () {
            if (pile[niveau] !== el) return;
            remplir(el, [{ vide: true, libelle: 'Indisponible' }], null, niveau);
            placerSous(el, bouton);
        });
    }

    /**
     * (Re)rend le CONTENU d'un menu déjà posé, et recâble ses entrées.
     *
     * Extrait d'`ouvrir` pour que le remplissage DIFFÉRÉ d'un sous-menu passe par le même code :
     * deux rendus auraient divergé au premier ajout de type d'entrée.
     */
    function remplir(el, entrees, titre, niveau) {
        el.innerHTML = (titre ? '<div class="wama-cm-titre">' + echapper(titre) + '</div>' : '')
            + '<ul>' + entrees.map(ligne).join('') + '</ul>';

        // Entrées DIFFÉRÉES de ce niveau : lancées au rendu, elles se remplacent elles-mêmes.
        entrees.forEach(function (e) {
            if (e && e.chargement && typeof e.charger === 'function') {
                chargerDifferee(el, entrees, e, titre, niveau);
            }
        });

        $$('.wama-cm-item', el).forEach(function (b) {
            var e = entrees[parseInt(b.dataset.i, 10)];
            if (!e) return;
            b._wamaEntree = e;          // lu par la navigation au clavier (→ ouvre son sous-menu)
            b.tabIndex = -1;            // on se déplace aux FLÈCHES, pas à la tabulation
            // SURVOL : après le délai d'intention, ouvre le sous-menu de cette entrée — ou
            // referme celui qu'une entrée voisine avait ouvert.
            b.addEventListener('mouseenter', function () {
                // Pointeur et clavier partagent UNE position : survoler une entrée y met le focus,
                // et les flèches repartent de là.
                if (!b.disabled) b.focus({ preventScroll: true });
                clearTimeout(minuteur);
                minuteur = setTimeout(function () {
                    if (e.sous && !b.disabled) ouvrirSous(b, e, niveau + 1);
                    else fermerDepuis(niveau + 1);
                }, DELAI_SURVOL);
            });
            if (e.sous) {
                // CLIC : même effet, immédiat — le tactile n'a pas de survol. `detail` 0 = clic
                // produit par Entrée/Espace : le focus ENTRE alors dans le sous-menu.
                b.addEventListener('click', function (ev) {
                    ev.stopPropagation();
                    ouvrirSous(b, e, niveau + 1, ev.detail === 0);
                });
                return;
            }
            b.addEventListener('click', function (ev) {
                ev.stopPropagation();
                fermer();
                try { e.agir(); } catch (err) { console.error('[WamaCardMenu]', err); }
            });
        });
    }

    // ── Assemblage des deux surfaces ─────────────────────────────────────────────────────

    /** Toutes les entrées pour ces cibles : rangée (①) puis transverses (②). */
    function entreesCompletes(card, cibles) {
        var rangee = cibles.length > 1 ? [] : actionsDeLaRangee(card);
        var transverses = actionsTransverses(card, cibles);
        if (rangee.length && transverses.length) {
            return rangee.concat([{ separateur: true }], transverses);
        }
        return rangee.concat(transverses);
    }

    /** Le DÉBORDEMENT : ce qui ne tient pas dans les `NOMINAL` premières places de la rangée. */
    function entreesDeDebordement(card) {
        var rangee = actionsDeLaRangee(card);
        var transverses = actionsTransverses(card, [card]);
        var surplus = rangee.slice(NOMINAL);          // 7ᵉ bouton et suivants, s'il en existe
        if (surplus.length && transverses.length) {
            return surplus.concat([{ separateur: true }], transverses);
        }
        return surplus.concat(transverses);
    }

    /**
     * Pose le bouton « … » sur une card, si elle a de quoi le remplir.
     *
     * Les boutons de rangée au-delà du nominal sont MASQUÉS (classe, pas `style`) : la rangée
     * garde exactement ses six premières places, et le reste est accessible par le « … ».
     */
    function poserDebordement(card) {
        var rangee = card.querySelector('.btn-group-actions');
        if (!rangee || rangee.querySelector('.wama-cm-plus')) return;
        var boutons = $$(':scope > button, :scope > a, :scope > .dropdown, :scope > .btn-group', rangee);
        boutons.slice(NOMINAL).forEach(function (b) { b.classList.add(CLASSE_MASQUE); });
        if (!entreesDeDebordement(card).length) return;

        var b = document.createElement('button');
        b.type = 'button';
        b.className = 'btn btn-sm btn-outline-secondary wama-cm-plus py-0 px-2';
        b.title = "Plus d'actions";
        b.setAttribute('aria-label', "Plus d'actions");
        b.innerHTML = '<i class="fas fa-ellipsis"></i>';
        b.addEventListener('click', function (ev) {
            ev.preventDefault(); ev.stopPropagation();
            var r = b.getBoundingClientRect();
            ouvrir(r.left, r.bottom + 4, entreesDeDebordement(card));
        });
        rangee.appendChild(b);
    }

    function monter(q) {
        if (q.dataset.wamaCardMenu === '1') return;
        q.dataset.wamaCardMenu = '1';

        $$(SEL_ANY_CARD, q).forEach(poserDebordement);

        // Cards INSÉRÉES ou REMPLACÉES après le montage (2026-09-15). Une card redemandée au
        // serveur — `refreshCard` des apps, lot réduit à une card par `queue-actions.js` — arrivait
        // SANS son « … » : le clic droit, délégué sur la file, la voyait déjà ; le débordement,
        // posé card par card au montage, non. `poserDebordement` est idempotent (garde sur
        // `.wama-cm-plus`), et le bouton qu'il ajoute n'est pas une card : pas de boucle.
        if (global.MutationObserver) {
            new MutationObserver(function (mutations) {
                mutations.forEach(function (m) {
                    Array.prototype.forEach.call(m.addedNodes, function (n) {
                        if (n.nodeType !== 1) return;
                        var cards = (n.matches && n.matches(SEL_ANY_CARD)) ? [n] : [];
                        cards.concat($$(SEL_ANY_CARD, n)).forEach(poserDebordement);
                    });
                });
            }).observe(q, { childList: true, subtree: true });
        }

        // CLIC DROIT — sur la card visée. Si elle fait partie d'une sélection multiple, le menu
        // agit sur TOUTE la sélection : c'est ce qui rend le geste utile à plusieurs cards.
        q.addEventListener('contextmenu', function (ev) {
            var card = ev.target.closest(SEL_ANY_CARD);
            if (!card || !q.contains(card)) return;
            ev.preventDefault();
            // La MÈRE agit sur son lot, jamais sur une sélection d'éléments : elle n'en fait pas
            // partie (la sélection ne porte que des `data-id`).
            var sel = card.classList.contains('is-batch') ? [] : selection(q);
            var cibles = (sel.length > 1 && sel.indexOf(card) !== -1) ? sel : [card];
            var titre = cibles.length > 1 ? cibles.length + ' éléments sélectionnés' : null;
            ouvrir(ev.clientX, ev.clientY, entreesCompletes(card, cibles), titre);
        });
    }

    function autoInit() {
        $$('[data-wama-dnd]').forEach(monter);
    }

    // FERMETURE — sur un geste de l'UTILISATEUR hors des menus, jamais sur un simple défilement.
    //
    // ⚠ La brique écoutait `scroll` (en capture). Mesuré le 2026-09-14 par la pile d'appels du
    // retrait : un clic droit dans l'arbre de fichiers donne le FOCUS à l'ancre, son conteneur
    // défile de lui-même pour la montrer, et ce défilement PROGRAMMATIQUE refermait le menu 7 ms
    // après son ouverture. Un `scroll` ne dit pas QUI a défilé ; `wheel` et `touchmove`, si.
    // `mousedown` (et non `click`) : un menu se ferme quand on appuie ailleurs, comme partout.
    document.addEventListener('mousedown', function (ev) {
        if (pile.length && !dansUnMenu(ev.target)) fermer();
    }, true);
    ['wheel', 'touchmove'].forEach(function (type) {
        window.addEventListener(type, function (ev) {
            if (pile.length && !dansUnMenu(ev.target)) fermer();
        }, { capture: true, passive: true });
    });
    // CLAVIER (2026-09-14, demande de Fabien) : ↑ ↓ Début Fin parcourent le menu où est le focus,
    // → (ou Entrée) ouvre le sous-menu et y entre, ← remonte au parent, Échap remonte d'un niveau
    // puis ferme en rendant le focus à qui l'avait, Tab ferme, PageUp/PageDown ferment (la page
    // défile : le menu ne resterait pas affiché loin de sa card).
    //
    // ⚠ EN CAPTURE sur `window`, et la propagation des touches TRAITÉES est arrêtée (audit du
    // 14/09). L'inspecteur (`wama-inspector.js`) et la file empilée (`wama-queue.js`) écoutent
    // aussi ↑ ↓ Entrée Espace Échap sur le document : en écoutant après eux, chaque ↓ changeait
    // la card sélectionnée derrière le menu, et Entrée était ANNULÉE par l'inspecteur au lieu de
    // déclencher l'entrée. Rien n'est intercepté quand le focus n'est pas dans un menu.
    function menuCourant() {
        for (var i = pile.length - 1; i >= 0; i--) {
            if (pile[i].contains(document.activeElement)) return i;
        }
        return pile.length - 1;
    }

    function fermerEtRendreLeFocus() {
        var retour = retourFocus;
        fermer();
        retourFocus = null;
        if (retour && retour.focus && document.contains(retour)) retour.focus({ preventScroll: true });
    }

    function clavier(ev) {
        // Seulement quand le focus est DANS un menu : ailleurs, le clavier reste à la page.
        if (!pile.length || !dansUnMenu(document.activeElement)) return;
        var niveau = menuCourant();
        var menu = pile[niveau];
        var items = entreesActives(menu);
        var active = document.activeElement;
        var i = items.indexOf(active);
        var cible = null;
        switch (ev.key) {
        case 'ArrowDown': cible = items[(i + 1) % items.length]; break;
        case 'ArrowUp':   cible = items[(i <= 0 ? items.length : i) - 1]; break;
        case 'Home':      cible = items[0]; break;
        case 'End':       cible = items[items.length - 1]; break;
        case 'ArrowRight':
            if (active && active._wamaEntree && active._wamaEntree.sous && menu.contains(active)) {
                ouvrirSous(active, active._wamaEntree, niveau + 1, true);
            }
            break;
        case 'Enter':
        case ' ':
            // Déclenché ICI, pas laissé au clic natif : l'inspecteur annule Entrée/Espace sur le
            // document dès qu'une card est sélectionnée. `click()` rend `detail` 0 → une entrée à
            // sous-menu y fait entrer le focus, comme →.
            if (active && active.classList.contains('wama-cm-item') && !active.disabled) active.click();
            break;
        case 'ArrowLeft':
        case 'Escape':
            if (niveau > 0) {
                var parent = pile[niveau]._wamaDepuis;
                fermerDepuis(niveau);
                if (parent) parent.focus({ preventScroll: true });
            } else if (ev.key === 'Escape') {
                fermerEtRendreLeFocus();
            }
            break;
        case 'Tab':
            fermerEtRendreLeFocus();
            return;                     // on laisse la tabulation suivre son cours
        case 'PageUp':
        case 'PageDown':
            fermer();
            return;                     // la page défile ; le menu ne reste pas loin de sa card
        default:
            return;
        }
        ev.preventDefault();
        ev.stopPropagation();           // l'inspecteur et la file ne rejouent pas la même touche
        if (cible) cible.focus({ preventScroll: true });
    }

    // CAPTURE sur `window` : passe avant les écouteurs du document (inspecteur, file empilée).
    window.addEventListener('keydown', clavier, true);
    window.addEventListener('resize', fermer);

    global.WamaCardMenu = {
        autoInit: autoInit, ouvrir: ouvrir, fermer: fermer,
        entreesCompletes: entreesCompletes, entreesDeDebordement: entreesDeDebordement,
        // Les gestes d'ÉLÉMENT pour d'autres surfaces que la card (l'arbre de fichiers) :
        // par coordonnées, ou par chemin de `media/` résolu au serveur (2026-09-18).
        entreesPourElement: entreesPourElement, entreesPourChemin: entreesPourChemin,
        NOMINAL: NOMINAL,
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', autoInit);
    } else {
        autoInit();
    }
})(window);
