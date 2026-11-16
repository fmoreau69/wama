/**
 * Brique `object_tracking` — SUIVRE UN OBJET DÉSIGNÉ (2026-11-16, la page de correction des
 * détections ; décision de Fabien : un clic sur un objet non détecté le suit sur toute la
 * séquence, sur le patron de l'écriture à la lecture). Un OUTIL DE DOMAINE, comme
 * `playback_writing` : ni un média, ni une vue — un process qui PROPOSE une donnée.
 *
 * Le geste : « Désigner un objet », puis un clic dans le média. La brique qui montre le média
 * (`image_boxes`) rend le point cliqué par le bus (`pick-request` → `pick`) : cette brique ne
 * connaît aucune vue. Elle pose le curseur que suit la boucle serveur commune (`playhead_follow`,
 * route `track_cursor` que la surface déclare) et lit ses résultats (`track_results`) : les zones
 * de l'objet, tranche après tranche — sur toute la séquence d'une vidéo, sur la seule image
 * sinon. Les zones PROPOSÉES se dessinent sur le média (bus `overlay`) ; « Accepter » les fait
 * entrer dans la couche de corrections (`WamaDetections.addMany` : UN geste, un cran
 * d'annulation), « Refuser » les oublie. Le serveur n'écrit jamais la correction.
 */
(function (global) {
    'use strict';

    var D = global.WamaDetections;
    var POLL_MS = 1200;              // la relecture des résultats pendant un suivi
    var KEEP_ALIVE_MS = 30000;       // le curseur est reposé tant qu'un suivi court (il expire)

    function mount(body, ctx) {
        var App = global.WamaApp || {};
        var routes = ctx.config.routes || {};
        body.classList.add('wama-brick-tracking');
        var head = document.createElement('div');
        head.className = 'wama-tracking-head';
        var pickBtn = document.createElement('button');
        pickBtn.type = 'button';
        pickBtn.className = 'btn btn-sm btn-outline-primary';
        pickBtn.dataset.tracking = 'pick';
        pickBtn.innerHTML = '<i class="fas fa-crosshairs"></i> Désigner un objet';
        pickBtn.title = 'Puis cliquer sur l’objet dans le média : il est segmenté et suivi, ses zones proposées';
        var classSelect = document.createElement('select');
        classSelect.className = 'form-select form-select-sm';
        classSelect.dataset.tracking = 'class';
        classSelect.title = 'Classe des zones proposées';
        head.appendChild(pickBtn);
        head.appendChild(classSelect);
        var list = document.createElement('div');
        list.className = 'wama-tracking-list';
        body.appendChild(head);
        body.appendChild(list);

        var targets = [];            // {id, i, point, label, frames: [{i, box}], done, error}
        var counter = 0, next = -1, polling = null, lastPost = 0, picking = false;

        function fillClasses() {
            var classes = (ctx.context().classes || []).filter(Boolean);
            if (!classes.length) classes = ['face'];
            classSelect.innerHTML = '';
            classes.forEach(function (c) {
                var o = document.createElement('option');
                o.value = c; o.textContent = c;
                classSelect.appendChild(o);
            });
        }

        function available() { return !!(routes.track_cursor && routes.track_results && ctx.canEdit); }

        function post(payload) {
            return App.csrfFetch(routes.track_cursor, App.csrfToken(), {
                method: 'POST', headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            }).then(function (r) { return r.json(); });
        }

        function pending() { return targets.filter(function (t) { return !t.done && !t.error; }); }

        /** Le curseur : les cibles encore suivies ; plus aucune, la boucle s'arrête. */
        function postCursor() {
            var open = pending();
            lastPost = Date.now();
            if (!open.length) return post({ enabled: false }).catch(function () {});
            return post({ targets: open.map(function (t) { return { id: t.id, i: t.i, point: t.point }; }) })
                .then(function (res) {
                    if (res && res.ok === false) {
                        open.forEach(function (t) { t.error = res.reason || 'suivi refusé'; });
                        render();
                    }
                }).catch(function () {});
        }

        /** Les zones proposées, dites à la brique qui montre le média : `{image: [zones]}`. */
        function showOverlay() {
            var frames = {};
            targets.forEach(function (t) {
                t.frames.forEach(function (f) {
                    (frames[f.i] = frames[f.i] || []).push({ box: f.box, label: t.label });
                });
            });
            ctx.emit('overlay', { key: 'object_tracking', frames: frames });
        }

        function row(t) {
            var el = document.createElement('div');
            el.className = 'wama-tracking-row';
            el.dataset.target = t.id;
            var text = document.createElement('span');
            text.className = 'wama-tracking-text';
            var count = t.frames.length;
            text.textContent = t.label + ' — ' + (t.error ? t.error
                : count + (count > 1 ? ' images' : ' image') + (t.done ? '' : '…'));
            el.appendChild(text);
            [['accept', 'fa-check', 'Accepter : ses zones entrent dans les corrections', !count],
             ['refuse', 'fa-xmark', 'Refuser : ses zones sont oubliées', false]].forEach(function (b) {
                var btn = document.createElement('button');
                btn.type = 'button';
                btn.className = 'btn btn-xs';
                btn.dataset.act = b[0];
                btn.title = b[2];
                btn.disabled = b[3];
                btn.innerHTML = '<i class="fas ' + b[1] + '"></i>';
                el.appendChild(btn);
            });
            return el;
        }

        function render() {
            pickBtn.disabled = !available();
            pickBtn.classList.toggle('active', picking);
            classSelect.disabled = !available();
            list.innerHTML = '';
            if (!available()) {
                list.textContent = ctx.canEdit ? 'Le suivi n’est pas proposé ici.' : 'Lecture seule.';
            } else if (!targets.length) {
                list.textContent = 'Aucun objet désigné.';
            } else {
                targets.forEach(function (t) { list.appendChild(row(t)); });
            }
            showOverlay();
        }

        function poll() {
            polling = null;
            fetch(routes.track_results + '?since=' + next, { credentials: 'same-origin' })
                .then(function (r) { return r.json(); })
                .then(function (d) {
                    var fresh = next < 0 ? [] : (d.results || []);
                    next = d.next || 0;
                    fresh.forEach(function (res) {
                        if (res.error) {
                            pending().forEach(function (t) { t.error = res.error; });
                            return;
                        }
                        var t = targets.filter(function (x) { return x.id === res.target; })[0];
                        if (!t) return;
                        t.frames = t.frames.concat(res.frames || []);
                        if (res.done) t.done = true;
                    });
                    if (fresh.length) render();
                    if (pending().length) {
                        if (Date.now() - lastPost > KEEP_ALIVE_MS) postCursor();
                        polling = setTimeout(poll, POLL_MS);
                    } else {
                        postCursor();
                    }
                })
                .catch(function () { if (pending().length) polling = setTimeout(poll, POLL_MS * 2); });
        }

        function follow() { if (!polling) polling = setTimeout(poll, next < 0 ? 0 : POLL_MS); }

        pickBtn.addEventListener('click', function () {
            if (!available()) return;
            picking = !picking;
            ctx.emit('pick-request', { key: 'object_tracking', on: picking });
            render();
        });

        ctx.on('pick', function (p) {
            if (!picking || !p || !p.point) return;
            picking = false;
            counter += 1;
            targets.push({ id: 't' + Date.now().toString(36) + counter, i: p.i || 0, point: p.point,
                           label: classSelect.value || 'face', frames: [], done: false, error: '' });
            render();
            // L'index des résultats d'abord (une page ne rejoue pas ceux d'avant), puis le curseur.
            (next < 0 ? fetch(routes.track_results + '?since=-1', { credentials: 'same-origin' })
                .then(function (r) { return r.json(); })
                .then(function (d) { next = d.next || 0; }) : Promise.resolve())
                .catch(function () { next = 0; })
                .then(postCursor).then(follow);
        });

        list.addEventListener('mousedown', function (e) { e.stopPropagation(); });
        list.addEventListener('click', function (e) {
            var btn = e.target.closest('button[data-act]');
            var el = e.target.closest('.wama-tracking-row');
            if (!btn || !el) return;
            var t = targets.filter(function (x) { return x.id === el.dataset.target; })[0];
            if (!t) return;
            if (btn.dataset.act === 'accept' && t.frames.length) {
                ctx.edit(function (v) { return D.addMany(v, t.frames, t.label); });
                if (App.toast && t.frames.length > 1) {
                    App.toast('Objet ajouté sur ' + t.frames.length + ' images', 'info');
                }
            }
            targets = targets.filter(function (x) { return x !== t; });
            render();
            postCursor();
        });

        fillClasses();
        render();
        return {
            help: 'Suivi : « Désigner un objet », puis cliquer dessus — ses zones sont proposées ; ' +
                  '« Accepter » les ajoute aux corrections (Ctrl+Z l’annule).',
        };
    }

    global.WamaSurface.registerBrick('object_tracking', { title: 'Suivi d’objet', mount: mount });
})(window);
