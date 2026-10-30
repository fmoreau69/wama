/**
 * Brique `timeseries_chart` — des COURBES dans le temps (2026-10-29 ; le premier plugin graphique
 * du monde Data, `WAMA_DATA_WORLD §8.4`, écrit sur le face_analyzer).
 *
 * Universelle : elle lit une donnée de type `timeseries` (`TypedFrame.to_payload()` : des colonnes,
 * `time` en tête, libellés et unités dans `meta.columns`), servie par la surface sous le nom que
 * l'emplacement donne (`options.source`, défaut `series`). L'emplacement choisit ses colonnes
 * (`options.columns`, défaut : toutes) — une surface pose plusieurs graphes sur la même donnée.
 *
 * Abonnée à l'AXE partagé (`ctx.axis()`) : un trait marque l'instant joué ; un clic dans le graphe
 * y amène la lecture. Elle ne pilote jamais une autre vue (`WAMA_DATA_WORLD §5bis`).
 *
 * Le dessin est uPlot (vendorisé, MIT — le candidat retenu par `WAMA_DATA_WORLD`, « Position sur
 * les BIBLIOTHÈQUES » : une bibliothèque qui DESSINE, jamais une qui décide de la mise en page). Ses
 * couleurs sont celles du thème (`WamaApp.themeColor`), aucune n'est écrite ici.
 */
(function (global) {
    'use strict';

    //: Les couleurs des séries, dans l'ordre : des JETONS du thème, jamais des valeurs.
    var PALETTE = ['--bs-primary', '--bs-danger', '--bs-success', '--bs-warning', '--bs-info',
                   '--bs-purple', '--bs-orange', '--bs-teal', '--bs-pink', '--bs-indigo'];

    function color(token, alpha) {
        var App = global.WamaApp;
        return App && App.themeColor ? App.themeColor(token, alpha) : '';
    }

    /** Les colonnes que l'emplacement montre, parmi celles que la donnée porte. Pure (V8). */
    function chartColumns(payload, wanted) {
        var fields = (payload && payload.fields) || [];
        var present = fields.filter(function (n) { return n !== 'time'; });
        if (!wanted || !wanted.length) return present;
        return wanted.filter(function (n) { return present.indexOf(n) >= 0; });
    }

    /** Le libellé d'une série : celui que la donnée déclare, et son unité. Pure (V8). */
    function seriesLabel(payload, name) {
        var meta = ((payload && payload.meta) || {}).columns || {};
        var declared = meta[name] || {};
        var label = declared.label || name;
        return declared.unit ? label + ' (' + declared.unit + ')' : label;
    }

    function mount(body, ctx, options) {
        options = options || {};
        var source = options.source || 'series';
        var axis = ctx.axis ? ctx.axis() : null;
        var Plot = global.uPlot;
        body.classList.add('wama-brick-chart');
        var host = document.createElement('div');
        host.className = 'wama-chart-host';
        var empty = document.createElement('div');
        empty.className = 'wama-chart-empty';
        body.appendChild(host);
        body.appendChild(empty);

        var plot = null, now = null, frame = 0, fitting = 0;

        /** La place du graphe : le corps de la brique, moins la légende que uPlot pose dessous. */
        function size() {
            var legend = plot && plot.root.querySelector('.u-legend');
            return { width: Math.max(120, body.clientWidth - 8),
                     height: Math.max(60, body.clientHeight - (legend ? legend.offsetHeight : 24) - 12) };
        }

        // Le graphe suit son cadre : la disposition le pose, le retaille, le replie — un rendu par
        // image au plus.
        function fit() {
            if (!plot || fitting) return;
            fitting = global.requestAnimationFrame(function () { fitting = 0; if (plot) plot.setSize(size()); });
        }

        // Le trait de l'instant joué, dessiné par uPlot à chaque rendu.
        var cursorLine = { hooks: { draw: function (u) {
            if (now == null) return;
            var x = u.valToPos(now, 'x', true);
            if (!isFinite(x)) return;
            var c = u.ctx;
            c.save();
            c.strokeStyle = color('--wama-chart-text');
            c.lineWidth = 1;
            c.beginPath();
            c.moveTo(x, u.bbox.top);
            c.lineTo(x, u.bbox.top + u.bbox.height);
            c.stroke();
            c.restore();
        } } };

        function build() {
            if (plot) { plot.destroy(); plot = null; }
            var payload = (ctx.context() || {})[source];
            var names = chartColumns(payload, options.columns);
            var time = payload && payload.columns && payload.columns.time;
            empty.hidden = !!(Plot && time && time.length && names.length);
            host.hidden = !empty.hidden;
            if (!empty.hidden) {
                empty.textContent = !Plot ? 'Bibliothèque de courbes indisponible.'
                    : 'Pas encore de mesures à montrer.';
                return;
            }
            var text = color('--wama-chart-text');
            var grid = color('--wama-overlay-rgb', 0.08);
            var axisStyle = { stroke: text, grid: { stroke: grid, width: 1 }, ticks: { stroke: grid } };
            var dims = size();
            plot = new Plot({
                width: dims.width, height: dims.height,
                scales: { x: { time: false } },
                // Le temps se lit dans la légende (« temps : 1.20 s ») : l'axe ne lui donne pas une
                // ligne de libellé, prise sur la hauteur du tracé.
                axes: [axisStyle, axisStyle],
                legend: { live: true },
                cursor: { drag: { x: false, y: false } },
                plugins: [cursorLine],
                series: [{ label: 'temps', value: function (u, v) {
                    return v == null ? '--' : v.toFixed(2) + ' s';
                } }].concat(names.map(function (name, i) {
                    return { label: seriesLabel(payload, name),
                             stroke: color(PALETTE[i % PALETTE.length]), width: 1.5 };
                })),
            }, [time].concat(names.map(function (name) { return payload.columns[name]; })), host);
            fit();
        }

        // Un clic dans le graphe y amène la lecture — lu au point du clic, dans la zone de tracé.
        host.addEventListener('click', function (ev) {
            if (!plot || !axis) return;
            var over = plot.over.getBoundingClientRect();
            var x = ev.clientX - over.left;
            if (x < 0 || x > over.width || ev.clientY < over.top || ev.clientY > over.bottom) return;
            axis.seek(Math.max(0, plot.posToVal(x, 'x')));
        });
        if (global.ResizeObserver) new global.ResizeObserver(fit).observe(body);

        if (axis) {
            axis.subscribe(function (s) {
                now = s.time;
                if (!plot || frame) return;
                // Un rendu par image au plus : la lecture notifie plus vite que l'écran.
                frame = global.requestAnimationFrame(function () { frame = 0; if (plot) plot.redraw(false); });
            });
        }
        ctx.on('change', function () { if (!plot) build(); });
        ctx.on('resize', fit);
        build();
        return {};
    }

    global.WamaSurface.registerBrick('timeseries_chart', { title: 'Courbes', mount: mount });
    // Les lectures pures, gardées en V8 (`tests_surfaces.TimeseriesChartTest`).
    global.WamaTimeseriesChart = { chartColumns: chartColumns, seriesLabel: seriesLabel };
})(window);
