/**
 * WAMA — Gestionnaire générique d'actions de file d'attente
 *
 * DOMICILE UNIQUE des actions de card. Ce fichier héberge TOUTES les actions possibles d'une
 * card et les distribue selon le besoin de l'app : une app qui ne rend pas le bouton n'a rien à
 * désactiver, une app qui le rend n'a rien à câbler. Ajouter une action ici, jamais dans l'app.
 *
 * Actions gérées :
 *   ⧉ Dupliquer  → <button class="… duplicate-btn" data-duplicate-url="{% url 'app:duplicate' o.id %}">
 *   🗑 Supprimer  → <button class="… delete-btn"    data-delete-url="{% url 'app:delete' o.id %}">
 *
 * Une SEULE délégation par action, posée sur le document. C'est ce qui satisfait l'intention de
 * CARD_DESIGN §3 (« un seul handler par file plutôt que N handlers ») : le mal visé y est le
 * double-fire né de N handlers accrochés par N apps, pas le fait que le sélecteur soit une
 * classe. Le nommage reste donc `.delete-btn`, symétrique de `.duplicate-btn` — deux boutons
 * voisins dans la même piste ACTIONS doivent porter le même genre de contrat (arbitrage Fabien,
 * 2026-08-22). Adopter `data-action` pour la seule suppression aurait fait cohabiter deux
 * contrats sur deux boutons côte à côte : moins homogène, pas plus.
 *
 * POURQUOI CETTE BRIQUE EXISTE (mesuré le 2026-08-22). La duplication, qui était déjà ici, est
 * uniforme sur 12 cards sur 12. La suppression, qui n'y était PAS, comptait SIX graphies pour
 * dix apps : `delete-btn` (6), `job-delete-btn` (converter ×2), `btn-delete-job` (avatarizer),
 * `js-audio-delete` et `js-delete-enhancement` (enhancer), `video-delete-btn` (imager vidéo),
 * et `data-action="delete"` sans classe (reader). Deux boutons côte à côte dans la même card,
 * l'un uniforme et l'autre éclaté : la divergence n'est pas une négligence de style, c'est la
 * conséquence mécanique de l'absence de brique.
 */

(function () {
    'use strict';

    function getCsrf() {
        const m = document.cookie.match(/csrftoken=([^;]+)/);
        return m ? m[1] : '';
    }

    function poster(url) {
        return fetch(url, {
            method: 'POST',
            headers: {
                'X-CSRFToken': getCsrf(),
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({}),
        });
    }

    // Un 204 (No Content) est un succès sans corps : `r.json()` y lèverait. Les vues WAMA
    // répondent tantôt en JSON, tantôt en 204 — on accepte les deux plutôt que d'imposer une
    // graphie de réponse aux 10 apps (même raison que le repli `id`/`job_id`/`pk` du trou #24).
    function lireReponse(r) {
        if (r.status === 204) return Promise.resolve({ success: true });
        return r.json().catch(function () { return { success: r.ok }; });
    }

    // ── ⧉ DUPLIQUER ────────────────────────────────────────────────────────────────────
    document.addEventListener('click', function (e) {
        const btn = e.target.closest('.duplicate-btn[data-duplicate-url]');
        if (!btn) return;

        const url = btn.dataset.duplicateUrl;
        if (!url) return;

        btn.disabled = true;
        const icon = btn.querySelector('i');
        if (icon) { icon.className = 'fas fa-spinner fa-spin'; }

        poster(url)
        .then(lireReponse)
        .then(function (data) {
            if (data.duplicated || data.success) {
                // Focus la card dupliquée après rechargement (WamaQueue.focusFromSession) —
                // comportement remonté du transcriber (03/08) : la repérer facilement,
                // surtout sortie/isolée d'un batch ou si elle n'atterrit pas en tête.
                if (data.duplicated && data.duplicated !== true) {
                    try {
                        sessionStorage.setItem('wama_focus_card',
                            '.wama-card[data-id="' + data.duplicated + '"]');
                    } catch (e) { /* stockage indisponible */ }
                }
                location.reload();
            } else {
                alert(data.error || 'Duplication impossible');
                btn.disabled = false;
                if (icon) { icon.className = 'fas fa-copy'; }
            }
        })
        .catch(function () {
            alert('Erreur réseau lors de la duplication');
            btn.disabled = false;
            if (icon) { icon.className = 'fas fa-copy'; }
        });
    });

    // ── 🗑 SUPPRIMER ───────────────────────────────────────────────────────────────────
    document.addEventListener('click', function (e) {
        const btn = e.target.closest('.delete-btn[data-delete-url]');
        if (!btn) return;

        const url = btn.dataset.deleteUrl;
        if (!url) return;

        // Confirmation CENTRALISÉE : chaque app réécrivait la sienne, avec des libellés
        // différents et parfois aucune. `data-confirm` permet un message propre à l'app
        // (« supprimer aussi le fichier source ? ») ; `data-confirm="false"` la supprime
        // quand la suppression est déjà gardée en amont.
        const demande = btn.dataset.confirm;
        if (demande !== 'false'
            && !window.confirm(demande || 'Supprimer cet élément ? Cette action est définitive.')) {
            return;
        }

        btn.disabled = true;
        const icon = btn.querySelector('i');
        const iconeInitiale = icon ? icon.className : '';
        if (icon) { icon.className = 'fas fa-spinner fa-spin'; }

        poster(url)
        .then(lireReponse)
        .then(function (data) {
            if (data.deleted || data.success || data.status === 'deleted') {
                location.reload();
            } else {
                alert(data.error || 'Suppression impossible');
                btn.disabled = false;
                if (icon) { icon.className = iconeInitiale; }
            }
        })
        .catch(function () {
            alert('Erreur réseau lors de la suppression');
            btn.disabled = false;
            if (icon) { icon.className = iconeInitiale; }
        });
    });
})();
