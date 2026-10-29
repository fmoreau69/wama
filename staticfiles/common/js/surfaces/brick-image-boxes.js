/**
 * Brique `image_boxes` — une image et ses zones, éditables (chantier SURFACES, 2026-10-10).
 *
 * Universelle : elle lit un rôle `image` (URL) et un rôle `detections` (document commun
 * `common/utils/detections`), et écrit une couche de CORRECTIONS (`WamaDetections`) — jamais
 * le document d'origine. Aucun mot d'app : l'anonymizer en est le premier consommateur, le Lab
 * ou le monde Data peuvent la monter sur tout document de détections.
 *
 * Rendu sur un <canvas> : une foule de 500 visages se dessine et se zoome sans créer 500
 * éléments DOM.
 *
 * Gestes (outil « Sélection ») : clic = sélectionner la zone la plus petite sous le pointeur ;
 * glisser dans la zone sélectionnée = la déplacer ; glisser une poignée = la redimensionner ;
 * glisser dans le vide = se déplacer dans l'image ; molette = zoom autour du pointeur.
 * Outil « Ajouter » (N) : glisser = tracer une zone, de la classe choisie.
 * Clavier : Suppr / Retour arrière = retirer ; R = rétablir une détection retirée ; N = ajouter ;
 * Échap = sélection ; F = image entière ; Ctrl+Z / Ctrl+Maj+Z (historique commun).
 */
(function (global) {
    'use strict';

    var D = global.WamaDetections;
    var HANDLE = 6;
    var COLORS = { detected: '#ffc107', manual: '#20c997', removed: '#dc3545', selected: '#0dcaf0' };

    function mount(body, ctx, options) {
        var frameIndex = options.frame || 0;
        body.classList.add('wama-brick-image');
        var canvas = document.createElement('canvas');
        canvas.tabIndex = 0;
        body.appendChild(canvas);
        var g = canvas.getContext('2d');
        var img = new Image();
        var view = { scale: 1, x: 0, y: 0, fitted: false };
        var tool = 'select';
        var drag = null;              // geste en cours : {kind, start, obj, box, handle}
        var objects = [];

        // ── Outils (dans le titre de la brique) ───────────────────────────────────────────
        var tools = document.createElement('div');
        tools.className = 'wama-brick-tools';
        tools.innerHTML =
            '<button type="button" class="btn btn-xs" data-tool="select" title="Sélection (Échap)"><i class="fas fa-arrow-pointer"></i></button>' +
            '<button type="button" class="btn btn-xs" data-tool="add" title="Ajouter une zone (N)"><i class="fas fa-vector-square"></i></button>' +
            '<select class="form-select form-select-sm wama-brick-class" title="Classe des zones ajoutées"></select>' +
            '<button type="button" class="btn btn-xs" data-act="fit" title="Image entière (F)"><i class="fas fa-expand"></i></button>' +
            '<span class="wama-brick-zoom"></span>';
        var classSelect = tools.querySelector('select');
        var zoomLabel = tools.querySelector('.wama-brick-zoom');
        tools.addEventListener('mousedown', function (e) { e.stopPropagation(); });
        tools.addEventListener('click', function (e) {
            var b = e.target.closest('button');
            if (!b) return;
            if (b.dataset.tool) setTool(b.dataset.tool);
            if (b.dataset.act === 'fit') fit();
        });

        function setTool(name) {
            tool = ctx.canEdit ? name : 'select';
            tools.querySelectorAll('[data-tool]').forEach(function (b) {
                b.classList.toggle('active', b.dataset.tool === tool);
            });
            canvas.style.cursor = tool === 'add' ? 'crosshair' : 'default';
        }

        function fillClasses() {
            var classes = (ctx.context().classes || []).filter(Boolean);
            if (!classes.length) classes = ['face'];
            classSelect.innerHTML = '';
            classes.forEach(function (c) {
                var o = document.createElement('option');
                o.value = c; o.textContent = c;
                classSelect.appendChild(o);
            });
            classSelect.disabled = !ctx.canEdit;
            tools.querySelector('[data-tool="add"]').disabled = !ctx.canEdit;
        }

        // ── Géométrie : image ↔ écran ─────────────────────────────────────────────────────
        function toScreen(p) { return [p[0] * view.scale + view.x, p[1] * view.scale + view.y]; }
        function toImage(p) { return [(p[0] - view.x) / view.scale, (p[1] - view.y) / view.scale]; }
        function point(ev) {
            var r = canvas.getBoundingClientRect();
            return [ev.clientX - r.left, ev.clientY - r.top];
        }

        function fit() {
            if (!img.naturalWidth) return;
            var w = canvas.clientWidth, h = canvas.clientHeight;
            view.scale = Math.min(w / img.naturalWidth, h / img.naturalHeight) || 1;
            view.x = (w - img.naturalWidth * view.scale) / 2;
            view.y = (h - img.naturalHeight * view.scale) / 2;
            view.fitted = true;
            draw();
        }

        function zoomAt(p, factor) {
            var before = toImage(p);
            view.scale = Math.max(0.05, Math.min(40, view.scale * factor));
            view.x = p[0] - before[0] * view.scale;
            view.y = p[1] - before[1] * view.scale;
            view.fitted = false;
            draw();
        }

        function focusOn(obj) {
            var w = canvas.clientWidth, h = canvas.clientHeight;
            var bw = obj.box[2] - obj.box[0], bh = obj.box[3] - obj.box[1];
            view.scale = Math.min(40, Math.max(view.scale, Math.min(w / (bw * 6), h / (bh * 6))));
            view.x = w / 2 - (obj.box[0] + bw / 2) * view.scale;
            view.y = h / 2 - (obj.box[1] + bh / 2) * view.scale;
            view.fitted = false;
            draw();
        }

        // ── Rendu ─────────────────────────────────────────────────────────────────────────
        function resize() {
            var ratio = global.devicePixelRatio || 1;
            var w = body.clientWidth, h = body.clientHeight;
            if (!w || !h) return;
            canvas.style.width = w + 'px';
            canvas.style.height = h + 'px';
            canvas.width = Math.round(w * ratio);
            canvas.height = Math.round(h * ratio);
            g.setTransform(ratio, 0, 0, ratio, 0, 0);
            if (view.fitted || !view.scale) fit(); else draw();
        }

        function screenBox(box) {
            var a = toScreen([box[0], box[1]]), b = toScreen([box[2], box[3]]);
            return [a[0], a[1], b[0] - a[0], b[1] - a[1]];
        }

        function draw() {
            var w = canvas.clientWidth, h = canvas.clientHeight;
            g.clearRect(0, 0, w, h);
            if (img.naturalWidth) {
                g.imageSmoothingEnabled = view.scale < 3;
                g.drawImage(img, view.x, view.y, img.naturalWidth * view.scale,
                            img.naturalHeight * view.scale);
            }
            var selected = ctx.selected();
            objects.forEach(function (o) {
                if (o.id === selected) return;
                var r = screenBox(o.box);
                g.lineWidth = 1.5;
                g.setLineDash(o.removed ? [4, 3] : []);
                g.strokeStyle = o.removed ? COLORS.removed : COLORS[o.origin];
                g.strokeRect(r[0], r[1], r[2], r[3]);
            });
            g.setLineDash([]);
            var sel = byId(selected);
            if (sel) {
                var box = drag && drag.obj && drag.obj.id === sel.id && drag.box ? drag.box : sel.box;
                var r = screenBox(box);
                g.lineWidth = 2.5;
                g.strokeStyle = sel.removed ? COLORS.removed : COLORS.selected;
                g.strokeRect(r[0], r[1], r[2], r[3]);
                if (!sel.removed && ctx.canEdit) handles(box).forEach(function (hd) {
                    g.fillStyle = COLORS.selected;
                    g.fillRect(hd.x - HANDLE / 2, hd.y - HANDLE / 2, HANDLE, HANDLE);
                });
            }
            if (drag && drag.kind === 'draw' && drag.box) {
                var d = screenBox(drag.box);
                g.lineWidth = 2;
                g.strokeStyle = COLORS.manual;
                g.strokeRect(d[0], d[1], d[2], d[3]);
            }
            zoomLabel.textContent = Math.round(view.scale * 100) + ' %';
        }

        function handles(box) {
            var r = screenBox(box);
            return [{ k: 'nw', x: r[0], y: r[1] }, { k: 'ne', x: r[0] + r[2], y: r[1] },
                    { k: 'sw', x: r[0], y: r[1] + r[3] }, { k: 'se', x: r[0] + r[2], y: r[1] + r[3] }];
        }

        function byId(id) {
            for (var k = 0; k < objects.length; k++) if (objects[k].id === id) return objects[k];
            return null;
        }

        function hit(p) {
            var q = toImage(p), best = null, area = Infinity;
            objects.forEach(function (o) {
                var b = o.box;
                if (q[0] >= b[0] && q[0] <= b[2] && q[1] >= b[1] && q[1] <= b[3]) {
                    var a = (b[2] - b[0]) * (b[3] - b[1]);
                    if (a < area) { area = a; best = o; }
                }
            });
            return best;
        }

        function handleAt(p) {
            var sel = byId(ctx.selected());
            if (!sel || sel.removed || !ctx.canEdit) return null;
            var found = null;
            handles(sel.box).forEach(function (hd) {
                if (Math.abs(p[0] - hd.x) <= HANDLE && Math.abs(p[1] - hd.y) <= HANDLE) found = hd.k;
            });
            return found;
        }

        function normalized(a, b) {
            return [Math.min(a[0], b[0]), Math.min(a[1], b[1]), Math.max(a[0], b[0]), Math.max(a[1], b[1])];
        }

        // ── Gestes ────────────────────────────────────────────────────────────────────────
        canvas.addEventListener('wheel', function (ev) {
            ev.preventDefault();
            zoomAt(point(ev), ev.deltaY < 0 ? 1.2 : 1 / 1.2);
        }, { passive: false });

        canvas.addEventListener('mousedown', function (ev) {
            if (ev.button !== 0) return;
            canvas.focus();
            var p = point(ev);
            if (tool === 'add' && ctx.canEdit) {
                drag = { kind: 'draw', start: toImage(p), box: null };
                return;
            }
            var hd = handleAt(p);
            var sel = byId(ctx.selected());
            if (hd) { drag = { kind: 'resize', handle: hd, obj: sel, start: toImage(p), box: sel.box.slice() }; return; }
            var o = hit(p);
            if (o && sel && o.id === sel.id && !o.removed && ctx.canEdit) {
                drag = { kind: 'move', obj: o, start: toImage(p), box: o.box.slice() };
                return;
            }
            if (o) { ctx.select(o.id); return; }
            ctx.select(null);
            drag = { kind: 'pan', start: p, view: { x: view.x, y: view.y } };
        });

        global.addEventListener('mousemove', function (ev) {
            if (!drag) return;
            var p = point(ev), q = toImage(p);
            if (drag.kind === 'pan') {
                view.x = drag.view.x + p[0] - drag.start[0];
                view.y = drag.view.y + p[1] - drag.start[1];
                view.fitted = false;
            } else if (drag.kind === 'draw') {
                drag.box = normalized(drag.start, q);
            } else if (drag.kind === 'move') {
                var dx = q[0] - drag.start[0], dy = q[1] - drag.start[1], b = drag.obj.box;
                drag.box = [b[0] + dx, b[1] + dy, b[2] + dx, b[3] + dy];
            } else if (drag.kind === 'resize') {
                var o = drag.obj.box.slice(), k = drag.handle;
                if (k.indexOf('n') >= 0) o[1] = q[1];
                if (k.indexOf('s') >= 0) o[3] = q[1];
                if (k.indexOf('w') >= 0) o[0] = q[0];
                if (k.indexOf('e') >= 0) o[2] = q[0];
                drag.box = normalized([o[0], o[1]], [o[2], o[3]]);
            }
            draw();
        });

        global.addEventListener('mouseup', function () {
            if (!drag) return;
            var done = drag;
            drag = null;
            var big = done.box && (done.box[2] - done.box[0]) * view.scale >= 4
                && (done.box[3] - done.box[1]) * view.scale >= 4;
            if (done.kind === 'draw' && big) {
                var label = classSelect.value || 'face';
                ctx.edit(function (v) { return D.add(v, done.box, label, frameIndex); });
                // La zone ajoutée est le DERNIER ajout : la sélectionner pour l'ajuster aussitôt.
                var added = (ctx.value().added || []).length - 1;
                ctx.select('a' + added);
            } else if ((done.kind === 'move' || done.kind === 'resize') && big) {
                var moved = done.box.join() !== done.obj.box.join();
                if (moved) {
                    ctx.edit(function (v) { return D.move(v, done.obj, done.box, frameIndex); });
                    if (done.obj.origin === 'detected') {
                        ctx.select('a' + ((ctx.value().added || []).length - 1));
                    }
                }
            }
            draw();
        });

        // Clavier : le clavier commun (`WamaKeys`, 2026-10-29) — une brique QUI A LA MAIN tant que
        // l'image est la dernière zone touchée : le canvas prend le focus au clic (`tabIndex`,
        // remesuré le 29/10, disposition figée comme modifiable), et le dernier clic compte quand
        // rien n'a le focus. (Le mousedown retenu par gridstack, mesuré au premier smoke, ne se
        // reproduit plus ; un clic sur une poignée de redimensionnement, lui, n'est pas dans
        // l'image.)
        global.WamaKeys.register({ owner: 'image_boxes', scope: 'brick', root: canvas, handle: function (ev) {
            if (ev.ctrlKey || ev.metaKey || ev.altKey) return false;
            var t = ev.target;
            if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.tagName === 'SELECT' || t.isContentEditable)) return false;
            var sel = byId(ctx.selected());
            var k = ev.key;
            if ((k === 'Delete' || k === 'Backspace') && sel && !sel.removed && ctx.canEdit) {
                ctx.edit(function (v) { return D.remove(v, sel, frameIndex); });
                if (sel.origin === 'manual') ctx.select(null);
            } else if ((k === 'r' || k === 'R') && sel && sel.removed && ctx.canEdit) {
                ctx.edit(function (v) { return D.restore(v, sel, frameIndex); });
            } else if (k === 'n' || k === 'N') {
                setTool('add');
            } else if (k === 'Escape') {
                setTool('select');
                ctx.select(null);
            } else if (k === 'f' || k === 'F') {
                fit();
            } else {
                return false;
            }
            return true;
        } });

        function refresh() {
            objects = D.objects(ctx.reads().detections, ctx.value(), frameIndex);
            if (canvas.width !== Math.round(body.clientWidth * (global.devicePixelRatio || 1))) resize();
            else draw();
        }

        ctx.on('select', function (s) {
            var o = byId(s.id);
            if (o && s.focus) focusOn(o); else draw();
        });

        if (global.ResizeObserver) new ResizeObserver(resize).observe(body);
        img.onload = function () { fit(); };
        img.src = ctx.reads().image || '';
        fillClasses();
        setTool('select');
        refresh();
        return { refresh: refresh, tools: tools,
                 help: 'Molette : zoom · glisser : se déplacer' };
    }

    global.WamaSurface.registerBrick('image_boxes', { title: 'Image et zones', mount: mount });
})(window);
