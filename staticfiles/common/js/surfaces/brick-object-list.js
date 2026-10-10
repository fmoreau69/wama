/**
 * Brique `object_list` — les objets d'un document de détections et de ses corrections
 * (chantier SURFACES, 2026-10-10). Universelle : elle ne lit que le rôle `detections` et la
 * couche de corrections (`WamaDetections`).
 *
 * En tête : les comptes par classe — gardés, retirés, ajoutés à la main — c'est ce qu'une
 * vérification veut savoir d'un coup d'œil (« 559 visages, 3 retirés, 12 ajoutés »).
 * Une ligne par objet : un clic le sélectionne et centre l'image dessus (événement `select`
 * du noyau) ; ✕ le retire, ↺ le rétablit.
 */
(function (global) {
    'use strict';

    var D = global.WamaDetections;
    var ORIGIN = { detected: 'détecté', manual: 'ajouté' };

    function mount(body, ctx, options) {
        var frameIndex = options.frame || 0;
        body.classList.add('wama-brick-objects');
        var summary = document.createElement('div');
        summary.className = 'wama-objects-summary';
        var list = document.createElement('div');
        list.className = 'wama-objects-list';
        body.appendChild(summary);
        body.appendChild(list);
        var objects = [];

        function row(o) {
            var el = document.createElement('div');
            el.className = 'wama-object-row' + (o.removed ? ' is-removed' : '') +
                (o.origin === 'manual' ? ' is-manual' : '') +
                (o.id === ctx.selected() ? ' is-selected' : '');
            el.dataset.id = o.id;
            var w = Math.round(o.box[2] - o.box[0]), h = Math.round(o.box[3] - o.box[1]);
            var label = document.createElement('span');
            label.className = 'wama-object-label';
            label.textContent = o.label || '—';
            var meta = document.createElement('span');
            meta.className = 'wama-object-meta';
            meta.textContent = ORIGIN[o.origin] + (o.origin === 'detected' && o.conf != null
                ? ' ' + Math.round(o.conf * 100) + ' %' : '') + ' · ' + w + '×' + h;
            el.appendChild(label);
            el.appendChild(meta);
            if (ctx.canEdit) {
                var btn = document.createElement('button');
                btn.type = 'button';
                btn.className = 'btn btn-xs';
                btn.dataset.act = o.removed ? 'restore' : 'remove';
                btn.title = o.removed ? 'Rétablir (R)' : 'Retirer (Suppr)';
                btn.innerHTML = o.removed ? '<i class="fas fa-rotate-left"></i>' : '<i class="fas fa-xmark"></i>';
                el.appendChild(btn);
            }
            return el;
        }

        function counts() {
            var by = {};
            objects.forEach(function (o) {
                var c = by[o.label || '—'] = by[o.label || '—'] || { kept: 0, removed: 0, added: 0 };
                if (o.removed) c.removed += 1;
                else if (o.origin === 'manual') c.added += 1;
                else c.kept += 1;
            });
            summary.innerHTML = '';
            Object.keys(by).sort().forEach(function (label) {
                var c = by[label];
                var line = document.createElement('div');
                line.textContent = label + ' : ' + (c.kept + c.added) +
                    (c.removed ? ' · ' + c.removed + ' retiré(s)' : '') +
                    (c.added ? ' · ' + c.added + ' ajouté(s)' : '');
                summary.appendChild(line);
            });
            if (!objects.length) summary.textContent = 'Aucun objet.';
        }

        function refresh() {
            objects = D.objects(ctx.reads().detections, ctx.value(), frameIndex);
            counts();
            var frag = document.createDocumentFragment();
            objects.forEach(function (o) { frag.appendChild(row(o)); });
            list.innerHTML = '';
            list.appendChild(frag);
        }

        list.addEventListener('click', function (ev) {
            var el = ev.target.closest('.wama-object-row');
            if (!el) return;
            var o = objects.filter(function (x) { return x.id === el.dataset.id; })[0];
            if (!o) return;
            var act = ev.target.closest('button') && ev.target.closest('button').dataset.act;
            if (act === 'remove') ctx.edit(function (v) { return D.remove(v, o, frameIndex); });
            else if (act === 'restore') ctx.edit(function (v) { return D.restore(v, o, frameIndex); });
            else ctx.select(o.id, { focus: true });
        });

        ctx.on('select', function (s) {
            list.querySelectorAll('.wama-object-row').forEach(function (el) {
                var on = el.dataset.id === s.id;
                el.classList.toggle('is-selected', on);
                if (on) el.scrollIntoView({ block: 'nearest' });
            });
        });

        refresh();
        return { refresh: refresh };
    }

    global.WamaSurface.registerBrick('object_list', { title: 'Objets', mount: mount });
})(window);
