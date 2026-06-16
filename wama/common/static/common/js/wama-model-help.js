/**
 * WAMA — Descriptif dynamique du modèle/moteur sélectionné (commun à toutes les apps).
 *
 * Affiche, sous un <select> de modèle, la description COURTE du choix courant (mise à jour
 * au `change`), avec une icône ⓘ (tooltip) portant la description LONGUE si elle diffère.
 * Toutes les apps WAMA utilisent des modèles → informer l'utilisateur de façon homogène.
 *
 * Deux tiers de description (cf. AIModel.description / description_short) :
 *   - court (`description`)       → affiché sous le sélecteur
 *   - long  (`description_long`)  → tooltip détaillé (à-propos)
 *
 * Source des `meta` :
 *   - apps dont le sélecteur = un MOTEUR/granularité propre (ex. Transcriber : whisper/
 *     vibevoice/qwen) → fournir `meta` depuis l'endpoint backends de l'app (descriptions
 *     opérationnelles, qui DIVERGENT légitimement du catalogue).
 *   - apps dont le sélecteur = un MODÈLE du catalogue → `WamaModelHelp.fetchCatalogMeta(source)`
 *     construit `meta` depuis model_manager (api/models/db/), source de vérité unique.
 *
 * Usage :
 *   const help = WamaModelHelp.init({ selectId:'backendSelect', helpId:'backendHelp',
 *                                     meta:{}, fallback:{auto:'…'} });
 *   help.setMeta({ whisper:{description:'…', description_long:'…', recommended_vram_gb:10}, … });
 *
 * meta : { <valeur option> : { description, description_long?, recommended_vram_gb|vram_gb } }
 * fallback : { <valeur option> : 'texte' } — utilisé si meta absent (ex. option « auto »).
 */
(function (global) {
  'use strict';

  function _escAttr(s) {
    return (s || '').replace(/[&<>"']/g, function (m) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[m];
    });
  }

  function init(cfg) {
    cfg = cfg || {};
    const sel = document.getElementById(cfg.selectId);
    const help = document.getElementById(cfg.helpId);
    if (!sel || !help) return null;
    let meta = cfg.meta || {};
    const fallback = cfg.fallback || {};

    function render() {
      const m = meta[sel.value] || {};
      let txt = m.description || fallback[sel.value] || '';
      const vram = m.recommended_vram_gb || m.vram_gb;
      if (txt && vram) txt += ' · ' + vram + ' Go VRAM';

      const long = m.description_long || '';
      if (txt && long && long !== (m.description || '')) {
        // Court + ⓘ portant le descriptif long en tooltip natif.
        help.innerHTML = _escAttr(txt) +
          ' <i class="fas fa-circle-info" style="cursor:help;opacity:.65;" title="' +
          _escAttr(long) + '"></i>';
      } else {
        help.textContent = txt;
      }
    }

    sel.addEventListener('change', render);
    render();

    return {
      setMeta: function (m) { meta = m || {}; render(); },
      render: render,
    };
  }

  /**
   * Construit une `meta` depuis le catalogue model_manager pour les apps dont les
   * options du <select> sont des modèles du catalogue.
   *   source : valeur ModelSource (ex. 'imager', 'describer', …)
   *   opts.keyBy : champ de to_dict() à utiliser comme clé d'option (def. 'model_key',
   *                souvent surchargé en 'id' selon les valeurs réelles du <select>)
   *   opts.url   : override de l'URL de l'API (def. /model-manager/api/models/db/)
   * → Promise<meta> : { <clé> : {description, description_short, vram_gb, …} }
   * NB : on mappe `description_short` du catalogue vers `description` (champ court attendu
   *      par init()) et `description` (long) vers `description_long`.
   */
  function fetchCatalogMeta(source, opts) {
    opts = opts || {};
    const keyBy = opts.keyBy || 'model_key';
    const base = opts.url || '/model-manager/api/models/db/';
    const url = base + '?source=' + encodeURIComponent(source) +
                (opts.downloadedOnly ? '&downloaded=true' : '');
    return fetch(url)
      .then(function (r) { return r.json(); })
      .then(function (data) {
        const meta = {};
        (data.models || []).forEach(function (m) {
          const key = m[keyBy];
          if (key == null) return;
          meta[key] = {
            description: m.description_short || m.description || '',
            description_long: m.description || '',
            vram_gb: m.vram_gb,
          };
        });
        return meta;
      })
      .catch(function () { return {}; });
  }

  global.WamaModelHelp = { init: init, fetchCatalogMeta: fetchCatalogMeta };
})(window);
