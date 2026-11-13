/**
 * WamaFullText — le TEXTE COMPLET d'un texte que le CSS coupe, au survol (et à l'appui long).
 *
 * Demande de Fabien (2026-11-13) : « quand je survole le titre d'une card, le nom complet ne
 * s'affiche pas — c'est géré ailleurs, comme dans le filemanager ; vérifier que c'est un mécanisme
 * commun, sans réinvention, et l'appliquer là où ça manque ». Relevé ce jour-là : AUCUN mécanisme
 * commun, et cinq façons de faire — le gestionnaire de fichiers copiait le texte de chaque nœud
 * dans `title` (`addFilenameTitles`), la visionneuse le nom de son titre (`media-preview.js`),
 * huit cards mettaient une INDICATION (« Aperçu ») à la place
 * du nom, deux le prompt (vide pour un cover), deux le nom ; et cinq gabarits coupaient le nom CÔTÉ
 * SERVEUR (`truncatechars`), qui n'existait alors plus nulle part dans la page.
 *
 * La règle, une fois pour toute page (`base.html`) : un élément dont le CSS coupe le texte — une
 * ellipse (`text-overflow: ellipsis`) ou une limite de lignes (`-webkit-line-clamp`) — et qui
 * DÉBORDE réellement, ou un texte d'une ligne qui dépasse du conteneur qui le rogne (un nœud
 * d'arbre), reçoit au survol son texte complet en `title`. Une indication que la page avait
 * écrite (`title="Aperçu"`, le prompt d'une card) est GARDÉE, sous le texte. Un texte qui tient
 * n'est pas touché. L'appui long au doigt montre ce `title` (`wama-gestures.js`) : la brique le pose
 * aussi à l'appui d'un pointeur qui n'est pas une souris.
 *
 * Aucune page n'écrit de `title` pour montrer un nom coupé ; aucun gabarit ne coupe un nom côté
 * serveur quand le CSS le fait (garde : `tests_preview_entry`).
 */
(function (global) {
    'use strict';

    /** Profondeur de recherche du texte coupé au-dessus de l'élément survolé (le nom d'une card
     *  est souvent un `<span>` dans un lien ou un bouton). */
    var DEPTH = 4;
    /** Le `title` que la page avait écrit, retenu une fois (une indication à garder). */
    var HINT = 'wamaTitleHint';

    /** Ce qu'un texte peut contenir à côté de ses mots sans cesser d'être UN texte (l'icône d'un
     *  nœud d'arbre, d'un lien). */
    var DECOR = { I: 1, SVG: 1, IMG: 1 };

    function isTextLeaf(el) {
        for (var c = el.firstElementChild; c; c = c.nextElementSibling) {
            if (!DECOR[c.tagName.toUpperCase()]) return false;
        }
        return true;
    }

    /** Le conteneur qui ROGNE `el` (premier ancêtre dont le débordement n'est pas visible). */
    function clipBox(el) {
        for (var p = el.parentElement, i = 0; p && i < 8; p = p.parentElement, i += 1) {
            if (global.getComputedStyle(p).overflowX !== 'visible') return p;
        }
        return null;
    }

    /** Coupé : (a) par le CSS du texte lui-même — ellipse ou limite de lignes — et il déborde ;
     *  (b) un texte sur une ligne (`nowrap`), sans autre enfant qu'une icône, qui dépasse du
     *  conteneur qui le rogne (le nom d'un nœud de l'arbre du gestionnaire de fichiers). */
    function isCut(el) {
        if (!el || el.nodeType !== 1 || !global.getComputedStyle) return false;
        var style = global.getComputedStyle(el);
        var clamp = style.webkitLineClamp || style.getPropertyValue('-webkit-line-clamp');
        if (style.textOverflow === 'ellipsis' || (clamp && clamp !== 'none')) {
            return el.scrollWidth > el.clientWidth + 1 || el.scrollHeight > el.clientHeight + 1;
        }
        if (style.whiteSpace.indexOf('nowrap') < 0 && style.whiteSpace !== 'pre') return false;
        if (!isTextLeaf(el)) return false;
        var box = clipBox(el);
        if (!box) return false;
        var r = el.getBoundingClientRect(), b = box.getBoundingClientRect();
        // Sans boîte (l'option d'une liste fermée, un élément masqué) : rien qu'on survole.
        if (!r.width || !r.height) return false;
        return r.right > b.right + 1 || r.left < b.left - 1;
    }

    function fullText(el) {
        return String(el.textContent || '').replace(/\s+/g, ' ').trim();
    }

    /** Le `title` d'un texte coupé : le texte entier, puis l'indication de la page s'il y en a une
     *  (et qu'elle ne le redit pas). */
    function titleFor(full, hint) {
        return hint && hint !== full && full.indexOf(hint) < 0 ? full + '\n' + hint : full;
    }

    function reveal(target) {
        for (var el = target, depth = 0; el && el.nodeType === 1 && depth < DEPTH;
             el = el.parentElement, depth += 1) {
            if (!isCut(el)) continue;
            var full = fullText(el);
            if (!full) return;
            if (!(HINT in el.dataset)) el.dataset[HINT] = el.getAttribute('title') || '';
            var title = titleFor(full, el.dataset[HINT]);
            if (el.getAttribute('title') !== title) el.setAttribute('title', title);
            return;
        }
    }

    if (typeof document !== 'undefined' && document.addEventListener) {
        document.addEventListener('mouseover', function (e) { reveal(e.target); }, true);
        document.addEventListener('pointerdown', function (e) {
            if (e.pointerType && e.pointerType !== 'mouse') reveal(e.target);
        }, true);
    }

    global.WamaFullText = { reveal: reveal, isCut: isCut, titleFor: titleFor };
})(window);
