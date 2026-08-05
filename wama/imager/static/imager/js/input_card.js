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

    function toast(msg, type) {
        if (window.WamaApp && WamaApp.toast) WamaApp.toast(msg, type || 'info');
        else console.log('[imager card]', msg);
    }

    function isBatchFile(f) { return /\.(txt|csv)$/i.test(f.name || ''); }
    function isImageFile(f) { return (f.type || '').indexOf('image/') === 0; }

    function initDomain(d) {
        const btn = document.getElementById(d.btnId);
        const promptEl = document.getElementById(d.promptId);
        const select = document.getElementById(d.selectId);
        const fileInput = document.getElementById(d.fileInputId);
        const dropZone = document.getElementById(d.dropZoneId);
        const refInput = document.getElementById(d.refInputId);
        if (!btn || !promptEl || !select) return;

        let batchFile = null;   // .txt/.csv de prompts (image seulement)

        // ── Appariement entrée↔modèle (brique commune, capacités catalogue) ──
        if (window.WamaInputMatch) {
            WamaInputMatch.init({
                selectId: d.selectId,
                statusId: d.statusId,
                meta: CFG.matchMeta || {},
                inputLabels: CFG.inputLabels || {},
                slots: { work_image: { inputId: d.refInputId, chipId: d.refChipId, zoneId: d.refSlotId } },
            });
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

        // ── Routage d'un fichier importé (dropzone / picker / médiathèque → file input) ──
        function routeFile(f) {
            if (!f) return;
            if (d.allowBatch && isBatchFile(f)) { setBatchFile(f); return; }
            if (isImageFile(f)) {
                try {
                    const dt = new DataTransfer();
                    dt.items.add(f);
                    refInput.files = dt.files;
                    refInput.dispatchEvent(new Event('change', { bubbles: true }));  // → chip WamaInputMatch
                } catch (e) { /* vieux navigateurs : passer par le bouton Ajouter du slot */ }
                return;
            }
            toast(d.allowBatch ? 'Format non géré : image, ou fichier de prompts .txt/.csv.'
                               : 'Format non géré : image attendue.', 'warning');
        }

        if (fileInput) {
            fileInput.addEventListener('change', function () {
                Array.prototype.forEach.call(fileInput.files || [], routeFile);
                fileInput.value = '';
            });
        }
        if (dropZone && fileInput) {
            dropZone.addEventListener('click', function () { fileInput.click(); });
            dropZone.addEventListener('dragover', function (e) { e.preventDefault(); dropZone.classList.add('dragover'); });
            dropZone.addEventListener('dragleave', function () { dropZone.classList.remove('dragover'); });
            dropZone.addEventListener('drop', function (e) {
                e.preventDefault();
                dropZone.classList.remove('dragover');
                Array.prototype.forEach.call((e.dataTransfer || {}).files || [], routeFile);
            });
        }

        // ── Dérivation du generation_mode (contrat backend INCHANGÉ) ──
        function deriveMode() {
            const hasPrompt = (promptEl.value || '').trim().length > 0;
            const hasRef = !!(refInput && refInput.files && refInput.files.length);
            if (d.domain === 'video') return hasRef ? 'img2vid' : 'txt2vid';
            if (batchFile) return 'file2img';
            if (hasRef) return hasPrompt ? 'img2img' : 'describe2img';
            return 'txt2img';
        }

        // ── Soumission ──
        btn.addEventListener('click', function () {
            const mode = deriveMode();
            const hasRef = !!(refInput && refInput.files && refInput.files.length);
            if (!batchFile && !hasRef && !(promptEl.value || '').trim()) {
                toast('Décrivez ce que vous voulez générer, ou fournissez une image / un fichier de prompts.', 'warning');
                return;
            }
            const fd = new FormData();
            fd.append('generation_mode', mode);
            fd.append('prompt', (promptEl.value || '').trim());
            fd.append('model', select.value || 'auto');
            if (batchFile) fd.append('prompt_file', batchFile);
            if (hasRef) fd.append('reference_image', refInput.files[0]);

            btn.disabled = true;
            fetch(CFG.urls.create, { method: 'POST', headers: { 'X-CSRFToken': CFG.csrf }, body: fd })
                .then(function (r) { return r.json().catch(function () { return {}; }).then(function (j) { return { ok: r.ok, j: j }; }); })
                .then(function (res) {
                    if (!res.ok || res.j.error) throw new Error(res.j.error || 'Création impossible');
                    // La card PENDING est rendue côté serveur → rechargement (provisoire :
                    // remplacé par card_html/refreshCard au palier « fondation file »).
                    window.location.reload();
                })
                .catch(function (e) { toast(e.message || 'Erreur de création', 'danger'); btn.disabled = false; });
        });
    }

    document.addEventListener('DOMContentLoaded', function () {
        initDomain({
            prefix: 'img', domain: 'image', allowBatch: true,
            selectId: 'imgModelSelect', promptId: 'imgPrompt',
            fileInputId: 'imgFileInput', dropZoneId: 'imgDropZone',
            refInputId: 'imgRefInput', refChipId: 'imgRefChip', refSlotId: 'imgRefSlot',
            statusId: 'imgMatchStatus', btnId: 'imgGenerateBtn',
        });
        initDomain({
            prefix: 'vid', domain: 'video', allowBatch: false,
            selectId: 'vidModelSelect', promptId: 'vidPrompt',
            fileInputId: 'vidFileInput', dropZoneId: 'vidDropZone',
            refInputId: 'vidRefInput', refChipId: 'vidRefChip', refSlotId: 'vidRefSlot',
            statusId: 'vidMatchStatus', btnId: 'vidGenerateBtn',
        });
    });
})();
