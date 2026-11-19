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
 * UNE VIDÉO (2026-11-15, `options.video`, le rôle lu par `options.role`) : la brique pose la vidéo
 * sous son canvas, l'attache à l'AXE partagé de la surface (`ctx.axis()` — elle le SUIT, comme
 * toute vidéo) et montre les zones de l'image que la vidéo PRÉSENTE (`WamaPreviewOverlay.follow`,
 * la règle de la visionneuse : l'image montrée, jamais l'instant de l'axe). Mêmes gestes, sur
 * l'image arrêtée : tracer, déplacer ou retirer une zone ARRÊTE la lecture, et la correction porte
 * l'indice de cette image. Elle dit l'image montrée aux autres briques par le bus (`frame`).
 * TOUTE LA SÉQUENCE (même jour) : la portée prise par son outil (prise d'office sur une vidéo),
 * retirer ou rétablir un objet détecté vaut pour toutes les images où il est — l'objet est demandé
 * au serveur (`WamaDetections.editObject`, la règle de l'interpolation) ; la portée se dit aux
 * autres briques par le bus (`scope`).
 *
 * DEUX SERVICES rendus aux autres briques par le bus (2026-11-16, le suivi d'un objet désigné) :
 * un POINT — une brique le demande (`pick-request` `{on}`), le prochain clic dans le média le lui
 * rend (`pick` `{i, point: [x, y]}`, en pixels du média, l'image montrée) ; et des zones
 * PROPOSÉES — `overlay` `{key, frames: {image: [{box, label}]}}`, dessinées en pointillé sur
 * l'image qu'elles concernent, jamais éditables ici.
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
    /** Les touches de la brique PAR DÉFAUT, `{touche: action}` — celles qu'elle déclare au registre
     *  (`surfaces.py`, `image_boxes.shortcuts`, tenues égales par `tests_surfaces`). */
    var BOXES_KEYS = {
        'Delete': 'remove', 'Backspace': 'remove',
        'KeyR': 'restore', 'KeyN': 'add', 'KeyF': 'fit',
    };
    var COLORS = { detected: '#ffc107', manual: '#20c997', removed: '#dc3545', selected: '#0dcaf0' };

    function mount(body, ctx, options) {
        var frameIndex = options.frame || 0;
        var role = options.role || 'image';
        var isVideo = !!options.video;
        var axis = isVideo && ctx.axis ? ctx.axis() : null;
        body.classList.add('wama-brick-image');
        var video = null, shown = null;
        if (isVideo) {
            // La vidéo est MONTRÉE sous le canvas (placée et mise à l'échelle par `draw`) : le
            // navigateur ne rappelle l'image présentée que d'une vidéo qu'il affiche.
            body.classList.add('is-video');
            video = document.createElement('video');
            video.preload = 'auto';
            video.playsInline = true;
            body.appendChild(video);
        }
        var canvas = document.createElement('canvas');
        canvas.tabIndex = 0;
        body.appendChild(canvas);
        var g = canvas.getContext('2d');
        var img = new Image();
        /** La taille de ce qui est montré, dans l'espace des ZONES : celui du document de
         *  détections pour une vidéo (sa copie de lecture peut être d'une autre taille). */
        function mediaSize() {
            var doc = ctx.reads().detections || {};
            // Une image absente (fichier d'origine perdu) : les zones se cadrent sur la taille
            // que le document de détections a mesurée — elles restent visibles et corrigeables.
            if (!isVideo) return [img.naturalWidth || doc.width, img.naturalHeight || doc.height];
            return [doc.width || video.videoWidth, doc.height || video.videoHeight];
        }
        /** Le fichier d'origine que la page devrait montrer n'est plus là (card sans fichier, ou
         *  fichier disparu du disque) : la page le DIT au lieu d'un fond vide sans un mot (relevé
         *  par Fabien le 2026-11-19, card #1047 : ni l'image ni les zones). */
        function sayGone() {
            ctx.status('Le fichier d’origine n’est plus disponible (retiré ou perdu) — les ' +
                       'zones restent affichées et corrigeables ; redéposer l’original pour ' +
                       'les revoir sur l’image', 'error');
            view.fitted = true;
            fit();
        }
        var view = { scale: 1, x: 0, y: 0, fitted: false };
        var tool = 'select';
        var picking = false;          // une brique attend un point : le prochain clic le lui rend
        var overlays = {};            // {clé: {image: [{box, label}]}} : les zones PROPOSÉES
        var drag = null;              // geste en cours : {kind, start, obj, box, handle}
        var objects = [];

        // ── Outils (dans le titre de la brique) ───────────────────────────────────────────
        var tools = document.createElement('div');
        // Une classe à eux : posés dans le TITRE du panneau, hors du corps de la brique, ils sont
        // la cible de leurs touches au registre (`Shortcut.targets`).
        tools.className = 'wama-brick-tools wama-image-tools';
        tools.innerHTML =
            '<button type="button" class="btn btn-xs" data-tool="select" title="Sélection"><i class="fas fa-arrow-pointer"></i></button>' +
            '<button type="button" class="btn btn-xs" data-tool="add" title="Ajouter une zone"><i class="fas fa-vector-square"></i></button>' +
            '<span data-slot="class"></span>' +
            (isVideo ? '<button type="button" class="btn btn-xs" data-scope="sequence" title="Toute la séquence : retirer ou rétablir un objet vaut pour toutes les images où il est (sinon : cette image seule)"><i class="fas fa-film"></i></button>' : '') +
            '<button type="button" class="btn btn-xs" data-act="fit" title="Image entière"><i class="fas fa-expand"></i></button>' +
            '<span class="wama-brick-zoom"></span>';
        // La classe d'une zone ajoutée : proposée (classes demandées, libellés du document) ou
        // écrite (`WamaDetections.classPicker`, le même champ que le suivi d'un objet désigné).
        var classPicker = D.classPicker(ctx, 'Classe des zones ajoutées');
        tools.querySelector('[data-slot="class"]').replaceWith(classPicker.element);
        var zoomLabel = tools.querySelector('.wama-brick-zoom');
        tools.addEventListener('mousedown', function (e) { e.stopPropagation(); });
        tools.addEventListener('click', function (e) {
            var b = e.target.closest('button');
            if (!b) return;
            if (b.dataset.tool) setTool(b.dataset.tool);
            if (b.dataset.scope) setSequence(!sequence);
            if (b.dataset.act === 'fit') fit();
        });

        // La PORTÉE d'un retrait ou d'un rétablissement : cette image, ou tout l'objet (une vidéo).
        var sequence = false;
        function setSequence(on) {
            sequence = !!on && isVideo;
            var b = tools.querySelector('[data-scope]');
            if (b) b.classList.toggle('active', sequence);
            ctx.emit('scope', { sequence: sequence });
        }
        function said(count, kind) {
            if (count > 1 && global.WamaApp && WamaApp.toast) {
                WamaApp.toast((kind === 'restore' ? 'Objet rétabli sur ' : 'Objet retiré sur ') + count + ' images', 'info');
            }
        }

        function setTool(name) {
            tool = ctx.canEdit ? name : 'select';
            tools.querySelectorAll('[data-tool]').forEach(function (b) {
                b.classList.toggle('active', b.dataset.tool === tool);
            });
            canvas.style.cursor = tool === 'add' ? 'crosshair' : 'default';
        }

        function fillClasses() {
            classPicker.refresh();
            classPicker.input.disabled = !ctx.canEdit;
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
            var size = mediaSize();
            if (!size[0] || !size[1]) return;
            var w = canvas.clientWidth, h = canvas.clientHeight;
            view.scale = Math.min(w / size[0], h / size[1]) || 1;
            view.x = (w - size[0] * view.scale) / 2;
            view.y = (h - size[1] * view.scale) / 2;
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
            if (isVideo) {
                // La vidéo elle-même, sous le canvas, à la place et à l'échelle de la vue.
                var size = mediaSize();
                video.style.left = view.x + 'px';
                video.style.top = view.y + 'px';
                video.style.width = size[0] * view.scale + 'px';
                video.style.height = size[1] * view.scale + 'px';
            } else if (img.naturalWidth) {
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
            // Les zones PROPOSÉES par une autre brique (un suivi), sur l'image montrée.
            g.setLineDash([6, 4]);
            g.lineWidth = 2;
            g.strokeStyle = COLORS.manual;
            Object.keys(overlays).forEach(function (key) {
                ((overlays[key] || {})[frameIndex] || []).forEach(function (z) {
                    var r = screenBox(z.box);
                    g.strokeRect(r[0], r[1], r[2], r[3]);
                });
            });
            g.setLineDash([]);
            if (drag && drag.kind === 'draw' && drag.box) {
                var d = screenBox(drag.box);
                g.lineWidth = 2;
                g.strokeStyle = COLORS.manual;
                g.strokeRect(d[0], d[1], d[2], d[3]);
            }
            zoomLabel.textContent = Math.round(view.scale * 100) + ' %' +
                (isVideo ? ' · image ' + frameIndex : '');
        }

        /** Un geste d'édition se fait sur une image ARRÊTÉE : la correction porte son indice. */
        function hold() { if (axis && axis.playing()) axis.pause(); }

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
            if (picking) {
                // Le point demandé par une autre brique : sur l'image ARRÊTÉE, en pixels du média.
                hold();
                picking = false;
                canvas.style.cursor = tool === 'add' ? 'crosshair' : 'default';
                var q0 = toImage(p), size0 = mediaSize();
                if (q0[0] >= 0 && q0[1] >= 0 && q0[0] <= size0[0] && q0[1] <= size0[1]) {
                    ctx.emit('pick', { i: frameIndex, point: [Math.round(q0[0]), Math.round(q0[1])] });
                } else {
                    ctx.emit('pick', { i: frameIndex, point: null });
                }
                return;
            }
            if (tool === 'add' && ctx.canEdit) {
                hold();
                drag = { kind: 'draw', start: toImage(p), box: null };
                return;
            }
            var hd = handleAt(p);
            var sel = byId(ctx.selected());
            if (hd) { hold(); drag = { kind: 'resize', handle: hd, obj: sel, start: toImage(p), box: sel.box.slice() }; return; }
            var o = hit(p);
            if (o && sel && o.id === sel.id && !o.removed && ctx.canEdit) {
                hold();
                drag = { kind: 'move', obj: o, start: toImage(p), box: o.box.slice() };
                return;
            }
            if (o) { hold(); ctx.select(o.id); return; }
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
                var label = classPicker.value();
                ctx.edit(function (v) { return D.add(v, done.box, label, frameIndex); });
                classPicker.refresh();       // une classe écrite à la main est désormais proposée
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
            // Une saisie garde ses touches : la règle du module (une liste a le focus hors de
            // l'image, qui n'a alors pas la main).
            if (ev.ctrlKey || ev.metaKey || ev.altKey) return false;
            var sel = byId(ctx.selected());
            // L'ACTION de la frappe, lue à la table de la brique (`WamaKeys.action`, 2026-11-13) ;
            // Échap ne se redonne pas.
            var act = global.WamaKeys.action(ev, 'image_boxes', BOXES_KEYS);
            if (act === 'remove' && sel && !sel.removed && ctx.canEdit) {
                hold();
                D.editObject(ctx, 'detections', sel, frameIndex, 'remove', sequence)
                    .then(function (n) { said(n, 'remove'); });
                if (sel.origin === 'manual') ctx.select(null);
            } else if (act === 'restore' && sel && sel.removed && ctx.canEdit) {
                D.editObject(ctx, 'detections', sel, frameIndex, 'restore', sequence)
                    .then(function (n) { said(n, 'restore'); });
            } else if (act === 'add') {
                setTool('add');
            } else if (ev.key === 'Escape') {
                setTool('select');
                ctx.select(null);
            } else if (act === 'fit') {
                fit();
            } else {
                return false;
            }
            return true;
        } });

        function refresh() {
            // La portée est REDITE à chaque rafraîchissement : une brique montée après celle-ci
            // (la liste des objets) n'a pas entendu l'annonce faite à son montage.
            ctx.emit('scope', { sequence: sequence });
            objects = D.objects(ctx.reads().detections, ctx.value(), frameIndex);
            if (canvas.width !== Math.round(body.clientWidth * (global.devicePixelRatio || 1))) resize();
            else draw();
        }

        ctx.on('pick-request', function (p) {
            picking = !!(p && p.on);
            canvas.style.cursor = picking ? 'crosshair' : (tool === 'add' ? 'crosshair' : 'default');
        });
        ctx.on('overlay', function (p) {
            if (!p || !p.key) return;
            overlays[p.key] = p.frames || {};
            draw();
        });

        ctx.on('select', function (s) {
            var o = byId(s.id);
            if (o && s.focus) focusOn(o); else draw();
        });

        if (global.ResizeObserver) new ResizeObserver(resize).observe(body);
        if (isVideo) {
            // L'image que la vidéo PRÉSENTE dit les zones à montrer — la règle de la visionneuse
            // (`WamaPreviewOverlay.follow`). Une image qui change emporte la sélection : `d3` y
            // désignerait un autre objet.
            shown = global.WamaPreviewOverlay.follow(
                video, function () { return ctx.reads().detections; }, function () {
                    var at = shown ? shown.index() : 0;
                    if (at === frameIndex) return;
                    frameIndex = at;
                    if (ctx.selected() != null && !drag) ctx.select(null);
                    objects = D.objects(ctx.reads().detections, ctx.value(), frameIndex);
                    draw();
                    ctx.emit('frame', { i: frameIndex });
                });
            video.addEventListener('loadedmetadata', function () { fit(); });
            // Une vidéo que le navigateur ne lit pas se DIT (2026-11-16 : la page montrait les zones
            // sur un fond noir, sans un mot). Sa copie de lecture en préparation (le serveur l'a
            // remise en file, `media[role].playback`) : la page le dit, relit l'adresse du média
            // jusqu'à ce que la copie soit prête, et la charge. Les zones restent corrigeables.
            var preparing = ((ctx.media() || {})[role] || {}).playback === 'preparing';
            var why = ((ctx.media() || {})[role] || {}).reason || '';
            function sayPreparing() {
                ctx.status('Copie de lecture en préparation — la vidéo d\u2019origine ne se lit pas ' +
                           'dans un navigateur' + (why ? ' (' + why + ')' : '') + '. Elle s\u2019affichera ' +
                           'd\u2019elle-même ; les zones restent corrigeables image par image.', 'busy');
            }
            video.addEventListener('error', function () {
                if (preparing) sayPreparing();
                else ctx.status('La vidéo ne se lit pas dans ce navigateur — les zones restent ' +
                                'corrigeables image par image', 'error');
                fit();
            });
            if (preparing) {
                sayPreparing();
                var first = ctx.reads()[role] || '';
                var waitCopy = function () {
                    fetch(ctx.config.data_url + '?only=state', { credentials: 'same-origin' })
                        .then(function (r) { return r.json(); })
                        .then(function (res) {
                            var now = ((res || {}).reads || {})[role] || '';
                            if (now && now !== first) {
                                var at = axis ? axis.time() : 0;
                                video.src = now;
                                if (axis) axis.seek(at);
                                ctx.status('Copie de lecture prête', 'ok');
                                preparing = false;
                                return;
                            }
                            setTimeout(waitCopy, 10000);
                        })
                        .catch(function () { setTimeout(waitCopy, 20000); });
                };
                setTimeout(waitCopy, 10000);
            }
            var url = ctx.source ? ctx.source(role).url : (ctx.reads()[role] || '');
            if (url) {
                video.src = url;
                if (axis) {
                    axis.pause();
                    axis.attach(video, { fps: Number((ctx.reads().detections || {}).fps) || 0 });
                }
            } else {
                sayGone();
            }
        } else {
            img.onload = function () { fit(); };
            img.onerror = sayGone;
            var src = ctx.reads()[role] || '';
            if (src) img.src = src; else sayGone();
        }
        fillClasses();
        setTool('select');
        setSequence(isVideo);
        refresh();
        return { refresh: refresh, tools: tools,
                 help: 'Molette : zoom · glisser : se déplacer' +
                       (isVideo ? ' · une zone se corrige sur l\u2019image arrêtée' : '') };
    }

    global.WamaSurface.registerBrick('image_boxes', { title: 'Image et zones', mount: mount });
})(window);
