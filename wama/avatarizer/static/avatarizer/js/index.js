/**
 * WAMA Avatarizer - Frontend JS
 * Gère : sélection avatar, upload fichiers, création/démarrage/polling des jobs
 */

"use strict";

(function () {
    const cfg = window.AVATARIZER_CONFIG;
    const csrf = cfg.csrfToken;

    // -----------------------------------------------------------------------
    // State
    // -----------------------------------------------------------------------
    // L'état des ENTRÉES n'est plus tenu ici (2026-09-29, card v4) : il se LIT dans les inputs
    // de port — un fichier joint ou une DÉSIGNATION (médiathèque, arbre). Tenir une copie en
    // variable (`audioFile`, `selectedAvatarSource`…) laissait l'écran et le formulaire diverger
    // dès qu'un geste commun (✕ de la card, désignation) passait par l'input sans elle.
    let activePollers        = {};    // {job_id: intervalId}

    // -----------------------------------------------------------------------
    // DOM Helpers
    // -----------------------------------------------------------------------
    const $  = (sel, ctx = document) => ctx.querySelector(sel);
    const $$ = (sel, ctx = document) => ctx.querySelectorAll(sel);

    // Le mode n'existe plus côté client (2026-08-28) : le serveur le DÉRIVE des entrées
    // (audio/URL → standalone, sinon texte → pipeline TTS→avatar — précédent imager,
    // MODES_QUEUE_UX §2bis). La card poste ce qu'elle a, le moteur décide.

    // -----------------------------------------------------------------------
    // Word counter
    // -----------------------------------------------------------------------
    const textArea = $('#text_content');
    const wordCountEl = $('#word-count');
    if (textArea) {
        textArea.addEventListener('input', () => {
            const words = textArea.value.trim().split(/\s+/).filter(Boolean).length;
            wordCountEl.textContent = words;
        });
    }

    // -----------------------------------------------------------------------
    // bbox_shift slider
    // -----------------------------------------------------------------------
    const bboxSlider = $('#bbox_shift');
    const bboxVal    = $('#bbox_shift_val');
    if (bboxSlider) {
        bboxSlider.addEventListener('input', () => {
            bboxVal.textContent = bboxSlider.value;
        });
    }

    // Le couple de modes rapide/qualité est MORT (2026-08-03) : l'Amélioration
    // CodeFormer (#use_enhancer) est le SEUL contrôle de qualité, toujours visible.

    // -----------------------------------------------------------------------
    // Ports de la card v4 : l'AUDIO (port principal, ids historiques) et l'IMAGE d'avatar
    // -----------------------------------------------------------------------
    // La galerie propre à l'app et l'import d'avatar du volet droit sont RETIRÉS (2026-09-29) :
    // l'avatar est le port `work_image`, dont la médiathèque s'ouvre sur l'onglet Avatar. Son
    // input se lit sur le pane du port (`data-port-input`) — l'id est dérivé par la card, on ne
    // le recompose pas ici.
    const avatarPane  = $('#avatarizerNewCard [data-port-pane="work_image"]');
    const avatarInput = avatarPane ? document.getElementById(avatarPane.dataset.portInput) : null;
    const AVATAR_TYPES = ['image/jpeg', 'image/png', 'image/webp'];
    // L'avatar 3D (2026-09-30) : le port `work_object3d`, qu'ouvre le moteur TalkingHead. Il
    // n'existe que si ce modèle est au catalogue (les ports viennent des modèles) — d'où `null`.
    // L'avatar est une photo OU un objet 3D : les deux ports alimentent `avatar_upload`.
    const avatar3dPane  = $('#avatarizerNewCard [data-port-pane="work_object3d"]');
    const avatar3dInput = avatar3dPane ? document.getElementById(avatar3dPane.dataset.portInput) : null;
    const avatarInputs  = [avatarInput, avatar3dInput].filter(Boolean);

    /** Le port d'avatar rempli (photo ou 3D), ou null. */
    function chosenAvatar() {
        return avatarInputs.find(hasEntry) || null;
    }

    /** Le port porte-t-il une entrée (fichier joint ou désignation) ? */
    function hasEntry(input) {
        return !!(input && ((input.files && input.files.length) || WamaApp.designationOf(input)));
    }

    /** Vide un port — même geste que le ✕ de la card, qui rafraîchit sa face « fichiers ». */
    function clearPort(input) {
        if (!input) return;
        input.value = '';
        WamaApp.clearDesignation(input);
        input.dispatchEvent(new Event('change', { bubbles: true }));
    }

    /** Remplir un port d'avatar VIDE l'autre : c'est l'un OU l'autre, jamais les deux. */
    function keepOnlyAvatar(input) {
        avatarInputs.filter(other => other !== input && hasEntry(other)).forEach(clearPort);
    }

    if (avatarInput) {
        avatarInput.addEventListener('change', () => {
            const f = avatarInput.files && avatarInput.files[0];
            if (f && !AVATAR_TYPES.includes(f.type)) {
                WamaApp.toast('Format non supporté. Utilisez JPG, PNG ou WebP.', 'error');
                clearPort(avatarInput);
                return;
            }
            if (hasEntry(avatarInput)) keepOnlyAvatar(avatarInput);
            updateGenerateButton();
        });
    }
    if (avatar3dInput) {
        avatar3dInput.addEventListener('change', () => {
            const f = avatar3dInput.files && avatar3dInput.files[0];
            if (f && !/\.glb$/i.test(f.name)) {
                WamaApp.toast('Avatar 3D : un fichier .glb riggé est attendu.', 'error');
                clearPort(avatar3dInput);
                return;
            }
            if (hasEntry(avatar3dInput)) keepOnlyAvatar(avatar3dInput);
            updateGenerateButton();
        });
    }

    // -----------------------------------------------------------------------
    // Audio upload (Standalone)
    // -----------------------------------------------------------------------
    const audioDropzone = $('#audio-dropzone');
    const audioInput    = $('#audio_input');
    // Zones rendues par la card commune _new_item_card : data-wama-app posé ici (le partial ne
    // le rend pas) — requis par le quick-drop filemanager (getAppFromDropZone → dataset.wamaApp).
    ['audio-dropzone'].forEach(id => {
        const z = document.getElementById(id);
        if (z && !z.dataset.wamaApp) z.dataset.wamaApp = 'avatarizer';
    });
    if (audioInput) audioInput.addEventListener('change', updateGenerateButton);

    // -----------------------------------------------------------------------
    // Zone prompt : drop d'un fichier texte → extraction serveur (TXT/MD/PDF/DOCX/CSV)
    // -----------------------------------------------------------------------
    // Réintroduit le 2026-08-28 avec le pipeline dérivé (retiré 2026-07-11) : la vue
    // `extract_text` était restée vivante et orpheline — on la re-câble, on ne la récrit pas.
    const promptZone = $('#text-prompt-zone');
    if (promptZone && textArea) {
        ['dragover', 'dragenter'].forEach(ev =>
            promptZone.addEventListener(ev, e => { e.preventDefault(); }));
        promptZone.addEventListener('drop', async (e) => {
            const file = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0];
            if (!file) return;   // drop interne (filemanager…) : laisser les handlers globaux
            e.preventDefault();
            e.stopPropagation();
            const fd = new FormData();
            fd.append('file', file);
            try {
                const resp = await fetch(cfg.urls.extractText, {
                    method: 'POST', headers: { 'X-CSRFToken': csrf }, body: fd,
                });
                const data = await resp.json();
                if (!resp.ok) throw new Error(data.error || 'Extraction impossible');
                textArea.value = (data.text || '').trim();
                textArea.dispatchEvent(new Event('input'));   // compteur + bouton Générer
            } catch (err) {
                WamaApp.toast('Extraction du texte : ' + err.message, 'error');
            }
        });
    }

    // (`handleAudioFile` puis `retenirAudio` — l'état de la card — sont RETIRÉS : l'audio
    // attaché est dans `audio_input`, que la card v4 affiche et que `WamaApp.addToQueue` poste.)

    // -----------------------------------------------------------------------
    // Update "Generate" button state
    // -----------------------------------------------------------------------
    function updateGenerateButton() {
        const btn = $('#btn-generate');
        if (!btn) return;

        // Une ENTRÉE (audio, URL ou texte à dire) + un avatar : le serveur dérive le mode.
        const urlInputEl = $('#avatarizerUrlInput');
        const hasUrl = !!(urlInputEl && urlInputEl.value.trim());
        const hasText = !!(textArea && textArea.value.trim());
        btn.disabled = !((hasEntry(audioInput) || hasUrl || hasText) && chosenAvatar());
    }

    if (textArea) {
        textArea.addEventListener('input', updateGenerateButton);
    }

    // Import par URL (brique _new_item_card show_url → WAMA_INGEST) : l'URL vaut fichier audio
    const avatarizerUrlInput = $('#avatarizerUrlInput');
    const avatarizerUrlSubmit = $('#avatarizerUrlSubmit');
    if (avatarizerUrlInput) avatarizerUrlInput.addEventListener('input', updateGenerateButton);
    if (avatarizerUrlSubmit) avatarizerUrlSubmit.addEventListener('click', (e) => {
        e.preventDefault();
        const btn = $('#btn-generate');
        if (btn && !btn.disabled) btn.click();
        else WamaApp.toast("URL prise en compte — choisissez aussi l'avatar (onglet Image ou Objet 3D).", 'info');
    });
    // État INITIAL du bouton (2026-09-29) : il n'était calculé qu'au premier geste, donc actif au
    // chargement sans entrée ni avatar — un clic postait une création vouée au refus.
    updateGenerateButton();

    // -----------------------------------------------------------------------
    // Bouton primaire → AJOUTE à la file, ne lance rien
    // -----------------------------------------------------------------------
    // Règle des deux temps (CARD_DESIGN §11.11 Étape 3, point 3 — « on ajoute, on règle, puis
    // on lance ») appliquée au portage v4, 2026-09-29 : ce bouton enchaînait `createJob()` puis
    // `startJob()`. L'élément naît en attente ; le ▶ de sa card (bouton de cycle commun) le lance.
    // Brique commune `WamaApp.addToQueue` (portage 2026-10-01) : bouton « Envoi… », texte à
    // dire, audio JOINT ou DÉSIGNÉ (médiathèque, arbre — pointé, jamais re-téléversé), URL de la
    // voix en repli, refus dit, toast. Pas de `mode` posté : le serveur le dérive (audio/URL
    // priment, sinon texte).
    const btnGenerate = $('#btn-generate');
    if (btnGenerate && window.WamaApp && WamaApp.addToQueue) {
        WamaApp.addToQueue({
            url:       cfg.urls.create,
            csrfToken: csrf,
            button:    btnGenerate,
            prompt:    { inputId: 'text_content', field: 'text_content' },
            ports:     [{ inputId: 'audio_input', field: 'audio_input',
                          urlField: 'source_url', urlInputId: 'avatarizerUrlInput' }],
            extraFields: function (fd) {
                // L'avatar est TOUJOURS un fichier (joint, ou désigné : le sien, un partagé, un
                // avatar système de la médiathèque — pointé). `avatar_source='gallery'` (un NOM)
                // ne reste que pour les lots, le Studio et l'API de l'assistant.
                fd.append('avatar_source', 'upload');
                // Photo OU objet 3D : le serveur dérive le moteur de la nature du fichier.
                WamaApp.appendInput(fd, chosenAvatar(), 'avatar_upload');
                // Modèle d'animation du volet (« auto » par défaut ; le serveur valide au catalogue).
                const animationModel = $('#animation_model');
                fd.append('animation_model', animationModel ? animationModel.value : 'auto');
                fd.append('bbox_shift', bboxSlider ? bboxSlider.value : '0');
                fd.append('use_enhancer', $('#use_enhancer') && $('#use_enhancer').checked ? 'true' : 'false');
            },
            // L'AVATAR reste choisi : plusieurs vidéos d'un même visage s'enchaînent. Seuls le
            // texte, l'audio et son URL se vident (geste de l'app : `clearPort` met le port à jour).
            reset:   false,
            onAdded: function (data) {
                // `id` = contrat COMMUN (trou #24) ; les anciennes graphies restent lues en repli.
                const jobId = data.id || data.job_id || data.pk || null;
                const empty = $('#no-jobs-msg');
                if (empty) empty.remove();
                addJobCard(jobId);
                updateJobsCount(1);
                if (textArea) textArea.value = '';
                if (wordCountEl) wordCountEl.textContent = '0';
                clearPort(audioInput);
                if (avatarizerUrlInput) avatarizerUrlInput.value = '';
            },
            // Le bouton rendu, l'app redit s'il doit rester grisé (entrées requises).
            onSettled: function () { updateGenerateButton(); },
        });
    }

    function updateJobsCount(delta) {
        const counter = $('#jobs-count');
        if (!counter) return;
        const current = parseInt(counter.textContent || '0', 10);
        counter.textContent = Math.max(0, current + delta);
    }

    // -----------------------------------------------------------------------
    // Create job (POST /avatarizer/create/)
    // -----------------------------------------------------------------------
    // Import de LOT (brique commune batch-import.js) : détection des fichiers batch
    // (txt/csv/pdf/docx → parseur serveur commun parse_unified_batch) + barre de détection.
    // ⚠ `cfg.urls.batch` N'EXISTE PAS (le gabarit déclare `batchPreview`/`batchCreate`,
    // index.html:311-312) : l'interpolation rendait `/avatarizer/undefinedpreview/`, soit un
    // 404 servi en HTML que la brique tentait de lire en JSON. Défaut MUET côté page — la
    // console seule le disait ; le geste, lui, ne créait jamais rien. Mesuré le 2026-08-27.
    // De même `batchExts` n'était lu par personne : la brique lit `batchExtensions`
    // (`batch-import.js:46`). Les deux extensions binaires restent une INTENTION — la garde
    // MIME de `isBatch()` (l.64) écarte tout ce qui n'est pas `text/*`, donc pdf/docx ne
    // passent pas encore, même déclarés ici.
    const batchImport = window.WamaBatchImport ? WamaBatchImport({
        batchPreviewUrl: cfg.urls.batchPreview,
        batchCreateUrl: cfg.urls.batchCreate,
        csrfToken: csrf,
        batchExtensions: ['txt', 'csv', 'pdf', 'docx'],
        afterCreate: () => window.location.reload(),
    }) : null;

    // ── Voie d'import : brique commune WamaImport, mode ATTACHE (portage 2026-09-08) ──
    // La card déclare `depot_cree=False` et `file_accept='.wav,.mp3,.ogg,.flac'` : un audio
    // déposé RESTE dans `audio_input` (le port), un fichier de lot part à la brique batch,
    // tout autre fichier est REFUSÉ à l'écran (avant : accepté comme audio sans regarder).
    // Le filemanager injecte dans le même input (`WamaApp.injectFiles`) → même chemin.
    if (typeof window.WamaImport === 'function' && audioDropzone && audioInput) {
        WamaImport({
            csrfToken:   csrf,
            dropZoneId:  'audio-dropzone',
            fileInputId: 'audio_input',
            batch:       batchImport,
            // Les DEUX ports : une image déposée sur la zone audio rejoint l'avatar (le
            // premier input dont l'`accept` l'admet), une désignation aussi.
            attach:      ['audio_input'].concat(avatarInputs.map(i => i.id)),
            afterAttach: function () { updateGenerateButton(); },
        });
    }

    // `createJob` (POST /avatarizer/create/) est porté par la brique commune ci-dessus.

    // -----------------------------------------------------------------------
    // Start job (POST /avatarizer/start/<pk>/)
    // -----------------------------------------------------------------------
    async function startJob(jobId, process) {
        // POST : la vue l'exige depuis le 2026-09-22 — un GET (le défaut de `fetch`) lançait la
        // génération, qu'un préchargement de lien pouvait déclencher sans jeton CSRF.
        // `process` : ▶ d'UN process de la bande (route `start/<id>/<process>/`, lancement borné).
        const resp = await fetch(WamaCycleButton.processUrl(`${cfg.urls.start}${jobId}/`, process), {
            method: 'POST',
            headers: { 'X-CSRFToken': csrf },
        });
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.error || 'Erreur démarrage job');
    }

    // -----------------------------------------------------------------------
    // Step label helper (from workers.py progress steps)
    // -----------------------------------------------------------------------
    function getStepLabel(progress, mode) {
        if (progress >= 100) return 'Vidéo générée ✓';
        if (progress >= 95)  return 'Finalisation…';
        if (progress >= 85)  return 'CodeFormer : amélioration faciale…';
        if (progress >= 80)  return 'Post-traitement…';
        if (progress >= 40)  return "Animation de l'avatar…";   // MuseTalk ou TalkingHead
        if (progress >= 30)  return 'Préparation de la sortie…';
        if (progress >= 20)  return "Résolution de l'avatar…";
        if (progress >= 10)  return 'Chargement audio…';
        if (progress >= 5)   return 'Démarrage…';
        return 'En attente…';
    }

    // -----------------------------------------------------------------------
    // Add job card dynamically (new job) — synthesis-card layout
    // -----------------------------------------------------------------------
    // Card = partial SERVEUR unique (_avatar_card.html via card_html) — le JS ne fabrique
    // plus de markup : il insere/remplace le fragment rendu par Django.
    // Redemandée par la brique commune (WamaApp.fetchCard, portage 2026-09-22) : le gabarit
    // d'URL vient du serveur (`urls.cardHtml`, résolu par {% url %}), plus de chemin recollé.
    async function fetchCardHtml(jobId) {
        const fresh = await WamaApp.fetchCard(cfg.urls.cardHtml, jobId);
        if (!fresh) throw new Error('card_html indisponible');
        return fresh;
    }

    async function addJobCard(jobId) {
        const container = $('#jobs-container');
        if (!container) return;
        try {
            const fresh = await fetchCardHtml(jobId);
            container.prepend(fresh);
            bindJobCardEvents(fresh);
        } catch (e) { /* la card apparaitra au prochain rechargement */ }
    }

    async function refreshCard(jobId) {
        const card = $(`#job-${jobId}`);
        if (!card) return;
        try {
            const fresh = await fetchCardHtml(jobId);
            card.replaceWith(fresh);
            bindJobCardEvents(fresh);   // RE-BIND apres re-rendu (lecon describer)
        } catch (e) { /* non-fatal */ }
    }

    // -----------------------------------------------------------------------
    // ⏹ Stop : arrête la génération (endpoint commun) → job relançable (↻ via autoSync sur data-status).
    async function stopJob(jobId) {
        const card = $(`.synthesis-card[data-job-id="${jobId}"]`);
        try {
            const r = await fetch(`${cfg.urls.stop}${jobId}/`, { method: 'POST', headers: { 'X-CSRFToken': csrf } });
            const data = await r.json().catch(() => ({}));
            if (card && data.status) card.dataset.status = data.status;
        } catch (e) { /* non-fatal */ }
        if (activePollers[jobId]) { clearInterval(activePollers[jobId]); delete activePollers[jobId]; }
        // Re-rendu SERVEUR de la card (badge/boutons/barre) — sans lui, l'état visuel restait
        // « en cours » jusqu'à un F5 (constat Fabien 17/08) : le poller étant coupé juste
        // au-dessus, aucune transition ne pouvait plus re-rendre la card.
        refreshCard(jobId);
    }

    // Bouton de cycle commun ▶/⏹/↻ : wire (start/restart→startJob+poll, stop→stopJob) + auto-sync.
    function initCycleButton() {
        const c = $('#jobs-container');
        if (!window.WamaCycleButton || !c) return;
        WamaCycleButton.wire(c, {
            start: async (id, btn) => {
                const card = $(`.synthesis-card[data-job-id="${id}"]`);
                if (card && (card.dataset.status || '').toUpperCase() === 'RUNNING') await stopJob(id);
                const process = WamaCycleButton.processOf(btn);
                try { await startJob(id, process); if (card) card.dataset.status = 'RUNNING'; startPolling(id); }
                catch (e) { WamaApp.toast(e.message || 'Erreur', 'error'); }
            },
            stop: (id) => stopJob(id),
        });
        WamaCycleButton.autoSync({ container: c, cardSelector: '.synthesis-card' });
    }
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', initCycleButton);
    else initCycleButton();

    // Poll job progress
    // -----------------------------------------------------------------------
    function startPolling(jobId) {
        if (activePollers[jobId]) return;
        activePollers[jobId] = setInterval(() => pollJob(jobId), 2000);
    }

    async function pollJob(jobId) {
        try {
            const resp = await fetch(`${cfg.urls.progress}${jobId}/`);
            const data = await resp.json();
            updateJobCard(jobId, data);

            if (data.status === 'SUCCESS' || data.status === 'FAILURE') {
                clearInterval(activePollers[jobId]);
                delete activePollers[jobId];
            }
        } catch (_) { /* ignore network errors */ }
    }

    // -----------------------------------------------------------------------
    // Update job card from API data
    // -----------------------------------------------------------------------
    function updateJobCard(jobId, data) {
        const card = $(`#job-${jobId}`);
        if (!card) return;

        // Transition d'etat -> la card est re-rendue par le serveur (source unique du markup)
        if ((card.dataset.status || '') !== data.status) {
            card.dataset.status = data.status;
            refreshCard(jobId);
            return;
        }

        // PROCESS de la card : les lignes bougent pendant le traitement — brique commune.
        if (window.WamaApp && WamaApp.updateProcessRows) WamaApp.updateProcessRows(card, data.processes);

        // Meme etat : progression/ETA/etape mises a jour en place (pas de re-fetch a chaque poll)
        // ⚠ .wama-progress-fill (brique commune) — l'ancien selecteur .progress-fill ne matchait
        // RIEN depuis le passage a la brique : la barre ne bougeait qu'aux transitions (no-op
        // silencieux attrape au port v3, 13/08).
        const fill     = $('.wama-progress-fill', card);
        const progText = $('.progress-text', card);
        if (fill)     fill.style.width = data.progress + '%';
        if (progText) progText.textContent = data.progress + '%';

        // ETA (moteur commun) — debit observe + seed serveur (apprentissage)
        if (window.WamaEta) {
            const est = WamaEta.update(jobId, { progress: data.progress, status: data.status,
                                                seedSeconds: data.estimated_seconds, modelLoaded: false });
            WamaEta.render($('.wama-eta', card), est);
        }

        const stepDesc = $('.step-desc', card);
        if (stepDesc && (data.status === 'RUNNING' || data.status === 'PENDING')) {
            stepDesc.textContent = getStepLabel(data.progress, data.mode || card.dataset.mode || 'pipeline');
        }
    }

    // -----------------------------------------------------------------------
    // Settings modal (per-job parameters)
    // -----------------------------------------------------------------------
    // ⚙ item : le CYCLE complet (rendre du schéma → greffer le pied → afficher → lire →
    // enregistrer → enchaîner) est la brique commune `WamaParams.settingsModal` (portage
    // 2026-09-24 — la modale statique `#jobSettingsModal` du gabarit, son remplissage champ par
    // champ, `saveJobSettings` et `buildParamsHtml` (qui repeignait la card en JS) vivaient ici).
    // Les VALEURS viennent des data-* du gear (brique `card_gear`), lues par LE lecteur unique
    // `WamaInspector.gearValues` ; la card enregistrée est RE-RENDUE par le serveur.
    //
    // L'APPARIEMENT voix ↔ langue ↔ moteur TTS (INPUT_MODEL_MATCHING §6.7) se branche à CHAQUE
    // ouverture (`decorate`), sur les champs de la modale générée — même configuration qu'au
    // chargement de la page jusque-là. Deux briques, deux directions, un seul catalogue :
    // `WamaModelCaps` (moteur → voix/langues) et `WamaInputMatch` (voix/langue → moteurs grisés).
    // ⚠ `WamaInputMatch` n'est ré-initialisable que depuis le 24/09 : son écouteur ✕ est unique
    // pour la page, une instance dont la modale a disparu se retire d'elle-même.
    function wireTtsMatching() {
        const match = window.AVATARIZER_MATCH || {};
        // Modèle → entrées : moteur sans clonage ⇒ voix ua_/cv_ masquées ; langues restreintes
        // à celles du moteur. Domaine par CAPACITÉ (route F4b ②), identique au synthesizer :
        // c'est le MÊME parc, et l'avatarizer n'en possède aucun moteur. Les deux prédicats sont
        // DÉFINIS DANS LA BRIQUE, cette page ne déclare que ses ids.
        let modelCaps = null;
        if (window.WamaModelCaps) {
            modelCaps = WamaModelCaps.init({
                task: 'text-to-speech',
                modelSelectId: 'settingsTtsModel',
                filters: [
                    WamaModelCaps.cloneVoiceFilter('settingsVoicePreset'),
                    WamaModelCaps.langFilter('settingsLanguage'),
                ],
            });
        }
        // Entrée → modèle : une voix CLONÉE choisie désactive les moteurs sans clonage, une
        // LANGUE choisie ceux qui ne la parlent pas — grisés avec la raison, jamais cachés.
        if (window.WamaInputMatch) {
            WamaInputMatch.init({
                selectId: 'settingsTtsModel',
                meta: match.meta || {},
                inputLabels: match.labels || {},
                slots: {
                    reference_voice: WamaInputMatch.voiceSlot('settingsVoicePreset'),
                    language: WamaInputMatch.langSlot('settingsLanguage'),
                },
                // Le MÊME catalogue que la direction modèle→choix (langues incluses).
                capsProvider: modelCaps ? modelCaps.caps : null,
                // Rejugé à l'arrivée du catalogue (2026-10-05) : sans lui, une langue choisie ne
                // grisait les moteurs qu'au geste suivant.
                capsReady: modelCaps ? modelCaps.ready : null,
            });
            // Troisième direction (2026-09-27) : les groupes de voix de la langue CHOISIE
            // remontent en tête du sélecteur. Rien n'est masqué — un timbre se clone d'une
            // langue à l'autre. 2ᵉ adoption de la brique, et elle coûte UNE ligne : c'est ce
            // que le synthesizer a payé pour elle. ⚠ Appelée ICI, dans `wireTtsMatching`, donc
            // à CHAQUE ouverture de la modale : ses champs sont re-générés à chaque fois.
            WamaInputMatch.voicesFollowLanguage('settingsVoicePreset', 'settingsLanguage');
        }
    }

    function openSettingsModal(id, btn) {
        const schema = window.AVATARIZER_PARAMS_SCHEMA || [];
        const card = (btn && btn.closest('.wama-card')) || btn;
        const voiceGroups = window.AVATARIZER_VOICE_GROUPS || [];
        return WamaParams.settingsModal({
            id: id,
            title: 'Paramètres du job',
            titleIcon: 'fa-cog',
            schema: schema,
            values: WamaInspector.gearValues(card, schema.map(function (p) { return p.name; })),
            formClass: 'avatarizer-settings-form',
            footerTplId: 'avatarizerSettingsFooterTpl',
            saveUrl: cfg.urls.updateSettings.replace('/0/', `/${id}/`),
            csrf: csrf,
            // Voix : groupes per-user injectés par la vue (brique commune get_voice_groups).
            optionsResolver: function (p) { return p.options_source === 'voices' ? voiceGroups : null; },
            decorate: function () { wireTtsMatching(); },
            onSaved: async function (jobId, restart) {
                await refreshCard(jobId);
                if (restart) {
                    try {
                        await startJob(jobId);
                        startPolling(jobId);
                    } catch (err) {
                        WamaApp.toast('Erreur démarrage : ' + err.message, 'error');
                    }
                }
            },
        });
    }

    // ⚙ item — ouvreur DÉCLARÉ à la brique commune (queue-actions.js), portage 2026-08-23.
    WamaQueueActions.onSettings(function (id, btn) { openSettingsModal(id, btn); });

    // 🗑 RÉSIDU de suppression — la brique retire la card, le lot vidé et signale au gestionnaire
    // de fichiers ; ne restent que le poller local (pas encore `WamaApp.Poller` ici), le compteur
    // d'en-tête et le message de file vide.
    WamaQueueActions.onDeleted(function (id) {
        if (activePollers[id]) { clearInterval(activePollers[id]); delete activePollers[id]; }
        updateJobsCount(-1);
        if (!$('.synthesis-card')) {
            const container = $('#jobs-container');
            if (container) container.innerHTML = `
                <div id="no-jobs-msg" class="text-center text-muted py-4">
                    <i class="fas fa-film fa-3x mb-2 d-block opacity-50"></i>
                    <p>Aucune vidéo générée pour l'instant.</p>
                </div>`;
        }
    });

    // -----------------------------------------------------------------------
    // Bind delete / start / preview-video buttons on job cards
    // -----------------------------------------------------------------------
    function bindJobCardEvents(card) {
        // 🗑 : plus de bind PAR CARD ici — brique commune queue-actions.js, délégation unique
        // (portage 2026-08-23). Le résidu est déclaré une seule fois, plus bas.


        // ⚙ : plus de bind PAR CARD ici — la brique commune (queue-actions.js) délègue une fois
        // pour toutes, y compris sur les cards rendues après coup (portage 2026-08-23).
    }

    // Bind events on pre-existing job cards (server-side rendered)
    $$('.synthesis-card').forEach(card => {
        bindJobCardEvents(card);
        const status = card.dataset.status;
        // Lancé seulement : `begin_processing` pose RUNNING dès l'acceptation (puis la tâche peut
        // attendre sa VRAM : AWAITING_RESOURCES). Un PENDING n'a jamais été lancé (ajouté à la
        // file, ou créé par un lot) — l'interroger toutes les 2 s ne s'arrêtait jamais
        // (2026-09-29, au passage à « ajouter sans lancer »).
        if (status === 'RUNNING' || status === 'AWAITING_RESOURCES') {
            startPolling(card.dataset.jobId);
            // Initialise step label from progress-fill width
            const stepDesc = $('.step-desc', card);
            const fill     = $('.progress-fill', card);
            if (stepDesc && fill) {
                const prog = parseInt((fill.style.width || '0').replace('%', ''), 10);
                stepDesc.textContent = getStepLabel(prog, card.dataset.mode || 'pipeline');
            }
        }
    });

    // -----------------------------------------------------------------------
    // Clear all
    // -----------------------------------------------------------------------
    // Boutons globaux serveur (audit 2026-07-11)
    const btnStartAll = $('#startAllBtn');
    if (btnStartAll) {
        btnStartAll.addEventListener('click', async () => {
            try {
                const r = await fetch(cfg.urls.startAll, {
                    method: 'POST',
                    headers: { 'X-CSRFToken': csrf },
                });
                const data = await r.json().catch(() => ({}));
                if (!r.ok) {
                    WamaApp.toast(data.error || 'Démarrage impossible', 'error');
                    return;
                }
                WamaApp.toast(`${data.count} job(s) démarré(s)`, 'success');
                location.reload();
            } catch (_) {
                WamaApp.toast('Erreur réseau', 'error');
            }
        });
    }

    const btnDownloadAll = $('#downloadAllBtn');
    if (btnDownloadAll) {
        btnDownloadAll.addEventListener('click', () => {
            window.location.href = cfg.urls.downloadAll;
        });
    }

    const btnClearAll = $('#clearAllBtn');
    if (btnClearAll) {
        btnClearAll.addEventListener('click', async () => {
            if (!confirm('Supprimer tous les jobs et leurs fichiers ?')) return;
            // Vue serveur commune (audit 2026-07-11) — remplace la boucle de DELETE unitaires
            try {
                const r = await fetch(cfg.urls.clearAll, {
                    method: 'POST',
                    headers: { 'X-CSRFToken': csrf },
                });
                const data = await r.json().catch(() => ({}));
                if (!r.ok) {
                    WamaApp.toast(data.error || 'Suppression impossible', 'error');
                    return;
                }
            } catch (_) {
                WamaApp.toast('Erreur réseau', 'error');
                return;
            }
            $$('.synthesis-card').forEach((card) => {
                const jid = card.dataset.jobId;
                clearInterval(activePollers[jid]);
                delete activePollers[jid];
                card.remove();
            });
            if (window.WamaFM) WamaFM.deleted();  // fichiers supprimés → refresh filemanager
            const container = $('#jobs-container');
            if (container && !$('.synthesis-card')) {
                container.innerHTML = `
                    <div id="no-jobs-msg" class="text-center text-muted py-4">
                        <i class="fas fa-film fa-3x mb-2 d-block opacity-50"></i>
                        <p>Aucune vidéo générée pour l'instant.</p>
                    </div>`;
            }
            const counter = $('#jobs-count');
            if (counter) counter.textContent = '0';
        });
    }

    /* ============================================================
     * Import par fichier batch (format à balises)
     * ============================================================ */

    /* ============================================================
     * Actions d'ÉLÉMENT et de LOT : toutes à la brique commune
     * ============================================================
     * ⧉ d'un job → brique commune depuis le 2026-07-31.
     * ▶ ⧉ 🗑 d'un LOT → brique commune depuis le 2026-08-27 (`actions_communes=True` sur
     * l'include `_queue_entry.html`). Les trois handlers qui vivaient ici POSTaient vers des
     * URLs RECONSTRUITES à la main (`cfg.urls.batchStart + id + '/start/'`, un chemin littéral
     * dans le gabarit) : la card mère porte désormais `data-batch-*-url` résolue par `{% url %}`.
     * Le retrait et l'opt-in sont le MÊME geste — garder les deux aurait POSTé deux fois par clic.
     * Aucune suite à déclarer : l'avatarizer rechargeait après lancement, ce que fait le défaut
     * de la brique.
     */


    // ── Parametres de LOT : la ⚙ des cards batch communes ouvre la modale WamaParams
    // (context='batch'), le save POST vers batch_update (applique a tous les jobs du lot).
    let _batchSettingsModal = null;
    function ensureBatchSettingsModal() {
        if (_batchSettingsModal) return _batchSettingsModal;
        const el = document.getElementById('batchSettingsModal');
        if (!el || !window.bootstrap) return null;
        _batchSettingsModal = new bootstrap.Modal(el);
        const saveBtn = document.getElementById('saveBatchSettingsBtn');
        if (saveBtn) saveBtn.addEventListener('click', saveBatchSettings);
        return _batchSettingsModal;
    }

    async function saveBatchSettings() {
        const batchId = (document.getElementById('batchSettingsBatchId') || {}).value;
        const host = document.getElementById('avatarizerBatchParams');
        if (!batchId || !host || !window.WamaParams) return;
        const fd = new FormData();
        Object.entries(WamaParams.read(host)).forEach(([k, v]) => fd.append(k, v));
        try {
            const r = await fetch(`${cfg.urls.batch}${batchId}/update/`, {
                method: 'POST', headers: { 'X-CSRFToken': csrf }, body: fd,
            });
            if (!r.ok) throw new Error(`batch_update ${r.status}`);
            _batchSettingsModal.hide();
            WamaApp.toast('Paramètres appliqués au lot', 'success');
            window.location.reload();
        } catch (e) { WamaApp.toast(e.message || 'Erreur', 'error'); }
    }

    document.addEventListener('click', (e) => {
        const b = e.target.closest('.batch-settings-btn');
        if (!b) return;
        e.preventDefault();
        const m = ensureBatchSettingsModal();
        const idInput = document.getElementById('batchSettingsBatchId');
        if (idInput) idInput.value = b.dataset.batchId || '';
        if (m) m.show();
    });

})();
