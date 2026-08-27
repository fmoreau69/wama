/**
 * WAMA Common — ABONNEMENT aux éléments de catalogue (la couche PRÉFÉRENCE).
 *
 * Référence : PROFILES_PERMISSIONS.md §8. Le pendant serveur est
 * `wama/common/services/subscriptions.py` + l'endpoint `common:api_subscription`.
 *
 * 🔴 CETTE BRIQUE N'OUVRE AUCUN DROIT. Elle écrit ou efface un MASQUAGE, rien d'autre. Une card
 * dont l'élément n'est pas autorisé ne porte tout simplement pas de bascule (le gabarit ne la
 * rend pas) : une bascule décochée y laisserait croire qu'un clic ouvre un accès.
 *
 * DÉCLARATIF — aucune page n'écrit de JS. Le montage est automatique et le contrat tient en
 * quatre attributs :
 *
 *   [data-abo="<kind>"]                 conteneur : la NATURE des éléments (cf. KINDS côté serveur)
 *   [data-abo-toggle][data-abo-id=…]    la bascule d'un élément (un <input type=checkbox>)
 *   [data-abo-all="true"|"false"]       le sélecteur TOUT / RIEN de la page
 *   [data-abo-compte]                   (facultatif) reçoit « N sur M » après chaque changement
 *
 * L'élément filtrable qui porte `data-f-abonnement` (contrat de la barre de filtrage commune)
 * est mis à jour en place, puis la barre est ré-appliquée : sans ça, masquer une app depuis la
 * vue « Mes applications » l'y laisserait affichée jusqu'au rechargement — l'utilisateur lirait
 * « mon clic n'a rien fait ».
 */
(function (global) {
    'use strict';

    function cookie(nom) {
        var m = ('; ' + document.cookie).split('; ' + nom + '=');
        return m.length === 2 ? m.pop().split(';').shift() : '';
    }

    function poster(url, charge) {
        return fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': cookie('csrftoken') },
            body: JSON.stringify(charge),
        }).then(function (r) { return r.ok ? r.json() : null; });
    }

    function signaler(message, type) {
        if (global.WamaApp && global.WamaApp.toast) { global.WamaApp.toast(message, type || 'info'); }
    }

    function init(racine) {
        racine = racine || document;
        var conteneurs = racine.querySelectorAll('[data-abo]');
        Array.prototype.forEach.call(conteneurs, function (hote) {
            var kind = hote.getAttribute('data-abo');
            var url = hote.getAttribute('data-abo-url');
            if (!kind || !url) { return; }

            // Sur quel élément filtrable se trouve l'état ? La bascule vit DANS la card, mais
            // c'est la card qui porte `data-f-abonnement` (c'est elle que la barre masque).
            function porteur(el) { return el.closest('[data-f-abonnement]'); }

            function reappliquerFiltre() {
                var sel = document.querySelector('[data-f-facette="abonnement"]');
                if (sel) { sel.dispatchEvent(new Event('change')); }
            }

            function majCompte() {
                var cible = hote.querySelector('[data-abo-compte]');
                if (!cible) { return; }
                var bascules = hote.querySelectorAll('[data-abo-toggle]');
                var actives = hote.querySelectorAll('[data-abo-toggle]:checked');
                cible.textContent = actives.length + ' sur ' + bascules.length;
            }

            function poser(bascule, abonne) {
                bascule.checked = abonne;
                var card = porteur(bascule);
                if (card) { card.setAttribute('data-f-abonnement', abonne ? 'mes' : 'masquees'); }
            }

            hote.addEventListener('change', function (ev) {
                var bascule = ev.target.closest('[data-abo-toggle]');
                if (!bascule || !hote.contains(bascule)) { return; }
                var id = bascule.getAttribute('data-abo-id');
                var voulu = bascule.checked;
                bascule.disabled = true;
                poster(url, { kind: kind, element_id: id, subscribed: voulu })
                    .then(function (j) {
                        // L'état vient du SERVEUR, jamais de la case : si l'écriture n'a pas eu
                        // lieu, la case doit revenir — une préférence qu'on croit posée et qui
                        // ne l'est pas est exactement la panne muette que le dépôt traque.
                        if (!j || !j.ok) { poser(bascule, !voulu); signaler('Préférence non enregistrée', 'error'); return; }
                        poser(bascule, j.subscribed);
                        majCompte();
                        reappliquerFiltre();
                    })
                    .catch(function () { poser(bascule, !voulu); signaler('Préférence non enregistrée', 'error'); })
                    .finally(function () { bascule.disabled = false; });
            });

            Array.prototype.forEach.call(hote.querySelectorAll('[data-abo-all]'), function (btn) {
                btn.addEventListener('click', function () {
                    var tout = btn.getAttribute('data-abo-all') === 'true';
                    var ids = Array.prototype.map.call(
                        hote.querySelectorAll('[data-abo-toggle]'),
                        function (b) { return b.getAttribute('data-abo-id'); });
                    btn.disabled = true;
                    poster(url, { kind: kind, all: tout, ids: ids })
                        .then(function (j) {
                            if (!j || !j.ok) { signaler('Préférences non enregistrées', 'error'); return; }
                            var hors = {};
                            (j.masques || []).forEach(function (e) { hors[e] = true; });
                            Array.prototype.forEach.call(hote.querySelectorAll('[data-abo-toggle]'),
                                function (b) { poser(b, !hors[b.getAttribute('data-abo-id')]); });
                            majCompte();
                            reappliquerFiltre();
                        })
                        .catch(function () { signaler('Préférences non enregistrées', 'error'); })
                        .finally(function () { btn.disabled = false; });
                });
            });

            majCompte();
        });
    }

    global.WamaAbonnement = { init: init };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function () { init(document); });
    } else {
        init(document);
    }
})(window);
