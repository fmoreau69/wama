/**
 * WAMA — WamaPromotion : « Demander la promotion » d'un élément d'auteur, le MÊME geste pour toutes
 * les familles (skill de prompt, thème de charte, modèle… — `ROADMAP §29` 6a, 2026-10-20).
 *
 * UNE route (`common:api_promotion_request`) ; la demande se tranche ensuite sur SA page
 * (`/common/requests/<pk>/`, celle des demandes d'accès), où les administrateurs, prévenus, la
 * valident ou la refusent. Aucune page n'écrit son propre appel :
 *
 *   <button data-promotion-request="{% url 'common:api_promotion_request' %}"
 *           data-registry="skills" data-pk="12">Demander la promotion</button>
 *
 * (`data-key` à la place de `data-pk` quand la famille se nomme par sa clé : un modèle.)
 * Délégué sur le document : les boutons rendus plus tard (inspecteur du model manager) en profitent.
 */
(function (global) {
    'use strict';

    function csrf() {
        var m = document.cookie.match(/csrftoken=([^;]+)/);
        return m ? m[1] : '';
    }

    function say(msg, tone) {
        if (global.WamaApp && global.WamaApp.toast) { global.WamaApp.toast(msg, tone); }
    }

    /** Envoie la demande ; rend la réponse du serveur ({requested, url} ou {requested:false, reason}). */
    function request(url, target) {
        return fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf() },
            body: JSON.stringify(target)
        }).then(function (r) { return r.json().catch(function () { return { requested: false }; }); });
    }

    document.addEventListener('click', function (ev) {
        var b = ev.target.closest && ev.target.closest('[data-promotion-request]');
        if (!b) { return; }
        ev.preventDefault();
        ev.stopPropagation();
        b.disabled = true;
        var target = { registry: b.dataset.registry };
        if (b.dataset.pk) { target.pk = b.dataset.pk; } else { target.key = b.dataset.key; }
        request(b.dataset.promotionRequest, target).then(function (res) {
            if (res && res.requested) {
                say('Promotion demandée : les administrateurs sont prévenus.', 'success');
                if (b.dataset.reload !== '0') { global.location.reload(); }
                return;
            }
            say('Impossible — ' + ((res && res.reason) || 'refusé'), 'danger');
            b.disabled = false;
        });
    });

    global.WamaPromotion = { request: request };
})(window);
