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
 * ⚠ POURQUOI PAS UN MENU TIERS. Celui du gestionnaire de fichiers est le `vakata-context` de
 * jsTree, rhabillé par des `!important` (`filemanager.css`) — il ne peut pas s'uniformiser
 * parce que ce n'est pas un composant WAMA. Celui-ci en est un ; le filemanager pourra y
 * migrer (jsTree sait déléguer son `contextmenu`).
 *
 * Montage AUTOMATIQUE sur les files `[data-wama-dnd]`. Aucune page n'écrit de JS.
 */
(function (global) {
    'use strict';

    //: Nombre d'actions NOMINALES dans la rangée, bouton édition compris (décision Fabien,
    //: 2026-09-08). Au-delà, le surplus part dans le « … ». Mesuré le même jour : aucune card
    //: du parc n'atteint ce seuil aujourd'hui (la plus fournie en a 5), donc le « … » n'apparaît
    //: que là où des actions TRANSVERSES s'ajoutent — l'apparence du parc ne change pas.
    var NOMINAL = 6;

    var SEL_CARD = '.wama-card[data-id]';
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
    function rangerEnMediatheque(co, role) {
        var url = '/media-library/api/export/' + encodeURIComponent(co.surface)
            + '/' + encodeURIComponent(co.pk) + '/';
        poster(url, { asset_type: role }).then(function (res) {
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

    function actionsTransverses(card, cibles) {
        var q = file(card);
        if (!q) return [];
        var d = q.dataset;
        var entrees = [];
        var dansUnLot = cibles.filter(lotDe);

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
            if (dispo) {
                entrees.push({
                    icone: 'fas fa-share-nodes',
                    libelle: estMere ? 'Partager le lot…' : 'Partager…',
                    agir: function () {
                        var nom = (card.textContent || '').trim().slice(0, 70);
                        if (estMere) WamaShare.ouvrirPourLot(card, nom);
                        else WamaShare.ouvrirPourCard(card, nom);
                    },
                });
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

        // ── LES DEUX « SORTIES COMPLÉMENTAIRES » (décision Fabien, 2026-09-11) ───────────────
        //
        // Ranger dans la MÉDIATHÈQUE et ajouter au RAG sont deux façons de garder une sortie.
        // Elles vont dans le « … » et PAS dans la rangée : celle-ci est figée à cinq actions
        // par les conventions (`[⚙][▶][⬇][⧉][🗑]`), et l'arbitrage du 2026-09-08 ci-dessus dit
        // déjà que « les sorties manquantes vont dans les "..." ».
        //
        // ⚠ « Ajouter au RAG » EXISTAIT DÉJÀ, mais seulement dans l'inspecteur, dans sa section
        // RAG (`wama-inspector.js:374`). Il fallait donc ouvrir le volet pour le trouver. Les
        // deux surfaces coexistent volontairement — c'est le MÊME endpoint, et l'inspecteur
        // garde l'avantage de dire l'état (« 3 fragments · en attente de vectorisation »).
        if (cibles.length === 1 && !card.classList.contains('is-batch')
                && global.WamaShare && WamaShare.coordonnees(card)) {
            var co = WamaShare.coordonnees(card);

            // MÉDIATHÈQUE — sous-menu des RÔLES, chargé au clic. Le rôle n'est pas dérivable du
            // fichier (un .mp3 peut être une voix, une musique ou un bruitage) : le serveur
            // rend les rôles admissibles, on ne propose donc jamais ce qu'il refuserait.
            entrees.push({
                icone: 'fas fa-photo-film', libelle: 'Ajouter à la médiathèque…',
                sous: [{ chargement: true }],
                videLibelle: 'Rien à ranger (pas encore de résultat)',
                charger: function () {
                    var base = '/media-library/api/export/' + encodeURIComponent(co.surface)
                        + '/' + encodeURIComponent(co.pk) + '/';
                    return fetch(base, { credentials: 'same-origin' })
                        .then(function (r) { return r.json(); })
                        .then(function (d) {
                            return (d.candidates || []).map(function (role) {
                                return {
                                    icone: 'fas fa-plus', libelle: (d.labels || {})[role] || role,
                                    agir: function () { rangerEnMediatheque(co, role); },
                                };
                            });
                        });
                },
            });

            entrees.push({
                icone: 'fas fa-book-open-reader', libelle: 'Ajouter au RAG',
                agir: function () { ajouterAuRag(co); },
            });
        }

        // « Ajouter à un lot » — n'a de sens que s'il EXISTE un lot d'accueil autre que le sien.
        if (d.dndMoveUrl) {
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
    var ouvert = null;

    function fermer() {
        if (!ouvert) return;
        if (ouvert.parentNode) ouvert.parentNode.removeChild(ouvert);
        ouvert = null;
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

    /**
     * Ouvre un menu aux coordonnées données. `entrees` peut contenir des `sous` (un niveau).
     *
     * Le menu est posé sur `document.body` et non dans la card : une card peut vivre dans un
     * conteneur à `overflow` (la file en mosaïque, le `.collapse` d'un lot), qui rognerait le
     * menu. C'est le défaut classique des menus contextuels — on ne l'introduit pas.
     */
    function ouvrir(x, y, entrees, titre) {
        fermer();
        if (!entrees.length) return;
        var el = document.createElement('div');
        el.className = 'wama-card-menu';
        el.setAttribute('role', 'menu');
        document.body.appendChild(el);
        remplir(el, entrees, titre);

        // Placement : on corrige APRÈS insertion, quand la taille réelle est connue — un menu
        // dimensionné à l'aveugle sort de l'écran en bas de page.
        var r = el.getBoundingClientRect();
        var gx = Math.min(x, window.innerWidth - r.width - 8);
        var gy = Math.min(y, window.innerHeight - r.height - 8);
        el.style.left = Math.max(8, gx) + 'px';
        el.style.top = Math.max(8, gy) + 'px';
        ouvert = el;
        return el;
    }

    /**
     * (Re)rend le CONTENU d'un menu déjà posé, et recâble ses entrées.
     *
     * Extrait d'`ouvrir` pour que le remplissage DIFFÉRÉ d'un sous-menu passe par le même code :
     * deux rendus auraient divergé au premier ajout de type d'entrée.
     */
    function remplir(el, entrees, titre) {
        el.innerHTML = (titre ? '<div class="wama-cm-titre">' + echapper(titre) + '</div>' : '')
            + '<ul>' + entrees.map(ligne).join('') + '</ul>';

        $$('.wama-cm-item', el).forEach(function (b) {
            var e = entrees[parseInt(b.dataset.i, 10)];
            if (!e) return;
            if (e.sous) {
                b.addEventListener('click', function (ev) {
                    ev.stopPropagation();
                    var rb = b.getBoundingClientRect();
                    var sousMenu = ouvrir(rb.right - 4, rb.top, e.sous, e.libelle);
                    // SOUS-MENU DIFFÉRÉ : `charger()` rend une promesse d'entrées. Le menu
                    // s'ouvre TOUT DE SUITE sur « Recherche… » puis se remplit — un menu qui
                    // attend le réseau avant de s'afficher se lit comme un clic perdu.
                    if (typeof e.charger !== 'function' || !sousMenu) return;
                    var pourCeMenu = sousMenu;
                    e.charger().then(function (entrees) {
                        // Le menu a pu être refermé (ou remplacé) entre-temps : on ne réécrit
                        // que CELUI qu'on a ouvert.
                        if (ouvert !== pourCeMenu || !pourCeMenu.parentNode) return;
                        // ⚠ Le message de vide était FIGÉ à « Aucune app ne prend ce format » —
                        // le vocabulaire d'UN appelant (« Envoyer vers… ») dans la brique
                        // commune. Dès le 2ᵉ sous-menu (médiathèque, 2026-09-11) il devenait
                        // faux. L'appelant le dit désormais ; le repli garde l'existant intact.
                        var liste = entrees && entrees.length ? entrees
                            : [{ vide: true,
                                 libelle: e.videLibelle || "Aucune app ne prend ce format" }];
                        remplir(pourCeMenu, liste, e.libelle);
                    }).catch(function () {
                        if (ouvert !== pourCeMenu || !pourCeMenu.parentNode) return;
                        remplir(pourCeMenu, [{ vide: true, libelle: 'Indisponible' }], e.libelle);
                    });
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

        $$(SEL_CARD, q).forEach(function (card) {
            if (card.classList.contains('is-batch')) { poserDebordement(card); return; }
            poserDebordement(card);
        });

        // CLIC DROIT — sur la card visée. Si elle fait partie d'une sélection multiple, le menu
        // agit sur TOUTE la sélection : c'est ce qui rend le geste utile à plusieurs cards.
        q.addEventListener('contextmenu', function (ev) {
            var card = ev.target.closest(SEL_CARD);
            if (!card || !q.contains(card)) return;
            ev.preventDefault();
            var sel = selection(q);
            var cibles = (sel.length > 1 && sel.indexOf(card) !== -1) ? sel : [card];
            var titre = cibles.length > 1 ? cibles.length + ' éléments sélectionnés' : null;
            ouvrir(ev.clientX, ev.clientY, entreesCompletes(card, cibles), titre);
        });
    }

    function autoInit() {
        $$('[data-wama-dnd]').forEach(monter);
    }

    document.addEventListener('click', function (ev) {
        if (ouvert && !ouvert.contains(ev.target)) fermer();
    });
    document.addEventListener('keydown', function (ev) { if (ev.key === 'Escape') fermer(); });
    window.addEventListener('resize', fermer);
    // `capture` : un défilement DANS la file ne remonte pas jusqu'à window en bubbling.
    window.addEventListener('scroll', fermer, true);

    global.WamaCardMenu = {
        autoInit: autoInit, ouvrir: ouvrir, fermer: fermer,
        entreesCompletes: entreesCompletes, entreesDeDebordement: entreesDeDebordement,
        NOMINAL: NOMINAL,
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', autoInit);
    } else {
        autoInit();
    }
})(window);
