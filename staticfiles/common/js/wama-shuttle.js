/*
 * WamaShuttle — commande de lecture J/K/L d'éditeur (shuttle), mutualisée entre apps
 * (Transcriber, cam_analyzer, …). Gère l'ÉTAT (paliers de vitesse + direction) et le
 * binding clavier ; chaque app fournit son callback `apply(speed)` pour appliquer la
 * vitesse à son lecteur (audio, vidéos synchronisées, …). Évite de dupliquer la logique.
 *
 *   Touches : L = avance / accélère (cran +1), J = ralentit / arrière (cran −1),
 *             K = stop (retour à 0).
 *
 * Usage :
 *   const sh = WamaShuttle.create({
 *       levels: [-4,-2,-1,0,1,2,4],          // optionnel (défaut = paliers éditeur)
 *       apply(speed) { ... },                // requis : négatif=arrière, 0=stop
 *       onChange(speed) { ... },             // optionnel : label/HUD
 *       enabled() { return true; },          // optionnel : gate (ex. lecteur visible)
 *   });
 *   sh.bindKeys();                           // écoute j/k/l au niveau document
 */
(function (global) {
    'use strict';

    var DEFAULT_LEVELS = [-16, -8, -4, -2, -1.75, -1.5, -1.25, -1,
                          0, 1, 1.25, 1.5, 1.75, 2, 4, 8, 16];

    function create(config) {
        config = config || {};
        var levels = config.levels || DEFAULT_LEVELS;
        var stopIdx = levels.indexOf(0);
        if (stopIdx < 0) stopIdx = 0;
        var idx = stopIdx;

        function applyCurrent() {
            var s = levels[idx];
            if (config.apply) config.apply(s);
            if (config.onChange) config.onChange(s);
        }
        function step(dir) {
            idx = Math.max(0, Math.min(levels.length - 1, idx + dir));
            applyCurrent();
        }

        var api = {
            forward: function () { step(1); },        // L
            reverse: function () { step(-1); },       // J
            stop: function () { idx = stopIdx; applyCurrent(); },  // K
            speed: function () { return levels[idx]; },
            reset: function () { idx = stopIdx; },
            bindKeys: function () {
                document.addEventListener('keydown', function (e) {
                    var t = e.target;
                    if (t && (t.matches && t.matches('input, textarea, select')
                              || t.isContentEditable
                              || (t.closest && t.closest('.modal.show')))) return;
                    if (config.enabled && !config.enabled()) return;
                    if (e.code === 'KeyL') { e.preventDefault(); api.forward(); }
                    else if (e.code === 'KeyJ') { e.preventDefault(); api.reverse(); }
                    else if (e.code === 'KeyK') { e.preventDefault(); api.stop(); }
                });
            },
        };
        return api;
    }

    global.WamaShuttle = { create: create, DEFAULT_LEVELS: DEFAULT_LEVELS };
})(window);
