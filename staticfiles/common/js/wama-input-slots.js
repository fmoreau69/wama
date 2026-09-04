/**
 * WAMA — ZONE DE PREVIEW de la card d'entrée : bascule de modalité par SLOT (card v4).
 * Spec : CARD_DESIGN.md §11.11 · maquette : docs/card_designs/card_v4_maquette.html
 *
 * Le contrat, en une phrase : le PORT est la case, la MODALITÉ est ce qu'on y met.
 *   - une sous-division (`[data-wama-slot]`) par port déclaré, TOUJOURS visible ;
 *   - ses icônes (`[data-slot-mod]`) basculent le pane actif (`[data-slot-pane]`) ;
 *   - la hauteur ne change JAMAIS — ce qui déborde défile (CSS wama-input-slots.css).
 *
 * Ce que cette brique NE fait pas, et pourquoi : elle n'envoie rien au serveur. L'import
 * reste le geste des briques existantes (`WamaImport`, `batch-import.js`, `MediaPicker`) et
 * du JS d'app, dont les ids sont préservés par le gabarit. Ajouter un second chemin d'upload
 * ici créerait exactement la duplication que la v4 cherche à supprimer.
 *
 * Zéro code par app : auto-init sur DOMContentLoaded, comme wama-new-item-card.js.
 */
(function () {
    'use strict';

    /** Bascule le pane actif d'un slot. Silencieux si la modalité n'a pas de pane rendu
     *  (cas légitime : `folder` n'est émis que pour un port `multi`). */
    function activate(slot, modality) {
        var pane = slot.querySelector('[data-slot-pane="' + modality + '"]');
        if (!pane) return false;
        slot.querySelectorAll('[data-slot-pane]').forEach(function (p) {
            p.classList.toggle('is-active', p === pane);
        });
        slot.querySelectorAll('[data-slot-mod]').forEach(function (m) {
            m.classList.toggle('is-active', m.dataset.slotMod === modality);
        });
        return true;
    }

    /** Rend la LISTE des fichiers attachés — ou la preview quand il n'y en a qu'UN.
     *  La règle vit ici et nulle part ailleurs (§11.11 E) : une preview de média n'a de
     *  sens qu'à un seul fichier ; à N, c'est une liste qui défile. */
    function renderFiles(slot, files) {
        var list = slot.querySelector('[data-slot-filelist]');
        var meta = slot.querySelector('[data-slot-filemeta]');
        if (!list) return;
        list.textContent = '';
        if (!files || !files.length) {
            activate(slot, 'drop');
            if (meta) meta.textContent = '';
            return;
        }
        var total = 0;
        Array.prototype.forEach.call(files, function (f, i) {
            total += f.size || 0;
            var chip = document.createElement('span');
            chip.className = 'badge bg-info bg-opacity-10 text-info border border-info border-opacity-25';
            chip.textContent = f.name;
            var x = document.createElement('span');
            x.className = 'ms-1';
            x.textContent = '✕';
            x.setAttribute('role', 'button');
            x.title = 'Retirer';
            x.addEventListener('click', function (ev) {
                ev.stopPropagation();
                removeAt(slot, i);
            });
            chip.appendChild(x);
            list.appendChild(chip);
        });
        if (meta) {
            meta.textContent = files.length + ' fichier(s) · ' + (total / 1048576).toFixed(1) + ' Mio';
        }
        activate(slot, 'files');
    }

    /** Retire un fichier de l'input du slot (DataTransfer : la seule façon de reconstruire
     *  une FileList — `input.files` n'est pas mutable élément par élément). */
    function removeAt(slot, index) {
        var input = inputOf(slot);
        if (!input || !input.files) return;
        try {
            var dt = new DataTransfer();
            Array.prototype.forEach.call(input.files, function (f, i) {
                if (i !== index) dt.items.add(f);
            });
            input.files = dt.files;
            renderFiles(slot, input.files);
            input.dispatchEvent(new Event('change', { bubbles: true }));
        } catch (e) { /* navigateur sans DataTransfer : la liste reste, pas de crash */ }
    }

    function inputOf(slot) {
        var id = slot.dataset.slotInput;
        return id ? document.getElementById(id) : slot.querySelector('input[type="file"]');
    }

    function wire(slot) {
        if (slot.dataset.slotWired === '1') return;   // garde anti-double-init (cf. wama-new-item-card)
        slot.dataset.slotWired = '1';

        slot.querySelectorAll('[data-slot-mod]').forEach(function (mod) {
            mod.addEventListener('click', function (ev) {
                ev.stopPropagation();   // ne pas replier la card en cliquant une icône
                activate(slot, mod.dataset.slotMod);
            });
        });

        // Le slot EST la dropzone : cliquer n'importe où dans le pane `drop` ouvre le
        // sélecteur. C'est ce qui rend l'import simple gratuit — zéro clic de modalité.
        var dz = slot.querySelector('.wama-slot-dz');
        var input = inputOf(slot);
        if (dz && input) {
            dz.addEventListener('click', function () { input.click(); });
            ['dragenter', 'dragover'].forEach(function (t) {
                dz.addEventListener(t, function (ev) {
                    ev.preventDefault();
                    dz.classList.add('is-hot');
                });
            });
            ['dragleave', 'drop'].forEach(function (t) {
                dz.addEventListener(t, function () { dz.classList.remove('is-hot'); });
            });
        }

        // Les fichiers arrivent par l'input (dépôt, clic, médiathèque, filemanager) : un seul
        // point d'écoute suffit, quelle que soit la modalité qui les y a mis.
        if (input) {
            input.addEventListener('change', function () { renderFiles(slot, input.files); });
        }

        // Médiathèque PAR RÔLE (exigence 5 du §11.8) : le filtre vient du slot, plus de la
        // card. C'est ce qui règle « l'utilisateur ne sait pas le rôle du fichier importé ».
        var libBtn = slot.querySelector('[data-slot-library-btn]');
        if (libBtn && input) {
            libBtn.addEventListener('click', function () {
                if (typeof MediaPicker === 'undefined') return;
                MediaPicker.open({
                    type: slot.dataset.slotLibrary || 'all',
                    onSelect: function (f) {
                        if (!f) return;
                        try {
                            var dt = new DataTransfer();
                            dt.items.add(f);
                            input.files = dt.files;
                        } catch (e) { /* pas de DataTransfer : l'app garde son chemin */ }
                        input.dispatchEvent(new Event('change', { bubbles: true }));
                    }
                });
            });
        }
    }

    document.addEventListener('DOMContentLoaded', function () {
        document.querySelectorAll('[data-wama-slot]').forEach(wire);
    });

    window.WamaInputSlots = { activate: activate, renderFiles: renderFiles };
})();
