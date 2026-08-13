/**
 * WAMA — Import de DOSSIER récursif (brique commune, facette F2).
 *
 * EXTRAIT du filemanager le 2026-08-13 (readEntry / readAllDirectoryEntries, 1er domicile
 * historique) : la traversée récursive d'un drop (webkitGetAsEntry) et la lecture d'un
 * <input webkitdirectory> ne vivaient que dans filemanager.js — critère `recursive_import`
 * mesuré 0/10 sur les apps. Montée GLOBALE dans base.html (avant filemanager.js).
 *
 * API (window.WamaFolderImport) — tout retourne des [{file, relativePath}] :
 *   collect(dataTransfer) → Promise<liste>  drop mêlant fichiers et dossiers (récursif,
 *                                           batching readEntries ; repli plat sans entries)
 *   fromInput(fileList)   → liste           input webkitdirectory (webkitRelativePath)
 *   files(liste)          → File[]          pour les apps sans notion d'arborescence
 *
 * Adoption par une app (2 lignes dans son handler de drop) :
 *   WamaFolderImport.collect(e.dataTransfer)
 *       .then(function (l) { handleFiles(WamaFolderImport.files(l)); });
 * + `folder_input_id` sur `_new_item_card.html` pour l'affordance « importer un dossier ».
 * Le filemanager conserve relativePath (il recrée l'arborescence) ; les apps l'ignorent.
 */
(function () {
    'use strict';

    function readBatch(reader) {
        return new Promise(function (resolve, reject) { reader.readEntries(resolve, reject); });
    }

    // readEntries rend les résultats PAR LOTS (100 max sur Chromium) : lire jusqu'au lot vide.
    async function readAllDirectoryEntries(reader) {
        const all = [];
        let batch;
        do {
            try {
                batch = await readBatch(reader);
                all.push(...batch);
            } catch (err) {
                console.error('[WamaFolderImport] readEntries :', err);
                break;
            }
        } while (batch && batch.length > 0);
        return all;
    }

    async function readEntry(entry, parentPath, out) {
        try {
            if (entry.isFile) {
                const file = await new Promise(function (res, rej) { entry.file(res, rej); });
                out.push({ file: file, relativePath: parentPath ? parentPath + '/' + entry.name : entry.name });
            } else if (entry.isDirectory) {
                const dirPath = parentPath ? parentPath + '/' + entry.name : entry.name;
                const children = await readAllDirectoryEntries(entry.createReader());
                await Promise.all(children.map(function (c) { return readEntry(c, dirPath, out); }));
            }
        } catch (err) {
            console.error('[WamaFolderImport] entrée illisible :', entry && entry.name, err);
        }
    }

    async function collect(dataTransfer) {
        const out = [];
        const items = dataTransfer && dataTransfer.items;
        const entries = [];
        if (items) {
            for (let i = 0; i < items.length; i++) {
                const entry = items[i].webkitGetAsEntry && items[i].webkitGetAsEntry();
                if (entry) entries.push(entry);
            }
        }
        if (entries.length > 0) {
            await Promise.all(entries.map(function (en) { return readEntry(en, '', out); }));
            return out;
        }
        // Repli : navigateur sans webkitGetAsEntry, ou items vides — liste plate.
        const files = (dataTransfer && dataTransfer.files) || [];
        for (let i = 0; i < files.length; i++) {
            out.push({ file: files[i], relativePath: files[i].name });
        }
        return out;
    }

    function fromInput(fileList) {
        const out = [];
        for (let i = 0; i < (fileList || []).length; i++) {
            const f = fileList[i];
            out.push({ file: f, relativePath: f.webkitRelativePath || f.name });
        }
        return out;
    }

    function files(liste) {
        return (liste || []).map(function (x) { return x.file; });
    }

    window.WamaFolderImport = { collect: collect, fromInput: fromInput, files: files };
})();
