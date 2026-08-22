/**
 * Actualisation d'un catalogue — brique COMMUNE.
 *
 * Une page catalogue ne déclare que la clé de son registre :
 *
 *     <button data-wama-refresh="fonctions">…</button>
 *
 * et hérite du reste — appel, état d'attente, compte-rendu, rechargement. Avant cette brique,
 * deux pages seulement avaient un bouton, chacune avec son script recopié dans son template :
 * des libellés différents, des réponses de formes différentes, et six pages sans rien.
 *
 * Attributs reconnus sur le bouton :
 *   data-wama-refresh   (requis) clé du registre — voir `wama/common/registries_builtin.py`
 *   data-refresh-reload "1" pour recharger la page après succès (défaut : mise à jour en place)
 *   data-refresh-target sélecteur d'un élément où écrire le compte-rendu
 */
(function () {
    'use strict';

    var URL_MODELE = '/common/api/registres/__CLE__/refresh/';
    var URL_TACHE = '/common/api/registres/tache/__ID__/';
    // Une actualisation en Celery peut durer : mesuré 31 s pour la grille de conformité, 21 s
    // pour le scan des modèles. On sonde donc jusqu'à 5 minutes, sans jamais bloquer la page.
    var SONDE_MS = 1500;
    var SONDE_MAX = 200;

    function attendre(ms) {
        return new Promise(function (r) { setTimeout(r, ms); });
    }

    /**
     * Suit une actualisation lancée en arrière-plan jusqu'à son terme.
     * Rendre la main tout de suite serait plus simple, mais l'utilisateur resterait devant des
     * chiffres périmés sans savoir si son clic a servi.
     */
    async function suivre(taskId, btn) {
        for (var i = 0; i < SONDE_MAX; i++) {
            await attendre(SONDE_MS);
            var r = await fetch(URL_TACHE.replace('__ID__', encodeURIComponent(taskId)));
            var d = await r.json();
            if (d.termine) { return d; }
            if (btn) {
                label(btn, 'Actualisation… ' + ((i + 1) * SONDE_MS / 1000 | 0) + ' s', true);
            }
        }
        return { ok: false, termine: false,
                 error: 'toujours en cours après 5 min — voir les journaux Celery' };
    }

    function csrf() {
        var m = document.cookie.match(/csrftoken=([^;]+)/);
        return m ? m[1] : '';
    }

    function toast(message, type) {
        // On PASSE par le toast commun s'il est là — pas de notification maison en doublon.
        if (window.WamaApp && typeof WamaApp.toast === 'function') {
            WamaApp.toast(message, type || 'info');
        } else {
            console.log('[catalogue] ' + message);
        }
    }

    function label(btn, texte, spin) {
        var icone = '<i class="fas fa-rotate' + (spin ? ' fa-spin' : '') + '"></i> ';
        btn.innerHTML = icone + texte;
    }

    async function actualiser(btn) {
        var cle = btn.getAttribute('data-wama-refresh');
        if (!cle) { return; }
        var original = btn.innerHTML;
        btn.disabled = true;
        label(btn, btn.getAttribute('data-refresh-busy') || 'Actualisation…', true);

        try {
            var reponse = await fetch(URL_MODELE.replace('__CLE__', encodeURIComponent(cle)), {
                method: 'POST',
                headers: { 'X-CSRFToken': csrf() },
            });
            var d = await reponse.json();

            // 202 = mise en FILE réussie, exécution pas commencée. Traiter ce cas comme un succès
            // afficherait « aucun changement » alors que le travail démarre à peine.
            if (reponse.status === 202 && d.task_id) {
                toast((d.registre ? d.registre.nom + ' : ' : '') +
                      'actualisation lancée en arrière-plan', 'info');
                d = await suivre(d.task_id, btn);
            }

            if (!d.ok) {
                toast(d.error || (d.messages || []).join(' · ') || 'Actualisation impossible',
                      'error');
            } else {
                toast((d.registre ? d.registre.nom + ' : ' : '') + d.resume, 'success');
                var cible = btn.getAttribute('data-refresh-target');
                if (cible) {
                    var el = document.querySelector(cible);
                    if (el) { el.textContent = d.resume; }
                }
                // Un rechargement n'est utile que si la page rend l'état côté serveur ; on le
                // laisse donc DÉCLARER par la page plutôt que de l'imposer.
                if (btn.getAttribute('data-refresh-reload') === '1') {
                    location.reload();
                    return;
                }
                // Le bouton porte souvent le total : on le remet à jour sans recharger.
                var compteur = document.querySelector('[data-refresh-count="' + cle + '"]');
                if (compteur && typeof d.total === 'number') { compteur.textContent = d.total; }
            }
        } catch (e) {
            toast('Erreur réseau', 'error');
        }

        btn.disabled = false;
        btn.innerHTML = original;
    }

    function brancher(racine) {
        (racine || document).querySelectorAll('[data-wama-refresh]').forEach(function (btn) {
            if (btn.dataset.wamaRefreshBound) { return; }   // idempotent : re-rendu partiel possible
            btn.dataset.wamaRefreshBound = '1';
            btn.addEventListener('click', function () { actualiser(btn); });
        });
    }

    document.addEventListener('DOMContentLoaded', function () { brancher(document); });

    window.WamaCatalogRefresh = { brancher: brancher, actualiser: actualiser };
})();
