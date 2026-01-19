document.addEventListener('DOMContentLoaded', function () {
  const consoleContainer = document.getElementById('anonymizer-console-content');
  if (!consoleContainer) {
    return;
  }

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
          consoleContainer.innerHTML = '<p mb-0">Aucun log disponible.</p>';
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

  refreshConsole();
  setInterval(refreshConsole, 4000);
});

