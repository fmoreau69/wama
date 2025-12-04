/**
 * Console générique pour toutes les apps WAMA
 * Utilise l'attribut data-console-url pour déterminer l'endpoint
 */
document.addEventListener('DOMContentLoaded', function () {
  // Chercher tous les conteneurs de console (pour supporter plusieurs apps)
  const consoleContainers = document.querySelectorAll('[data-console-url]');

  consoleContainers.forEach(function(consoleContainer) {
    const endpoint = consoleContainer.dataset.consoleUrl;
    if (!endpoint) {
      return;
    }

    function refreshConsole() {
      fetch(endpoint)
        .then((response) => response.json())
        .then((data) => {
          const lines = data.output || [];
          if (!lines.length) {
            consoleContainer.innerHTML = '<p class="text-muted mb-0">Aucun log disponible.</p>';
            return;
          }
          consoleContainer.innerHTML = lines
            .map(
              (line) =>
                `<div class="console-line" style="white-space: pre-wrap; word-break: break-word;">${escapeHtml(
                  line
                )}</div>`
            )
            .join('');
          const panelBody = consoleContainer.parentElement;
          if (panelBody) {
            panelBody.scrollTop = panelBody.scrollHeight;
          }
        })
        .catch(() => {
          consoleContainer.innerHTML =
            '<p class="text-danger mb-0">Impossible de charger les logs (voir celery-worker.log).</p>';
        });
    }

    function escapeHtml(str) {
      return str
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
    }

    // Initialiser et rafraîchir toutes les 4 secondes
    refreshConsole();
    setInterval(refreshConsole, 4000);
  });
});
