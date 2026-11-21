/**
 * wama-durations.js — les DURÉES LISIBLES de WAMA, côté navigateur (2026-11-19, demande de Fabien :
 * « une petite fonction au commun pour aligner les durées en heures, minutes et secondes […] partout
 * où il y a des durées »). Jumelle de `wama/common/utils/durations.py` : mêmes formes, mêmes règles
 * (la garde `tests_display_format` les joue côte à côte). Pure, sans dépendance — chargée par
 * `base.html` avant ses consommateurs : `WamaApp.formatDuration`, l'horloge de l'axe
 * (`WamaAxis.formatTime`), le lecteur audio commun, le temps restant (`WamaEta`), l'aperçu.
 *
 *   WamaDurations.clock(value, from, precision)  « 1:35 », « 1:02:30 », « 1:23.4 » — une position,
 *                                                une durée en horloge ; 0 se lit « 0:00 »
 *   WamaDurations.duration(value, from)          la durée d'un média : '' inconnue ou nulle
 *   WamaDurations.elapsed(value, from)           « 45 s », « 1 min 05 s », « 1 h 02 min » —
 *                                                un temps de traitement, une attente
 * `from` dit l'unité reçue ('s' par défaut, 'ms', 'min', 'h'). La valeur est TRONQUÉE (décision de
 * Fabien, 2026-11-19 : comme le lecteur — 95,6 s se lit « 1:35 »).
 */
(function (global) {
    'use strict';

    var FACTORS = { ms: 0.001, s: 1, min: 60, h: 3600 };

    /** Un nombre de secondes ≥ 0, ou null quand la valeur ne se lit pas. */
    function seconds(value, from) {
        if (value == null || value === '') return null;
        var n = Number(value) * (FACTORS[String(from || 's')] || 1);
        return isFinite(n) ? Math.max(0, n) : null;
    }

    function pad(x) { return String(x).padStart(2, '0'); }

    function clock(value, from, precision) {
        var total = seconds(value, from);
        if (total === null) return '';
        var whole = Math.floor(total);
        var h = Math.floor(whole / 3600), m = Math.floor((whole % 3600) / 60), s = whole % 60;
        var out = h ? h + ':' + pad(m) + ':' + pad(s) : m + ':' + pad(s);
        var p = Number(precision) || 0;
        if (p > 0) {
            var fraction = Math.floor((total - whole) * Math.pow(10, p) + 1e-6);
            out += '.' + String(fraction).padStart(p, '0');
        }
        return out;
    }

    function duration(value, from) {
        var total = seconds(value, from);
        return total ? clock(total) : '';
    }

    function elapsed(value, from) {
        var total = seconds(value, from);
        var whole = total ? Math.floor(total) : 0;
        if (whole <= 0) return '';
        var h = Math.floor(whole / 3600), m = Math.floor((whole % 3600) / 60), s = whole % 60;
        if (h) return m ? h + ' h ' + pad(m) + ' min' : h + ' h';
        if (m) return s ? m + ' min ' + pad(s) + ' s' : m + ' min';
        return s + ' s';
    }

    global.WamaDurations = { clock: clock, duration: duration, elapsed: elapsed };
})(typeof window !== 'undefined' ? window : this);
