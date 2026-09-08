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
 * ⚠ CE QUE CETTE MODALE NE PROMET PAS. Le partage est en LECTURE SEULE — `visibility` ne dit que
 * qui VOIT. L'escalade « demande → acceptation » est le jalon S3 `AccessGrant`
 * (`PROFILES_PERMISSIONS §8.7`), encore dû. La modale le DIT à l'écran : une UI qui laisse croire
 * qu'on donne l'écriture serait un mensonge sur un sujet de droits.
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

    function urlDe(surface, pk) {
        return '/common/api/partage/' + encodeURIComponent(surface) + '/' + encodeURIComponent(pk) + '/';
    }

    /** Surface + pk lus sur la CARD, via le contrat `data-preview-url`. */
    function coordonnees(card) {
        var hote = (card.matches && card.matches('[data-preview-url]'))
            ? card : card.querySelector('[data-preview-url]');
        var url = hote && hote.getAttribute('data-preview-url');
        if (!url) return null;
        // `/common/preview/<surface>/<pk>/` — éventuellement suivi d'un `?side=…`.
        var m = url.split('?')[0].match(/\/common\/preview\/([^/]+)\/(\d+)\//);
        return m ? { surface: m[1], pk: m[2] } : null;
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
                + echapper(p.libelle) + '</span>' + cibles + '</span></label></div>';
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
            // Dire la portée du geste, à l'endroit où on le fait. L'écriture est S3.
            + '<div class="wama-share-note mt-3"><i class="fas fa-eye me-1"></i>'
            + 'Partage en <b>lecture seule</b>. Les destinataires voient l\'élément et son '
            + 'résultat ; ils ne peuvent ni le relancer ni le modifier.</div>'
            + '</div><div class="modal-footer border-secondary">'
            + '<button type="button" class="btn btn-sm btn-outline-secondary" data-bs-dismiss="modal">Annuler</button>'
            + '<button type="button" class="btn btn-sm btn-info wama-share-ok">Appliquer</button>'
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

    function ouvrir(surface, pk, nom) {
        return fetch(urlDe(surface, pk), { credentials: 'same-origin' })
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
                    var fd = new FormData();
                    fd.append('visibility', choix.value);
                    var cible = enveloppe.querySelector('.wama-share-cible[data-pour="' + choix.value + '"]');
                    if (cible && !cible.disabled) {
                        fd.append(choix.value === 'unit' ? 'org_unit_id' : 'project_id', cible.value);
                    }
                    fetch(urlDe(surface, pk), {
                        method: 'POST', headers: { 'X-CSRFToken': csrf() },
                        body: fd, credentials: 'same-origin',
                    }).then(function (r) {
                        return r.json().catch(function () { return { ok: r.ok }; });
                    }).then(function (res) {
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
                modale.show();
                return enveloppe;
            })
            .catch(function (err) {
                dire("Partage indisponible pour cet élément", 'error');
                console.warn('[WamaShare]', err);
            });
    }

    /** Ouvre depuis une CARD, en lisant ses coordonnées. Rend false si la card ne les porte pas. */
    function ouvrirPourCard(card, nom) {
        var c = coordonnees(card);
        if (!c) return false;
        ouvrir(c.surface, c.pk, nom);
        return true;
    }

    global.WamaShare = { ouvrir: ouvrir, ouvrirPourCard: ouvrirPourCard,
                         coordonnees: coordonnees };
})(window);
