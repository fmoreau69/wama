/**
 * WAMA — Gestionnaire générique d'actions de file d'attente
 *
 * Gère le bouton de duplication commun à toutes les applications.
 * Usage : ajouter data-duplicate-url="<url>" sur le bouton .duplicate-btn
 *
 * <button class="btn btn-sm btn-outline-info duplicate-btn"
 *         data-duplicate-url="{% url 'app:duplicate' item.id %}"
 *         title="Dupliquer">
 *     <i class="fas fa-copy"></i>
 * </button>
 */

(function () {
    'use strict';

    function getCsrf() {
        const m = document.cookie.match(/csrftoken=([^;]+)/);
        return m ? m[1] : '';
    }

    document.addEventListener('click', function (e) {
        const btn = e.target.closest('.duplicate-btn[data-duplicate-url]');
        if (!btn) return;

        const url = btn.dataset.duplicateUrl;
        if (!url) return;

        btn.disabled = true;
        const icon = btn.querySelector('i');
        if (icon) { icon.className = 'fas fa-spinner fa-spin'; }

        fetch(url, {
            method: 'POST',
            headers: {
                'X-CSRFToken': getCsrf(),
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({}),
        })
        .then(function (r) { return r.json(); })
        .then(function (data) {
            if (data.duplicated || data.success) {
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
})();
