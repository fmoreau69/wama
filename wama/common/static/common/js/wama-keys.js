/**
 * wama-keys.js — LE CLAVIER DES BRIQUES : une touche, UN propriétaire (2026-10-29, étape 2 du
 * chantier des raccourcis, `WAMA_VOLETS §3-ter` ; règle décidée par Fabien le même jour).
 *
 * Avant lui, chaque module écoutait le document de son côté et « tout le monde réagissait » — le
 * modèle de BIND que `WAMA_DATA_WORLD §4.4` écarte. Mesuré au navigateur le 29/10 : ↓ dans le
 * panneau des notifications déplaçait aussi la card choisie, Échap qui le fermait désélectionnait
 * la card et vidait la sélection multiple, et Échap qui fermait une modale vidait cette sélection.
 *
 * Une frappe, dans cet ordre — la première étape qui la prend l'arrête :
 *   0. déjà PRISE (`defaultPrevented`) plus près du focus — un champ, un panneau qui écoute sur
 *      son propre élément (les notifications), une note gravée de la partition (le clavier
 *      d'abcjs) ;
 *   1. une COUCHE ouverte au moment de la frappe — une modale, un panneau en dialogue — garde le
 *      clavier : rien n'est distribué, SAUF au clavier propre d'une couche inscrite (`scope:
 *      'layer'`, avec `open()` qui dit si elle est ouverte — la visionneuse). Une couche inscrite
 *      ouverte compte comme couche même hors d'une modale. Relevé en CAPTURE : Bootstrap ferme une
 *      modale sur Échap avant que la frappe ne remonte jusqu'ici ;
 *   2. pendant une SAISIE, seules les touches qu'un inscrit déclare `typing` (Ctrl+Espace) — une
 *      liste de noms, ou une fonction de la frappe pour une touche qui se lit au CARACTÈRE produit
 *      (Ctrl+Z : `KeyW` en AZERTY, l'historique lit `e.key`) ;
 *      un CONTRÔLE garde les siennes : atteint au clavier, Espace et Entrée ; une liste, un curseur
 *      leurs flèches et Début/Fin ; cliqué à la souris, rien d'autre (règle de l'étape 0) ;
 *   3. la brique qui A LA MAIN (`scope: 'brick'` — son `root` contient le focus, ou le dernier
 *      clic quand rien n'a le focus) ;
 *   4. les briques PRIORITAIRES (`scope: 'page'` — le transport, la sélection de la file), dans
 *      l'ordre d'inscription.
 * Le premier `handle(e)` qui rend vrai PREND la touche (`preventDefault`), personne d'autre.
 * Un inscrit `observe: true` ne la prend jamais : il SUIT ce qui s'est passé (`handle(e, owner)`,
 * appelé après) — la pile de la file suit la sélection, la sélection multiple se relâche avec
 * l'abandon de l'inspecteur ; il n'est appelé que si la frappe a franchi les étapes 0 à 2.
 *
 *   var off = WamaKeys.register({owner: 'media_transport', scope: 'page', typing: ['Ctrl+Space'],
 *                                handle: function (e) { … return true si prise ; }});
 */
(function (global) {
    'use strict';

    var TEXT_ENTRY = 'textarea, input:not([type="button"]):not([type="submit"]):not([type="reset"])' +
                     ':not([type="checkbox"]):not([type="radio"]):not([type="range"])';
    var CONTROL = 'button, select, summary, a[href], [role="button"], input[type="button"], ' +
                  'input[type="submit"], input[type="reset"], input[type="checkbox"], ' +
                  'input[type="radio"], input[type="range"]';
    /** Ces contrôles se servent eux-mêmes des flèches et de Début/Fin. */
    var OWN_ARROWS = 'select, input[type="range"], input[type="radio"]';
    var SCOPE_RANK = { layer: -1, brick: 0, page: 1 };

    var entries = [];
    var pointerFocus = null, lastPointer = null, captured = null;
    var doc = global.document;

    function typing(t) {
        return !!(t && (t.isContentEditable || (t.matches && t.matches(TEXT_ENTRY))));
    }
    function inLayer(t) {
        return !!((doc.querySelector && doc.querySelector('.modal.show'))
                  || (t && t.closest && t.closest('[role="dialog"]')));
    }
    /** `Ctrl+Shift+KeyZ` — le nom que déclarent les briques (`surfaces.Shortcut`). */
    function combo(e) {
        return (e.ctrlKey || e.metaKey ? 'Ctrl+' : '') + (e.altKey ? 'Alt+' : '') +
               (e.shiftKey ? 'Shift+' : '') + e.code;
    }
    /** Le contrôle qui a le focus garde-t-il cette touche ? */
    function controlKeeps(t, e) {
        if (!t || !t.matches || !t.matches(CONTROL)) return false;
        if (/^(Arrow|Home$|End$)/.test(e.code) && t.matches(OWN_ARROWS)) return true;
        return (e.code === 'Space' || e.code === 'Enter') && t !== pointerFocus;
    }
    function handElement() {
        var a = doc.activeElement;
        return (a && a !== doc.body && a !== doc.documentElement) ? a : lastPointer;
    }
    function rootOf(entry) {
        return typeof entry.root === 'function' ? entry.root() : entry.root;
    }

    /** Une couche INSCRITE (`scope: 'layer'`) est-elle ouverte ? */
    function layerOpen(entry) {
        if (entry.scope !== 'layer') return false;
        try { return !!(entry.open && entry.open()); }
        catch (err) { console.error('[keys]', entry.owner, err); return false; }
    }

    function dispatch(e) {
        var layer = captured && captured.event === e ? captured.layer : inLayer(e.target);
        captured = null;
        if (e.defaultPrevented) return;
        var layers = entries.filter(layerOpen);      // ouvertes : elles seules reçoivent la frappe
        if (layer && !layers.length) return;
        var t = e.target, isTyping = typing(t), name = combo(e);
        if (!isTyping && controlKeeps(t, e)) return;
        var hand = handElement();
        function eligible(entry) {
            if (layers.length ? layers.indexOf(entry) < 0 : entry.scope === 'layer') return false;
            var allowed = typeof entry.typing === 'function' ? entry.typing(e)
                : (entry.typing || []).indexOf(name) >= 0;
            if (isTyping && !allowed) return false;
            if (entry.scope !== 'brick') return true;
            var root = rootOf(entry);
            return !!(root && hand && root.contains(hand));
        }
        var live = entries.filter(eligible);
        var claimers = live.filter(function (x) { return !x.observe; }).map(function (x, i) { return [x, i]; })
            .sort(function (a, b) { return (SCOPE_RANK[a[0].scope] - SCOPE_RANK[b[0].scope]) || (a[1] - b[1]); });
        var owner = null;
        for (var i = 0; i < claimers.length && !owner; i++) {
            try { if (claimers[i][0].handle(e)) owner = claimers[i][0]; }
            catch (err) { console.error('[keys]', claimers[i][0].owner, err); }
        }
        if (owner) e.preventDefault();
        live.forEach(function (x) {
            if (!x.observe) return;
            try { x.handle(e, owner ? owner.owner : null); }
            catch (err) { console.error('[keys]', x.owner, err); }
        });
    }

    if (doc && doc.addEventListener) {
        doc.addEventListener('pointerdown', function (e) {
            lastPointer = e.target || null;
            pointerFocus = e.target && e.target.closest ? e.target.closest(CONTROL) : null;
        }, true);
        doc.addEventListener('focusin', function (e) {
            if (e.target !== pointerFocus) pointerFocus = null;     // venu au clavier ou par script
        }, true);
        doc.addEventListener('focusout', function (e) {
            if (e.target === pointerFocus) pointerFocus = null;     // quitté : y revenir n'est plus un clic
        }, true);
        doc.addEventListener('keydown', function (e) { captured = { event: e, layer: inLayer(e.target) }; }, true);
        doc.addEventListener('keydown', dispatch);
    }

    /** Inscrit un propriétaire de touches ; rend la fonction qui le désinscrit. */
    function register(entry) {
        entry = Object.assign({ scope: 'page' }, entry);
        entries.push(entry);
        return function () {
            var at = entries.indexOf(entry);
            if (at >= 0) entries.splice(at, 1);
        };
    }

    global.WamaKeys = {
        register: register,
        typing: typing,
        combo: combo,
        /** Le contrôle `t` a-t-il été CLIQUÉ (et non atteint au clavier) ? */
        clicked: function (t) { return !!t && t === pointerFocus; },
    };
})(window);
