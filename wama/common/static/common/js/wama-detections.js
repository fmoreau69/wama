/**
 * wama-detections.js — les détections et leurs CORRECTIONS humaines, côté navigateur.
 *
 * Le pendant JS de `common/utils/detections.apply_corrections` (2026-10-10, chantier
 * SURFACES) : la page de correction doit montrer EN DIRECT ce que le floutage fera, donc
 * appliquer la même règle — un retrait ôte, sur sa frame, les détections qu'il recouvre à
 * IoU ≥ 0,5 ; un ajout entre « manuel ». ⚠ Deux écritures d'une même règle ne tiennent que si
 * un test les confronte : `tests_surfaces.CorrectionsParityTest` exécute ce fichier (V8) et la
 * fonction Python sur les mêmes cas.
 *
 * Couche de corrections : {added: [{i, box, label}], removed: [{i, box}]} — jamais le document
 * du détecteur, qui reste tel qu'il a été produit.
 *
 * Les GESTES (retirer, rétablir, ajouter, déplacer) rendent une NOUVELLE couche : l'appelant
 * garde l'ancienne pour l'historique (`wama-history.js`).
 */
(function (global) {
    'use strict';

    var MIN_IOU = 0.5;   // = detections.CORRECTION_MIN_IOU

    function iou(a, b) {
        var ix = Math.max(0, Math.min(a[2], b[2]) - Math.max(a[0], b[0]));
        var iy = Math.max(0, Math.min(a[3], b[3]) - Math.max(a[1], b[1]));
        var inter = ix * iy;
        var union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter;
        return union > 0 ? inter / union : 0;
    }

    /** L'arrondi de Python (`round` : au PAIR sur ,5) — `Math.round` arrondit vers le haut, et
     *  les deux écritures de la règle divergeraient d'un pixel sur 2,5. */
    function roundHalfEven(v) {
        var f = Math.floor(v), d = v - f;
        if (d > 0.5) return f + 1;
        if (d < 0.5) return f;
        return f % 2 === 0 ? f : f + 1;
    }

    function layer(value) {
        value = value || {};
        return { added: (value.added || []).slice(), removed: (value.removed || []).slice() };
    }

    /** `{indice d'image: [détections]}` d'un document — GARDÉ sur le document (propriété cachée,
     *  hors de sa forme JSON) : une vidéo le demande à chaque image montrée, et un document de
     *  plusieurs milliers d'images ne se réindexe pas vingt-cinq fois par seconde (2026-11-15). */
    function framesOf(doc) {
        if (doc && doc.__byFrame) return doc.__byFrame;
        var by = {};
        ((doc && doc.frames) || []).forEach(function (f) { by[f.i] = (by[f.i] || []).concat(f.d || []); });
        if (doc && typeof doc === 'object') {
            try { Object.defineProperty(doc, '__byFrame', { value: by, enumerable: false }); } catch (e) { /* figé */ }
        }
        return by;
    }

    /** Le document CORRIGÉ (mêmes règles que la fonction Python) — pour le test de parité. */
    function applyCorrections(doc, value) {
        var c = layer(value);
        if (!c.added.length && !c.removed.length) return doc;
        var gone = {};
        c.removed.forEach(function (r) { (gone[r.i] = gone[r.i] || []).push(r.box); });
        var by = framesOf(doc), frames = {};
        Object.keys(by).forEach(function (i) {
            var kept = by[i].filter(function (d) {
                return !(gone[i] || []).some(function (box) { return iou(d.box, box) >= MIN_IOU; });
            });
            if (kept.length) frames[i] = kept.map(function (d) { return Object.assign({}, d); });
        });
        c.added.forEach(function (a) {
            var entry = { label: a.label || 'face', conf: 1, manual: true,
                          box: a.box.map(roundHalfEven) };
            (frames[a.i] = frames[a.i] || []).push(entry);
        });
        var out = Object.assign({}, doc);
        out.frames = Object.keys(frames).map(Number).sort(function (a, b) { return a - b; })
            .map(function (i) { return { i: i, d: frames[i] }; });
        out.corrected = { added: c.added.length, removed: c.removed.length };
        return out;
    }

    /**
     * Les OBJETS d'une frame tels que la page les montre : les détections (retirées ou non) et
     * les ajouts. `id` : `d<k>` (k-ième détection de la frame) ou `a<k>` (k-ième ajout).
     */
    function objects(doc, value, frame) {
        frame = frame || 0;
        var c = layer(value);
        var removed = c.removed.filter(function (r) { return r.i === frame; });
        var list = (framesOf(doc)[frame] || []).map(function (d, k) {
            return { id: 'd' + k, box: d.box, label: d.label || '', conf: d.conf,
                     origin: 'detected',
                     removed: removed.some(function (r) { return iou(d.box, r.box) >= MIN_IOU; }) };
        });
        c.added.forEach(function (a, k) {
            if (a.i === frame) list.push({ id: 'a' + k, box: a.box, label: a.label || '',
                                           conf: 1, origin: 'manual', removed: false });
        });
        return list;
    }

    function round(box) { return box.map(function (v) { return Math.round(v * 10) / 10; }); }

    /** Retirer : une détection → un retrait ; un ajout → il disparaît. */
    function remove(value, obj, frame) {
        var c = layer(value);
        if (obj.origin === 'manual') c.added.splice(Number(obj.id.slice(1)), 1);
        else if (!obj.removed) c.removed.push({ i: frame || 0, box: round(obj.box) });
        return c;
    }

    /** Rétablir une détection retirée : ôte les retraits qui la recouvrent. */
    function restore(value, obj, frame) {
        var c = layer(value);
        c.removed = c.removed.filter(function (r) {
            return !(r.i === (frame || 0) && iou(obj.box, r.box) >= MIN_IOU);
        });
        return c;
    }

    function add(value, box, label, frame) {
        var c = layer(value);
        c.added.push({ i: frame || 0, box: round(box), label: label || 'face' });
        return c;
    }

    /** Déplacer / redimensionner : un ajout change de place ; une détection devient un retrait
     *  plus un ajout (le détecteur ne l'a pas vue là). */
    function move(value, obj, box, frame) {
        if (obj.origin === 'manual') {
            var c = layer(value);
            var k = Number(obj.id.slice(1));
            c.added[k] = Object.assign({}, c.added[k], { box: round(box) });
            return c;
        }
        return add(remove(value, obj, frame), box, obj.label, frame);
    }

    /** Retirer un objet sur PLUSIEURS images (`entries` : `[{i, box}]`, la chaîne d'un objet) :
     *  un retrait par image, sauf là où un retrait le désigne déjà. */
    function removeMany(value, entries) {
        var c = layer(value);
        (entries || []).forEach(function (e) {
            var already = c.removed.some(function (r) { return r.i === e.i && iou(e.box, r.box) >= MIN_IOU; });
            if (!already) c.removed.push({ i: e.i, box: round(e.box) });
        });
        return c;
    }

    /** Rétablir un objet sur plusieurs images : ôte les retraits qui le désignent, image par image. */
    function restoreMany(value, entries) {
        var c = layer(value);
        var by = {};
        (entries || []).forEach(function (e) { (by[e.i] = by[e.i] || []).push(e.box); });
        c.removed = c.removed.filter(function (r) {
            return !(by[r.i] || []).some(function (box) { return iou(box, r.box) >= MIN_IOU; });
        });
        return c;
    }

    /** L'OBJET sur toute la séquence (2026-11-15) : promesse de `[{i, box, label}]`, demandée à
     *  la route commune de la surface (`?only=chain`, `detections.object_chain` — la règle de
     *  « c'est le même objet » n'est écrite qu'en Python). `gap` : le trou franchi, que la surface
     *  donne par son contexte (`chain_gap`). Un ajout à la main n'a pas de chaîne : lui seul. */
    function chain(ctx, role, obj, frame) {
        if (obj.origin !== 'detected') return Promise.resolve([{ i: frame, box: obj.box, label: obj.label }]);
        var gap = Number((ctx.context() || {}).chain_gap) || 0;
        var url = ctx.config.data_url + '?only=chain&role=' + encodeURIComponent(role) +
            '&i=' + frame + '&box=' + obj.box.join(',') + '&gap=' + gap;
        return fetch(url, { credentials: 'same-origin' })
            .then(function (r) { return r.json(); })
            .then(function (res) {
                if (res.error) throw new Error(res.error);
                return (res.chain && res.chain.length) ? res.chain : [{ i: frame, box: obj.box, label: obj.label }];
            });
    }

    /** Retirer ou rétablir (`kind`) l'objet `obj` de l'image `frame` — sur cette image, ou, la
     *  portée « toute la séquence » prise (`sequence`), sur toutes celles où il est : UN geste,
     *  un cran d'annulation. Rend une promesse du nombre d'images touchées. Le geste commun de
     *  la brique des zones et de la liste des objets. */
    function editObject(ctx, role, obj, frame, kind, sequence) {
        var one = kind === 'restore' ? restore : remove;
        if (!sequence || obj.origin !== 'detected') {
            ctx.edit(function (v) { return one(v, obj, frame); });
            return Promise.resolve(1);
        }
        return chain(ctx, role, obj, frame).then(function (entries) {
            ctx.edit(function (v) {
                return kind === 'restore' ? restoreMany(v, entries) : removeMany(v, entries);
            });
            return entries.length;
        });
    }

    global.WamaDetections = {
        MIN_IOU: MIN_IOU, iou: iou, applyCorrections: applyCorrections, objects: objects,
        remove: remove, restore: restore, add: add, move: move,
        removeMany: removeMany, restoreMany: restoreMany, chain: chain, editObject: editObject,
    };
})(typeof window !== 'undefined' ? window : this);
