/**
 * Reader — OCR Document
 * Gestion de la file d'attente, upload, polling, actions par item.
 */
(function () {
    'use strict';

    const cfg = window.READER_APP || {};
    const urls = cfg.urls || {};
    const csrf = cfg.csrfToken || '';

    // ─── Helpers ─────────────────────────────────────────────────────────────

    // Délégués à WamaApp (brique commune wama-app-base.js) ; repli local si non chargé.
    function csrfFetch(url, opts = {}) {
        if (window.WamaApp) return WamaApp.csrfFetch(url, csrf, opts);
        opts.headers = Object.assign({ 'X-CSRFToken': csrf }, opts.headers || {});
        return fetch(url, opts);
    }

    function urlFor(key, id) {
        const base = urls[key] || '';
        if (id === undefined) return base;
        return window.WamaApp ? WamaApp.getUrl(base, id) : base.replace('/0/', `/${id}/`);
    }

    function formatDate(iso) {
        try {
            const d = new Date(iso);
            return d.toLocaleString('fr-FR', { dateStyle: 'short', timeStyle: 'short' });
        } catch (e) { return ''; }
    }

    function statusBadge(status) {
        const m = {
            PENDING: '<span class="badge bg-secondary">En attente</span>',
            RUNNING: '<span class="badge bg-warning text-dark"><i class="fas fa-spinner fa-spin me-1"></i>En cours</span>',
            SUCCESS: '<span class="badge bg-success">Terminé</span>',
            FAILURE: '<span class="badge bg-danger">Échec</span>',
            DONE:    '<span class="badge bg-success">Terminé</span>',   // tolérance ancien vocabulaire
            ERROR:   '<span class="badge bg-danger">Échec</span>',
        };
        return m[status] || `<span class="badge bg-secondary">${status}</span>`;
    }

    function backendLabel(b) {
        const m = { auto: 'Auto', olmocr: 'olmOCR-2', doctr: 'docTR' };
        return m[b] || b;
    }

    function modeLabel(m) {
        const l = { auto: 'Auto', printed: 'Imprimé', handwritten: 'Manuscrit' };
        return l[m] || m;
    }

    // ─── Card rendering ───────────────────────────────────────────────────────

    // buildCard() SUPPRIMÉE 2026-07-06 : le markup vient du SERVEUR (reader:card_html)
    // — la copie JS aurait divergé de la card v2 (chips/point d'état). CARD_DESIGN §3.

    function escapeHtml(str) {
        return String(str)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;')
            .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }

    async function upsertCard(item) {
        // Card v2 : re-rendue SERVEUR (reader:card_html) puis remplacée EN PLACE —
        // le JS ne reconstruit plus le markup (CARD_DESIGN §3 ; l'ex-buildCard() était
        // une 2ᵉ source qui aurait divergé des chips/du point d'état serveur).
        let card = document.querySelector(`.reader-card[data-id="${item.id}"]`);
        // Redemandée par la brique commune (WamaApp.fetchCard, portage 2026-09-22) ; null en cas
        // de réseau → on garde la card existante, le poll réessaiera.
        const fresh = await WamaApp.fetchCard(urlFor('cardHtml'), item.id);
        if (fresh) {
            if (card) card.replaceWith(fresh);
            else {
                const empty = document.getElementById('emptyState');
                if (empty) empty.remove();
                document.getElementById('queueContainer').prepend(fresh);
            }
            card = fresh;
        }
        if (!card) return null;
        if (window.WamaEta) WamaEta.render(card.querySelector('.wama-eta'), WamaEta.update(item.id, { progress: item.progress, status: item.status, seedSeconds: item.estimated_seconds, modelLoaded: false }));
        bindCardActions(card, item);
        updateDownloadAllBtn();
        return card;
    }

    // Le RETRAIT de card appartient désormais à la brique commune (queue-actions.js) ; il ne
    // reste ici que la bascule d'état vide, appelée APRÈS elle (2026-08-23).
    function insertEmptyStateIfNeeded() {
        if (document.querySelectorAll('.reader-card').length > 0) return;
        const container = document.getElementById('queueContainer');
        if (!container || container.querySelector('#emptyState')) return;
        container.innerHTML = `<div id="emptyState" class="text-center text-secondary py-5">
            <i class="fas fa-inbox fa-3x mb-3 opacity-50"></i>
            <p>File d'attente vide — importez des documents pour commencer</p>
        </div>`;
    }

    // ─── Card actions ─────────────────────────────────────────────────────────

    function bindCardActions(card, item) {
        // ⚙ et 🗑 ne passent PLUS par ce dispatch : tous deux sont délégués par la brique commune
        // queue-actions.js (portage 2026-08-23). Les garder ici en plus ferait partir chaque clic
        // deux fois — le bind est par card, la brique est sur le document.
        card.querySelectorAll('[data-action]').forEach(btn => {
            btn.addEventListener('click', () => {
                const action = btn.dataset.action;
                if (action === 'start' || action === 'restart') startItem(item.id);
                if (action === 'expand') expandPreview(item.id);
            });
        });
        // (double-clic → visionneuse commune, délégation de `media-preview.js` — rien par card.)
        if (typeof window.initMediaPreview === 'function') window.initMediaPreview();
    }

    // ─── Polling ──────────────────────────────────────────────────────────────

    // Polling : brique commune WamaApp.Poller (résilient : retries ; jamais deux requêtes en vol,
    // pause en onglet caché). Sa copie locale « de repli si WamaApp absent » est retirée le
    // 2026-10-13 : la brique est montée par `base.html`, le repli ne servait jamais — et c'est
    // son dictionnaire, vide, que « Tout effacer » parcourait : rien n'était arrêté.
    const poller = new WamaApp.Poller({
        urlTemplate: urls.progress,
        onData: function (id, item) {
            upsertCard(item);
            if (item.status !== 'RUNNING' && item.status !== 'PENDING') {
                poller.stop(id);
            }
        },
    });

    function startPolling(id) { poller.start(id); }

    function stopPolling(id) { poller.stop(id); }

    // ─── Item actions ─────────────────────────────────────────────────────────

    // ⏹ Stop : arrête l'OCR (endpoint commun) → item relançable (↻ via autoSync sur data-status).
    async function stopItem(id) {
        const card = document.querySelector(`.reader-card[data-id="${id}"]`);
        try {
            const r = await csrfFetch(urlFor('stop', id), { method: 'POST' });
            const data = await r.json().catch(() => ({}));
            if (card && data.status) card.dataset.status = data.status;
            stopPolling(id);
        } catch (e) {
            console.error('[Reader] stop error:', e);
        }
    }

    // `process` : le ▶ d'UN process de la bande (2026-10-13, pipeline) → lancement borné (route
    // `start/<id>/<process>/`, adresse composée par la brique commune) ; vide pour le ▶ de la
    // card, qui lance tout ce qui est dû.
    async function startItem(id, process) {
        const card = document.querySelector(`.reader-card[data-id="${id}"]`);
        // Relance pendant le traitement : stopper d'abord (évite le 409 « déjà en cours »).
        if (card && (card.dataset.elementStatus || card.dataset.status || '').toUpperCase() === 'RUNNING') {
            await stopItem(id);
        }
        if (card) {
            card.dataset.status = 'RUNNING';
            card.dataset.elementStatus = 'RUNNING';
        }
        try {
            await csrfFetch(WamaCycleButton.processUrl(urlFor('start', id), process), { method: 'POST' });
            startPolling(id);
        } catch (e) {
            console.error('[Reader] start error:', e);
        }
    }

    // 🗑 RÉSIDU de suppression — la brique commune (queue-actions.js) porte la confirmation, le
    // POST et le retrait de la card. Portage 2026-08-23.
    WamaQueueActions.onDeleted(function (id) {
        stopPolling(id);
        insertEmptyStateIfNeeded();
    });

    // ⚙ item — ouvreur DÉCLARÉ à la brique commune (queue-actions.js).
    WamaQueueActions.onSettings(function (id, btn) { openItemSettings(btn); });

    // Duplication : brique commune queue-actions.js (bouton [data-duplicate-url]),
    // qui pose aussi le focus de la card dupliquée avant le reload.

    // ─── Settings modal ───────────────────────────────────────────────────────
    // ⚙ item : le CYCLE complet (rendre du schéma → greffer le pied → afficher → lire →
    // enregistrer → enchaîner) est la brique commune `WamaParams.settingsModal` (portage
    // 2026-09-24 — `getOrCreateSettingsModal` + `openItemSettings` + `saveItemSettings` le
    // recopiaient ici, avec des ids `rSettings_*` et une liste de champs écrite à la main qui
    // OUBLIAIT `output_format`, pourtant au schéma). Les VALEURS viennent des data-* du gear
    // (brique `card_gear`), lues par LE lecteur unique `WamaInspector.gearValues` ; le POST est
    // un FormData que la vue lit par `read_settings_payload` (JSON ou formulaire, coercé au
    // schéma). La réponse est la card à jour (`_item_to_dict`) : `upsertCard` la reflète.
    // (Réglages LUS par le moteur — mode, langue : DÉCLARÉS au schéma, `cap_from` « reads » de
    // `reader/params.py`, câblés par `WamaParams` dans le volet, la modale d'élément et celle du
    // lot. Le câblage à la main `wireEngineParams`, ici depuis le 29/09, est retiré le
    // 2026-10-13 : il ne grisait plus rien depuis les clés entières du 07/10.)

    function openItemSettings(btn) {
        const schema = window.WAMA_READER_SCHEMA || [];
        const card = (btn && btn.closest('.wama-card')) || btn;
        const id = btn.dataset.id;
        return WamaParams.settingsModal({
            id: id,
            title: 'Paramètres OCR',
            titleIcon: 'fa-cog',
            schema: schema,
            values: WamaInspector.gearValues(card, schema.map(function (p) { return p.name; })),
            formClass: 'reader-settings-form',
            footerTplId: 'readerSettingsFooterTpl',
            saveUrl: urlFor('updateSettings', id),
            csrf: csrf,
            onSaved: function (_id, _restart, resp) { if (resp && resp.id) upsertCard(resp); },
        });
    }

    // Double-clic sur une preview de card → la visionneuse COMMUNE (`media-preview.js`), sur
    // la face Sortie avec sa bascule Entrée | Sortie. Le reader l'interceptait (`wama:card-expand`
    // + `openFullTextModal` sur `reader:text`) pour ouvrir le seul texte OCR, sans faces ;
    // retiré le 2026-10-12 (REMOVAL_LEDGER R118) : la face Sortie sert déjà le texte intégral.

    function expandPreview(id) {
        const preview = document.querySelector(
            `.reader-card[data-id="${id}"] .reader-preview`
        );
        if (!preview) return;
        if (preview.style.maxHeight === 'none') {
            preview.style.maxHeight = '80px';
        } else {
            preview.style.maxHeight = 'none';
        }
    }

    // ─── Upload ───────────────────────────────────────────────────────────────

    // ─── Voie d'import : brique commune WamaImport (wama-import.js) — portage 2026-09-07 ──
    //
    // 6ᵉ app EN PLACE à l'adopter (plan « fichiers d'entrée », MEDIA_STORAGE_TIERING §8 ;
    // inventaire ROUTE §Portage F2 : « multi-upload + réponse liste »). Ce qui vivait ici —
    // `uploadFiles` (N fichiers en UNE requête, champ `files`), `uploadFilesWithBatch`, la
    // zone de dépôt (`initDropZone`) — est le contrat de la brique depuis ses évolutions 1 et 2
    // (réponse `created[]`, `multiple:true`), écrites POUR le reader et utilisées ici pour la
    // 1ʳᵉ fois par une app en place. L'app ne DÉCLARE que :
    //   • `multiple:true`   : une seule requête, le SERVEUR groupe (`{created:[…], multi}`) —
    //                         donc pas de `consolidateUrl` ;
    //   • `extraFields`     : moteur, mode, format, langue du volet ;
    //   • `afterImport`     : SA politique — `multi` → reload (la structure de lot est rendue
    //                         serveur), sinon `upsertCard` par élément créé + progression globale.
    // La garde « un clic sur un lien de la zone n'ouvre pas le sélecteur » (gabarit de lot),
    // que seul le reader avait, est passée DANS la brique : les 5 apps déjà portées en héritent.
    function initImport() {
        if (typeof window.WamaImport !== 'function') {
            // Défaut le plus silencieux qui soit (une zone de dépôt que rien n'écoute) → on le DIT.
            WamaApp.toast("Voie d'import non chargée (wama-import.js) — dépôt impossible", 'error');
            console.error('[Reader] WamaImport absent : wama-import.js non chargé par le gabarit');
            return;
        }
        window._import = WamaImport({
            uploadUrl:    urls.upload,
            csrfToken:    csrf,
            dropZoneId:   'dropZone',
            fileInputId:  'fileInput',
            folderInputId:'readerFolderInput',
            batch:        window._batchImport,
            multiple:     true,
            extraFields:  function (fd) {
                fd.append('backend',       document.getElementById('backendSelect')?.value || 'auto');
                fd.append('mode',          document.getElementById('modeSelect')?.value || 'auto');
                fd.append('output_format', document.getElementById('outputFormatSelect')?.value || 'txt');
                fd.append('language',      document.getElementById('languageInput')?.value.trim() || '');
                // Curseur rapide/qualité (chantier C) : réglage d'app, persisté par le serveur.
                fd.append('quality_intent', document.getElementById('qualityIntent')?.value || '');
                // Modèle de langage et interrupteurs des process optionnels (pipeline, 2026-10-13),
                // lus par la brique sur le volet rendu du schéma.
                const panel = document.getElementById('readerPanelParams');
                const vals = (window.WamaParams && panel) ? WamaParams.read(panel) : {};
                ['llm_model', 'format_markdown', 'generate_analysis'].forEach(function (name) {
                    if (name in vals) fd.append(name, vals[name]);
                });
            },
            afterImport:  function (ids, reponses) {
                const data = reponses[0] || {};
                if (data.multi) { window.location.reload(); return; }
                (data.created || []).forEach(item => upsertCard(item));
            },
        });
    }

    // ─── Global actions ───────────────────────────────────────────────────────

    function updateDownloadAllBtn() {
        const btn = document.getElementById('reader-download-all-btn');
        if (!btn) return;
        const hasSuccess = document.querySelector('.reader-card[data-status="SUCCESS"], .reader-card[data-status="DONE"]') !== null;
        btn.disabled = !hasSuccess;
    }

    function initGlobalButtons() {
        // ▶ Démarrer tout et 🗑 Tout effacer : brique `queue-actions.js` (2026-10-17, URLs passées
        // au partial). Le ▶ déclare sa suite : suivre les cards lancées au lieu de recharger.
        WamaQueueActions.onQueueStarted(() => {
            document.querySelectorAll('.reader-card').forEach(card => {
                const st = card.dataset.status;
                if (st === 'RUNNING' || st === 'PENDING') {
                    startPolling(parseInt(card.dataset.id));
                }
            });
        });

        // ⬇ « Télécharger tout » : PLUS de handler ici (2026-08-30) — le bouton est rendu par
        // la brique commune _download_button (menu des formats déclarés, navigation par <a>).
        // Un window.location au clic détournerait l'OUVERTURE du menu. Ne reste côté app que
        // le bascule d'état updateDownloadAllBtn() ci-dessus (le bouton naît disabled).

        document.getElementById('resetOptions')?.addEventListener('click', () => {
            const fields = [
                { id: 'backendSelect', key: 'backendSelect' },
                { id: 'modeSelect',    key: 'modeSelect' },
                { id: 'languageInput', key: 'languageInput' },
            ];
            fields.forEach(({ id, key }) => {
                const el = document.getElementById(id);
                if (el) {
                    if (el.tagName === 'SELECT') {
                        el.selectedIndex = 0;
                    } else {
                        el.value = '';
                    }
                }
                localStorage.removeItem(`reader_setting_${key}`);
            });
        });
    }

    // (Barre globale + ETA : brique commune wama-global-progress.js. La copie locale, neutralisée
    // par un `return` et pourtant rappelée toutes les 2 s et après chaque geste, est retirée le
    // 2026-10-13 avec ses appels.)

    // ─── Batch group URL helper ───────────────────────────────────────────────

    function urlForBatch(key, id) {
        const base = urls[key] || '';
        return id !== undefined ? base.replace('/0/', `/${id}/`) : base;
    }

    // ─── Batch group actions ──────────────────────────────────────────────────

    // Suite du ▶ de LOT : suivre les éléments lancés sans recharger, et déplier le lot.
    function followBatchStart(data, batchId) {
        (data.started || []).forEach(id => startPolling(id));
        const batchEl = document.querySelector(`.batch-group[data-batch-id="${batchId}"]`);
        if (batchEl) {
            const collapseEl = batchEl.querySelector('.collapse');
            if (collapseEl) bootstrap.Collapse.getOrCreateInstance(collapseEl).show();
        }
    }

    // « Enregistrer et lancer » de la modale de lot : le seul lancement de lot que l'app POSTe
    // elle-même — celui du bouton ▶ appartient à la brique commune (`bindBatchGroupActions`).
    async function startBatch(batchId) {
        try {
            const r = await csrfFetch(urlForBatch('batchStart', batchId), { method: 'POST' });
            followBatchStart(await r.json(), batchId);
        } catch (e) {
            console.error('[Reader] batch start error:', e);
        }
    }

    // ─── Batch settings modal ─────────────────────────────────────────────────

    let _batchSettingsModal = null;

    function initBatchSettingsModal() {
        const el = document.getElementById('batchSettingsModal');
        if (!el) return;
        _batchSettingsModal = new bootstrap.Modal(el);

        const saveBtn = document.getElementById('saveBatchSettingsBtn');
        if (saveBtn) saveBtn.addEventListener('click', () => saveBatchSettings(false));
        const saveStartBtn = document.getElementById('saveBatchSettingsAndStartBtn');
        if (saveStartBtn) saveStartBtn.addEventListener('click', () => saveBatchSettings(true));
    }

    function openBatchSettingsModal(btn) {
        if (!_batchSettingsModal) return;
        const id = btn.dataset.batchId;
        document.getElementById('batchSettingsBatchLabel').textContent = '#' + id;
        document.getElementById('batchSettingsBatchId').value = id;
        // Presets = réglages de la 1re fille (la card mère commune _batch_card.html ne porte
        // plus de data-backend/mode/language — ils vivent sur les cards, source serveur unique),
        // lus par LE lecteur unique des data-* du gear (`WamaInspector.gearValues`) sur les noms
        // du SCHÉMA. Les trois champs écrits ici à la main ignoraient le format de sortie et tout
        // réglage ajouté (le modèle de langage et les process optionnels, 2026-10-13).
        const firstCfg = document.querySelector(`#batchItems${id} [data-action="settings"]`);
        const host = document.getElementById('readerBatchParams');
        if (window.WamaParams && host && firstCfg) {
            const schema = window.WAMA_READER_SCHEMA || [];
            WamaParams.apply(host, WamaInspector.gearValues(firstCfg.closest('.wama-card') || firstCfg,
                                                            schema.map(function (p) { return p.name; })));
        }
        _batchSettingsModal.show();
    }

    async function saveBatchSettings(andStart) {
        const batchId = document.getElementById('batchSettingsBatchId').value;
        // Les valeurs de la modale, lues par la brique sur le schéma rendu (`WamaParams.read`).
        const host = document.getElementById('readerBatchParams');
        const payload = (window.WamaParams && host) ? WamaParams.read(host) : {};
        try {
            const r = await csrfFetch(urlForBatch('batchUpdate', batchId), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            });
            const data = await r.json();
            if (!r.ok || !data.success) { WamaApp.toast(data.error || 'Erreur sauvegarde', 'error'); return; }
            _batchSettingsModal.hide();
            if (andStart) {
                await startBatch(batchId);
            } else {
                window.location.reload();
            }
        } catch { WamaApp.toast('Erreur réseau', 'error'); }
    }

    // ▶ ⧉ 🗑 ⚙ de LOT : la brique commune (`queue-actions.js`) tient le clic, la confirmation, le
    // POST et le rechargement ; l'app DÉCLARE seulement la suite du ▶ et l'ouvreur du ⚙.
    // ⚠ Jusqu'au 2026-10-13 ces boutons étaient AUSSI branchés ici (handlers d'avril, d'avant la
    // brique) : chaque clic partait DEUX fois — un ⧉ créait deux copies du lot, un ▶ lançait le lot
    // deux fois (relevé par le geste nocturne `reader.batch_actions`, rouge les 12 et 13/10).
    function bindBatchGroupActions() {
        if (!window.WamaQueueActions) return;
        WamaQueueActions.onBatchStarted(followBatchStart);
        WamaQueueActions.onBatchSettings((id, btn) => openBatchSettingsModal(btn));
    }

    // ─── Init ─────────────────────────────────────────────────────────────────

    // Inspecteur contextuel commun : clic card/batch → bandeau « Réglages de l'élément #N » + valeurs
    // de l'élément dans le volet + sauvegarde routée. Câblage générique dérivé du schéma WamaParams.
    // Actions inspecteur = CLONE + PROXY vers les vrais boutons (brique WamaInspector.cloneActions).
    // Approche UNIQUE inter-apps (CARD_DESIGN §10) : aucune hypothèse sur les fonctions de l'app.
    function _renderItemActions(host, card) {
        WamaInspector.cloneActions(host, card.querySelector('.btn-group-actions'),
            '<i class="fas fa-crosshairs text-info"></i> Actions — élément #' + card.dataset.id);
    }

    function initInspector() {
        const q  = document.getElementById('queueContainer');
        const ph = document.getElementById('readerPanelParams');
        if (!q || !ph || !window.WamaInspector || !WamaInspector.initFromSchema) return;
        const readPanel = () => (window.WamaParams ? WamaParams.read(ph) : {});
        window._readerInspector = WamaInspector.initFromSchema({
            queueContainer: q,
            cardSelector:   '.reader-card',
            batchSelector:  '.batch-group',
            panelContainer: ph,
            schema:         window.WAMA_READER_SCHEMA || [],
            itemLabel:  (id) => "l'élément #" + id,
            batchLabel: (id) => "le batch #" + id + " (tous les éléments)",
            saveItem: async (id) => {
                const r = await csrfFetch(urlFor('updateSettings', id), {
                    method: 'POST', headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(readPanel()),
                });
                if (r && r.ok) upsertCard(await r.json());
            },
            saveBatch: async (bid) => {
                const r = await csrfFetch(urlForBatch('batchUpdate', bid), {
                    method: 'POST', headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(readPanel()),
                });
                if (r && r.ok) window.location.reload();
            },
            renderItemActions: _renderItemActions,
            // Actions d'un LOT : brique commune (résout la card mère depuis son IDENTIFIANT).
            renderBatchActions: function (host, batchId) { WamaInspector.cloneBatchActions(host, batchId); },
        });
    }

    function initCycleButton() {
        if (!window.WamaCycleButton) return;
        const q = document.getElementById('queueContainer');
        if (!q) return;
        // Câblage délégué (start/restart→startItem, stop→stopItem) + auto-sync de l'icône sur data-status.
        // Le 3ᵉ argument de `start` : le process dont on a cliqué le ▶ dans la bande (2026-10-13).
        WamaCycleButton.wire(q, {
            start: (id, btn, process) => startItem(id, process),
            stop: (id) => stopItem(id),
        });
        WamaCycleButton.autoSync({ container: q, cardSelector: '.reader-card' });
    }

    function init() {
        initImport();
        initGlobalButtons();
        initBatchSettingsModal();
        initInspector();
        initCycleButton();
        bindBatchGroupActions();
        updateDownloadAllBtn();

        // (Aperçu du fichier source : geste COMMUN `.preview-media-link` de la card, écouté par
        // `media-preview.js` — l'écoute locale de `.source-preview-btn` est retirée le 2026-10-12.)

        // Persist settings
        ['backendSelect', 'modeSelect', 'languageInput'].forEach(id => {
            const el = document.getElementById(id);
            if (!el) return;
            const key = `reader_setting_${id}`;
            const saved = localStorage.getItem(key);
            if (saved) el.value = saved;
            el.addEventListener('change', () => localStorage.setItem(key, el.value));
        });

        // Bind existing cards and start polling for RUNNING + PENDING items
        // (PENDING items may have tasks already queued — catch the RUNNING transition).
        // Lu sur l'état de l'ÉLÉMENT (`data-element-status`, 2026-10-13) : `data-status` est l'état
        // MONTRÉ, déduit des process — une card terminée dont un optionnel reste à compléter s'y
        // montre « en attente ».
        document.querySelectorAll('.reader-card').forEach(card => {
            const id = parseInt(card.dataset.id);
            const status = (card.dataset.elementStatus || card.dataset.status || '').toUpperCase();
            if (status === 'RUNNING' || status === 'PENDING') {
                startPolling(id);
            }
            // Bind action buttons. ⚙ et 🗑 sont délégués par la brique commune (queue-actions.js),
            // comme dans `bindCardActions` depuis le 2026-08-23 — ce second câblage, resté ici,
            // ouvrait la modale de la card DEUX FOIS : deux modales de même id, et le ⚙ d'un
            // process ouvert ensuite remplissait le select de l'ANCIENNE (catalogue vide dans la
            // nouvelle, mesuré le 2026-10-13). La branche 🗑 appelait `deleteItem`, qui n'existe plus.
            card.querySelectorAll('[data-action]').forEach(btn => {
                btn.addEventListener('click', () => {
                    const action = btn.dataset.action;
                    if (action === 'start' || action === 'restart') startItem(id);
                    if (action === 'expand') expandPreview(id);
                });
            });
        });
        // Cards (re)rendues : la brique commune décore les nouvelles previews (motif du parc —
        // anonymizer, enhancer font pareil). Le double-clic lui-même est écouté en délégation.
        if (typeof window.initMediaPreview === 'function') window.initMediaPreview();
    }

    // uploadFilesWithBatch / initDropZone SUPPRIMÉS (2026-09-07) : lot testé sur un fichier
    // seul, sélecteur, drop récursif et sélecteur de dossier sont câblés par WamaImport (initImport).

    // Handle files imported via filemanager "Envoyer vers Reader" context menu
    document.addEventListener('wama:fileimported', e => {
        const result = e.detail;
        if (!result || result.app !== 'reader') return;
        if (result.id && !result.batch) {
            // Single-file import with known ID: add card dynamically.
            // `handled` désamorce le repli générique de wama-app-base.js (rechargement) :
            // insérer la card est strictement meilleur, on ne veut pas les deux.
            result.handled = true;
            fetch(urlFor('progress', result.id))
                .then(r => r.json())
                .then(item => { upsertCard(item); })
                .catch(() => {});
        }
        // Import GROUPÉ (`batch` : fichiers reçus ensemble = un LOT côté serveur) ou sans id → on
        // laisse le repli commun recharger la page. ⚠ Les envois groupés portent des `id` depuis
        // le 14/09 (`WamaSendTo.envoyer`) : les insérer un par un les montrait sans leur card de lot.
    });

    document.addEventListener('DOMContentLoaded', init);

})();
