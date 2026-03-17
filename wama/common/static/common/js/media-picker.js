/**
 * WAMA — MediaPicker
 * Composant réutilisable : ouvre une modale de sélection d'asset depuis la Médiathèque.
 *
 * Usage:
 *   MediaPicker.open({
 *     type:     'image',          // asset_type à filtrer
 *     onSelect: (file, asset) => { ... }  // callback avec File + meta
 *   });
 *
 * Prérequis: window.ML_LIST_URL doit être défini avant l'appel
 *   <script>const ML_LIST_URL = "{% url 'media_library:api_list' %}";</script>
 */
const MediaPicker = (() => {
  const MODAL_ID = 'wama-mediapicker-modal';
  let _options   = null;
  let _loading   = false;

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
        <div id="mp-grid"
             class="row row-cols-2 row-cols-sm-3 row-cols-md-4 row-cols-lg-6 g-2">
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
      <div class="modal-footer border-secondary py-2">
        <small class="text-muted me-auto" id="mp-count"></small>
        <button id="mp-load-more" class="btn btn-outline-secondary btn-sm" style="display:none">
          <i class="fas fa-chevron-down me-1"></i>Charger plus
        </button>
        <button type="button" class="btn btn-secondary btn-sm"
                data-bs-dismiss="modal">Annuler</button>
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
  }

  // ── Load assets ────────────────────────────────────────────────────────────

  async function _load(page, reset) {
    if (_loading) return;
    _loading = true;

    const q   = document.getElementById('mp-search-input').value.trim();
    const url = new URL(window.ML_LIST_URL || '/media-library/api/assets/', location.origin);
    url.searchParams.set('type', _options.type);
    url.searchParams.set('page', page);
    if (q) url.searchParams.set('q', q);

    const spinner  = document.getElementById('mp-spinner');
    const empty    = document.getElementById('mp-empty');
    const errorDiv = document.getElementById('mp-error');
    const grid     = document.getElementById('mp-grid');
    const loadMore = document.getElementById('mp-load-more');
    const count    = document.getElementById('mp-count');

    errorDiv.style.display = 'none';
    if (reset) {
      grid.innerHTML = '';
      spinner.style.display = '';
      empty.style.display   = 'none';
      loadMore.style.display = 'none';
    }

    try {
      const res  = await fetch(url);
      const data = await res.json();
      spinner.style.display = 'none';

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

  // ── Build a card ───────────────────────────────────────────────────────────

  function _buildCard(asset) {
    const isImage = ['image', 'avatar'].includes(asset.asset_type);
    const col = document.createElement('div');
    col.className = 'col';
    col.innerHTML = `
<div class="card bg-dark border-secondary h-100 mp-asset-card"
     style="cursor:pointer;transition:border-color .15s"
     title="${asset.name}">
  ${isImage
    ? `<img src="${asset.file_url}" class="card-img-top"
            style="height:80px;object-fit:cover;border-radius:4px 4px 0 0" alt="">`
    : `<div class="d-flex align-items-center justify-content-center bg-secondary bg-opacity-25"
              style="height:80px;border-radius:4px 4px 0 0">
         <i class="fas fa-file-audio fa-2x text-secondary"></i>
       </div>`
  }
  <div class="card-body p-1">
    <small class="text-light d-block text-truncate" style="font-size:.7rem"
           title="${asset.name}">${asset.name}</small>
    ${asset.duration ? `<small class="text-muted" style="font-size:.65rem">${asset.duration}</small>` : ''}
  </div>
</div>`;

    const card = col.querySelector('.mp-asset-card');
    card.addEventListener('mouseenter', () => card.style.borderColor = '#0dcaf0');
    card.addEventListener('mouseleave', () => card.style.borderColor = '');
    card.addEventListener('click', () => _selectAsset(asset));
    return col;
  }

  // ── Select & fetch ─────────────────────────────────────────────────────────

  async function _selectAsset(asset) {
    const modal = bootstrap.Modal.getInstance(document.getElementById(MODAL_ID));

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

    // Reset state
    document.getElementById('mp-search-input').value = '';
    document.getElementById('mp-grid').innerHTML      = '';
    document.getElementById('mp-spinner').style.display = '';
    document.getElementById('mp-empty').style.display   = 'none';
    document.getElementById('mp-error').style.display   = 'none';
    document.getElementById('mp-load-more').style.display = 'none';
    document.getElementById('mp-count').textContent = '';

    const modal = new bootstrap.Modal(document.getElementById(MODAL_ID));
    modal.show();
    _load(1, true);
  }

  return { open };
})();
