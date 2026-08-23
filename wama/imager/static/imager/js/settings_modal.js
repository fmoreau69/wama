/**
 * Imager — modale « Paramètres de la génération », SCHÉMA-DRIVEN (P3 du portage).
 *
 * ORCHESTRATION COMMUNE : WamaParams.settingsModal fait tout le cycle (charger → rendre →
 * greffer le pied → afficher → lire → enregistrer → enchaîner). Ce fichier ne déclare plus
 * que les SPÉCIFICITÉS de l'imager, via les hooks decorate/collect/onSaved.
 * Schéma du DOMAINE : params.py (source unique typage/bornes/groupes).
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

    function esc(s) {
        const d = document.createElement('div');
        d.textContent = s == null ? '' : String(s);
        return d.innerHTML;
    }

    function CFG() { return window.IMAGER_CONFIG || { urls: {} }; }
    function CARD() { return window.IMAGER_CARD || { urls: {} }; }
    function isVideo(mode) { return ['txt2vid', 'img2vid'].indexOf(mode) !== -1; }



    function groupBody(host, key) {
        return host.querySelector('[data-group="' + key + '"] .wama-param-group-body');
    }

    // ── Options du select modèle : mêmes groupes que la card d'entrée (catalogue) ──
    function fillModelChoices(host, domain, current) {
        // WamaParams.render génère les champs avec `data-param` + `id`, PAS avec `name`
        // (mesuré au navigateur le 2026-08-06 : nameAttr=null, dataParam='model'). Chercher
        // `[name="model"]` seul renvoyait null → sortie silencieuse ligne suivante → select
        // modèle VIDE sur les deux surfaces schéma-driven. On accepte les deux écritures.
        const sel = host.querySelector('[name="model"], [data-param="model"]');
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
        // Meme piege que fillModelChoices ci-dessus : la surface generee par WamaParams n'a pas
        // de `name` — `[name="model"]` seul renvoyait null, donc le listener `change` ne se
        // posait jamais et changer de modele ne rafraichissait pas la liste des resolutions.
        const modelSel = host.querySelector('[name="model"], [data-param="model"]');

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

    // ── Ouverture : l'app ne déclare que ses spécificités ──
    function openSettingsModal(id) {
        return fetch(WamaApp.getUrl(CFG().urls.getSettings, id))
            .then(r => r.ok ? r.json() : Promise.reject(new Error('HTTP ' + r.status)))
            .then(function (data) {
                const video = isVideo(data.generation_mode);
                const domain = video ? 'video' : 'image';
                return WamaParams.settingsModal({
                    id: id,
                    title: (video ? 'Paramètres de la vidéo #' : 'Paramètres de la génération #') + id,
                    titleIcon: video ? 'fa-film' : 'fa-image',
                    schema: (video ? window.IMAGER_VIDEO_SCHEMA : window.IMAGER_IMAGE_SCHEMA) || [],
                    groups: (video ? window.IMAGER_VIDEO_GROUPS : window.IMAGER_IMAGE_GROUPS) || [],
                    values: data,                       // déjà chargées (domaine à déterminer)
                    formClass: 'imager-settings-form',
                    footerTplId: 'imagerSettingsFooterTpl',
                    saveUrl: WamaApp.getUrl(CFG().urls.saveSettings, id),
                    csrf: CFG().csrfToken,
                    decorate: function (host, d) {
                        fillModelChoices(host, domain, d.model);
                        appendPromptZone(host, d, domain, id);
                        appendReferencePreview(host, d);
                        if (!video) appendResolutionZone(host, d);
                    },
                    collect: function (fd, host) {
                        // Prompt à deux états : poster l'ORIGINAL + l'état (apply_prompt_state arbitre).
                        const p = host.querySelector('textarea[name="prompt"]');
                        if (p && window.WamaPromptEnrich) {
                            const ctrl = WamaPromptEnrich.get(p);
                            if (ctrl) {
                                const snap = ctrl.snapshot();
                                fd.set('prompt', snap.state === 'processed' ? snap.original : p.value);
                                fd.set('prompt_state', snap.state);
                            }
                        }
                        // Résolution (hors schéma) : champs cachés de la zone d'app.
                        host.querySelectorAll('input[type="hidden"][name]').forEach(function (i) {
                            fd.set(i.name, i.value);
                        });
                    },
                    onSaved: function (gid, restart) {
                        if (restart) {
                            WamaApp.csrfFetch(WamaApp.getUrl(CFG().urls.restart, gid), CFG().csrfToken,
                                              { method: 'POST' })
                                .then(function () { if (window.imagerRefreshCard) imagerRefreshCard(gid); });
                        } else if (window.imagerRefreshCard) {
                            imagerRefreshCard(gid);
                        }
                    },
                });
            })
            .catch(function () { WamaApp.toast('Impossible de charger les paramètres', 'error'); });
    }
    window.imagerOpenSettings = openSettingsModal;
    // Exposé pour le VOLET DROIT (index.js:renderRightPanel) : les deux surfaces peuplent leur
    // select modèle depuis les MÊMES groupes de catalogue. Exporter plutôt que recopier — sans
    // ça le volet rendait un <select> VIDE (mesuré au navigateur le 2026-08-06).
    window.imagerFillModelChoices = fillModelChoices;

    // Ouverture depuis les cards : ouvreur DÉCLARÉ à la brique commune (queue-actions.js).
    // Les DEUX domaines partagent déjà la même modale générée — et depuis le 2026-08-23 ils
    // partagent aussi la même GRAPHIE de bouton : `.video-settings-btn` a disparu du gabarit,
    // le domaine se lit sur la card (`data-domain`) et, ici, sur `generation_mode`. Une classe
    // par domaine ne portait aucune information que la donnée ne portait déjà.
    WamaQueueActions.onSettings(function (id) { openSettingsModal(id); });
})();
