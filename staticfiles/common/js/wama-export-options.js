/* WamaExportOptions — les RÉGLAGES d'un export avant de le télécharger (2026-11-19).
 *
 * Demande de Fabien : « une petite modale à l'export pdf pour régler les paramètres […] centralisé
 * et parfaitement aligné sur le fonctionnement du converter ». Rien n'est écrit pour une page : un
 * lien d'export DÉCLARE l'adresse de ses réglages (`data-wama-export-options`), qui rend le SCHÉMA
 * (des `Param`, ceux de la sortie commune — `output_formats.output_quality_param`, appliqué par le
 * converter) et ses valeurs. La fenêtre est la modale commune (`WamaParams.renderSettingsModal`),
 * lue par `WamaParams.read` ; l'export part avec les valeurs en paramètres de l'adresse.
 *
 * Sans la brique des réglages, sans Bootstrap, ou sans réglage à proposer, le lien télécharge tel
 * quel — l'export ne dépend jamais de la fenêtre.
 */
(function (global) {
  'use strict';

  function exportWith(link, values) {
    const url = new URL(link.href, global.location.href);
    Object.keys(values || {}).forEach(function (key) {
      if (values[key] !== undefined && values[key] !== null && values[key] !== '') {
        url.searchParams.set(key, values[key]);
      }
    });
    global.location.href = url.toString();
  }

  function open(link) {
    return fetch(link.dataset.wamaExportOptions, { credentials: 'same-origin' })
      .then(function (res) { return res.ok ? res.json() : {}; })
      .then(function (res) {
        const schema = res.schema || [];
        if (!schema.length) { exportWith(link, {}); return; }
        const built = global.WamaParams.renderSettingsModal({
          id: 'Export', title: res.title || link.title || 'Exporter', titleIcon: 'fa-file-export',
          schema: schema, values: res.values || {}, context: 'item',
          buttons: [
            { label: 'Annuler', className: 'btn btn-secondary', data: { 'bs-dismiss': 'modal' } },
            { label: 'Exporter', className: 'btn btn-primary wama-export-go', icon: 'fa-file-export' },
          ],
        });
        const dialog = new global.bootstrap.Modal(built.modal);
        built.modal.addEventListener('click', function (e) {
          if (!e.target.closest('.wama-export-go')) return;
          const values = global.WamaParams.read(built.host);
          dialog.hide();
          exportWith(link, values);
        });
        built.modal.addEventListener('hidden.bs.modal', function () { built.modal.remove(); });
        dialog.show();
      })
      .catch(function () { exportWith(link, {}); });
  }

  document.addEventListener('click', function (e) {
    const link = e.target.closest && e.target.closest('a[data-wama-export-options]');
    if (!link || !global.WamaParams || !global.WamaParams.renderSettingsModal || !global.bootstrap) return;
    e.preventDefault();
    open(link);
  });

  global.WamaExportOptions = { exportWith: exportWith };
})(window);
