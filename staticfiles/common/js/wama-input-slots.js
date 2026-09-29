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
        // Un fichier DÉSIGNÉ (médiathèque, arbre — pointé, pas téléversé) s'affiche comme un
        // fichier joint : même chip, même ✕ (2026-09-28, `WamaApp.designateInto`).
        var designation = (!files.length && global.WamaApp && WamaApp.designationOf)
            ? WamaApp.designationOf(input) : null;
        if (designation) files = [{ name: designation.name, size: 0, designated: true }];
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
        // Un fichier DÉSIGNÉ n'a pas de taille côté navigateur : il est pointé, pas téléversé.
        if (meta) meta.textContent = files.length + ' fichier(s) · ' + (designation
            ? 'désigné (pointé, non copié)' : (total / 1048576).toFixed(1) + ' Mio');
        showFace(pane, 'files');
    }

    /** Retire un fichier de l'input (DataTransfer : seule façon de rebâtir une FileList). */
    function removeAt(card, pane, index) {
        var input = inputOf(pane);
        if (!input || !input.files) return;
        if (!input.files.length && global.WamaApp && WamaApp.designationOf
                && WamaApp.designationOf(input)) {
            WamaApp.clearDesignation(input);          // la désignation affichée est la seule entrée
            renderFiles(card, pane);
            input.dispatchEvent(new Event('change', { bubbles: true }));
            return;
        }
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
        // port, plus de la card. L'asset est DÉSIGNÉ par la voie d'import du port (même geste
        // que la tuile v3, `WamaApp.pickFromLibrary`, 2026-09-28) — pointé, jamais re-téléversé.
        // `prefer` = l'ONGLET d'ouverture que l'app déclare pour ce port (`library_natures` du
        // domaine : l'image de l'avatarizer s'ouvre sur « avatar », 2026-09-29).
        var lib = pane.querySelector('[data-mod-library-btn]');
        var own = pane.querySelector('[data-port-import-self]');
        if (lib && input) {
            lib.addEventListener('click', function () {
                if (global.WamaApp && WamaApp.pickFromLibrary) {
                    WamaApp.pickFromLibrary({ type: pane.dataset.portLibrary || 'all',
                                              prefer: pane.dataset.portLibraryPrefer || undefined,
                                              designate: !!own,
                                              fileInputId: input.id });
                }
            });
        }

        // Tuile IMPORT d'un port SANS voie d'import (`data-port-import-self` : port de travail
        // secondaire, port de référence) — celle-là, personne d'autre ne la câble : clic =
        // sélecteur, dépôt = fichier(s) posé(s) dans l'input du port. Le `change` fait le reste.
        if (own && input && own.dataset.slotsImportBound !== '1') {
            own.dataset.slotsImportBound = '1';
            own.addEventListener('click', function (e) {
                if (e.target && e.target.closest && e.target.closest('a, input')) return;
                input.click();
            });
            own.addEventListener('dragover', function (e) {
                e.preventDefault();
                own.classList.add('dragover', 'drag-over');
            });
            own.addEventListener('dragleave', function () { own.classList.remove('dragover', 'drag-over'); });
            own.addEventListener('drop', function (e) {
                e.preventDefault();
                own.classList.remove('dragover', 'drag-over');
                var files = (e.dataTransfer && e.dataTransfer.files) ? Array.prototype.slice.call(e.dataTransfer.files) : [];
                // Le DÉPÔT ne passe pas par le filtre du sélecteur (`accept`) : on refuse ici avec
                // la règle de la voie d'import (`WamaImport.accepts`, 2026-09-29) — un `.txt` posé
                // sur une mélodie de référence y serait entré, et serait parti comme audio.
                var check = global.WamaImport && WamaImport.accepts;
                var kept = check ? files.filter(function (f) { return check(input, f); }) : files;
                if (kept.length < files.length) {
                    var tabEl = card.querySelector('[data-port-tab="' + pane.dataset.portPane + '"]');
                    var label = tabEl ? tabEl.textContent.trim().replace(/\s+/g, ' ') : 'ce port';
                    toast('Non accepté par « ' + label + ' » : '
                          + files.filter(function (f) { return kept.indexOf(f) < 0; })
                                 .map(function (f) { return f.name; }).join(', '));
                }
                if (kept.length && global.WamaApp && WamaApp.injectFiles) WamaApp.injectFiles(input, kept);
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

    /** Montre l'onglet `id` et son pane. */
    function activate(card, id) {
        card.querySelectorAll('[data-port-tab]').forEach(function (t) {
            t.classList.toggle('is-active', t.dataset.portTab === id);
        });
        card.querySelectorAll('[data-port-pane]').forEach(function (p) {
            p.classList.toggle('is-active', p.dataset.portPane === id);
        });
    }

    function toast(msg) {
        if (global.WamaApp && WamaApp.toast) WamaApp.toast(msg, 'error'); else alert(msg);
    }

    /** Pane LOT (2026-09-29) — pas un port : il n'a pas d'input de port, il remet le fichier à
     *  la brique de lot de la card (`WamaBatchImport`, retrouvée par la base d'ids de sa barre),
     *  en intention DÉCLARÉE. Et il bascule dessus quand la barre s'ouvre, quelle que soit la
     *  voie qui a apporté le lot (dépôt sur le port de travail, texte collé). */
    function wireLot(card, pane) {
        var base = pane.dataset.lotBase || 'batch';
        var input = pane.querySelector('[data-lot-input]');
        var tile = pane.querySelector('[data-lot-import]');
        var tab = card.querySelector('[data-port-tab="lot"] [data-port-count]');

        function take(file) {
            var batch = global.WamaBatchImport && WamaBatchImport.instances
                && WamaBatchImport.instances[base];
            if (!batch || !batch.previewFile) {
                toast("L'import de lot n'est pas branché sur cette page.");
                return;
            }
            batch.previewFile(file);
        }

        if (tile && input) {
            tile.addEventListener('click', function (e) {
                if (e.target && e.target.closest && e.target.closest('a, input')) return;
                input.click();
            });
            tile.addEventListener('dragover', function (e) {
                e.preventDefault();
                tile.classList.add('dragover', 'drag-over');
            });
            tile.addEventListener('dragleave', function () { tile.classList.remove('dragover', 'drag-over'); });
            tile.addEventListener('drop', function (e) {
                e.preventDefault();
                e.stopPropagation();       // le lot n'est pas un fichier de travail
                tile.classList.remove('dragover', 'drag-over');
                var files = (e.dataTransfer && e.dataTransfer.files) || [];
                if (files.length) take(files[0]);
            });
            input.addEventListener('change', function () {
                if (input.files && input.files.length) take(input.files[0]);
                input.value = '';          // re-choisir le même fichier doit re-déclencher
            });
        }

        card.addEventListener('wama:batch-shown', function (e) {
            if (!e.detail || e.detail.base !== base) return;
            activate(card, 'lot');
            var list = pane.querySelector('[data-files-list]');
            var title = pane.querySelector('[data-files-title]');
            if (title) title.textContent = e.detail.name || 'lot';
            if (list) {
                list.textContent = '';
                var chip = document.createElement('span');
                chip.className = 'wama-file-chip';
                chip.textContent = e.detail.count + ' élément(s) reconnu(s)';
                list.appendChild(chip);
            }
            if (tab) tab.textContent = '· ' + e.detail.count;
            showFace(pane, 'files');
        });
        card.addEventListener('wama:batch-hidden', function (e) {
            if (!e.detail || e.detail.base !== base) return;
            if (tab) tab.textContent = '';
            showFace(pane, 'mods');
        });
        var back = pane.querySelector('[data-files-back]');
        if (back) back.addEventListener('click', function () { showFace(pane, 'mods'); });
    }

    function wire(card) {
        if (card.dataset.slotsWired === '1') return;
        card.dataset.slotsWired = '1';
        card.querySelectorAll('[data-port-tab]').forEach(function (tab) {
            tab.addEventListener('click', function (e) {
                e.stopPropagation();   // ne pas replier la card
                activate(card, tab.dataset.portTab);
            });
        });
        card.querySelectorAll('[data-port-pane]').forEach(function (p) {
            if (p.dataset.portKind === 'file') wirePane(card, p);
            else if (p.dataset.portKind === 'lot') wireLot(card, p);
        });
    }

    function boot() { document.querySelectorAll('[data-wama-ports]').forEach(wire); }
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
    else boot();

    global.WamaInputSlots = { renderFiles: renderFiles, showFace: showFace, activate: activate };
})(window);
