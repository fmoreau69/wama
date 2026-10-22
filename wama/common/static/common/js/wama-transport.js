/**
 * wama-transport.js — le TRANSPORT commun : les COMMANDES du temps, et rien d'autre (2026-10-21,
 * ROUTE §F3b ; redécoupage décidé par Fabien le même jour).
 *
 * Quatre niveaux, chacun à sa place : l'AXE est le temps (`wama-axis.js`) ; le TRANSPORT lui
 * envoie des commandes — ce module, montable PARTOUT (`WamaTransport.mount(hôte, cfg)`) : la
 * surface (enveloppe `media_transport`), demain l'aperçu (visionneuse, Comparer) et le magnéto du
 * monde Data (`WAMA_DATA_WORLD §5bis`) ; les VUES regardent l'axe (ligne de temps
 * `wama-timeline.js`, vidéo, partition) ; les OUTILS DE DOMAINE agissent pendant la lecture (modes
 * d'écriture du transcriber). Le transport ne connaît ni média, ni vue, ni donnée : il pilote
 * l'axe, jamais une vue — c'est la vue qui s'abonne.
 *
 * Il ne réécrit rien de ce qui existe : J/K/L sont ceux de `WamaShuttle`, Espace, ←/→ et
 * Début/Fin le clavier de l'axe, l'arrière silencieux celui de l'axe.
 *
 * Options (toutes facultatives ; sans elles, le magnéto de la partition du composer) :
 *   jump    saut des boutons et de ←/→ (5 s)
 *   speed   'select' (liste de vitesses) | 'steps' (− / valeur / +, de 0,5 à 2 par 0,25)
 *   goto    champ « aller à » (m:ss, h:mm:ss, virgule admise) — l'axe dit `goto` à ses abonnés :
 *           la ligne de temps recentre sa fenêtre, la liste choisit le segment
 * Jusqu'à ce redécoupage, l'onde fenêtrée et ses couches, le zoom, la bande de qualité, la
 * minimap, l'outil Bornes et les modes d'écriture étaient aussi des options d'ici : les premiers
 * sont la VUE `wama-timeline.js`, les derniers la brique `playback_writing`.
 */
(function (global) {
    'use strict';

    var RATES = [0.5, 0.75, 1, 1.25, 1.5, 1.75, 2];
    var SPEED_MIN = 0.5, SPEED_MAX = 2, SPEED_STEP = 0.25;

    /** Le libellé de la vitesse — UN pour tout WAMA : la vitesse choisie, ou le cran du shuttle. */
    function speedLabel(st) {
        if (st.shuttling) return (st.rate > 0 ? '▶▶ ' + st.rate : '◀◀ ' + (-st.rate)) + '×';
        return st.speed.toFixed(2).replace(/0$/, '') + '×';
    }

    function el(tag, cls, attrs) {
        var e = document.createElement(tag);
        if (cls) e.className = cls;
        Object.keys(attrs || {}).forEach(function (k) { e.setAttribute(k, attrs[k]); });
        return e;
    }

    function button(name, icon, title, text) {
        var b = el('button', 'btn btn-sm btn-outline-emphasis', { type: 'button', 'data-transport': name, title: title });
        b.innerHTML = (icon ? '<i class="fas ' + icon + '"></i>' : '') + (text ? ' ' + text : '');
        return b;
    }

    /** Le clavier est-il à une saisie ? La règle commune (`WamaApp.isTyping`). */
    function typing() { return global.WamaApp.isTyping(); }

    function mount(host, cfg) {
        cfg = cfg || {};
        var o = cfg.options || {};
        var Axis = global.WamaAxis;
        var axis = cfg.axis;
        var jump = Number(o.jump) || 5;
        host.classList.add('wama-transport');

        // ── La rangée de commandes ──────────────────────────────────────────────────────────
        var bar = el('div', 'wama-transport-bar');
        var toStart = button('start', 'fa-backward-step', 'Début (Début)');
        var back = button('skip-back', o.speed === 'steps' ? 'fa-backward' : 'fa-rotate-left',
                          'Reculer ' + jump + ' s (←)', o.speed === 'steps' ? jump + 's' : '');
        var play = button('play', 'fa-play', 'Lecture / pause (Espace)');
        var fwd = button('skip-fwd', '', 'Avancer ' + jump + ' s (→)',
                         o.speed === 'steps' ? jump + 's <i class="fas fa-forward"></i>' : '<i class="fas fa-rotate-right"></i>');
        var clock = el('span', 'wama-transport-clock', { 'data-transport': 'clock' });
        [toStart, back, play, fwd].forEach(function (b) { bar.appendChild(b); });

        var rate = null, speedLabelEl = null, shuttleOpt = null;
        if (o.speed === 'steps') {
            var down = button('speed-down', 'fa-minus', 'Ralentir');
            speedLabelEl = el('span', 'badge bg-secondary wama-transport-speed', { 'data-transport': 'speed-label' });
            var up = button('speed-up', 'fa-plus', 'Accélérer');
            var bump = function (d) {
                axis.setSpeed(Math.max(SPEED_MIN, Math.min(SPEED_MAX, Math.round((axis.speed() + d) * 100) / 100)));
            };
            down.addEventListener('click', function () { bump(-SPEED_STEP); });
            up.addEventListener('click', function () { bump(SPEED_STEP); });
            bar.appendChild(el('span', 'text-body-secondary ms-2')).innerHTML = '<i class="fas fa-gauge-high"></i>';
            [down, speedLabelEl, up].forEach(function (b) { bar.appendChild(b); });
        } else {
            rate = el('select', 'form-select form-select-sm wama-transport-rate', { 'data-transport': 'rate', title: 'Vitesse de lecture' });
            RATES.forEach(function (r) {
                var opt = document.createElement('option');
                opt.value = String(r); opt.textContent = '×' + r;
                rate.appendChild(opt);
            });
            shuttleOpt = document.createElement('option');
            shuttleOpt.hidden = true;
            rate.appendChild(shuttleOpt);
            bar.appendChild(rate);
        }
        bar.appendChild(clock);

        var gotoInp = null;
        if (o.goto) {
            gotoInp = el('input', 'form-control form-control-sm wama-transport-goto',
                         { type: 'text', 'data-transport': 'goto', placeholder: 'mm:ss',
                           title: 'Aller à un timecode (mm:ss ou hh:mm:ss) — Entrée' });
            var gotoBtn = button('goto-btn', 'fa-arrow-right-to-bracket', 'Aller au timecode');
            bar.appendChild(el('span', 'text-body-secondary ms-2')).innerHTML = '<i class="fas fa-clock"></i>';
            bar.appendChild(gotoInp);
            bar.appendChild(gotoBtn);
            gotoBtn.addEventListener('click', function () { gotoTimecode(); });
            gotoInp.addEventListener('keydown', function (e) {
                if (e.key === 'Enter') { e.preventDefault(); gotoTimecode(); }
            });
        }
        host.appendChild(bar);

        var shuttle = global.WamaShuttle ? global.WamaShuttle.create({
            apply: function (level) { axis.shuttle(level); },
        }) : null;

        toStart.addEventListener('click', function () { axis.seek(0); });
        back.addEventListener('click', function () { axis.jump(-jump); });
        fwd.addEventListener('click', function () { axis.jump(jump); });
        play.addEventListener('click', function () { axis.toggle(); });
        if (rate) rate.addEventListener('change', function () {
            if (shuttle) shuttle.reset();
            axis.setRate(Number(rate.value) || 1);
        });
        if (axis) axis.bindKeys({ jump: jump, shuttle: shuttle });

        /** Aller à un timecode — lecture COMMUNE du temps ; l'axe dit `goto` à ceux qui regardent. */
        function gotoTimecode() {
            var sec = Axis.parseTime(gotoInp && gotoInp.value);
            if (sec == null) {
                if (gotoInp) { gotoInp.classList.add('is-invalid'); setTimeout(function () { gotoInp.classList.remove('is-invalid'); }, 1200); }
                return;
            }
            var D = axis.duration();
            axis.seek(D ? Math.min(sec, D) : sec, 'goto');
        }

        // Échap à une saisie du transport (« aller à ») rend le clavier ; jamais déjà traité.
        document.addEventListener('keydown', function (e) {
            if (e.key !== 'Escape' || e.defaultPrevented || !typing()) return;
            if (host.contains(document.activeElement)) { e.preventDefault(); document.activeElement.blur(); }
        });

        // ── L'abonnement à l'axe ────────────────────────────────────────────────────────────
        if (axis) axis.subscribe(function (st) {
            play.innerHTML = '<i class="fas ' + (st.playing ? 'fa-pause' : 'fa-play') + '"></i>';
            clock.textContent = Axis.formatTime(st.time, true) + ' / ' + (st.duration ? Axis.formatTime(st.duration) : '--:--');
            if (speedLabelEl) speedLabelEl.textContent = speedLabel(st);
            if (rate) {
                if (!st.shuttling && RATES.indexOf(st.rate) >= 0) {
                    rate.value = String(st.rate);
                } else {
                    shuttleOpt.value = String(st.rate);
                    shuttleOpt.textContent = speedLabel(st);
                    rate.value = shuttleOpt.value;
                }
            }
        });

        var help = 'Transport : Espace = lecture/pause · ←/→ = ±' + jump + ' s (Maj : ×6) · Début/Fin · ' +
                   'J/K/L = arrière / arrêt / avant par crans';

        return { help: help };
    }

    global.WamaTransport = { mount: mount, speedLabel: speedLabel, RATES: RATES };
})(window);
