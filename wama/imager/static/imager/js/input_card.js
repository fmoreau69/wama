/**
 * Imager — card d'entrée commune (une instance PAR DOMAINE : image / vidéo).
 *
 * Principe (INPUT_MODEL_MATCHING.md) : AUCUN radio de mode — le `generation_mode`
 * legacy est DÉRIVÉ des entrées fournies + du modèle, le backend reste inchangé :
 *   image : réf + prompt → img2img · réf sans prompt → describe2img · prompt seul → txt2img
 *   vidéo : réf → img2vid · sinon txt2vid
 * Appariement entrée↔modèle : WamaInputMatch (capacités catalogue inputs_required/
 * optional — ex. qwen-image-edit exige une image, cogvideox-5b-i2v aussi).
 * Routage des imports : un seul point d'entrée (dropzone / fichier / médiathèque) —
 * .txt/.csv → brique commune de LOT (barre `batch_detect_bar`), image/* → slot de référence.
 * Config : window.IMAGER_CARD = {urls:{create}, csrf, matchMeta, inputLabels, enhanceUrl}.
 *
 * La card porte les ENTRÉES ; le MODÈLE et le PROMPT NÉGATIF sont des RÉGLAGES du volet droit
 * (CARD_DESIGN §11.11 Étape 3 (c), 2026-09-28). La card n'a plus de select à elle :
 * l'appariement grise les options du select du VOLET (`#model`, `#panel_video_model`) et la
 * création poste le volet entier. ⚠ Ce script doit donc s'exécuter APRÈS index.js, qui rend et
 * remplit ce select (ordre d'inclusion dans index.html).
 */
(function () {
    'use strict';

    const CFG = window.IMAGER_CARD || {};

    function toast(msg, type) { WamaApp.toast(msg, type || 'info'); }   // brique globale

    function initDomain(d) {
        const btn = document.getElementById(d.btnId);
        const promptEl = document.getElementById(d.promptId);
        const select = document.getElementById(d.selectId);
        const fileInput = document.getElementById(d.fileInputId);
        const dropZone = document.getElementById(d.dropZoneId);
        // ── L'INPUT D'IMAGE EST CELUI QUE LA CARD REND, pas celui qu'on suppose (2026-09-11) ──
        // Depuis que les ports viennent des MODÈLES (INPUT_MODEL_MATCHING §6.3), l'imager ne
        // déclare plus de port `reference_image` — aucun de ses 12 modèles ne le réclame — mais
        // un port `work_image`, que 6 d'entre eux consomment (qwen-image-edit et cogvideox-i2v
        // l'exigent, SD/SDXL/LTX l'acceptent). La card v4 rend donc UN volet fichier, servi par
        // `file_input_id` ; l'ancien `reference_input_id` n'y existe plus.
        // Mesuré au navigateur : la v4 ne rendait que `imgFileInput`, et `attach: ['imgRefInput']`
        // visait un élément ABSENT — le fichier déposé allait nulle part, sans une erreur. La v3
        // (les 10 apps en place) rend encore les deux, et garde donc exactement son comportement.
        // On RÉSOUT au lieu de supposer : la référence si la card l'offre, le port de travail
        // sinon. Le champ POSTé reste `reference_image` — c'est la frontière des DONNÉES, et le
        // backend s'en sert déjà comme image source de l'i2v (`imager/tasks.py`).
        const refInput = document.getElementById(d.refInputId)
                      || document.getElementById(d.fileInputId);
        const refInputId = (refInput && refInput.id) || d.refInputId;
        // Référence par URL (WAMA_INGEST, contrat composer 307b9fb) : champ SANS bouton —
        // l'URL fait partie du payload Générer, téléchargée AU LANCEMENT par la tâche.
        const urlInput = document.getElementById(d.urlInputId);
        if (!btn || !promptEl) return;
        if (!select) {
            // Le select du VOLET n'est pas (encore) rendu : sans lui, ni appariement ni création
            // cohérente. Le DIRE — une card inerte sans un mot est le pire des défauts.
            console.error('[imager] select de modèle du volet #' + d.selectId +
                          ' absent : input_card.js doit être inclus APRÈS index.js.');
            return;
        }

        function refUrl() { return urlInput ? (urlInput.value || '').trim() : ''; }

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
                    inputId: refInputId, chipId: d.refChipId, zoneId: d.refSlotId,
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

        // L'aide du modèle (description + VRAM) n'est plus câblée ici : le select est celui du
        // volet, dont `WamaParams` câble l'aide depuis le schéma (`help_source='imager'`).

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

        // ── Voie d'import : brique commune WamaImport, mode ATTACHE (portage 2026-09-08) ──
        // Ce que faisait `routeFile` (dropzone / sélecteur / médiathèque → .txt/.csv au lot
        // commun, image/* dans le slot de référence, toast sinon) est le contrat de la brique,
        // DÉCLARÉ : `attach: [refInputId]` — le fichier va au port dont l'`accept` (image/*,
        // déclaré par la card) l'admet ; `batch` (image seulement, `batchScope:'each'` : chaque
        // fichier est testé) ; sans `uploadUrl`, le reste est REFUSÉ à l'écran. `afterAttach`
        // = le refresh EXPLICITE de l'appariement (injection programmatique).
        // ⚠ Le repli « brique de lot absente » (`beforeFile` → chip + mode `file2img`) est RETIRÉ
        // le 2026-09-28 avec la zone d'extension qui portait sa chip : index.html charge TOUJOURS
        // `batch-import.js`, et sans elle un fichier de prompts est refusé à l'écran, comme
        // dans les 9 autres apps — jamais gardé dans un état invisible.
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
                attach:      [refInputId],
                afterAttach: function () { if (matcher) matcher.refresh(); },
            });
        }

        // Une référence est un fichier JOINT ou DÉSIGNÉ (médiathèque, arbre — pointé, jamais
        // re-téléversé : `WamaApp.designateInto`, 2026-09-28).
        function refProvided() {
            return !!(refInput && ((refInput.files && refInput.files.length)
                                   || (window.WamaApp && WamaApp.designationOf(refInput))));
        }

        // ── Dérivation du generation_mode (contrat backend INCHANGÉ) ──
        function deriveMode() {
            const hasPrompt = (promptEl.value || '').trim().length > 0;
            const hasRefFile = refProvided();
            const hasRef = hasRefFile || !!refUrl();
            if (d.domain === 'video') return hasRef ? 'img2vid' : 'txt2vid';
            // describe2img exige le fichier LOCAL (BLIP tourne à la création) : une référence
            // par URL seule dérive en img2img (avec ou sans prompt — img2img pur accepté).
            if (hasRefFile) return hasPrompt ? 'img2img' : 'describe2img';
            if (hasRef) return 'img2img';
            return 'txt2img';
        }

        // ── Soumission ──
        btn.addEventListener('click', function () {
            const mode = deriveMode();
            const hasRefFile = refProvided();
            const hasRef = hasRefFile || !!refUrl();
            // Garde de dernier recours (le bouton est déjà gaté par onState).
            if (matcher && !matcher.isLaunchable()) {
                toast('Ce modèle attend une entrée qui manque encore.', 'warning');
                return;
            }
            if (!hasRef && !(promptEl.value || '').trim()) {
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
            const fd = new FormData();
            fd.append('generation_mode', mode);
            fd.append('prompt', promptValue);

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
                // Modèle et prompt négatif COMPRIS : ce sont des réglages du volet (étape 3 (c)).
                Object.keys(panel).forEach(function (k) {
                    const v = panel[k];
                    if (v !== null && v !== undefined && v !== '') fd.append(k, v);
                });
            }
            if (!fd.has('model')) fd.append('model', select.value || 'auto');
            // Résolution image : hors schéma (widget à présets) → width/height calculés.
            const wEl = document.getElementById('width');
            const hEl = document.getElementById('height');
            if (d.domain !== 'video' && wEl && hEl) {
                fd.append('width', wEl.value);
                fd.append('height', hEl.value);
            }
            if (hasRefFile) WamaApp.appendInput(fd, refInput, 'reference_image');
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
            selectId: 'model', promptId: 'imgPrompt',              // select du VOLET image
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
            selectId: 'panel_video_model', promptId: 'vidPrompt',  // select du VOLET vidéo
            fileInputId: 'vidFileInput', dropZoneId: 'vidDropZone',
            refInputId: 'vidRefInput', refChipId: 'vidRefChip', refSlotId: 'vidRefSlot',
            urlInputId: 'vidUrlInput',
            statusId: 'vidMatchStatus', btnId: 'vidGenerateBtn',
        });
    });
})();
