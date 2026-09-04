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
 * ══ DEUX FAÇONS DE MARQUER UN CRAN — ET C'EST L'ADOPTION QUI L'A RÉVÉLÉ ═════════════════
 *
 *   `push()`    AVANT la mutation  — le transcriber marque en tête de chaque opération.
 *   `commit()`  APRÈS la mutation  — le studio fait tout passer par UN entonnoir
 *                                    (`persistDraft()`, en fin de ses 9 opérations).
 *   `silence(fn)`                  — chargement programmatique : ne rien enregistrer.
 *
 * ⚠ La v1 de cette brique n'offrait que `push()`. C'était suffisant pour le consommateur dont
 * elle sortait, et insuffisant pour le suivant : imposer `push()` au studio aurait voulu dire
 * disperser 9 marquages dans du code qui en a déjà UN, chacun étant une occasion de se tromper
 * d'ordre. *Une brique n'est validée que par son SECOND consommateur — c'est lui qui révèle ce
 * que la première extraction avait pris pour universel.*
 *
 * ══ CE QUI N'EST PAS UNIVERSEL, ET RESTE DONC UNE OPTION ════════════════════════════════
 *
 * La COALESCENCE DES RAFALES (`burstWindow`) : sans elle, une saisie au clavier produirait un
 * cran d'annulation par caractère.
 *
 * ⚠ J'avais écrit ici qu'elle « n'a aucun sens sur un graphe, où chaque mutation est déjà
 * atomique ». **C'est faux, et l'adoption l'a montré** : c'est vrai des mutations STRUCTURELLES
 * (ajouter un nœud, tirer un lien, déplacer) et faux des CHAMPS DE PARAMÈTRES d'un nœud, qui
 * sont du texte comme ailleurs. Un même éditeur a les deux natures — d'où un choix par APPEL
 * (`commit({burst: true})`) et non par consommateur. *Une généralisation tirée d'un seul cas
 * décrit ce cas, pas la règle.*
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

        // ── Mode ENTONNOIR (`commit`) : l'état connu AVANT la dernière mutation ───────────
        //
        // Il existe DEUX façons de marquer un cran, parce que les consommateurs marquent à
        // deux endroits différents — et ce n'est pas un détail de style :
        //
        //   `push()`    AVANT la mutation. Le transcriber appelle `pushHistory()` en tête de
        //               chaque opération (splitAt, mergeAt, compact…).
        //   `commit()`  APRÈS la mutation. Le studio fait tout passer par UN entonnoir
        //               (`persistDraft()`, appelé en fin de ses 9 opérations) — un `push()`
        //               y photographierait l'état DÉJÀ modifié, et « annuler » ne ferait
        //               rien de visible.
        //
        // Imposer `push()` au studio aurait voulu dire disperser 9 marquages dans du code
        // qui en a déjà UN, chacun étant une occasion de se tromper d'ordre. On garde donc
        // son entonnoir et on retient l'état précédent ici.
        var previous = snapshot();

        // ⚠⚠ RÉ-ENTRANCE — la raison pour laquelle `commit` doit vivre DANS la brique.
        // Restaurer, c'est muter : chez le studio, `loadGraph()` appelle `clearCanvas()`,
        // qui appelle `removeNode`/`removeLink`… qui appellent `persistDraft()`. Sans ce
        // drapeau, une annulation empilerait un cran par nœud détruit — et l'historique se
        // remplirait de son propre travail. Tout consommateur à entonnoir a ce problème :
        // c'est pourquoi la garde n'est pas laissée à sa charge.
        var restoring = false;

        function syncButtons() {
            document.querySelectorAll(undoSelector).forEach(function (b) {
                b.disabled = !undoStack.length;
            });
            document.querySelectorAll(redoSelector).forEach(function (b) {
                b.disabled = !redoStack.length;
            });
        }

        /** Empile un état donné. Cœur commun de `push()` et `commit()`. */
        function stack(state) {
            undoStack.push(state);
            // Le plafond protège la mémoire : un snapshot est une copie profonde du modèle, et
            // une session d'édition longue en produit des centaines.
            if (undoStack.length > max) undoStack.shift();
            // Une nouvelle action abandonne la branche « rétablir » : c'est le comportement
            // attendu de tout éditeur, et le conserver donnerait un redo qui rejoue un futur
            // qui n'existe plus.
            redoStack.length = 0;
            syncButtons();
        }

        /** Empile l'état COURANT — à appeler AVANT la mutation (cf. l'en-tête). */
        function push() {
            if (restoring) return;
            var state = snapshot();
            stack(state);
            previous = state;        // rien n'a encore muté : courant == état d'avant
            burstActive = false;     // une action structurelle ferme la rafale de frappe
        }

        /**
         * Marque un cran APRÈS la mutation — mode entonnoir (cf. `previous` plus haut).
         *
         * `opts.burst` coalesce : à utiliser depuis un champ de saisie, où l'entonnoir se
         * déclenche à CHAQUE caractère. Sans lui, taper « bonjour » dans le paramètre d'un
         * nœud coûterait sept crans d'annulation.
         *
         * ⚠ Ce qui corrige au passage une phrase trop absolue que j'avais écrite : « la
         * coalescence n'a aucun sens sur un graphe, où chaque mutation est atomique ». C'est
         * vrai des mutations STRUCTURELLES (ajouter un nœud, tirer un lien, déplacer) et FAUX
         * des champs de paramètres, qui sont du texte comme ailleurs. Un éditeur de graphe a
         * les deux natures — c'est l'APPELANT qui sait laquelle il déclenche, pas la brique.
         */
        function commit(opts) {
            if (restoring) return;
            opts = opts || {};
            if (opts.burst && burstWindow) {
                if (!burstActive) { stack(previous); burstActive = true; }
                clearTimeout(burstTimer);
                burstTimer = setTimeout(function () { burstActive = false; }, burstWindow);
            } else {
                stack(previous);
                burstActive = false;
            }
            previous = snapshot();
        }

        /**
         * Exécute `fn` SANS rien enregistrer — chargement programmatique (restauration d'un
         * brouillon, ouverture d'un document). L'état d'après devient la nouvelle référence.
         *
         * Se compose pour rendre UN cran d'un geste qui mute en cascade :
         *     history.commit();                  // l'état d'avant
         *     history.silence(clearCanvas);      // les N suppressions ne comptent pas
         */
        function silence(fn) {
            var before = restoring;
            restoring = true;
            try { fn(); } finally { restoring = before; }
            previous = snapshot();
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

        // Restaurer, c'est muter : on lève `restoring` pour que l'entonnoir d'un consommateur
        // ne se remplisse pas de son propre travail (cf. le bloc RÉ-ENTRANCE plus haut), et on
        // recale `previous` — sinon le `commit()` suivant empilerait un état périmé.
        function apply(state) {
            restoring = true;
            try { restore(state); } finally { restoring = false; }
            previous = snapshot();
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

        /** Vide l'historique — nouveau document, pas nouvel état. */
        function reset() {
            undoStack.length = 0;
            redoStack.length = 0;
            burstActive = false;
            previous = snapshot();
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
            push: push, commit: commit, silence: silence,
            undo: undo, redo: redo,
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
        return { push: noop, commit: noop, silence: function (fn) { fn(); },
                 undo: function () { return false; }, redo: function () { return false; },
                 beginBurst: noop, endBurst: noop, reset: noop, syncButtons: noop,
                 canUndo: function () { return false; }, canRedo: function () { return false; },
                 depth: function () { return { undo: 0, redo: 0 }; } };
    }

    global.WamaHistory = { create: create };
})(window);
