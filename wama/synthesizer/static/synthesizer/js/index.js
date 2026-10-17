// Attendre que le DOM soit chargé
document.addEventListener('DOMContentLoaded', function() {
    // Configuration - URLs définies côté serveur (injectées depuis le template)
    if (!window.WAMA_CONFIG) {
        console.error('WAMA_CONFIG not found. Make sure the template injects it.');
        WamaApp.toast('Erreur de configuration. Veuillez recharger la page.', 'warning');
        return;
    }

    const URLS = window.WAMA_CONFIG.urls;
    const csrfToken = window.WAMA_CONFIG.csrfToken;

    // Bouton de cycle commun ▶/⏹/↻ : clics délégués (start/restart→start, stop→stop). Les cards sont
    // re-rendues depuis le partial serveur au poll → l'icône suit le statut (pas besoin d'autoSync ici).
    if (window.WamaCycleButton) {
        WamaCycleButton.wire(document, {
            start: async (id, btn) => {
                // POST : lancer une synthèse CHANGE l'état — la vue l'exige depuis le 2026-09-22.
                // ▶ d'UN process (bande des process, `data-process`) : route `start/<id>/<process>/`.
                const process = WamaCycleButton.processOf(btn);
                try { await fetch(WamaCycleButton.processUrl(URLS.start + id + '/', process), { method: 'POST', headers: { 'X-CSRFToken': csrfToken } }); } catch (e) {}
                window.location.reload();
            },
            stop: async (id) => {
                try { await fetch(URLS.stop + id + '/', { method: 'POST', headers: { 'X-CSRFToken': csrfToken } }); } catch (e) {}
                window.location.reload();
            },
        });
    }

    // Le volet est GÉNÉRÉ du schéma (2026-10-11) : les curseurs vitesse/hauteur affichent eux-mêmes
    // leur valeur (renderer `range` commun) — plus de `#speed_value` / `#pitch_value` tenus ici.

    // « Réinitialiser » : les défauts du SCHÉMA (brique commune applyDefaults, comme le
    // transcriber), posés par l'applicateur de l'inspecteur — il émet `change`, donc les options
    // Higgs, les filtres voix/langue et l'appariement suivent. Remettait vitesse et hauteur seules.
    const resetBtn = document.getElementById('resetOptions');
    if (resetBtn && window.WamaParams) {
        resetBtn.addEventListener('click', () => {
            const vals = WamaParams.applyDefaults(document.getElementById('synthPanelFields'),
                                                  window.SYNTH_PARAMS_SCHEMA || [], 'panel');
            if (window._synthInspector && window._synthInspector.apply) window._synthInspector.apply(vals);
        });
    }

    // Le bandeau « ce modèle ne supporte que l'anglais » a été retiré le 2026-08-28 avec les
    // trois moteurs qu'il visait (REMOVAL_LEDGER R32) : son jeu déclencheur était devenu VIDE,
    // donc les trois bandeaux étaient devenus inatteignables.
    // ⚠ Le BESOIN reste entier et il est GÉNÉRAL — tout moteur peut ne pas couvrir une langue
    // du select, ce n'est le cas particulier d'aucun. Mesuré le 28/08 : bark ne gère pas 3 des
    // 15 langues proposées, higgs-audio 6, kokoro 8, coqui-xtts 0. La liste écrite en dur se
    // trompait donc DEUX fois (3 moteurs cités, 3 autres lacunaires ignorés).
    // ✅ REMPLACÉE le 29/08, et pas par un bandeau : `WamaModelCaps.langFilter` agit SUR le
    // select de langue (init dans index.html), dérivé des `languages`/`fallback_languages`
    // déclarées au catalogue. Le champ dit lui-même ce qu'il accepte.

    // === Higgs Audio model toggle ===
    function toggleHiggsOptions(modelValue) {
        const higgsOptions = document.getElementById('higgsOptions');
        const languageGroup = document.getElementById('languageGroup');
        const voicePresetGroup = document.getElementById('voicePresetGroup');
        // Suffixe TOLÉRÉ (même règle qu'engine_for_model côté serveur) : les valeurs du
        // select sont des clés catalogue ENTIÈRES depuis le 01/09 (`synthesizer:higgs-audio`)
        // — la comparaison au nom nu ne matchait plus jamais, les options Higgs avaient
        // silencieusement disparu (défaut latent relevé le 02/09).
        const isHiggs = /(^|:)higgs-audio$/.test(modelValue || '');

        if (higgsOptions) higgsOptions.style.display = isHiggs ? 'block' : 'none';
        // Higgs handles language internally, hide language/voice preset selectors
        if (languageGroup) languageGroup.style.display = isHiggs ? 'none' : '';
        if (voicePresetGroup) voicePresetGroup.style.display = isHiggs ? 'none' : '';
    }

    // Le curseur d'INTENTION n'est plus basculé ici (2026-10-11) : son `show_if` (tts_model = auto),
    // déclaré au schéma, le montre et le cache dans le volet généré comme dans les modales.

    const ttsModelSelect = document.getElementById('tts_model');
    if (ttsModelSelect) {
        ttsModelSelect.addEventListener('change', (e) => {
            toggleHiggsOptions(e.target.value);
        });
        // Initialize on page load
        toggleHiggsOptions(ttsModelSelect.value);
    }

    const multiSpeakerCheckbox = document.getElementById('multi_speaker');
    if (multiSpeakerCheckbox) {
        multiSpeakerCheckbox.addEventListener('change', (e) => {
            const sceneDescGroup = document.getElementById('sceneDescGroup');
            if (sceneDescGroup) sceneDescGroup.style.display = e.target.checked ? 'block' : 'none';
        });
    }

    // Les réglages du VOLET, tels que la synthèse les reçoit — UNE lecture pour le bouton
    // « Ajouter », l'aperçu et l'import (2026-09-28 : trois copies de la même liste). Lecteur
    // gardé : un champ absent donne son défaut, jamais une exception dans un `async`.
    function appendPanelSettings(fd) {
        const v = (id, dft) => { const el = document.getElementById(id); return el ? el.value : dft; };
        fd.append('tts_model', v('tts_model', ''));   // vide → défaut du serveur (DEFAULT_TTS_MODEL)
        fd.append('quality_intent', v('quality_intent', '50'));
        fd.append('language', v('language', 'fr'));
        fd.append('voice_preset', v('voice_preset', 'default'));
        fd.append('speed', v('speed', '1.0'));
        fd.append('pitch', v('pitch', '1.0'));
        fd.append('output_format', v('output_format', '') || 'original');
        fd.append('output_quality', v('output_quality', '') || 'balanced');
        appendHiggsFields(fd);
    }

    // Helper: append Higgs-specific fields to FormData
    function appendHiggsFields(formData) {
        const multiSpeaker = document.getElementById('multi_speaker');
        if (multiSpeaker) {
            formData.append('multi_speaker', multiSpeaker.checked ? '1' : '0');
        }
        const sceneDesc = document.getElementById('scene_description');
        if (sceneDesc && sceneDesc.value.trim()) {
            formData.append('scene_description', sceneDesc.value.trim());
        }
    }

    // Zone de dépôt : clic, survol, drop récursif, sélecteur de fichiers et sélecteur de dossier
    // sont câblés par WamaImport (instancié plus bas, APRÈS `_batchImport` dont il dépend —
    // portage 2026-09-07). Ne reste ici que l'écouteur du canal FileManager (vakata), qui n'est
    // pas un `drop` natif. Le bouton « parcourir » (#browseBtn) n'est rendu par aucun gabarit.
    // ⚠ La branche « drop depuis le FileManager » (`getFileManagerData` → `importToApp`) est
    // RETIRÉE, même verdict que le describer : `application/x-wama-file` n'est émis nulle part,
    // et un glisser jstree ne produit aucun `drop` natif — il arrive par `filemanager:imported`
    // ci-dessous, émis par le canal GLOBAL de filemanager.js (import serveur).
    const dropZone = document.getElementById('dropZoneSynthesizer');

    if (dropZone) {
        // FileManager import result (vakata.dnd path — native drop event never fires for filemanager drags)
        dropZone.addEventListener('filemanager:imported', (e) => {
            const result = e.detail;
            if (result.is_batch && result.tasks && result.tasks.length > 0) {
                e.preventDefault(); // Prevent filemanager from reloading
                _serverBatchDirect(result);
            }
            // Non-batch: let filemanager reload the page (defaultPrevented stays false)
        });
    }

    // ⚙ item : le CYCLE complet (rendre du schéma → greffer le pied → afficher → lire →
    // enregistrer → enchaîner) est la brique commune `WamaParams.settingsModal` (portage
    // 2026-09-24 — la modale statique `#settingsModal` du gabarit, `saveSettings` et sa liste de
    // champs écrite à la main vivaient ici). Les VALEURS viennent des data-* du gear (brique
    // `card_gear`), lues par LE lecteur unique `WamaInspector.gearValues` ; les spécificités de
    // l'app restent des HOOKS : options des selects clonées du volet compose (`optionsResolver`),
    // champs Higgs ajoutés au POST (`collect`). Le bouton de la médiathèque (écouter, ajouter,
    // choisir une voix) n'est PLUS greffé ici (`decorate`, retiré le 2026-09-30) : `WamaParams` le
    // pose sur tout champ `options_source: 'voices'`. ⚠ « Sauvegarder et démarrer » POSTe le démarrage : l'ancien
    // cycle le faisait en GET, refusé par la vue (`@require_POST` depuis le 22/09).
    function _panelOptionsResolver(param) {
        const src = document.getElementById((param.dom_id && param.dom_id.panel) || param.name);
        if (!src || src.tagName !== 'SELECT') return null;
        return Array.from(src.options).map(function (o) {
            const grp = o.parentElement && o.parentElement.tagName === 'OPTGROUP'
                ? o.parentElement.label + ' — ' : '';
            return { value: o.value, label: grp + o.textContent.trim() };
        });
    }

    function openSettingsModal(id, btn) {
        const schema = window.SYNTH_PARAMS_SCHEMA || [];
        const card = (btn && btn.closest('.wama-card')) || btn;
        const values = Object.assign(
            { quality_intent: '50', speed: '1.0', pitch: '1.0' },
            WamaInspector.gearValues(card, schema.map(function (p) { return p.name; })));
        return WamaParams.settingsModal({
            id: id,
            title: 'Paramètres de synthèse',
            titleIcon: 'fa-cog',
            schema: schema,
            values: values,
            formClass: 'synthesis-settings-form',
            footerTplId: 'synthSettingsFooterTpl',
            saveUrl: URLS.updateSettings.replace('/0/', '/' + id + '/'),
            csrf: csrfToken,
            optionsResolver: _panelOptionsResolver,
            collect: function (fd) { appendHiggsFields(fd); },
            onSaved: async function (sid, restart) {
                if (restart) {
                    try {
                        const r = await fetch(URLS.start + sid + '/',
                                              { method: 'POST', headers: { 'X-CSRFToken': csrfToken } });
                        if (!r.ok) {
                            const data = await r.json().catch(function () { return {}; });
                            WamaApp.toast('Paramètres sauvegardés mais erreur au démarrage: ' + (data.error || 'Échec'), 'error');
                        }
                    } catch (error) { WamaApp.toast('Erreur: ' + error.message, 'error'); }
                }
                location.reload();
            },
        });
    }

    // === Unified card button delegation ===
    // Uses document-level event delegation so that cards replaced in-place by the
    // polling loop (no full page reload) automatically get working buttons.
    document.addEventListener('click', async e => {
        // .start-btn — start or retry a synthesis
        const startBtn = e.target.closest('.start-btn');
        if (startBtn) {
            const id = startBtn.dataset.id;
            try {
                const r = await fetch(URLS.start + id + '/', { method: 'GET', headers: { 'X-CSRFToken': csrfToken } });
                if (r.ok) {
                    location.reload();
                } else {
                    const d = await r.json();
                    WamaApp.toast('Erreur: ' + (d.error || 'Échec du démarrage'), 'error');
                }
            } catch (err) { WamaApp.toast('Erreur: ' + err.message, 'error'); }
            return;
        }

        // (Aperçu du texte source : geste COMMUN `.preview-media-link` de la card, face Entrée de
        // l'aperçu unifié — la branche locale `.preview-text-btn` est retirée le 2026-10-12.)

        // Duplication, suppression et ⚙ paramètres : brique commune queue-actions.js. Les trois
        // branches locales ont été retirées (⚙ et 🗑 le 2026-08-23) — les garder à côté de la
        // délégation commune ferait partir CHAQUE clic deux fois.
    });

    // ⚙ item — ouvreur DÉCLARÉ à la brique commune (queue-actions.js) ; le cycle est celui de
    // `WamaParams.settingsModal` (openSettingsModal ci-dessus).
    WamaQueueActions.onSettings(function (id, settingsBtn) { openSettingsModal(id, settingsBtn); });

    // Bulk actions — ▶ Démarrer tout et 🗑 Tout effacer : brique `queue-actions.js` (2026-10-17,
    // URLs passées au partial). « Démarrer tout » vaut ici « appliquer à tout » : le CORPS porte
    // les options du volet (la vue `start_all` lit `request.POST`, et la voix de référence est un
    // fichier — d'où un FormData, que la brique envoie tel quel en multipart).
    WamaQueueActions.onQueueStartBody(function () {
        const formData = new FormData();
        formData.append('tts_model', document.getElementById('tts_model').value);
        formData.append('quality_intent', (document.getElementById('quality_intent') || { value: '50' }).value);
        formData.append('language', document.getElementById('language').value);
        formData.append('voice_preset', document.getElementById('voice_preset').value);
        formData.append('speed', document.getElementById('speed').value);
        formData.append('pitch', document.getElementById('pitch').value);
        formData.append('output_format', (document.getElementById('output_format') || {}).value || 'original');
        formData.append('output_quality', (document.getElementById('output_quality') || {}).value || 'balanced');
        appendHiggsFields(formData);
        return formData;
    });

    const downloadAllBtn = document.getElementById('downloadAllBtn');
    if (downloadAllBtn) {
        downloadAllBtn.addEventListener('click', () => {
            window.location.href = URLS.downloadAll;
        });
    }

    // Console toggle
    const toggleConsoleBtn = document.getElementById('toggleConsole');
    const consoleContainer = document.getElementById('consoleContainer');

    if (toggleConsoleBtn && consoleContainer) {
        toggleConsoleBtn.addEventListener('click', () => {
            if (consoleContainer.style.display === 'none') {
                consoleContainer.style.display = 'block';
                updateConsole();
            } else {
                consoleContainer.style.display = 'none';
            }
        });
    }

    // Suivi des cards en cours — boucle COMMUNE `WamaApp.Poller`, une par card (2026-10-13 : c'était
    // un `setInterval` local qui relisait les cards du DOM toutes les 2 s, l'une après l'autre,
    // sans attendre la fin du tour précédent et en onglet caché). Chaque geste de lancement
    // RECHARGE la page (▶, lot, modale) : les cards en cours se lisent donc au chargement.
    // Lu sur `data-status` : la classe `.processing` a été retirée des cards le 2026-09-18
    // (le CSS lit l'attribut) — vu par le geste `synthesizer.worker_death`, 2026-09-24.
    const RUNNING_CARDS = '.synthesis-card[data-status="RUNNING"], .synthesis-card[data-status="AWAITING_RESOURCES"]';
    const cardPoller = new WamaApp.Poller({
        urlTemplate: (id) => URLS.progress + id + '/',
        interval: 2000,
        maxFails: Infinity,
        onError: (id, error) => console.error('Progress update error:', error),
        onData: async (id, data) => {
            const card = document.querySelector(`.synthesis-card[data-id="${id}"]`);
            if (!card) { cardPoller.stop(id); return; }

            const progressBar = card.querySelector('.wama-progress-fill');
            const progressText = card.querySelector('.progress-text');
            if (progressBar) {
                progressBar.style.width = data.progress + '%';
                progressBar.classList.add('active');
            }
            if (progressText) progressText.textContent = data.progress + '%';
            if (window.WamaEta) WamaEta.render(card.querySelector('.wama-eta'), WamaEta.update(id, { progress: data.progress, status: data.status, seedSeconds: data.estimated_seconds, modelLoaded: false }));

            // Update card in-place on completion — no full page reload
            // (a full reload interrupts audio preview and reloads the slow FileManager)
            if (data.status === 'SUCCESS' || data.status === 'FAILURE') {
                cardPoller.stop(id);
                // Card redemandée par la brique commune (WamaApp.fetchCard, portage
                // 2026-09-22 — la copie en ligne du fetch + parse vivait ici).
                const newCard = await WamaApp.fetchCard(URLS.cardHtml, id);
                if (newCard) card.replaceWith(newCard);
            }
        },
    });
    document.querySelectorAll(RUNNING_CARDS).forEach((card) => cardPoller.start(card.dataset.id));

    // (Barre globale + ETA : brique commune wama-global-progress.js. La copie locale, neutralisée
    // par un `return` et pourtant rappelée toutes les 2 s, est retirée le 2026-10-13.)

    // Soumission via le bouton primaire de la card d'entrée COMMUNE : brique commune
    // `WamaApp.addToQueue` (portage 2026-10-01) — bouton « Envoi… », refus dit, toast. Le texte
    // à synthétiser est la consigne de la card ; les réglages du volet (`appendPanelSettings`,
    // Higgs compris) partent avec lui, le titre aussi. La card est rendue côté serveur :
    // rechargement.
    const submitTextBtn = document.getElementById('submitTextBtn');
    if (submitTextBtn && window.WamaApp && WamaApp.addToQueue) {
        WamaApp.addToQueue({
            url:       URLS.uploadText,
            csrfToken: csrfToken,
            button:    submitTextBtn,
            prompt:    { inputId: 'textContent', field: 'text_content' },
            extraFields: function (fd) {
                const titleEl = document.getElementById('textTitle');
                fd.append('title', titleEl ? titleEl.value.trim() : '');
                appendPanelSettings(fd);
            },
            validate: function (fd) {
                return fd.get('text_content') ? '' : 'Veuillez entrer du texte à synthétiser.';
            },
            successMessage: function (data) {
                return "Texte ajouté à la file d'attente — " + (data.word_count || 0) + ' mots.';
            },
            onAdded: function () {
                const titleEl = document.getElementById('textTitle');
                if (titleEl) titleEl.value = '';
                location.reload();
            },
        });
    }

    // ── Card « Nouvelle synthèse » : le texte, et rien que le texte ────────────────────────
    // ⚠ Les MIROIRS voix et vitesse vivaient ici (recopie du volet droit, synchronisation
    // bidirectionnelle) — RETIRÉS le 2026-09-27 avec les contrôles qu'ils servaient
    // (`_new_item_extra.html`, constat de Fabien) : la card annonçait elle-même que ces
    // réglages sont à droite, et un miroir sans source propre est un doublon qui se répare
    // (il a fallu le recâbler sur `wama:options-filled` quand le select est devenu généré).
    // Le pliage/dépliage reste la brique COMMUNE `wama-new-item-card.js`.
    (function initQuickCompose() {
        const textContent = document.getElementById('textContent');
        if (!textContent) return;
        // Entrée (sans Maj) ne saute plus vers la voix rapide : elle n'existe plus. Le texte
        // est l'entrée, la touche ne doit pas y insérer un saut de ligne involontaire —
        // on donne la main au bouton d'aperçu, geste suivant le plus probable.
        textContent.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                const preview = document.getElementById('previewTextBtn');
                if (preview) preview.focus();
            }
        });
    })();

    // ── Aperçu de la voix — alignée sur le COMMUN le 2026-09-28 ────────────────────────────
    // Le serveur rend les premiers mots par LA chaîne de la synthèse (`utils/speech_render`) et
    // renvoie un aperçu de la forme COMMUNE (`url`, `mime_type`, `peaks`) ; la page ne fait que :
    //   • réserver le canal de parole (`WamaApp.Speech.claim`) — un 2ᵉ clic ABANDONNE la requête
    //     en vol, et une réponse périmée n'est jamais rendue ;
    //   • rendre par `WamaMediaPreview.renderInline` — lecteur `WamaAudioPlayer`, onde
    //     dessinée des pics serveur, exclusivité (page, onglets, voix) comprise ;
    //   • lancer la lecture (`WamaAudioPlayer.play`), geste demandé par le clic.
    // La légende du lecteur (`name`) dit le moteur RÉEL — « auto » résolu — et le nombre de mots.
    // Ce qui vivait ici : flux SSE, WAV base64 recollés EN-TÊTES COMPRIS, `<audio>` nu.
    const previewTextBtn = document.getElementById('previewTextBtn');
    const PREVIEW_PLAYER = 'synthVoicePreview';

    if (previewTextBtn) {
        previewTextBtn.addEventListener('click', async () => {
            const textContent = document.getElementById('textContent').value.trim();
            if (!textContent) {
                WamaApp.toast('Veuillez entrer du texte pour générer un aperçu.', 'warning');
                return;
            }
            const host = document.getElementById('previewAudioContainer');
            const turn = WamaApp.Speech.claim();
            const label = previewTextBtn.innerHTML;
            previewTextBtn.disabled = true;
            previewTextBtn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Génération...';
            try {
                const formData = new FormData();
                formData.append('text_content', textContent);
                appendPanelSettings(formData);
                const response = await fetch(URLS.voicePreview, {
                    method: 'POST', headers: { 'X-CSRFToken': csrfToken },
                    body: formData, signal: turn.signal,
                });
                const data = await response.json();
                if (!turn.valid()) return;
                if (!response.ok || !data.url) {
                    WamaApp.toast(data.error || "Échec de l'aperçu", data.busy ? 'warning' : 'error');
                    return;
                }
                host.dataset.playerId = PREVIEW_PLAYER;
                host.style.display = 'block';
                WamaMediaPreview.renderInline(host, data, true);
                WamaAudioPlayer.play(PREVIEW_PLAYER);
            } catch (error) {
                // Abandon par un 2ᵉ clic ou une autre lecture : rien à signaler.
                if (error && error.name === 'AbortError') return;
                WamaApp.toast('Erreur: ' + error.message, 'error');
            } finally {
                previewTextBtn.disabled = false;
                previewTextBtn.innerHTML = label;
            }
        });
    }

    // Helper functions
    function escHtml(s) {
        return String(s)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;')
            .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }

    // ── Batch detection ───────────────────────────────────────────────────────
    // Detects if a file is a pipe-separated batch file before uploading.
    // For text-based formats (txt/md/csv): client-side analysis.
    // For binary formats (pdf/docx): server-side via batch_preview endpoint.

    // ── Import batch COMMUN (brique batch-import.js, barre common/batch_detect_bar) ──
    // Le flux server_path (drop FileManager) passe en création directe confirmée
    // (la brique ne gère pas server_path).
    const _batchImport = (typeof WamaBatchImport !== 'undefined') ? WamaBatchImport({
        batchExtensions: ['txt', 'md', 'csv'],
        batchPreviewUrl: URLS.batchPreview,
        batchCreateUrl: URLS.batchCreate,
        csrfToken: csrfToken,
        formDataBuilder: function (fd) {
            const v = (id, dft) => { const el = document.getElementById(id); return el ? el.value : dft; };
            fd.append('tts_model', v('tts_model', ''));   // vide → défaut du serveur (DEFAULT_TTS_MODEL)
            fd.append('quality_intent', v('quality_intent', '50'));
            fd.append('language', v('language', 'fr'));
            fd.append('voice_preset', v('voice_preset', 'default'));
            fd.append('speed', v('speed', '1.0'));
            fd.append('pitch', v('pitch', '1.0'));
        },
        afterCreate: function (data, autoStart) {
            if (autoStart && data && data.batch_id) {
                fetch(URLS.batchStart + data.batch_id + '/start/', { method: 'POST', headers: { 'X-CSRFToken': csrfToken } })
                    .finally(() => location.reload());
            } else {
                location.reload();
            }
        },
    }) : null;

    // ── Voie d'import : brique commune WamaImport (wama-import.js) — portage 2026-09-07 ──
    //
    // 4ᵉ app EN PLACE à l'adopter (plan « fichiers d'entrée », MEDIA_STORAGE_TIERING §8 ;
    // inventaire ROUTE §Portage F2). Ce qui vivait ici — `handleFilesWithDetect` (lot testé sur
    // CHAQUE fichier), `handleFiles` (upload séquentiel, consolidation `ids`, reload),
    // `uploadFile` (les réglages du volet postés avec le fichier) — est le contrat de la brique.
    // L'app ne DÉCLARE que :
    //   • `batchScope:'each'` : chaque fichier déposé est testé comme descripteur de lot, les
    //                           lots reconnus sortent de l'envoi (évolution 6 de la brique, écrite
    //                           POUR cette politique — la brique ne connaissait que « si seul ») ;
    //   • `extraFields`     : les réglages du volet (mêmes ids et mêmes défauts que le
    //                           `formDataBuilder` du lot ci-dessus) + les champs Higgs.
    // PRÉSERVÉ par les défauts : `id` lu en repli, reload après consolidation, rien si aucun id.
    // ⚠ L'ancien `uploadFile` lisait `#tts_model` et consorts SANS garde : un id absent levait
    // dans un `async` non attendu — import mort, sans un mot. Le lecteur `v(id, défaut)` du lot
    // est réutilisé : même valeur quand le champ existe, un défaut sinon.
    if (typeof window.WamaImport === 'function') {
        window._import = WamaImport({
            uploadUrl:        URLS.upload,
            consolidateUrl:   URLS.consolidate,
            consolidateField: 'ids',
            csrfToken:        csrfToken,
            dropZoneId:       'dropZoneSynthesizer',
            fileInputId:      'fileInput',
            folderInputId:    'synthFolderInput',
            batch:            _batchImport,
            batchScope:       'each',
            extraFields:      appendPanelSettings,
        });
    } else {
        // Défaut le plus silencieux qui soit (une zone de dépôt que rien n'écoute) → on le DIT.
        WamaApp.toast("Voie d'import non chargée (wama-import.js) — dépôt impossible", 'error');
        console.error('[Synthesizer] WamaImport absent : wama-import.js non chargé par le gabarit');
    }

    async function _serverBatchDirect(result) {
        // Batch depuis un fichier DÉJÀ sur le serveur (FileManager).
        const n = (result.tasks || []).length;
        if (!confirm('Fichier batch détecté (' + n + ' synthèses). Créer le batch avec les réglages du volet ?')) return;
        const fd = new FormData();
        fd.append('server_path', result.server_path || '');
        const v = (id, dft) => { const el = document.getElementById(id); return el ? el.value : dft; };
        fd.append('tts_model', v('tts_model', ''));   // vide → défaut du serveur (DEFAULT_TTS_MODEL)
        fd.append('quality_intent', v('quality_intent', '50'));
        fd.append('language', v('language', 'fr'));
        fd.append('voice_preset', v('voice_preset', 'default'));
        fd.append('speed', v('speed', '1.0'));
        fd.append('pitch', v('pitch', '1.0'));
        try {
            const r = await fetch(URLS.batchCreate, { method: 'POST', headers: { 'X-CSRFToken': csrfToken }, body: fd });
            const d = await r.json();
            if (r.ok) location.reload();
            else WamaApp.toast('Erreur batch : ' + (d.error || r.status), 'error');
        } catch (err) { WamaApp.toast('Erreur réseau : ' + err.message, 'error'); }
    }
    // ─────────────────────────────────────────────────────────────────────────

    async function updateConsole() {
        try {
            const response = await fetch(URLS.console);
            const data = await response.json();

            const output = document.getElementById('consoleOutput');
            if (output && data.output) {
                output.innerHTML = data.output.map(line => `<div>${line}</div>`).join('');
                output.scrollTop = output.scrollHeight;
            }
        } catch (error) {
            console.error('Console update error:', error);
        }
    }

    // ⚠ « Custom Voice Management » RETIRÉ le 2026-09-30 : la modale « Ajouter une voix »,
    // l'enregistrement au micro et l'insertion de l'option vivaient ici. Un champ
    // `options_source: 'voices'` reçoit désormais d'office le bouton de la fenêtre commune de la
    // médiathèque (`WamaParams`, `LIBRARY_SOURCES`) : écouter, AJOUTER (fichier ou micro) puis
    // choisir — au volet, dans la modale ⚙ et dans l'avatarizer, sans code d'app.

}); // Fin DOMContentLoaded
