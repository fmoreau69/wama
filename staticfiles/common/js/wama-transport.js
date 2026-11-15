/**
 * wama-transport.js — le TRANSPORT commun : les COMMANDES du temps, et rien d'autre (2026-10-21,
 * ROUTE §F3b ; redécoupage décidé par Fabien le même jour).
 *
 * Quatre niveaux, chacun à sa place : l'AXE est le temps (`wama-axis.js`) ; le TRANSPORT lui
 * envoie des commandes — ce module, montable PARTOUT (`WamaTransport.mount(hôte, cfg)`) : la
 * surface (enveloppe `media_transport`) et le magnéto du monde Data (`WAMA_DATA_WORLD §5bis`) ;
 * l'aperçu a, depuis le 2026-11-05, l'axe et SES touches (`WamaAxis.keys`) sous les contrôles
 * natifs de ses vidéos — sa barre de transport reste à décider ; les VUES regardent l'axe (ligne de temps
 * `wama-timeline.js`, vidéo, partition) ; les OUTILS DE DOMAINE agissent pendant la lecture (modes
 * d'écriture du transcriber). Le transport ne connaît ni média, ni vue, ni donnée : il pilote
 * l'axe, jamais une vue — c'est la vue qui s'abonne.
 *
 * Il ne réécrit rien de ce qui existe : J/K/L sont ceux de `WamaShuttle`, Espace, ←/→ et
 * Début/Fin le clavier de l'axe, l'arrière silencieux celui de l'axe.
 *
 * Options (toutes facultatives ; sans elles, le magnéto de la partition du composer) :
 *   jump    saut des boutons et de Maj+←/→ (5 s)
 *   speed   'select' (liste de vitesses) | 'steps' (− / valeur / +, de 0,5 à 2 par 0,25)
 *   goto    champ « aller à » (m:ss, h:mm:ss, virgule admise) — l'axe dit `goto` à ses abonnés :
 *           la ligne de temps recentre sa fenêtre, la liste choisit le segment
 * Les commandes que d'autres lecteurs avaient et que le commun n'avait pas (2026-11-15, marche ②
 * de la cartographie du 12/11 — `ROUTE §F3b` : « on complète le commun, par option, puis on
 * porte ») ; aucune n'est montrée sans son option, une page d'aujourd'hui ne change pas :
 *   step      boutons « pas précédent / suivant » (`axis.step`, la lecture arrêtée — touches , .)
 *   stop      bouton arrêt : pause ET retour au début (`axis.stop`)
 *   reverse   bouton lecture arrière, un cran de shuttle (J) — demande `WamaShuttle`
 *   position  curseur de POSITION : glisser = y aller (celui des contrôles natifs d'une vidéo)
 *   remaining l'horloge dit aussi le temps RESTANT
 *   volume    muet et curseur de volume, pour tous les médias que l'axe suit (`axis.setVolume`)
 *   remember  la position est GARDÉE (toutes les 2 s, au navigateur) et reprise à l'ouverture —
 *             sous la clé que donne qui monte le transport (`cfg.key` : la page et son élément)
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

    function mount(host, cfg) {
        cfg = cfg || {};
        var o = cfg.options || {};
        var Axis = global.WamaAxis;
        var axis = cfg.axis;
        var jump = Number(o.jump) || 5;
        host.classList.add('wama-transport');

        // ── La rangée de commandes ──────────────────────────────────────────────────────────
        var bar = el('div', 'wama-transport-bar');
        var toStart = button('start', 'fa-backward-step', 'Début');
        var back = button('skip-back', o.speed === 'steps' ? 'fa-backward' : 'fa-rotate-left',
                          'Reculer ' + jump + ' s', o.speed === 'steps' ? jump + 's' : '');
        var play = button('play', 'fa-play', 'Lecture / pause');
        var fwd = button('skip-fwd', '', 'Avancer ' + jump + ' s',
                         o.speed === 'steps' ? jump + 's <i class="fas fa-forward"></i>' : '<i class="fas fa-rotate-right"></i>');
        var clock = el('span', 'wama-transport-clock', { 'data-transport': 'clock' });
        // Les commandes en option (marche ②) se rangent autour de la lecture, du plus large au plus
        // fin : début, saut, pas, [arrière, arrêt] lecture, pas, saut.
        var shuttle = global.WamaShuttle ? global.WamaShuttle.forAxis(axis) : null;
        var stepBack = o.step ? button('step-back', 'fa-caret-left', 'Pas précédent') : null;
        var stepFwd = o.step ? button('step-fwd', 'fa-caret-right', 'Pas suivant') : null;
        var reverse = (o.reverse && shuttle) ? button('reverse', 'fa-play fa-flip-horizontal', 'Lecture arrière') : null;
        var stop = o.stop ? button('stop', 'fa-stop', 'Arrêt : pause et retour au début') : null;
        [toStart, back, stepBack, reverse, stop, play, stepFwd, fwd].forEach(function (b) {
            if (b) bar.appendChild(b);
        });

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
        // Le curseur de POSITION : dans la rangée, il prend la place qui reste.
        var position = null, dragging = false;
        if (o.position) {
            position = el('input', 'form-range wama-transport-position',
                          { type: 'range', min: '0', max: '0', step: '0.01', value: '0',
                            'data-transport': 'position', title: 'Position — glisser pour y aller',
                            'aria-label': 'Position' });
            position.addEventListener('input', function () { dragging = true; axis.seek(Number(position.value) || 0); });
            position.addEventListener('change', function () { dragging = false; });
            bar.appendChild(position);
        }
        bar.appendChild(clock);

        var mute = null, volume = null;
        if (o.volume) {
            mute = button('mute', 'fa-volume-high', 'Couper / rétablir le son');
            volume = el('input', 'form-range wama-transport-volume',
                        { type: 'range', min: '0', max: '1', step: '0.05', value: '1',
                          'data-transport': 'volume', title: 'Volume', 'aria-label': 'Volume' });
            mute.addEventListener('click', function () { axis.setMuted(!axis.muted()); });
            volume.addEventListener('input', function () { axis.setVolume(Number(volume.value)); });
            bar.appendChild(mute);
            bar.appendChild(volume);
        }

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

        if (stepBack) stepBack.addEventListener('click', function () { axis.step(-1); });
        if (stepFwd) stepFwd.addEventListener('click', function () { axis.step(1); });
        if (reverse) reverse.addEventListener('click', function () { shuttle.reverse(); });
        // L'arrêt REND le shuttle d'abord (son K) : sinon l'axe gardait la vitesse arrière.
        if (stop) stop.addEventListener('click', function () { if (shuttle) shuttle.stop(); axis.stop(); });

        // La position GARDÉE : reprise une fois, quand la durée est connue ; gardée toutes les 2 s.
        var remember = (o.remember && cfg.key) ? 'wama.transport.position.' + cfg.key : null;
        var restored = !remember, keptAt = 0;
        function stored() {
            try { return Number(global.localStorage.getItem(remember)); } catch (e) { return NaN; }
        }
        function keep(t) {
            try { global.localStorage.setItem(remember, String(Math.round(t * 100) / 100)); } catch (e) { /* pas de stockage */ }
        }

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

        // Échap à une saisie du transport (« aller à ») rend le clavier — par le clavier commun
        // (`WamaKeys`) : la brique a la main quand le focus est chez elle.
        global.WamaKeys.register({ owner: 'media_transport', scope: 'brick', root: host, typing: ['Escape'],
                                   handle: function (e) {
            if (e.key !== 'Escape' || !global.WamaKeys.typing(e.target)) return false;
            e.target.blur();
            return true;
        } });

        // ── L'abonnement à l'axe ────────────────────────────────────────────────────────────
        // L'icône du bouton lecture change de CLASSE, et seulement quand l'état change (2026-10-28,
        // relevé par Fabien : un clic sur « pause » pendant la lecture était perdu). L'axe parle à
        // chaque image : réécrire le bouton remplaçait l'icône sous le pointeur entre l'appui et le
        // relâché, et le navigateur ne reconnaissait plus un clic.
        var playIcon = play.querySelector('i'), shownPlaying = null;
        var muteIcon = mute ? mute.querySelector('i') : null, shownSound = null;
        if (axis) axis.subscribe(function (st) {
            if (st.playing !== shownPlaying) {
                shownPlaying = st.playing;
                playIcon.className = 'fas ' + (st.playing ? 'fa-pause' : 'fa-play');
            }
            clock.textContent = Axis.formatTime(st.time, true) + ' / ' + (st.duration ? Axis.formatTime(st.duration) : '--:--')
                + (o.remaining && st.duration ? ' · −' + Axis.formatTime(Math.max(0, st.duration - st.time)) : '');
            if (position) {
                if (Number(position.max) !== st.duration) position.max = String(st.duration || 0);
                if (!dragging) position.value = String(st.time);
            }
            if (mute) {
                var sound = (st.muted || !st.volume) ? 'fa-volume-xmark' : 'fa-volume-high';
                if (sound !== shownSound) { shownSound = sound; muteIcon.className = 'fas ' + sound; }
                if (Number(volume.value) !== st.volume) volume.value = String(st.volume);
            }
            if (remember) {
                if (!restored && st.duration > 0) {
                    restored = true;
                    var at = stored();
                    if (at > 0 && at < st.duration && !st.time) axis.seek(at);
                }
                var now = Date.now();
                if (restored && now - keptAt >= 2000) { keptAt = now; keep(st.time); }
            }
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

        // Ses touches (Espace, J/K/L, ←/→, Début/Fin, Ctrl+Espace) sont DÉCLARÉES au registre des
        // briques (`surfaces.py`, `media_transport.shortcuts`) : la liste de la brique Actions les lit.
        return {};
    }

    global.WamaTransport = { mount: mount, speedLabel: speedLabel, RATES: RATES };
})(window);
