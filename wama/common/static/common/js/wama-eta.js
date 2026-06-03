/* ===========================================================================
 * WAMA — Moteur d'estimation de temps restant (ETA) commun à toutes les apps
 * ===========================================================================
 * Un seul moteur, utilisé aux 3 niveaux : carte individuelle, batch, globale.
 *
 * Principe :
 *   - ETA calculé par DÉBIT OBSERVÉ : restant = écoulé / Δprogress × (100−p).
 *     → corrige automatiquement la lenteur initiale (chargement du modèle) :
 *       l'estimation s'affine dès que la progression avance réellement.
 *   - seed statique OPTIONNEL (estimation a priori de l'app) pour la phase
 *     précoce, avant d'avoir assez de points de mesure.
 *   - 3 niveaux de CONFIANCE : 'loading' (pas de nombre), 'low' (≈, arrondi
 *     grossier, atténué), 'high' (~, précis, net). Aucun feu tricolore.
 *
 * Intégration côté app (un seul point par boucle de polling par-item) :
 *     WamaEta.update(id, { progress, status, seedSeconds, modelLoaded });
 *     WamaEta.render(cardEtaEl, WamaEta.get(id));
 *   À la suppression / fin :  WamaEta.reset(id);
 *   Niveau global / batch :    WamaEta.render(el, WamaEta.aggregateAll());
 *                              WamaEta.render(el, WamaEta.aggregate([id1,id2]));
 * ======================================================================== */
window.WamaEta = (function () {
    'use strict';

    // Registre par item : { id: { firstAt, firstProgress, lastProgress, est } }
    var store = {};

    var HIGH_DELTA = 8;   // % de progression observée avant confiance "high"
    var BLEND_FULL = 15;  // % observé au-delà duquel on ignore le seed

    function _round(sec, confidence) {
        sec = Math.max(0, Math.round(sec));
        if (confidence === 'high') {
            if (sec < 60) return sec + ' s';
            var m = Math.floor(sec / 60), s = sec % 60;
            return s ? m + ' min ' + String(s).padStart(2, '0') + ' s' : m + ' min';
        }
        // low : arrondi grossier (pas de fausse précision)
        if (sec < 45) return '< 1 min';
        if (sec < 90) return '1 min';
        if (sec < 3600) return Math.round(sec / 60) + ' min';
        return Math.round(sec / 3600) + ' h';
    }

    function format(seconds, confidence) {
        if (confidence === 'loading' || seconds == null) return null;
        var prefix = confidence === 'high' ? '~' : '≈';
        return prefix + ' ' + _round(seconds, confidence);
    }

    /* Calcule et mémorise l'estimation pour un item. Retourne {seconds, confidence}. */
    function update(id, opts) {
        opts = opts || {};
        var now = opts.now || Date.now();
        var status = opts.status;
        var p = Math.max(0, Math.min(100, opts.progress || 0));
        var st = store[id] || (store[id] = { firstAt: null, firstProgress: 0, lastProgress: 0, est: null });

        // Terminé / erreur → plus de temps restant
        if (status && status !== 'RUNNING' && status !== 'PENDING') {
            st.est = { seconds: 0, confidence: 'high' };
            return st.est;
        }

        // Override serveur si fourni (le backend sait parfois mieux)
        if (opts.serverEta != null && opts.serverEta >= 0) {
            st.est = { seconds: opts.serverEta, confidence: opts.modelLoaded ? 'high' : 'low' };
            return st.est;
        }

        // Pas encore de progression mesurable → phase "chargement du modèle"
        if (p <= 0) {
            if (opts.modelLoaded && opts.seedSeconds) {
                st.est = { seconds: opts.seedSeconds, confidence: 'low' };
            } else {
                st.est = { seconds: null, confidence: 'loading' };
            }
            return st.est;
        }

        if (st.firstAt == null) { st.firstAt = now; st.firstProgress = p; }
        st.lastProgress = p;

        var elapsed = (now - st.firstAt) / 1000;     // s depuis 1ère progression
        var delta = p - st.firstProgress;             // % gagnés depuis
        var observed = (delta >= 1 && elapsed > 0.5) ? (elapsed / delta) * (100 - p) : null;
        var seed = (opts.seedSeconds != null) ? opts.seedSeconds * (1 - p / 100) : null;

        var seconds, confidence;
        if (observed != null) {
            if (seed != null) {
                var w = Math.min(1, delta / BLEND_FULL);   // poids croissant de l'observé
                seconds = w * observed + (1 - w) * seed;
            } else {
                seconds = observed;
            }
            confidence = (delta >= HIGH_DELTA) ? 'high' : 'low';
        } else if (seed != null) {
            seconds = seed;
            confidence = 'low';
        } else {
            st.est = { seconds: null, confidence: 'loading' };
            return st.est;
        }

        st.est = { seconds: seconds, confidence: confidence };
        return st.est;
    }

    function get(id) { return store[id] ? store[id].est : null; }
    function reset(id) { delete store[id]; }

    /* Agrège une liste d'estimations (somme des restants ; confiance = la plus basse). */
    function _aggregateEstimates(estimates) {
        var total = 0, anyLoading = false, anyLow = false, has = false;
        estimates.forEach(function (e) {
            if (!e) return;
            if (e.confidence === 'loading') { anyLoading = true; return; }
            if (e.seconds > 0) { total += e.seconds; has = true; if (e.confidence === 'low') anyLow = true; }
        });
        if (!has) return anyLoading ? { seconds: null, confidence: 'loading' }
                                    : { seconds: 0, confidence: 'high' };
        return { seconds: total, confidence: (anyLoading || anyLow) ? 'low' : 'high' };
    }

    function aggregate(ids) {
        return _aggregateEstimates(ids.map(function (id) { return get(id); }));
    }

    function aggregateAll() {
        return _aggregateEstimates(Object.keys(store).map(function (id) { return store[id].est; }));
    }

    /* Rend une estimation dans un élément <span class="wama-eta">. */
    function render(el, est) {
        if (!el) return;
        el.classList.remove('wama-eta--loading', 'wama-eta--low', 'wama-eta--high');

        if (!est || est.confidence === 'loading') {
            el.classList.add('wama-eta--loading');
            el.textContent = el.dataset.loadingLabel || 'Estimation…';
            el.title = 'Estimation en cours (modèle en chargement)…';
            return;
        }
        if (est.seconds <= 0 && est.confidence === 'high') {
            el.textContent = '';
            el.title = '';
            return;
        }
        el.classList.add('wama-eta--' + est.confidence);
        el.textContent = format(est.seconds, est.confidence);
        el.title = (est.confidence === 'high')
            ? 'Estimation affinée (rythme mesuré)'
            : 'Estimation approximative';
    }

    return { update: update, get: get, reset: reset, format: format,
             aggregate: aggregate, aggregateAll: aggregateAll, render: render };
})();
