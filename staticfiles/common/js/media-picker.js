/**
 * WAMA — MediaPicker
 * Composant réutilisable : ouvre une modale de sélection d'asset depuis la Médiathèque.
 *
 * Usage:
 *   MediaPicker.open({
 *     type:     'image',          // catégorie ('image', 'audio'…) ou nature exacte ('avatar')
 *     prefer:   'avatar',         // (option) l'ONGLET sur lequel la fenêtre s'ouvre
 *     sources:  'all' | 'mine',   // (option) défaut : 'all' avec onPick, 'mine' avec onSelect
 *     onSelect: (file, asset) => { ... }  // callback avec File + meta (le fichier est TÉLÉCHARGÉ)
 *     onPick:   (asset) => { ... }        // OU : l'asset seul, SANS téléchargement — pour qui
 *                                         // le DÉSIGNE (`asset.path`) au lieu de le re-téléverser
 *   });
 *
 * ONGLETS et PROVENANCES (2026-09-29, fenêtre universelle — `CARD_DESIGN §11.11` étape 3 (d)) :
 * les onglets sont ceux de la CATÉGORIE demandée — « Tous » puis chaque nature déclarée
 * (`natures.py`), servis par `api_list?tabs=1` ; rien n'est recopié ici. `sources:'all'` montre
 * les miens, ceux qu'on me PARTAGE (labo, projet, public) et ceux du SYSTÈME (la galerie
 * d'avatars) — chaque card dit sa provenance. Ce n'est PAS le défaut d'`onSelect` : ce chemin-là
 * télécharge le fichier pour le re-téléverser, il RECOPIERAIT l'asset d'autrui ; la portée se
 * demande (`media_library/views.py`, portée `mine`/`visible`).
 *
 * `onPick` (2026-09-28, D10 de MEDIA_STORAGE_TIERING §8.6) : le téléchargement du fichier avant
 * `onSelect` servait à le re-téléverser — une copie. Une card qui POINTE l'asset n'a besoin que de
 * son chemin ; `onPick` prime sur `onSelect` quand les deux sont donnés.
 *
 * APERÇU AVANT LE CHOIX (2026-09-29, demande : « sinon on ne sait pas de quoi il s'agit ») : un
 * clic MONTRE l'asset dans le volet d'aperçu de la fenêtre — le rendu INLINE commun
 * (`WamaInspector.renderInlinePreview` : image, vidéo, lecteur audio commun, PDF, texte), celui
 * du volet droit des apps ; « Choisir » confirme, un DOUBLE-CLIC choisit directement. Avant, un
 * clic choisissait à l'aveugle, et tout ce qui n'était pas une image portait la même icône
 * « fichier audio » (vidéos, documents, modèles 3D compris).
 *
 * Prérequis: window.ML_LIST_URL doit être défini avant l'appel
 *   <script>const ML_LIST_URL = "{% url 'media_library:api_list' %}";</script>
 */
const MediaPicker = (() => {
  const MODAL_ID = 'wama-mediapicker-modal';
  let _options   = null;
  let _loading   = false;
  let _activeType = 'all';   // l'onglet courant : catégorie ou nature
  let _activeExact = false;  // nature EXACTE (`image`, `video`, `document` sont aussi des catégories)
  let _tabsShown  = false;   // les onglets ne se demandent qu'une fois par ouverture
  let _focused    = null;    // l'asset montré dans l'aperçu, celui que « Choisir » retiendra

  // ── Modal HTML ─────────────────────────────────────────────────────────────

  function _ensureModal() {
    if (document.getElementById(MODAL_ID)) return;
    const wrapper = document.createElement('div');
    wrapper.innerHTML = `
<div class="modal fade" id="${MODAL_ID}" tabindex="-1">
  <div class="modal-dialog modal-xl modal-dialog-scrollable">
    <div class="modal-content bg-dark text-light border-secondary">
      <div class="modal-header border-secondary py-2">
        <h6 class="modal-title mb-0">
          <i class="fas fa-photo-video me-2 text-info"></i>Médiathèque
        </h6>
        <div class="d-flex align-items-center gap-2 ms-3">
          <input type="text" id="mp-search-input"
                 class="form-control form-control-sm bg-dark text-white border-secondary"
                 placeholder="Rechercher…" style="width:180px">
        </div>
        <button type="button" class="btn-close btn-close-white ms-auto"
                data-bs-dismiss="modal"></button>
      </div>
      <div class="modal-body p-2">
        <div id="mp-tabs" class="nav nav-pills gap-1 mb-2" role="tablist"></div>
        <div class="row g-2">
          <div class="col-12 col-lg-8">
            <div id="mp-grid"
                 class="row row-cols-2 row-cols-sm-3 row-cols-md-4 g-2">
            </div>
            <div id="mp-spinner" class="text-center py-5">
              <div class="spinner-border text-info" role="status"></div>
              <p class="text-muted small mt-2">Chargement…</p>
            </div>
            <div id="mp-empty" class="text-center text-muted py-5" style="display:none">
              <i class="fas fa-inbox fa-2x mb-2"></i><br>Aucun asset trouvé
            </div>
            <div id="mp-error" class="alert alert-danger mt-2" style="display:none"></div>
          </div>
          <div class="col-12 col-lg-4">
            <div id="mp-preview" class="border border-secondary rounded p-2 h-100">
              <div id="mp-preview-empty" class="text-center text-muted small py-4">
                <i class="fas fa-eye fa-lg mb-2 d-block"></i>
                Cliquez sur un élément pour l'aperçu<br>— double-clic pour le choisir.
              </div>
              <div id="mp-preview-body" style="display:none">
                <div id="mp-preview-media" class="mb-2 text-center"></div>
                <div class="small text-light text-break" id="mp-preview-name"></div>
                <div class="small text-muted" id="mp-preview-meta"></div>
                <div class="small text-muted mt-1" id="mp-preview-desc"></div>
              </div>
            </div>
          </div>
        </div>
      </div>
      <div class="modal-footer border-secondary py-2">
        <small class="text-muted me-auto" id="mp-count"></small>
        <button id="mp-load-more" class="btn btn-outline-secondary btn-sm" style="display:none">
          <i class="fas fa-chevron-down me-1"></i>Charger plus
        </button>
        <button type="button" class="btn btn-secondary btn-sm"
                data-bs-dismiss="modal">Annuler</button>
        <button type="button" id="mp-choose" class="btn btn-info btn-sm" disabled>
          <i class="fas fa-check me-1"></i>Choisir
        </button>
      </div>
    </div>
  </div>
</div>`;
    document.body.appendChild(wrapper.firstElementChild);

    // Search debounce
    let _debTimer;
    document.getElementById('mp-search-input').addEventListener('input', () => {
      clearTimeout(_debTimer);
      _debTimer = setTimeout(() => _load(1, true), 400);
    });

    document.getElementById('mp-load-more').addEventListener('click', () => {
      const btn = document.getElementById('mp-load-more');
      _load(parseInt(btn.dataset.nextPage, 10), false);
    });

    document.getElementById('mp-choose').addEventListener('click', () => {
      if (_focused) _selectAsset(_focused);
    });
    // Fermer la fenêtre fait taire l'aperçu (un audio continuerait sinon, sans lecteur visible).
    document.getElementById(MODAL_ID).addEventListener('hidden.bs.modal', _clearPreview);
  }

  // ── Aperçu (volet de la fenêtre) ───────────────────────────────────────────

  /** Le type pour l'aperçu : `preview_mime` (résolu par le SERVEUR, du fichier quand le type
   *  stocké manque — `media_library/views.py::_preview_mime`), sinon celui de la nature. */
  function _mimeOf(asset) {
    if (asset.preview_mime) return asset.preview_mime;
    if (asset.mime_type) return asset.mime_type;
    if (['image', 'avatar'].includes(asset.asset_type)) return 'image/*';
    if (asset.asset_type === 'video') return 'video/*';
    return '';
  }

  function _clearPreview() {
    _focused = null;
    const media = document.getElementById('mp-preview-media');
    if (window.WamaAudioPlayer && WamaAudioPlayer.pauseAll) WamaAudioPlayer.pauseAll();
    if (media) media.innerHTML = '';
    const body = document.getElementById('mp-preview-body');
    const empty = document.getElementById('mp-preview-empty');
    if (body) body.style.display = 'none';
    if (empty) empty.style.display = '';
    const choose = document.getElementById('mp-choose');
    if (choose) choose.disabled = true;
    document.querySelectorAll('#mp-grid .mp-asset-card.mp-focused').forEach(c => {
      c.classList.remove('mp-focused');
      c.style.borderColor = '';
    });
  }

  function _focus(asset, card) {
    _clearPreview();
    _focused = asset;
    card.classList.add('mp-focused');
    card.style.borderColor = '#0dcaf0';
    const media = document.getElementById('mp-preview-media');
    media.dataset.playerId = 'mediapicker';
    const data = { url: asset.file_url, name: asset.name, mime_type: _mimeOf(asset) };
    if (window.WamaInspector && WamaInspector.renderInlinePreview) {
      WamaInspector.renderInlinePreview(media, data, false);
    } else if (data.mime_type.indexOf('image/') === 0) {
      media.innerHTML = `<img src="${_esc(asset.file_url)}" alt="" style="max-width:100%;max-height:220px">`;
    }
    // L'aperçu commun légende déjà le média par son nom : ne le répéter que s'il n'en a rien dit.
    document.getElementById('mp-preview-name').textContent =
      media.querySelector('small') ? '' : (asset.name || '');
    document.getElementById('mp-preview-meta').textContent =
      [asset.duration, asset.origin === 'system' ? 'Ressource système'
        : asset.origin === 'shared' ? 'Partagé par ' + (asset.owner || '—') : '']
        .filter(Boolean).join(' · ');
    document.getElementById('mp-preview-desc').textContent = asset.description || '';
    document.getElementById('mp-preview-empty').style.display = 'none';
    document.getElementById('mp-preview-body').style.display = '';
    document.getElementById('mp-choose').disabled = false;
  }

  // ── Load assets ────────────────────────────────────────────────────────────

  async function _load(page, reset) {
    if (_loading) return;
    _loading = true;

    const q   = document.getElementById('mp-search-input').value.trim();
    const url = new URL(window.ML_LIST_URL || '/media-library/api/assets/', location.origin);
    url.searchParams.set('type', _activeType);
    if (_activeExact) url.searchParams.set('exact', '1');
    url.searchParams.set('page', page);
    if (q) url.searchParams.set('q', q);
    if (_allSources()) {
      url.searchParams.set('scope', 'visible');
      url.searchParams.set('with_system', '1');
    }
    if (!_tabsShown) url.searchParams.set('tabs', '1');

    const spinner  = document.getElementById('mp-spinner');
    const empty    = document.getElementById('mp-empty');
    const errorDiv = document.getElementById('mp-error');
    const grid     = document.getElementById('mp-grid');
    const loadMore = document.getElementById('mp-load-more');
    const count    = document.getElementById('mp-count');

    errorDiv.style.display = 'none';
    if (reset) {
      _clearPreview();
      grid.innerHTML = '';
      spinner.style.display = '';
      empty.style.display   = 'none';
      loadMore.style.display = 'none';
    }

    try {
      const res  = await fetch(url);
      const data = await res.json();
      spinner.style.display = 'none';
      if (data.tabs) _renderTabs(data.tabs);

      if (!data.assets || !data.assets.length) {
        if (reset) empty.style.display = '';
        _loading = false;
        return;
      }

      count.textContent = `${data.total} asset${data.total > 1 ? 's' : ''}`;

      for (const a of data.assets) {
        grid.appendChild(_buildCard(a));
      }

      if (data.has_more) {
        loadMore.style.display = '';
        loadMore.dataset.nextPage = page + 1;
      } else {
        loadMore.style.display = 'none';
      }
    } catch (err) {
      spinner.style.display = 'none';
      errorDiv.textContent  = `Erreur : ${err.message}`;
      errorDiv.style.display = '';
    }

    _loading = false;
  }

  // ── Onglets (catégorie → natures) ──────────────────────────────────────────

  function _allSources() {
    const s = _options.sources || (_options.onPick ? 'all' : 'mine');
    return s === 'all';
  }

  function _renderTabs(tabs) {
    const host = document.getElementById('mp-tabs');
    host.innerHTML = '';
    tabs.forEach(t => {
      const b = document.createElement('button');
      b.type = 'button';
      const isActive = t.key === _activeType && !!t.exact === _activeExact;
      b.className = 'nav-link py-1 px-2 small' + (isActive ? ' active' : '');
      b.dataset.mpTab = t.key;
      b.innerHTML = `<i class="fas ${_esc(t.icon)} me-1"></i>${_esc(t.label)}` +
                    ` <span class="badge bg-secondary ms-1">${t.count}</span>`;
      b.addEventListener('click', () => {
        if (_activeType === t.key && _activeExact === !!t.exact) return;
        _activeType = t.key;
        _activeExact = !!t.exact;
        host.querySelectorAll('[data-mp-tab]').forEach(x => x.classList.toggle('active', x === b));
        _load(1, true);
      });
      host.appendChild(b);
    });
    _tabsShown = true;
  }

  function _esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, c =>
      ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  // La PROVENANCE d'un asset partagé ou système se dit sur sa card ; les miens n'ont rien à dire.
  function _originBadge(asset) {
    if (asset.origin === 'system') {
      return '<span class="badge bg-dark border border-info text-info mp-origin" title="Ressource système">' +
             '<i class="fas fa-building-columns me-1"></i>Système</span>';
    }
    if (asset.origin === 'shared') {
      return `<span class="badge bg-dark border border-warning text-warning mp-origin" title="Partagé avec moi">` +
             `<i class="fas fa-share-nodes me-1"></i>${_esc(asset.owner || 'partagé')}</span>`;
    }
    return '';
  }

  // ── Build a card ───────────────────────────────────────────────────────────

  /** L'icône d'un asset sans vignette, par la famille de son type. */
  function _iconOf(mime) {
    if (mime.indexOf('audio/') === 0) return 'fa-music';
    if (mime === 'application/pdf') return 'fa-file-pdf';
    if (mime.indexOf('text/') === 0) return 'fa-file-lines';
    if (mime.indexOf('model/') === 0) return 'fa-cube';
    return 'fa-file';
  }

  function _thumb(asset) {
    const mime = _mimeOf(asset);
    const url = _esc(asset.file_url);
    const box = 'height:80px;border-radius:4px 4px 0 0';
    if (mime.indexOf('image/') === 0) {
      return `<img src="${url}" class="card-img-top" style="${box};object-fit:cover" alt="" loading="lazy">`;
    }
    if (mime.indexOf('video/') === 0) {
      // La 1ʳᵉ image de la vidéo (`#t=0.1`, métadonnées seules) : ce qu'elle montre, pas une icône.
      return `<video src="${url}#t=0.1" preload="metadata" muted playsinline
                     class="card-img-top bg-black" style="${box};object-fit:cover"></video>`;
    }
    return `<div class="d-flex align-items-center justify-content-center bg-secondary bg-opacity-25"
                 style="${box}"><i class="fas ${_iconOf(mime)} fa-2x text-secondary"></i></div>`;
  }

  function _buildCard(asset) {
    const col = document.createElement('div');
    col.className = 'col';
    col.innerHTML = `
<div class="card bg-dark border-secondary h-100 mp-asset-card"
     style="cursor:pointer;transition:border-color .15s"
     title="${_esc(asset.name)} — clic : aperçu · double-clic : choisir">
  ${_thumb(asset)}
  <div class="card-body p-1">
    <small class="text-light d-block text-truncate" style="font-size:.7rem">${_esc(asset.name)}</small>
    ${_originBadge(asset)}
    ${asset.duration ? `<small class="text-muted" style="font-size:.65rem">${_esc(asset.duration)}</small>` : ''}
  </div>
</div>`;

    const card = col.querySelector('.mp-asset-card');
    card.addEventListener('mouseenter', () => { if (_focused !== asset) card.style.borderColor = '#6c757d'; });
    card.addEventListener('mouseleave', () => { if (_focused !== asset) card.style.borderColor = ''; });
    card.addEventListener('click', () => _focus(asset, card));
    card.addEventListener('dblclick', () => _selectAsset(asset));
    return col;
  }

  // ── Select & fetch ─────────────────────────────────────────────────────────

  async function _selectAsset(asset) {
    const modal = bootstrap.Modal.getInstance(document.getElementById(MODAL_ID));
    if (window.WamaAudioPlayer && WamaAudioPlayer.pauseAll) WamaAudioPlayer.pauseAll();

    // Désignation : rien à télécharger, l'appelant pointe l'asset par son chemin.
    if (_options.onPick) {
      _options.onPick(asset);
      modal.hide();
      return;
    }

    // Show loading state on card
    try {
      const resp = await fetch(asset.file_url);
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const blob = await resp.blob();

      // Build a proper File name with extension
      let name = asset.name;
      const urlExt = asset.file_url.split('?')[0].split('.').pop().toLowerCase();
      if (urlExt && urlExt.length <= 5 && !name.includes('.')) {
        name = name + '.' + urlExt;
      }
      const mime = asset.mime_type || blob.type || 'application/octet-stream';
      const file = new File([blob], name, { type: mime });

      if (_options.onSelect) {
        _options.onSelect(file, asset);
      }

      modal.hide();
    } catch (err) {
      const errorDiv = document.getElementById('mp-error');
      errorDiv.textContent  = `Impossible de charger le fichier : ${err.message}`;
      errorDiv.style.display = '';
    }
  }

  // ── Public API ─────────────────────────────────────────────────────────────

  function open(options) {
    _options = options || {};
    _ensureModal();
    // L'onglet d'ouverture : la nature préférée si l'appelant en dit une, sinon ce qu'il filtre.
    _activeType = _options.prefer || _options.type || 'all';
    _activeExact = !!_options.prefer;          // une nature préférée est une nature EXACTE
    _tabsShown = false;

    // Reset state
    document.getElementById('mp-tabs').innerHTML = '';
    document.getElementById('mp-search-input').value = '';
    document.getElementById('mp-grid').innerHTML      = '';
    document.getElementById('mp-spinner').style.display = '';
    document.getElementById('mp-empty').style.display   = 'none';
    document.getElementById('mp-error').style.display   = 'none';
    document.getElementById('mp-load-more').style.display = 'none';
    document.getElementById('mp-count').textContent = '';
    _clearPreview();

    const modal = new bootstrap.Modal(document.getElementById(MODAL_ID));
    modal.show();
    _load(1, true);
  }

  return { open };
})();

// ⚠ Une `const` de haut niveau n'est PAS une propriété de `window` (binding lexical global) :
// `window.MediaPicker` valait `undefined`. Trois consommateurs le lisaient ainsi et sortaient EN
// SILENCE — la tuile Médiathèque de la card v4 (`wama-input-slots.js`) et le bouton médiathèque de
// `wama-modes.js` n'ont jamais rien ouvert (mesuré au navigateur le 2026-09-28) ; le studio le
// savait et contournait sur place (`wama-studio.js:414`). Exposé ici, une fois, pour tous.
window.MediaPicker = MediaPicker;
