/**
 * Imager — modale « Paramètres de la génération », SCHÉMA-DRIVEN (P3 du portage).
 *
 * La modale est GÉNÉRÉE par la brique commune WamaParams.renderSettingsModal depuis le
 * schéma du DOMAINE (params.py = source unique typage/bornes/groupes) ; le pied vient du
 * gabarit serveur #imagerSettingsFooterTpl (_settings_modal_footer.html, délégation par
 * classes .save-settings-btn / .save-and-restart-btn).
 *
 * Remplace les DEUX modales hand-built (~400 lignes de HTML qui recopiaient le schéma)
 * et leurs remplisseurs champ par champ dans index.js.
 *
 * Exceptions app-spécifiques (déclarées en tête de params.py, PAS des champs du schéma) :
 *   • prompt        : entrée primaire de la card ; ici éditable, à deux états (WamaPromptEnrich)
 *   • width/height  : résolution à PRÉSETS par modèle (endpoint api_model_resolutions)
 *   • model         : options peuplées du catalogue (mêmes groupes que la card d'entrée)
 *   • image de référence : aperçu seul (le fichier se change depuis la card)
 */
(function () {
    'use strict';

    function CFG() { return window.IMAGER_CONFIG || { urls: {} }; }
    function CARD() { return window.IMAGER_CARD || { urls: {} }; }
    function isVideo(mode) { return ['txt2vid', 'img2vid'].indexOf(mode) !== -1; }

    function esc(s) {
        const d = document.createElement('div');
        d.textContent = s == null ? '' : String(s);
        return d.innerHTML;
    }

    // ── Pied commun : clone du gabarit serveur (remplace le footer par défaut) ──
    function graftCommonFooter(modal) {
        const tpl = document.getElementById('imagerSettingsFooterTpl');
        if (!tpl || !tpl.content.firstElementChild) return;
        const foot = tpl.content.firstElementChild.cloneNode(true);
        const old = modal.querySelector('.modal-footer');
        if (old) old.replaceWith(foot);
    }

    function groupBody(host, key) {
        return host.querySelector('[data-group="' + key + '"] .wama-param-group-body');
    }

    // ── Options du select modèle : mêmes groupes que la card d'entrée (catalogue) ──
    function fillModelChoices(host, domain, current) {
        const sel = host.querySelector('[name="model"]');
        const groups = (CARD().modelGroups || {})[domain] || [];
        if (!sel || !groups.length) return;
        sel.innerHTML = '<option value="auto">Auto (selon la VRAM et les entrées)</option>' +
            groups.map(function (g) {
                return '<optgroup label="' + esc(g.label) + '">' + g.models.map(function (m) {
                    return '<option value="' + esc(m.id) + '">' + esc(m.name) +
                        (m.vram ? ' — ' + esc(m.vram) : '') + '</option>';
                }).join('') + '</optgroup>';
            }).join('');
        sel.value = current || 'auto';
        if (!sel.value) sel.value = 'auto';
    }

    // ── Prompt (hors schéma : entrée primaire) — à deux états, dans le groupe « Modèle » ──
    function appendPromptZone(host, data, domain, id) {
        const body = groupBody(host, 'modele') || host;
        const wrap = document.createElement('div');
        wrap.className = 'wama-param mb-2';
        wrap.innerHTML =
            '<label class="form-label small mb-1" for="msPrompt' + id + '">' +
            '<i class="fas fa-pen-to-square me-1"></i>Prompt</label>' +
            '<textarea class="form-control form-control-sm bg-dark text-light border-secondary" ' +
            'id="msPrompt' + id + '" name="prompt" rows="3"></textarea>';
        body.insertBefore(wrap, body.firstChild);

        const el = wrap.querySelector('textarea');
        // La valeur affichée est l'état COURANT (enrichi si présent) ; la brique tient les deux.
        el.value = data.prompt_processed || data.prompt || '';
        if (window.WamaPromptEnrich) {
            WamaPromptEnrich.attach(el, {
                app: 'imager', domain: domain,
                endpoint: CFG().urls.enhancePrompt, csrf: CFG().csrfToken,
                original: data.prompt || '', processed: data.prompt_processed || '',
                keywords: data.prompt_keywords || [],
            });
        }
    }

    // ── Aperçu de l'image de référence (le fichier se change depuis la card) ──
    function appendReferencePreview(host, data) {
        if (!data.reference_image_url) return;
        const body = groupBody(host, 'modele') || host;
        const wrap = document.createElement('div');
        wrap.className = 'wama-param mb-2 d-flex align-items-center gap-2';
        wrap.innerHTML =
            '<img src="' + esc(data.reference_image_url) + '" alt="Référence" ' +
            'class="img-thumbnail bg-dark border-secondary" style="max-height:70px;">' +
            '<small class="text-muted">Image de référence</small>';
        body.appendChild(wrap);
    }

    // ── Résolution à PRÉSETS (image) — hors schéma, dans le groupe « Sortie » ──
    function appendResolutionZone(host, data) {
        const body = groupBody(host, 'sortie') || host;
        const wrap = document.createElement('div');
        wrap.className = 'wama-param mb-2';
        wrap.innerHTML =
            '<label class="form-label small mb-1"><i class="fas fa-expand me-1"></i>Résolution</label>' +
            '<select class="form-select form-select-sm" id="msResolution"></select>' +
            '<input type="hidden" name="width" value="' + esc(data.width) + '">' +
            '<input type="hidden" name="height" value="' + esc(data.height) + '">';
        body.appendChild(wrap);

        const sel = wrap.querySelector('select');
        const w = wrap.querySelector('[name="width"]');
        const h = wrap.querySelector('[name="height"]');
        const modelSel = host.querySelector('[name="model"]');

        function load() {
            const model = (modelSel && modelSel.value) || data.model || '';
            fetch(CFG().urls.modelResolutions + '?model=' + encodeURIComponent(model))
                .then(r => r.ok ? r.json() : Promise.reject(new Error('HTTP ' + r.status)))
                .then(function (res) {
                    const list = res.resolutions || [];
                    if (!list.length) { wrap.style.display = 'none'; return; }
                    wrap.style.display = '';
                    sel.innerHTML = list.map(function (r) {
                        return '<option value="' + r.width + 'x' + r.height + '">' +
                            esc(r.label || (r.width + '×' + r.height)) + '</option>';
                    }).join('');
                    const cur = data.width + 'x' + data.height;
                    if (list.some(r => (r.width + 'x' + r.height) === cur)) sel.value = cur;
                    apply();
                })
                .catch(function () { wrap.style.display = 'none'; });
        }
        function apply() {
            const parts = (sel.value || '').split('x');
            if (parts.length === 2) { w.value = parts[0]; h.value = parts[1]; }
        }
        sel.addEventListener('change', apply);
        if (modelSel) modelSel.addEventListener('change', load);
        load();
    }

    // ── Ouverture ──
    function openSettingsModal(id) {
        return fetch(WamaApp.getUrl(CFG().urls.getSettings, id))
            .then(r => r.ok ? r.json() : Promise.reject(new Error('HTTP ' + r.status)))
            .then(function (data) {
                const video = isVideo(data.generation_mode);
                const domain = video ? 'video' : 'image';
                const res = WamaParams.renderSettingsModal({
                    id: id,
                    title: (video ? 'Paramètres de la vidéo #' : 'Paramètres de la génération #') + id,
                    titleIcon: video ? 'fa-film' : 'fa-image',
                    schema: (video ? window.IMAGER_VIDEO_SCHEMA : window.IMAGER_IMAGE_SCHEMA) || [],
                    groups: (video ? window.IMAGER_VIDEO_GROUPS : window.IMAGER_IMAGE_GROUPS) || [],
                    values: data,
                    formClass: 'imager-settings-form',
                });
                const modal = res.modal, host = res.host;
                modal.dataset.generationId = id;
                modal.dataset.domain = domain;
                graftCommonFooter(modal);
                fillModelChoices(host, domain, data.model);
                appendPromptZone(host, data, domain, id);
                appendReferencePreview(host, data);
                if (!video) appendResolutionZone(host, data);
                new bootstrap.Modal(modal).show();
            })
            .catch(function () { WamaApp.toast('Impossible de charger les paramètres', 'error'); });
    }
    window.imagerOpenSettings = openSettingsModal;

    // ── Enregistrement (délégation par classes du pied commun) ──
    function saveSettings(modal, restart) {
        const id = modal.dataset.generationId;
        const host = modal.querySelector('.wama-modal-fields');
        const vals = WamaParams.read(host);

        const fd = new FormData();
        Object.keys(vals).forEach(function (k) { fd.append(k, vals[k]); });
        // Prompt à deux états : on poste l'ORIGINAL + l'état, la brique commune
        // `apply_prompt_state` arbitre côté serveur dans quel champ écrire.
        const promptEl = host.querySelector('textarea[name="prompt"]');
        if (promptEl && window.WamaPromptEnrich) {
            const ctrl = WamaPromptEnrich.get(promptEl);
            if (ctrl) {
                const snap = ctrl.snapshot();
                fd.set('prompt', snap.state === 'processed' ? snap.original : promptEl.value);
                fd.set('prompt_state', snap.state);
            }
        }
        // Résolution (hors schéma) : champs cachés de la zone d'app
        host.querySelectorAll('input[type="hidden"][name]').forEach(function (i) {
            fd.set(i.name, i.value);
        });
        fd.append('csrfmiddlewaretoken', CFG().csrfToken);

        return WamaApp.csrfFetch(WamaApp.getUrl(CFG().urls.saveSettings, id), CFG().csrfToken,
                                 { method: 'POST', body: fd })
            .then(r => r.json().catch(() => ({})))
            .then(function (data) {
                if (data.error) { WamaApp.toast(data.error, 'error'); return; }
                bootstrap.Modal.getInstance(modal).hide();
                WamaApp.toast('Paramètres enregistrés', 'success');
                if (restart) {
                    return WamaApp.csrfFetch(WamaApp.getUrl(CFG().urls.restart, id), CFG().csrfToken,
                                             { method: 'POST' })
                        .then(function () { if (window.imagerRefreshCard) imagerRefreshCard(id); });
                }
                if (window.imagerRefreshCard) imagerRefreshCard(id);
            })
            .catch(function () { WamaApp.toast("Erreur réseau à l'enregistrement", 'error'); });
    }

    document.addEventListener('click', function (e) {
        const save = e.target.closest('.save-settings-btn');
        const saveRestart = e.target.closest('.save-and-restart-btn');
        if (!save && !saveRestart) return;
        const modal = (save || saveRestart).closest('.modal');
        if (!modal || !modal.dataset.generationId) return;
        saveSettings(modal, !!saveRestart);
    });

    // Ouverture depuis les cards (les deux domaines partagent la même modale générée).
    // Délégation simple : les anciens handlers d'index.js ont été SUPPRIMÉS avec les
    // modales hand-built — plus de concurrence, donc plus de capture ni de stopImmediate.
    document.addEventListener('click', function (e) {
        const btn = e.target.closest('.settings-btn, .video-settings-btn');
        if (btn) openSettingsModal(btn.getAttribute('data-id'));
    });
})();
