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

    function framesOf(doc) {
        var by = {};
        ((doc && doc.frames) || []).forEach(function (f) { by[f.i] = (by[f.i] || []).concat(f.d || []); });
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

    global.WamaDetections = {
        MIN_IOU: MIN_IOU, iou: iou, applyCorrections: applyCorrections, objects: objects,
        remove: remove, restore: restore, add: add, move: move,
    };
})(typeof window !== 'undefined' ? window : this);
