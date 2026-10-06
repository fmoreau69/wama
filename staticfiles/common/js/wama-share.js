/**
 * WAMA — PARTAGE d'un élément de file : la modale. Brique COMMUNE.
 *
 * `WamaShare.ouvrir(surface, pk, nom)` — lit l'état et les portées OFFRABLES au serveur, rend la
 * modale, applique. Le menu contextuel en est le premier appelant ; l'inspecteur pourra le
 * devenir sans rien changer ici.
 *
 * POURQUOI UNE MODALE GÉNÉRÉE, et pas un partial HTML. C'est l'idiome du dépôt depuis le
 * 2026-08-06 : le partial `_settings_modal.html` prévu par la feuille de route a été « livré
 * autrement » — `WamaParams.settingsModal()` GÉNÈRE la modale depuis un schéma. Ici le schéma
 * vient du serveur (`/common/api/partage/<surface>/<pk>/`), donc un gabarit ne saurait de toute
 * façon pas quoi rendre : les unités et les projets offerts dépendent de l'utilisateur.
 *
 * ⚠ CE QUE CETTE MODALE NE PROMET PAS. Une PORTÉE (unité, projet, public) partage en LECTURE
 * SEULE — `visibility` ne dit que qui VOIT. L'écriture (la collaboration) ne s'accorde qu'à une
 * PERSONNE nommée (E1, 2026-10-03), dans la section « Avec une personne » (une ligne
 * `ObjectGrant`, 2026-10-06). La modale le DIT à l'écran : une UI qui laisse croire qu'une
 * portée donne l'écriture serait un mensonge sur un sujet de droits.
 *
 * ⚠ Les portées sont celles que le SERVEUR offre, jamais une liste écrite ici. Une portée sans
 * cible réelle (« Unité » pour un profil sans affiliation) n'est pas rendue — même règle que les
 * attributs du glisser-déposer : *ce qui n'est pas déclaré n'existe pas*. C'est aussi la leçon du
 * Geste 14 : un menu qui offre ce que le serveur refuse est pire qu'un menu incomplet.
 */
(function (global) {
    'use strict';

    function csrf() {
        var m = document.cookie.match(/csrftoken=([^;]+)/);
        return m ? m[1] : '';
    }

    function echapper(s) {
        return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
            return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
        });
    }

    function dire(msg, type) {
        if (global.WamaApp && WamaApp.toast) { WamaApp.toast(msg, type || 'info'); return; }
        if (type === 'error') alert(msg);
    }

    function urlDe(surface, pk, nature) {
        return '/common/api/partage/' + encodeURIComponent(surface) + '/'
             + encodeURIComponent(nature || 'element') + '/' + encodeURIComponent(pk) + '/';
    }

    /**
     * Surface + pk lus sur la CARD, via le contrat `data-preview-url`.
     *
     * ⚠ La card MÈRE d'un lot ne le porte PAS (`_batch_card.html` : 0 occurrence, mesuré) —
     * elle porte `data-batch-id`. C'est `coordonneesDuLot` qui la traite : la surface vient
     * alors d'une card FILLE, et le pk du lot de l'enveloppe `.batch-group`.
     */
    function coordonnees(card) {
        var hote = (card.matches && card.matches('[data-preview-url]'))
            ? card : card.querySelector('[data-preview-url]');
        var url = hote && hote.getAttribute('data-preview-url');
        if (!url) return null;
        // `/common/preview/<surface>/<pk>/` — éventuellement suivi d'un `?side=…`.
        var m = url.split('?')[0].match(/\/common\/preview\/([^/]+)\/(\d+)\//);
        return m ? { surface: m[1], pk: m[2] } : null;
    }

    /**
     * CONSENTEMENT (2026-09-30, décision de Fabien) : un élément qui porte une PERSONNE (une voix)
     * ne se partage au-delà du privé qu'après avoir VALIDÉ ce texte — sinon on annule. Le serveur
     * le donne d'avance (`etat.consent`), la modale le montre dès qu'une portée partagée est
     * choisie ; il le redonne en 409 si la modale ne l'avait pas (état changé entre-temps).
     */
    function consentBlock(statement) {
        return '<div class="wama-share-consent mt-3" data-consent hidden>'
            + '<div class="alert alert-warning small mb-2 py-2"><i class="fas fa-user-shield me-1"></i>'
            + echapper(statement) + '</div>'
            + '<label class="form-check small mb-0"><input type="checkbox" class="form-check-input" '
            + 'data-consent-check> Je valide ce consentement</label></div>';
    }

    /**
     * PARTAGE À UNE PERSONNE (2026-10-06, question de Fabien : « on ne peut pas partager à un
     * utilisateur seul »). Une PORTÉE donne la lecture ; une PERSONNE nommée reçoit le MODE choisi
     * — c'est là, et seulement là, que la collaboration s'accorde (E1, 2026-10-03). Les modes
     * viennent du serveur (`sharing.SHARE_MODES`) : un mode non construit est montré grisé
     * (« bientôt »), jamais retiré de la liste. Le destinataire est désigné comme pour
     * « Transférer à… » (identifiant ou adresse e-mail) et il est PRÉVENU (N1).
     */
    function personRows(persons) {
        if (!persons || !persons.length) {
            return '<div class="small text-white-50" data-person-empty>Partagé avec personne en particulier.</div>';
        }
        return persons.map(function (p) {
            var since = p.since ? new Date(p.since).toLocaleDateString('fr-FR') : '';
            return '<div class="d-flex justify-content-between align-items-center small mb-1" data-person-row>'
                + '<span>' + echapper(p.mode.icon) + ' <b>' + echapper(p.name) + '</b> · '
                + echapper(p.mode.label) + (since ? ' · depuis le ' + echapper(since) : '') + '</span>'
                + '<button type="button" class="btn btn-link btn-sm p-0" style="color:#fca5a5;" '
                + 'data-person-revoke="' + echapper(p.user_id) + '">retirer</button></div>';
        }).join('');
    }

    function personsBlock(persons, modes) {
        var options = (modes || []).map(function (m) {
            return '<option value="' + echapper(m.key) + '"' + (m.available ? '' : ' disabled') + '>'
                + echapper(m.icon) + ' ' + echapper(m.label) + (m.available ? '' : ' (bientôt)')
                + '</option>';
        }).join('');
        return '<div class="wama-share-persons mt-3"><div class="small text-white-50 mb-1">'
            + 'Avec une personne</div><div data-person-list>' + personRows(persons) + '</div>'
            + '<div class="d-flex gap-2 mt-2">'
            + '<input type="text" class="form-control form-control-sm" data-person-input '
            + 'placeholder="identifiant ou adresse e-mail">'
            + '<select class="form-select form-select-sm w-auto" data-person-mode>' + options + '</select>'
            + '<button type="button" class="btn btn-sm btn-outline-info" data-person-add>Partager</button>'
            + '</div></div>';
    }

    function corps(donnees, nom) {
        var e = donnees.etat || {};
        var lignes = (donnees.portees || []).map(function (p) {
            var choisi = e.visibility === p.valeur;
            var cibles = '';
            if (p.cibles && p.cibles.length) {
                cibles = '<select class="form-select form-select-sm mt-1 wama-share-cible" '
                    + 'data-pour="' + echapper(p.valeur) + '"'
                    + (choisi ? '' : ' disabled') + '>'
                    + p.cibles.map(function (c) {
                        var sel = (p.valeur === 'unit' ? e.org_unit_id : e.project_id) === c.id;
                        return '<option value="' + c.id + '"' + (sel ? ' selected' : '') + '>'
                            + echapper(c.libelle) + '</option>';
                    }).join('') + '</select>';
            }
            return '<div class="wama-share-choix' + (choisi ? ' est-actif' : '') + '">'
                + '<label class="d-flex align-items-start gap-2 mb-0">'
                + '<input type="radio" name="wama-share-portee" class="form-check-input mt-1" '
                + 'value="' + echapper(p.valeur) + '"' + (choisi ? ' checked' : '') + '>'
                + '<span class="flex-grow-1"><span class="wama-share-libelle">'
                + echapper(p.libelle) + '</span>'
                // Depuis quand la portée COURANTE est posée (2026-10-06) — absente d'un partage
                // antérieur à la tenue de la date : on ne l'invente pas.
                + (choisi && p.valeur !== 'private' && e.scope_since
                   ? '<span class="small text-white-50 ms-2">depuis le '
                     + echapper(new Date(e.scope_since).toLocaleDateString('fr-FR')) + '</span>'
                   : '')
                + cibles + '</span></label></div>';
        }).join('');

        // ⚠ CAS RÉEL, trouvé au smoke : la portée COURANTE peut ne plus être offrable — un
        // élément partagé à une unité dont l'utilisateur n'est plus membre, par exemple. Aucun
        // radio n'est alors coché, et « Appliquer » ne pourrait que réclamer un choix sans
        // expliquer pourquoi. On le DIT : l'état actuel reste lisible même quand il n'est plus
        // reconductible. *Un formulaire qui ne peut pas représenter l'état courant doit le
        // nommer, pas l'effacer.*
        var offertes = (donnees.portees || []).map(function (p) { return p.valeur; });
        var orpheline = e.visibility && offertes.indexOf(e.visibility) === -1
            ? '<div class="wama-share-note mb-3"><i class="fas fa-circle-info me-1"></i>'
              + 'Portée actuelle : <b>' + echapper(e.visibility) + '</b> — vous ne pouvez plus '
              + 'l\'offrir (affiliation ou projet perdu). Choisir ci-dessous la REMPLACERA.</div>'
            : '';

        return '<div class="modal-header border-secondary">'
            + '<h5 class="modal-title"><i class="fas fa-share-nodes text-info me-2"></i>Partager</h5>'
            + '<button type="button" class="btn-close btn-close-white" data-bs-dismiss="modal"></button>'
            + '</div><div class="modal-body">'
            + (nom ? '<p class="text-white-50 small mb-3">' + echapper(nom) + '</p>' : '')
            + orpheline
            + lignes
            + (e.consent ? consentBlock(e.consent.statement) : '')
            // Dire la portée du geste, à l'endroit où on le fait.
            + '<div class="wama-share-note mt-3"><i class="fas fa-eye me-1"></i>'
            + 'Une portée partage en <b>lecture seule</b> : on voit l\'élément et son résultat, on '
            + 'peut le dupliquer ou vous demander d\'en devenir propriétaire, sans le relancer ni le '
            + 'modifier.</div>'
            + '<div class="text-end mt-2"><button type="button" class="btn btn-sm btn-info wama-share-ok">'
            + 'Appliquer la portée</button></div>'
            + personsBlock(e.persons, donnees.modes)
            + '</div><div class="modal-footer border-secondary">'
            + '<button type="button" class="btn btn-sm btn-outline-secondary" data-bs-dismiss="modal">Fermer</button>'
            + '</div>';
    }

    /**
     * L'hôte UNIQUE de la modale — créé une fois, réutilisé, jamais retiré du DOM.
     *
     * ⚠⚠ DEUX DÉFAUTS MESURÉS AU SMOKE (2026-09-08), et c'est le second qui a dicté cette forme.
     *
     * ① Une modale créée à chaque ouverture ne repartait pas : après un partage, l'élément
     *    restait `.show` dans le DOM et une seconde ouverture en empilait une autre — **deux
     *    backdrops** et `body.modal-open` conservé. Un backdrop orphelin couvre la page et
     *    avale tous les clics : le symptôme n'est pas « la modale est encore là », c'est
     *    « l'application ne répond plus ». Cause connue et déjà payée sur l'anonymizer :
     *    *Bootstrap ignore `hide()` pendant l'animation d'ouverture.*
     * ② Ma première réponse — purger l'ancienne avant d'ouvrir — a produit
     *    `TypeError: Cannot read properties of null` DANS Bootstrap : retirer l'élément
     *    pendant que `_showElement` est encore en vol lui fait déréférencer un null.
     *
     * D'où la forme retenue : **UN seul élément**, dont on remplace le contenu. Il n'y a alors
     * plus d'empilement possible, plus de retrait pendant une animation, plus de backdrop
     * orphelin — la classe de défaut disparaît au lieu d'être gardée. *Quand un correctif crée
     * un second défaut de la même famille, c'est la forme qu'il faut changer, pas la garde.*
     */
    function hote() {
        var el = document.querySelector('.wama-share-modal');
        if (el) return el;
        el = document.createElement('div');
        el.className = 'modal fade wama-share-modal';
        el.tabIndex = -1;
        el.innerHTML = '<div class="modal-dialog modal-dialog-centered">'
            + '<div class="modal-content bg-dark text-light border-secondary"></div></div>';
        document.body.appendChild(el);
        return el;
    }

    function ouvrir(surface, pk, nom, nature) {
        return fetch(urlDe(surface, pk, nature), { credentials: 'same-origin' })
            .then(function (r) {
                if (!r.ok) throw new Error('HTTP ' + r.status);
                return r.json();
            })
            .then(function (donnees) {
                // Hôte UNIQUE : on remplace son CONTENU, on ne recrée jamais l'élément.
                // `innerHTML` du contenu suffit à défaire les écouteurs de l'ouverture
                // précédente (les nœuds qui les portaient disparaissent), donc rien à
                // désabonner à la main.
                var enveloppe = hote();
                enveloppe.querySelector('.modal-content').innerHTML = corps(donnees, nom);

                // Un select n'est actif que si SA portée est choisie : sinon on éditerait la
                // cible d'un partage qu'on n'a pas retenu, et le POST l'emporterait.
                function refletter() {
                    var val = (enveloppe.querySelector('input[name="wama-share-portee"]:checked') || {}).value;
                    enveloppe.querySelectorAll('.wama-share-cible').forEach(function (s) {
                        s.disabled = s.dataset.pour !== val;
                    });
                    enveloppe.querySelectorAll('.wama-share-choix').forEach(function (d) {
                        var r = d.querySelector('input[name="wama-share-portee"]');
                        d.classList.toggle('est-actif', !!r && r.checked);
                    });
                    // Le consentement ne concerne qu'un partage : revenir au privé (retirer le
                    // partage) n'en demande aucun — c'est toujours possible, sans condition.
                    var consent = enveloppe.querySelector('[data-consent]');
                    if (consent) consent.hidden = !val || val === 'private';
                }
                enveloppe.querySelectorAll('input[name="wama-share-portee"]').forEach(function (r) {
                    r.addEventListener('change', refletter);
                });
                refletter();

                // `getOrCreateInstance` et non `new` : l'hôte survit d'une ouverture à l'autre,
                // et en recréer une instance dessus laisserait la précédente vivante (deux
                // gestionnaires pour un même élément). Rien à retirer sur `hidden` : l'élément
                // RESTE — c'est tout l'intérêt de la forme singleton.
                var modale = bootstrap.Modal.getOrCreateInstance(enveloppe);

                enveloppe.querySelector('.wama-share-ok').addEventListener('click', function () {
                    var choix = enveloppe.querySelector('input[name="wama-share-portee"]:checked');
                    if (!choix) { dire('Choisissez une portée', 'error'); return; }
                    var consentBox = enveloppe.querySelector('[data-consent]');
                    var consentCheck = enveloppe.querySelector('[data-consent-check]');
                    if (consentBox && !consentBox.hidden && !(consentCheck && consentCheck.checked)) {
                        dire('Validez le consentement pour partager — ou annulez.', 'error');
                        return;
                    }
                    var fields = { visibility: choix.value };
                    if (consentBox && !consentBox.hidden && consentCheck && consentCheck.checked) {
                        fields.consent = '1';
                    }
                    var cible = enveloppe.querySelector('.wama-share-cible[data-pour="' + choix.value + '"]');
                    if (cible && !cible.disabled) {
                        fields[choix.value === 'unit' ? 'org_unit_id' : 'project_id'] = cible.value;
                    }
                    postShare(surface, pk, nature, fields).then(function (res) {
                        if (res && res.consent_required) {
                            // Le serveur exige un consentement que la modale ne montrait pas : on
                            // l'ajoute et on attend la validation, au lieu d'un refus sec.
                            if (!enveloppe.querySelector('[data-consent]')) {
                                // Avant la DERNIÈRE note (« lecture seule ») : la première peut être
                                // celle d'une portée orpheline, au-dessus des choix.
                                var notes = enveloppe.querySelectorAll('.wama-share-note');
                                notes[notes.length - 1].insertAdjacentHTML(
                                    'beforebegin', consentBlock(res.statement || res.reason));
                                refletter();
                            }
                            dire('Validez le consentement pour partager — ou annulez.', 'warning');
                            return;
                        }
                        if (!res || res.ok === false) {
                            dire('Partage impossible — ' + ((res && res.reason) || 'refusé'), 'error');
                            return;
                        }
                        modale.hide();
                        // Le compte-rendu DIT ce qui a été touché : on n'annonce pas plus large
                        // que le serveur n'a fait. Le lot compte — une card partagée sans son
                        // lot n'apparaît PAS chez le destinataire (§7.4bis).
                        var msg = 'Portée appliquée : ' + res.libelle;
                        if (res.lot_non_partageable) {
                            dire(msg + " — ⚠ le lot de cet élément n'est pas partageable, "
                                + "le destinataire ne le verra pas dans sa file", 'error');
                        } else {
                            dire(msg + (res.lot ? ' (élément et lot)' : ''), 'success');
                        }
                    });
                });
                bindPersons(enveloppe, surface, pk, nature);
                modale.show();
                return enveloppe;
            })
            .catch(function (err) {
                dire("Partage indisponible pour cet élément", 'error');
                console.warn('[WamaShare]', err);
            });
    }

    /** POST sur la route du partage ; rend la réponse JSON (ou `{ok:false}` illisible). */
    function postShare(surface, pk, nature, fields) {
        var fd = new FormData();
        Object.keys(fields).forEach(function (k) { fd.append(k, fields[k]); });
        return fetch(urlDe(surface, pk, nature), {
            method: 'POST', headers: { 'X-CSRFToken': csrf() }, body: fd, credentials: 'same-origin',
        }).then(function (r) { return r.json().catch(function () { return { ok: r.ok }; }); });
    }

    /** Les gestes de la section « Avec une personne » : partager (consentement compris), retirer. */
    function bindPersons(enveloppe, surface, pk, nature) {
        var list = enveloppe.querySelector('[data-person-list]');
        var input = enveloppe.querySelector('[data-person-input]');
        var mode = enveloppe.querySelector('[data-person-mode]');
        if (!list || !input || !mode) return;

        function redraw(persons) { list.innerHTML = personRows(persons); }

        function share(consent) {
            var who = (input.value || '').trim();
            if (!who) { dire('Indiquez l\'identifiant ou l\'adresse e-mail de la personne', 'error'); return; }
            var fields = { person: who, mode: mode.value };
            if (consent) fields.consent = '1';
            postShare(surface, pk, nature, fields).then(function (res) {
                if (res && res.consent_required && global.WamaApp && WamaApp.ask) {
                    WamaApp.ask({ text: res.statement || res.reason, okLabel: 'Partager', danger: false,
                                  option: { label: 'Je valide ce consentement', checked: false } })
                        .then(function (a) {
                            if (a.ok && a.option) share(true);
                            else if (a.ok) dire('Partage annulé : consentement non validé', 'warning');
                        });
                    return;
                }
                if (!res || res.ok === false) {
                    dire('Partage impossible — ' + ((res && res.reason) || 'refusé'), 'error');
                    return;
                }
                input.value = '';
                redraw(res.persons);
                dire('Partagé avec ' + res.person + ' (' + res.libelle + ') — prévenu dans WAMA', 'success');
            });
        }

        enveloppe.querySelector('[data-person-add]').addEventListener('click', function () { share(false); });
        input.addEventListener('keydown', function (ev) {
            if (ev.key === 'Enter') { ev.preventDefault(); share(false); }
        });
        list.addEventListener('click', function (ev) {
            var b = ev.target.closest('[data-person-revoke]');
            if (!b) return;
            postShare(surface, pk, nature, { revoke_person: b.dataset.personRevoke }).then(function (res) {
                if (!res || res.ok === false) {
                    dire('Retrait impossible — ' + ((res && res.reason) || 'refusé'), 'error');
                    return;
                }
                redraw(res.persons);
                dire('Partage retiré pour cette personne', 'success');
            });
        });
    }

    /**
     * Coordonnées d'un LOT, depuis sa card mère ou n'importe quelle card du groupe.
     *
     * Le pk est celui du LOT (`.batch-group[data-batch-id]`) ; la SURFACE, elle, ne peut venir
     * que d'une card fille — la mère ne la déclare pas. Un lot REPLIÉ garde ses filles dans le
     * DOM (`.collapse`, taille nulle), donc la lecture marche plié comme déplié : c'est déjà
     * l'hypothèse du glisser-déposer, vérifiée par son scénario nocturne.
     */
    function coordonneesDuLot(el) {
        var groupe = el.closest ? el.closest('.batch-group[data-batch-id]') : null;
        if (!groupe) return null;
        var fille = groupe.querySelector('.wama-card:not(.is-batch) [data-preview-url], '
                                       + '.wama-card:not(.is-batch)[data-preview-url]');
        var c = fille ? coordonnees(fille) : null;
        if (!c) return null;
        return { surface: c.surface, pk: groupe.dataset.batchId, nature: 'lot' };
    }

    /** Ouvre depuis une CARD, en lisant ses coordonnées. Rend false si la card ne les porte pas. */
    function ouvrirPourCard(card, nom) {
        var c = coordonnees(card);
        if (!c) return false;
        ouvrir(c.surface, c.pk, nom, 'element');
        return true;
    }

    /** Ouvre pour le LOT auquel appartient cet élément du DOM. */
    function ouvrirPourLot(el, nom) {
        var c = coordonneesDuLot(el);
        if (!c) return false;
        ouvrir(c.surface, c.pk, nom, 'lot');
        return true;
    }

    /**
     * « TRANSFÉRER À… » (2026-10-01, `WAMA_COLLABORATION §3bis`) — la card change de propriétaire.
     * Le serveur (`common/services/card_transfer.py`) applique la règle des fichiers (possédés
     * déplacés, désignés copiés) ; ici : demander le destinataire, faire valider le consentement
     * si la card porte une personne (même règle que le partage), puis retirer la card de la file
     * (`WamaQueueActions.removeCard` — le lot quitté dit ce qu'il devient, sans rechargement).
     */
    function transfer(card, name) {
        var c = coordonnees(card);
        if (!c || !(global.WamaApp && WamaApp.ask)) return;
        WamaApp.ask({
            text: 'Transférer « ' + (name || 'cette card') + ' » à un autre compte ? Elle ne sera '
                + 'plus à vous : ses fichiers partent avec elle (ceux qu’elle ne faisait que '
                + 'désigner sont copiés, vous gardez les vôtres).',
            okLabel: 'Transférer', danger: false,
            input: { label: 'Destinataire', placeholder: 'identifiant ou adresse e-mail' },
        }).then(function (answer) {
            if (answer.ok && answer.value) send(c, card, answer.value, false);
        });
    }

    /** Le LOT entier (depuis sa card mère ou une card du groupe) : lot et cards partent ensemble. */
    function transferLot(el, name) {
        var c = coordonneesDuLot(el);
        if (!c || !(global.WamaApp && WamaApp.ask)) return;
        WamaApp.ask({
            text: 'Transférer le lot « ' + (name || 'ce lot') + ' » et toutes ses cards à un autre '
                + 'compte ? Ils ne seront plus à vous : leurs fichiers partent avec eux (ceux qu’ils '
                + 'ne faisaient que désigner sont copiés, vous gardez les vôtres).',
            okLabel: 'Transférer le lot', danger: false,
            input: { label: 'Destinataire', placeholder: 'identifiant ou adresse e-mail' },
        }).then(function (answer) {
            if (answer.ok && answer.value) send(c, el, answer.value, false);
        });
    }

    function send(c, card, recipient, consent) {
        var fd = new FormData();
        fd.append('surface', c.surface);
        fd.append('pk', c.pk);
        fd.append('to', recipient);
        if (c.nature === 'lot') fd.append('nature', 'lot');
        if (consent) fd.append('consent', '1');
        fetch('/common/api/transfer/', { method: 'POST', body: fd, credentials: 'same-origin',
                                         headers: { 'X-CSRFToken': WamaApp.csrfToken() } })
            .then(function (r) { return r.json(); })
            .then(function (res) {
                if (res.consent_required) {
                    WamaApp.ask({ text: res.statement, okLabel: 'Transférer', danger: false,
                                  option: { label: 'Je valide ce consentement', checked: false } })
                        .then(function (a) {
                            if (a.ok && a.option) send(c, card, recipient, true);
                            else if (a.ok) WamaApp.toast('Transfert annulé : consentement non validé', 'warning');
                        });
                    return;
                }
                if (!res.transferred) {
                    WamaApp.toast('Transfert impossible : ' + (res.reason || res.error || 'erreur'), 'error');
                    return;
                }
                var what = res.nature === 'lot' ? 'Lot (' + res.cards + ' card(s)) transféré' : 'Card transférée';
                WamaApp.toast(what + ' à ' + res.to + ' (' + res.moved + ' fichier(s) déplacé(s), '
                              + res.copied + ' copié(s))', 'success');
                if (res.nature === 'lot') {
                    // Le lot part en entier : son groupe quitte la file, rien à recalculer.
                    var group = document.querySelector('.batch-group[data-batch-id="' + c.pk + '"]');
                    if (group) group.remove(); else location.reload();
                    if (global.WamaFM && WamaFM.deleted) WamaFM.deleted();
                } else if (global.WamaQueueActions && WamaQueueActions.removeCard) {
                    WamaQueueActions.removeCard(c.pk, card, res.batch);
                } else {
                    location.reload();
                }
            })
            .catch(function () { WamaApp.toast('Transfert impossible (réseau)', 'error'); });
    }

    global.WamaShare = { ouvrir: ouvrir, ouvrirPourCard: ouvrirPourCard,
                         ouvrirPourLot: ouvrirPourLot,
                         coordonnees: coordonnees, coordonneesDuLot: coordonneesDuLot,
                         transfer: transfer, transferLot: transferLot };
})(window);
