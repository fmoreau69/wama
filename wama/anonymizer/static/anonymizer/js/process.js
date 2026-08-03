/**
 * Anonymizer — bouton GLOBAL ▶ Démarrer / ⏹ Arrêter du volet droit (port 2026-08-03).
 *
 * Le suivi par card (polling, refreshCard, ETA) vit dans queue.js (AnonQueue) ; la barre
 * globale est la brique commune wama-global-progress. Ce fichier ne garde que le cycle
 * du traitement GLOBAL : POST process/ (verrou batch serveur) puis stop_process/.
 * Remplace l'ancienne machine de polling legacy ([data-media-id], refreshMediaTable).
 */
document.addEventListener("DOMContentLoaded", function () {
    const cfg = window.WAMA_ANON || {};
    const btn = document.getElementById('process-toggle-btn');
    if (!btn) return;

    let isRunning = false;

    function setButton(running) {
        isRunning = running;
        btn.innerHTML = running
            ? '<i class="fas fa-stop"></i> Arrêter'
            : '<i class="fas fa-play"></i> Démarrer';
        btn.classList.toggle('btn-danger', running);
        btn.classList.toggle('btn-success', !running);
        if (running) {
            document.body.setAttribute('data-wama-processing', '1');
        } else {
            document.body.removeAttribute('data-wama-processing');
        }
    }

    async function startAll() {
        let d;
        try {
            d = await (await fetch('/anonymizer/process/', {
                method: 'POST',
                headers: { 'X-CSRFToken': cfg.csrfToken },
            })).json();
        } catch (e) {
            WamaApp.toast('Erreur réseau au lancement', 'error');
            return;
        }
        if (d.error) {
            WamaApp.toast(d.error, 'warning');
            return;
        }
        setButton(true);
        WamaApp.toast('Traitement global lancé', 'success');
        // Cards re-rendues PENDING côté serveur → reload puis polling au chargement
        setTimeout(() => location.reload(), 500);
    }

    async function stopAll() {
        try {
            await fetch('/anonymizer/stop_process/', {
                method: 'POST',
                headers: { 'X-CSRFToken': cfg.csrfToken },
            });
        } catch (e) { /* réseau */ }
        setButton(false);
        setTimeout(() => location.reload(), 300);
    }

    btn.addEventListener('click', function () {
        if (isRunning) {
            stopAll();
        } else {
            startAll();
        }
    });

    // État initial : des cards tournent déjà → bouton en mode Arrêter + polling par card
    const anyRunning = document.querySelector('.anon-card[data-status="RUNNING"]');
    if (anyRunning) {
        setButton(true);
        if (window.AnonQueue) AnonQueue.pollAllCards();
    }
});
