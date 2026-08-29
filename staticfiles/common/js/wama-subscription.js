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
 * ⚠ Les attributs `data-abo-*` restent en français À DESSEIN (2026-08-29) : ce sont des noms de
 * DONNÉES, écrits dans les gabarits et jumeaux du vocabulaire de facettes de la barre de filtrage
 * (`data-f-abonnement`, `data-f-categorie`, `data-f-registre`… — 6 gabarits, 2 JS). Les renommer
 * ici seulement créerait un demi-vocabulaire ; c'est un arbitrage à mener sur les DEUX briques.
 * Les identifiants du module, eux, sont anglais (règle de nommage, CLAUDE.md).
 *
 * L'élément filtrable qui porte `data-f-abonnement` (contrat de la barre de filtrage commune)
 * est mis à jour en place, puis la barre est ré-appliquée : sans ça, masquer une app depuis la
 * vue « Mes applications » l'y laisserait affichée jusqu'au rechargement — l'utilisateur lirait
 * « mon clic n'a rien fait ».
 */
(function (global) {
    'use strict';

    function cookie(name) {
        var m = ('; ' + document.cookie).split('; ' + name + '=');
        return m.length === 2 ? m.pop().split(';').shift() : '';
    }

    function post(url, payload) {
        return fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': cookie('csrftoken') },
            body: JSON.stringify(payload),
        }).then(function (r) { return r.ok ? r.json() : null; });
    }

    function notify(message, type) {
        if (global.WamaApp && global.WamaApp.toast) { global.WamaApp.toast(message, type || 'info'); }
    }

    function init(root) {
        root = root || document;
        var containers = root.querySelectorAll('[data-abo]');
        Array.prototype.forEach.call(containers, function (host) {
            var kind = host.getAttribute('data-abo');
            var url = host.getAttribute('data-abo-url');
            if (!kind || !url) { return; }

            // Sur quel élément filtrable se trouve l'état ? La bascule vit DANS la card, mais
            // c'est la card qui porte `data-f-abonnement` (c'est elle que la barre masque).
            function carrier(el) { return el.closest('[data-f-abonnement]'); }

            function reapplyFilter() {
                var sel = document.querySelector('[data-f-facette="abonnement"]');
                if (sel) { sel.dispatchEvent(new Event('change')); }
            }

            function updateCount() {
                var target = host.querySelector('[data-abo-compte]');
                if (!target) { return; }
                var toggles = host.querySelectorAll('[data-abo-toggle]');
                var active = host.querySelectorAll('[data-abo-toggle]:checked');
                target.textContent = active.length + ' sur ' + toggles.length;
            }

            function setState(toggle, subscribed) {
                toggle.checked = subscribed;
                var card = carrier(toggle);
                if (card) { card.setAttribute('data-f-abonnement', subscribed ? 'mes' : 'masquees'); }
            }

            host.addEventListener('change', function (ev) {
                var toggle = ev.target.closest('[data-abo-toggle]');
                if (!toggle || !host.contains(toggle)) { return; }
                var id = toggle.getAttribute('data-abo-id');
                var wanted = toggle.checked;
                toggle.disabled = true;
                post(url, { kind: kind, element_id: id, subscribed: wanted })
                    .then(function (j) {
                        // L'état vient du SERVEUR, jamais de la case : si l'écriture n'a pas eu
                        // lieu, la case doit revenir — une préférence qu'on croit posée et qui
                        // ne l'est pas est exactement la panne muette que le dépôt traque.
                        if (!j || !j.ok) { setState(toggle, !wanted); notify('Préférence non enregistrée', 'error'); return; }
                        setState(toggle, j.subscribed);
                        updateCount();
                        reapplyFilter();
                    })
                    .catch(function () { setState(toggle, !wanted); notify('Préférence non enregistrée', 'error'); })
                    .finally(function () { toggle.disabled = false; });
            });

            Array.prototype.forEach.call(host.querySelectorAll('[data-abo-all]'), function (btn) {
                btn.addEventListener('click', function () {
                    var all = btn.getAttribute('data-abo-all') === 'true';
                    var ids = Array.prototype.map.call(
                        host.querySelectorAll('[data-abo-toggle]'),
                        function (b) { return b.getAttribute('data-abo-id'); });
                    btn.disabled = true;
                    post(url, { kind: kind, all: all, ids: ids })
                        .then(function (j) {
                            if (!j || !j.ok) { notify('Préférences non enregistrées', 'error'); return; }
                            var hidden = {};
                            (j.masques || []).forEach(function (e) { hidden[e] = true; });
                            Array.prototype.forEach.call(host.querySelectorAll('[data-abo-toggle]'),
                                function (b) { setState(b, !hidden[b.getAttribute('data-abo-id')]); });
                            updateCount();
                            reapplyFilter();
                        })
                        .catch(function () { notify('Préférences non enregistrées', 'error'); })
                        .finally(function () { btn.disabled = false; });
                });
            });

            updateCount();
        });
    }

    global.WamaSubscription = { init: init };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function () { init(document); });
    } else {
        init(document);
    }
})(window);
