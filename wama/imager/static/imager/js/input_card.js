/**
 * Imager — card d'entrée commune (une instance PAR DOMAINE : image / vidéo).
 *
 * Principe (INPUT_MODEL_MATCHING.md) : AUCUN radio de mode — le `generation_mode`
 * legacy est DÉRIVÉ des entrées fournies + du modèle, le backend reste inchangé :
 *   image : fichier batch → file2img · réf + prompt → img2img · réf sans prompt →
 *           describe2img · prompt seul → txt2img
 *   vidéo : réf → img2vid · sinon txt2vid
 * Appariement entrée↔modèle : WamaInputMatch (capacités catalogue inputs_required/
 * optional — ex. qwen-image-edit exige une image, cogvideox-5b-i2v aussi).
 * Routage des imports : un seul point d'entrée (dropzone / fichier / médiathèque) —
 * .txt/.csv → fichier de prompts (batch), image/* → slot de référence.
 * Config : window.IMAGER_CARD = {urls:{create}, csrf, matchMeta, inputLabels, enhanceUrl}.
 */
(function () {
    'use strict';

    const CFG = window.IMAGER_CARD || {};

    function toast(msg, type) { WamaApp.toast(msg, type || 'info'); }   // brique globale

    function isBatchFile(f) { return /\.(txt|csv)$/i.test(f.name || ''); }

    function initDomain(d) {
        const btn = document.getElementById(d.btnId);
        const promptEl = document.getElementById(d.promptId);
        const select = document.getElementById(d.selectId);
        const fileInput = document.getElementById(d.fileInputId);
        const dropZone = document.getElementById(d.dropZoneId);
        const refInput = document.getElementById(d.refInputId);
        // Référence par URL (WAMA_INGEST, contrat composer 307b9fb) : champ SANS bouton —
        // l'URL fait partie du payload Générer, téléchargée AU LANCEMENT par la tâche.
        const urlInput = document.getElementById(d.urlInputId);
        if (!btn || !promptEl || !select) return;

        function refUrl() { return urlInput ? (urlInput.value || '').trim() : ''; }

        let batchFile = null;   // .txt/.csv de prompts (image seulement)

        // ── Appariement entrée↔modèle (brique commune, capacités catalogue) ──
        // INVARIANT INPUT_MODEL_MATCHING : « requis → lancement GATÉ avec la raison,
        // jamais d'échec silencieux » → onState pilote l'état du bouton Générer.
        let matcher = null;
        if (window.WamaInputMatch) {
            matcher = WamaInputMatch.init({
                selectId: d.selectId,
                statusId: d.statusId,
                meta: CFG.matchMeta || {},
                inputLabels: CFG.inputLabels || {},
                slots: { work_image: {
                    inputId: d.refInputId, chipId: d.refChipId, zoneId: d.refSlotId,
                    // Le slot est FOURNI par un fichier OU par une URL (crochets déclaratifs
                    // de la brique) ; le ✕ de la chip efface les deux.
                    isProvided: function (el) { return !!(el.files && el.files.length) || !!refUrl(); },
                    describe: function (el) {
                        return (el.files && el.files.length) ? el.files[0].name : refUrl();
                    },
                    clear: function (el) { el.value = ''; if (urlInput) urlInput.value = ''; },
                } },
                onState: function (st) {
                    btn.disabled = !st.launchable;
                    btn.title = st.launchable ? '' : (st.reason || 'Entrée requise manquante');
                },
            });
            // La frappe dans le champ URL fournit/retire le slot → re-apparier.
            if (urlInput) urlInput.addEventListener('input', function () { matcher.refresh(); });
        }

        // ── Aide modèle (description + VRAM, catalogue) ──
        if (window.WamaModelHelp && WamaModelHelp.fetchCatalogMeta) {
            WamaModelHelp.fetchCatalogMeta('imager', { keyBy: 'id' }).then(function (meta) {
                WamaModelHelp.init({ selectId: d.selectId, helpId: d.prefix + 'ModelHelp', meta: meta });
            }).catch(function () {});
        }

        // ── Enrichissement de prompt (pipeline commun conservé) ──
        if (window.WamaPromptEnrich) {
            WamaPromptEnrich.attach(promptEl, {
                app: 'imager', domain: d.domain,
                endpoint: CFG.enhanceUrl, csrf: CFG.csrf,
                original: promptEl.value, processed: '',
            });
        }

        // ── Affordances sous le prompt : bouton ✨ + tags proposés (chips) ──
        // Le déclencheur ✨ est le handler DÉLÉGUÉ existant d'index.js (.enhance-prompt-btn,
        // data-target/data-mode) ; les chips sont la brique WamaPromptChips par domaine.
        (function () {
            const bar = document.createElement('div');
            bar.className = 'd-flex align-items-start gap-2 mt-1';
            bar.innerHTML =
                '<button type="button" class="btn btn-sm btn-outline-info enhance-prompt-btn py-0" ' +
                'data-target="' + d.promptId + '" data-mode="' + d.domain + '" ' +
                'title="Traduire et enrichir le prompt (le texte original est conservé)">' +
                '<i class="fas fa-wand-magic-sparkles"></i></button>' +
                '<div id="' + d.prefix + 'PromptChips" class="flex-grow-1"></div>';
            promptEl.insertAdjacentElement('afterend', bar);
            if (window.WamaPromptChips) {
                WamaPromptChips.init({ container: '#' + d.prefix + 'PromptChips',
                                       target: '#' + d.promptId,
                                       domain: d.domain, collapsed: true });
            }
        })();

        // ── Chip du fichier batch (hors appariement : affordance de card, pas une capacité) ──
        function setBatchFile(f) {
            batchFile = f || null;
            const chip = document.getElementById(d.prefix + 'BatchChip');
            if (!chip) return;
            if (batchFile) {
                chip.style.display = '';
                chip.innerHTML = '<span class="badge bg-info text-dark d-inline-flex align-items-center gap-1">' +
                    '<i class="fas fa-list"></i> ' + batchFile.name +
                    ' <button type="button" class="btn-close btn-close-white btn-sm ms-1" aria-label="Retirer"></button></span>';
                chip.querySelector('button').addEventListener('click', function () { setBatchFile(null); });
            } else {
                chip.style.display = 'none';
                chip.innerHTML = '';
            }
        }

        // ── Voie d'import : brique commune WamaImport, mode ATTACHE (portage 2026-09-08) ──
        // Ce que faisait `routeFile` (dropzone / sélecteur / médiathèque → .txt/.csv au lot
        // commun, image/* dans le slot de référence, toast sinon) est le contrat de la brique,
        // DÉCLARÉ : `attach: [refInputId]` — le fichier va au port dont l'`accept` (image/*,
        // déclaré par la card) l'admet ; `batch` (image seulement, `batchScope:'each'` : chaque
        // fichier est testé) ; sans `uploadUrl`, le reste est REFUSÉ à l'écran. `afterAttach`
        // = le refresh EXPLICITE de l'appariement (injection programmatique). Le repli
        // `setBatchFile` (brique batch absente) est conservé par `beforeFile`.
        if (typeof window.WamaImport === 'function' && dropZone && fileInput) {
            WamaImport({
                csrfToken:   CFG.csrf,
                dropZoneId:  d.dropZoneId,
                fileInputId: d.fileInputId,
                // `_batchImport` naît dans un DOMContentLoaded du gabarit enregistré APRÈS
                // celui-ci : résolution PARESSEUSE, jamais au moment de l'instanciation
                // (mesuré : lot ignoré, fichier de prompts refusé comme « non attendu »).
                batch:       d.allowBatch ? { detectAndHandle: function (f) {
                                 var b = window[d.batchGlobal];
                                 return b ? b.detectAndHandle(f) : Promise.resolve(false); } } : null,
                batchScope:  'each',
                attach:      [d.refInputId],
                afterAttach: function () { if (matcher) matcher.refresh(); },
                beforeFile:  function (f) {
                    if (d.allowBatch && isBatchFile(f) && !window[d.batchGlobal]) { setBatchFile(f); return false; }
                    return true;
                },
            });
        }

        // ── Dérivation du generation_mode (contrat backend INCHANGÉ) ──
        function deriveMode() {
            const hasPrompt = (promptEl.value || '').trim().length > 0;
            const hasRefFile = !!(refInput && refInput.files && refInput.files.length);
            const hasRef = hasRefFile || !!refUrl();
            if (d.domain === 'video') return hasRef ? 'img2vid' : 'txt2vid';
            if (batchFile) return 'file2img';
            // describe2img exige le fichier LOCAL (BLIP tourne à la création) : une référence
            // par URL seule dérive en img2img (avec ou sans prompt — img2img pur accepté).
            if (hasRefFile) return hasPrompt ? 'img2img' : 'describe2img';
            if (hasRef) return 'img2img';
            return 'txt2img';
        }

        // ── Soumission ──
        btn.addEventListener('click', function () {
            const mode = deriveMode();
            const hasRefFile = !!(refInput && refInput.files && refInput.files.length);
            const hasRef = hasRefFile || !!refUrl();
            // Garde de dernier recours (le bouton est déjà gaté par onState).
            if (matcher && !matcher.isLaunchable()) {
                toast('Ce modèle attend une entrée qui manque encore.', 'warning');
                return;
            }
            if (!batchFile && !hasRef && !(promptEl.value || '').trim()) {
                toast('Décrivez ce que vous voulez générer, ou fournissez une image / un fichier de prompts.', 'warning');
                return;
            }
            // INVARIANT prompt (WAMA_LLM) : on poste toujours l'ORIGINAL — l'enrichi
            // vit en prompt_processed et est recalculé à l'ingestion, jamais figé à la création.
            let promptValue = (promptEl.value || '').trim();
            if (window.WamaPromptEnrich) {
                const ctrl = WamaPromptEnrich.get(promptEl);
                if (ctrl && ctrl.snapshot().state === 'processed') promptValue = (ctrl.original || '').trim();
            }
            const negEl = document.getElementById(d.prefix + 'NegativePrompt');
            const fd = new FormData();
            fd.append('generation_mode', mode);
            fd.append('prompt', promptValue);
            fd.append('negative_prompt', negEl ? (negEl.value || '').trim() : '');
            fd.append('model', select.value || 'auto');

            // ── Réglages du VOLET DROIT ────────────────────────────────────────────────
            // Sans ça, le serveur retombe sur get_model_defaults() et régler « 4 images » ou
            // « steps 50 » dans le volet n'a AUCUN effet. La régression datait du remplacement
            // du formulaire bespoke par la card commune : l'ancien `handleFormSubmit` lisait
            // bien le volet, mais son <form> hôte a disparu avec lui (code mort depuis).
            // `WamaParams.read` rend un objet clé = NOM de param, c.-à-d. exactement les noms
            // de champs attendus par la vue de création — aucune table de correspondance.
            const panelHost = document.getElementById(
                d.domain === 'video' ? 'videoPanelParams' : 'imagePanelParams');
            if (panelHost && window.WamaParams) {
                const panel = WamaParams.read(panelHost) || {};
                Object.keys(panel).forEach(function (k) {
                    // Le modèle vient du select de la CARD (surface primaire), pas du volet :
                    // le volet ne porte que le DÉFAUT de l'utilisateur.
                    if (k === 'model' || k === 'negative_prompt') return;
                    const v = panel[k];
                    if (v !== null && v !== undefined && v !== '') fd.append(k, v);
                });
            }
            // Résolution image : hors schéma (widget à présets) → width/height calculés.
            const wEl = document.getElementById('width');
            const hEl = document.getElementById('height');
            if (d.domain !== 'video' && wEl && hEl) {
                fd.append('width', wEl.value);
                fd.append('height', hEl.value);
            }
            if (batchFile) fd.append('prompt_file', batchFile);
            if (hasRefFile) fd.append('reference_image', refInput.files[0]);
            // Un fichier joint PRIME sur l'URL (ensure_local_input ne télécharge que si vide).
            if (!hasRefFile && refUrl()) fd.append('source_url', refUrl());

            btn.disabled = true;
            WamaApp.csrfFetch(CFG.urls.create, CFG.csrf, { method: 'POST', body: fd })
                .then(function (r) { return r.json().catch(function () { return {}; }).then(function (j) { return { ok: r.ok, j: j }; }); })
                .then(function (res) {
                    if (!res.ok || res.j.error) throw new Error(res.j.error || 'Création impossible');
                    // La card PENDING est rendue côté serveur → rechargement.
                    // ⚠ Le commentaire précédent annonçait un remplacement par
                    // card_html/refreshCard « au palier fondation file » : ce palier est livré
                    // (`2e330cf`) et le rechargement est TOUJOURS là, parce que `refreshCard`
                    // (queue.js:26) fait `el.outerHTML = …` — il REMPLACE une card existante et
                    // ne sait pas en INSÉRER une nouvelle. Insérer proprement suppose de savoir
                    // dans quel batch la ranger (build_batches_list / auto_wrap_orphans) :
                    // c'est un geste à part entière, pas un nettoyage.
                    window.location.reload();
                })
                .catch(function (e) { toast(e.message || 'Erreur de création', 'error'); btn.disabled = false; });
        });
    }

    document.addEventListener('DOMContentLoaded', function () {
        initDomain({
            prefix: 'img', domain: 'image', allowBatch: true, batchGlobal: '_batchImport',
            selectId: 'imgModelSelect', promptId: 'imgPrompt',
            fileInputId: 'imgFileInput', dropZoneId: 'imgDropZone',
            refInputId: 'imgRefInput', refChipId: 'imgRefChip', refSlotId: 'imgRefSlot',
            urlInputId: 'imgUrlInput',
            statusId: 'imgMatchStatus', btnId: 'imgGenerateBtn',
        });
        initDomain({
            // Lot vidéo AUTORISÉ (2026-09-08, décision Fabien) : sa propre instance de brique
            // (`_batchImportVideo`, ids `vidBatch…`), sinon un fichier de prompts déposé sur la
            // card vidéo était refusé comme « non attendu ».
            prefix: 'vid', domain: 'video', allowBatch: true, batchGlobal: '_batchImportVideo',
            selectId: 'vidModelSelect', promptId: 'vidPrompt',
            fileInputId: 'vidFileInput', dropZoneId: 'vidDropZone',
            refInputId: 'vidRefInput', refChipId: 'vidRefChip', refSlotId: 'vidRefSlot',
            urlInputId: 'vidUrlInput',
            statusId: 'vidMatchStatus', btnId: 'vidGenerateBtn',
        });
    });
})();
