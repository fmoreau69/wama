/**
 * wama-history.js — HISTORIQUE annuler/rétablir, générique.
 *
 * Extrait du transcriber (`transcriber/js/edit.js`, 2026-09-04), seule implémentation du dépôt.
 * Ce n'était donc PAS une duplication à résorber : c'est une extraction faite pour un SECOND
 * consommateur identifié — le studio, qui possède déjà les trois pièces d'un historique
 * (`serializeGraph()`, `restoreDraft()`, 9 points de mutation appelant `persistDraft()`) et
 * n'en garde qu'UN cran, parce qu'il répondait à une autre demande (« ne plus perdre le graphe
 * en changeant d'app »). Transformer cet emplacement unique en pile, c'est l'undo.
 *
 * ══ POURQUOI C'EST PORTABLE ═════════════════════════════════════════════════════════════
 *
 * La machinerie ne touche JAMAIS le modèle. Elle ne le connaît que par deux fonctions que
 * l'appelant fournit — `snapshot()` et `restore(state)` — et tout le reste (les deux piles,
 * le plafond, l'état des boutons, les raccourcis) est agnostique. C'est ce qui permet à un
 * éditeur de texte et à un éditeur de graphe de partager exactement le même code.
 *
 * ══ CE QUI N'EST PAS UNIVERSEL, ET RESTE DONC UNE OPTION ════════════════════════════════
 *
 * La COALESCENCE DES RAFALES (`burstWindow`) : sans elle, une saisie au clavier produirait un
 * cran d'annulation par caractère. Elle n'a aucun sens sur un graphe, où chaque mutation est
 * déjà atomique — d'où `burstWindow: 0` pour la désactiver. *Porter cette option comme un
 * acquis est exactement le genre de détail qui fait qu'une brique « marche » chez son premier
 * consommateur et surprend le second.*
 *
 * ══ CE QUE CETTE BRIQUE NE COUVRE PAS — ET IL FAUT LE DIRE ══════════════════════════════
 *
 * ⚠⚠ **La FILE D'ATTENTE ne peut pas l'utiliser, et ce n'est pas un manque d'effort.** Les
 * deux consommateurs ci-dessus partagent un modèle client **pas encore enregistré** : c'est ce
 * qui rend le snapshot possible et bon marché. La file, elle, COMMET côté serveur à l'instant
 * où l'utilisateur lâche la souris — il n'y a rien à photographier. Son « annuler » est un
 * REJEU D'OPÉRATION INVERSE : même mot, mécanisme différent.
 *
 * Les réunir sous cette API serait la faute : une pile de snapshots promet qu'on peut remonter
 * loin, ce qui est FAUX sur un état partagé qui bouge sous vous (une tâche se termine, un lot
 * vidé s'auto-supprime, un autre onglet déplace une card). Une API qui ment sur ce qu'elle
 * garantit est pire qu'une API absente.
 *
 * ══ USAGE ═══════════════════════════════════════════════════════════════════════════════
 *
 *   const hist = WamaHistory.create({
 *     snapshot: () => JSON.parse(JSON.stringify(segments)),
 *     restore:  (state) => { segments.length = 0; segments.push(...state); render(); },
 *     undoSelector: '.t-undo', redoSelector: '.t-redo',   // défaut : .wama-undo / .wama-redo
 *     shortcuts: true,          // Ctrl+Z / Ctrl+Maj+Z / Ctrl+Y sur le document
 *     burstWindow: 900,         // 0 = pas de coalescence (éditeur non textuel)
 *   });
 *   hist.push();                // ⚠ AVANT de muter — voir ci-dessous
 *
 * 🔴 `push()` PHOTOGRAPHIE L'ÉTAT COURANT, DONC IL S'APPELLE **AVANT** LA MUTATION. C'est le
 * contrat du code d'origine et il n'est pas négociable : appelé après, on empilerait l'état
 * déjà modifié et « annuler » ne ferait rien de visible — un historique qui ne rend pas la
 * main est plus déroutant que pas d'historique du tout. Aucune vérification ne peut l'imposer
 * depuis ici : c'est le seul point où l'appelant doit savoir ce qu'il fait.
 */

(function (global) {
    'use strict';

    var DEFAULT_MAX = 100;
    var DEFAULT_BURST_MS = 900;

    function create(config) {
        config = config || {};
        var snapshot = config.snapshot;
        var restore = config.restore;
        if (typeof snapshot !== 'function' || typeof restore !== 'function') {
            console.warn('[wama-history] `snapshot` et `restore` sont requis — historique inerte.');
            return inert();
        }

        var max = config.max || DEFAULT_MAX;
        var undoSelector = config.undoSelector || '.wama-undo';
        var redoSelector = config.redoSelector || '.wama-redo';
        var burstWindow = config.burstWindow === undefined ? DEFAULT_BURST_MS : config.burstWindow;

        var undoStack = [];
        var redoStack = [];
        var burstActive = false;
        var burstTimer = null;

        function syncButtons() {
            document.querySelectorAll(undoSelector).forEach(function (b) {
                b.disabled = !undoStack.length;
            });
            document.querySelectorAll(redoSelector).forEach(function (b) {
                b.disabled = !redoStack.length;
            });
        }

        /** Empile l'état COURANT — à appeler AVANT la mutation (cf. l'en-tête). */
        function push() {
            undoStack.push(snapshot());
            // Le plafond protège la mémoire : un snapshot est une copie profonde du modèle, et
            // une session d'édition longue en produit des centaines.
            if (undoStack.length > max) undoStack.shift();
            // Une nouvelle action abandonne la branche « rétablir » : c'est le comportement
            // attendu de tout éditeur, et le conserver donnerait un redo qui rejoue un futur
            // qui n'existe plus.
            redoStack.length = 0;
            burstActive = false;     // une action structurelle ferme la rafale de frappe
            syncButtons();
        }

        /**
         * Ouvre (ou prolonge) une RAFALE de frappe : le premier appel empile, les suivants ne
         * font que repousser la fin de rafale. Sans cela, chaque caractère saisi coûterait un
         * cran d'annulation.
         */
        function beginBurst() {
            if (!burstWindow) { push(); return; }
            if (!burstActive) { push(); burstActive = true; }
            clearTimeout(burstTimer);
            burstTimer = setTimeout(function () { burstActive = false; }, burstWindow);
        }

        /** Ferme la rafale : la frappe suivante recréera une entrée d'historique propre. */
        function endBurst() { burstActive = false; }

        function apply(state) {
            restore(state);
            syncButtons();
        }

        function undo() {
            if (!undoStack.length) return false;
            redoStack.push(snapshot());
            apply(undoStack.pop());
            return true;
        }

        function redo() {
            if (!redoStack.length) return false;
            undoStack.push(snapshot());
            apply(redoStack.pop());
            return true;
        }

        function reset() {
            undoStack.length = 0;
            redoStack.length = 0;
            burstActive = false;
            syncButtons();
        }

        // Boutons : délégation sur le document, pas d'écouteur par nœud — les barres d'outils
        // sont parfois rendues en double (le transcriber en a deux, haut et bas) et parfois
        // re-rendues. Une délégation couvre les deux cas sans réattacher quoi que ce soit.
        document.addEventListener('click', function (ev) {
            if (ev.target.closest(undoSelector)) { ev.preventDefault(); undo(); return; }
            if (ev.target.closest(redoSelector)) { ev.preventDefault(); redo(); }
        });

        if (config.shortcuts) {
            document.addEventListener('keydown', function (ev) {
                if (!(ev.ctrlKey || ev.metaKey) || ev.altKey) return;
                // ⚠ `ev.key`, jamais `ev.code` : en AZERTY, Z et W sont permutés par rapport au
                // QWERTY — `ev.code` y rendrait `KeyW` pour un Ctrl+Z. `ev.key` donne le
                // caractère réellement produit par la disposition.
                var k = (ev.key || '').toLowerCase();
                if (k !== 'z' && k !== 'y') return;
                // ⚠ On laisse Ctrl+Z à un CHAMP DE FORMULAIRE (input/textarea) : sa pile
                // native est la bonne à cet endroit, et la voler ferait perdre une saisie
                // sans rien annuler d'utile (le studio a un champ « nom du pipeline » juste
                // à côté de son canvas).
                // Mais PAS à un `contenteditable` : c'est là que vit le modèle édité, et le
                // remplacement de l'annulation native y est justement l'intention — sinon
                // deux historiques concurrents se contredisent sur le même contenu.
                var t = ev.target;
                if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA')) return;
                // `restore()` reconstruit le DOM (le champ en cours d'édition disparaît) : on
                // ferme la rafale pour que la frappe d'après ouvre une entrée propre.
                endBurst();
                ev.preventDefault();
                if (k === 'y' || (k === 'z' && ev.shiftKey)) redo(); else undo();
            });
        }

        syncButtons();

        return {
            push: push, undo: undo, redo: redo,
            beginBurst: beginBurst, endBurst: endBurst,
            reset: reset, syncButtons: syncButtons,
            canUndo: function () { return undoStack.length > 0; },
            canRedo: function () { return redoStack.length > 0; },
            depth: function () { return { undo: undoStack.length, redo: redoStack.length }; },
        };
    }

    /** Historique NEUTRE — rendu quand la configuration est incomplète, pour que l'appelant
     *  ne tombe pas sur `undefined` et que la page continue de fonctionner sans annulation. */
    function inert() {
        var noop = function () {};
        return { push: noop, undo: function () { return false; }, redo: function () { return false; },
                 beginBurst: noop, endBurst: noop, reset: noop, syncButtons: noop,
                 canUndo: function () { return false; }, canRedo: function () { return false; },
                 depth: function () { return { undo: 0, redo: 0 }; } };
    }

    global.WamaHistory = { create: create };
})(window);
