/**
 * WAMA — ZONE DE PREVIEW de la card d'entrée (card v4) : ports en onglets, modalités dans la
 * preview, bascule sur les fichiers attachés. Spec : CARD_DESIGN.md §11.11 B / B bis / D.
 *
 * Le contrat, en une phrase : le PORT est la case, la MODALITÉ est ce qu'on y met.
 *   - onglet `[data-port-tab]`  → montre le pane `[data-port-pane]` du port ;
 *   - face `mods` du pane       → TOUTES les modalités du port, visibles d'un coup ;
 *   - face `files`              → ce qui est attaché à l'input du port (liste ou aperçu) ;
 *   - la hauteur ne change JAMAIS (CSS) ; ce qui déborde défile.
 *
 * CE QUE CETTE BRIQUE NE FAIT PAS, et pourquoi : elle n'ENVOIE rien. L'import reste le geste
 * des briques existantes — `WamaImport` (liée aux ids `dropZoneId`/`fileInputId`/`folderInputId`,
 * qui sont ceux de la v3), `batch-import.js`, `MediaPicker`, `WamaInputMatch` (chip du fichier
 * de référence, requis/suggéré) — et du JS d'app, dont les ids sont préservés. La modalité
 * « attache » d'une card `data-wama-depot="attache"` n'est PAS un autre chemin : le fichier
 * entre dans l'input du port, et le `change` de l'app fait le reste (le geste de MediaPicker).
 *
 * Zéro code par app : auto-init sur DOMContentLoaded. Garde anti-double-init comme
 * wama-new-item-card.js.
 */
(function (global) {
    'use strict';

    function inputOf(pane) {
        var id = pane.dataset.portInput;
        return (id && document.getElementById(id)) || pane.querySelector('input[type="file"]');
    }

    function showFace(pane, name) {
        pane.querySelectorAll('[data-port-face]').forEach(function (f) {
            f.classList.toggle('is-active', f.dataset.portFace === name);
        });
    }

    /** Liste des fichiers attachés au port — ou l'aperçu quand il n'y en a qu'UN (§11.11 E).
     *  La règle vit ici et nulle part ailleurs : une preview de MÉDIA n'a de sens qu'à un
     *  fichier ; à N, c'est une liste retirable qui défile, même cadre, même hauteur. */
    function renderFiles(card, pane) {
        var input = inputOf(pane);
        var list = pane.querySelector('[data-files-list]');
        var meta = pane.querySelector('[data-files-meta]');
        var title = pane.querySelector('[data-files-title]');
        var tab = card.querySelector('[data-port-tab="' + pane.dataset.portPane + '"] [data-port-count]');
        var files = (input && input.files) ? Array.prototype.slice.call(input.files) : [];
        if (tab) tab.textContent = files.length ? '· ' + files.length : '';
        if (!list) return;
        list.textContent = '';
        if (!files.length) { showFace(pane, 'mods'); if (meta) meta.textContent = ''; return; }
        var total = 0;
        files.forEach(function (f, i) {
            total += f.size || 0;
            var chip = document.createElement('span');
            chip.className = 'wama-file-chip';
            chip.title = f.name;
            chip.appendChild(document.createTextNode(f.name));
            var x = document.createElement('span');
            x.className = 'wama-file-x'; x.textContent = '✕'; x.setAttribute('role', 'button'); x.title = 'Retirer';
            x.addEventListener('click', function (ev) { ev.stopPropagation(); removeAt(card, pane, i); });
            chip.appendChild(x);
            list.appendChild(chip);
        });
        if (title) title.textContent = files.length === 1 ? files[0].name : files.length + ' fichiers';
        if (meta) meta.textContent = files.length + ' fichier(s) · ' + (total / 1048576).toFixed(1) + ' Mio';
        showFace(pane, 'files');
    }

    /** Retire un fichier de l'input (DataTransfer : seule façon de rebâtir une FileList). */
    function removeAt(card, pane, index) {
        var input = inputOf(pane);
        if (!input || !input.files) return;
        try {
            var dt = new DataTransfer();
            Array.prototype.forEach.call(input.files, function (f, i) { if (i !== index) dt.items.add(f); });
            input.files = dt.files;
        } catch (e) { return; }
        renderFiles(card, pane);
        input.dispatchEvent(new Event('change', { bubbles: true }));
    }

    function wirePane(card, pane) {
        var input = inputOf(pane);

        // Onglet → pane
        // (câblé au niveau card, voir wire)

        // Tuile IMPORT : c'est la dropzone — et cette brique NE la câble PAS. Sur une card
        // « crée », `WamaImport` s'y lie par ses ids (clic + drop + dossier) ; sur une card
        // « attache », c'est le JS de l'app (imager : routeFile ; avatarizer : handleAudioFile)
        // qui écoute sa zone, exactement comme en v3. Un second écouteur ici doublerait le
        // geste. La v4 change la PRÉSENTATION des modalités, jamais qui les traite.

        // Tuile MÉDIATHÈQUE — filtrée PAR PORT (exigence 5 du §11.8) : le filtre vient du
        // port, plus de la card. Le File choisi entre dans l'input du port (le geste commun).
        var lib = pane.querySelector('[data-mod-library-btn]');
        if (lib && input) {
            lib.addEventListener('click', function () {
                if (typeof global.MediaPicker === 'undefined') return;
                MediaPicker.open({
                    type: pane.dataset.portLibrary || 'all',
                    onSelect: function (f) {
                        if (!f) return;
                        if (global.WamaApp && WamaApp.injectFiles) WamaApp.injectFiles(input, [f]);
                    }
                });
            });
        }

        // Les fichiers arrivent par l'input, quelle que soit la modalité : un seul point
        // d'écoute → la face FICHIERS.
        if (input) {
            input.addEventListener('change', function () { renderFiles(card, pane); });
        }
        var back = pane.querySelector('[data-files-back]');
        if (back) back.addEventListener('click', function () { showFace(pane, 'mods'); });
    }

    function wire(card) {
        if (card.dataset.slotsWired === '1') return;
        card.dataset.slotsWired = '1';
        var tabs = card.querySelectorAll('[data-port-tab]');
        var panes = card.querySelectorAll('[data-port-pane]');
        tabs.forEach(function (tab) {
            tab.addEventListener('click', function (e) {
                e.stopPropagation();   // ne pas replier la card
                tabs.forEach(function (t) { t.classList.toggle('is-active', t === tab); });
                panes.forEach(function (p) { p.classList.toggle('is-active', p.dataset.portPane === tab.dataset.portTab); });
            });
        });
        panes.forEach(function (p) { if (p.dataset.portKind === 'file') wirePane(card, p); });
    }

    function boot() { document.querySelectorAll('[data-wama-ports]').forEach(wire); }
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
    else boot();

    global.WamaInputSlots = { renderFiles: renderFiles, showFace: showFace };
})(window);
