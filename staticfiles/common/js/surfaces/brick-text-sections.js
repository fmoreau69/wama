/**
 * Brique `text_sections` — un texte structuré (Markdown), découpé en sections à ses titres et
 * corrigé à la main (chantier SURFACES, 2026-10-13 ; 1ʳᵉ surface : le FOND du Writer).
 *
 * Universelle : elle lit la valeur éditée de la surface quand c'est un TEXTE (le contenu d'un
 * champ fichier, `surfaces.text_value`) et la réécrit telle quelle — jamais un format à elle.
 * Le découpage ne perd rien : `sections.join('') === texte` (titre compris, fins de ligne
 * gardées) ; un titre `# …` hors bloc de code commence une section.
 *
 * Décisions qu'elle porte (ROADMAP §21.5, n°2) : on corrige le FOND, la forme se DEMANDE — aucune
 * barre de mise en forme ; l'aperçu n'est jamais édité (brique `html_preview`).
 *
 * L'ANNULER/RÉTABLIR est celui de WAMA : chaque section est un `contenteditable` (et non un
 * `<textarea>`, dont l'historique commun laisse Ctrl+Z à la pile native du navigateur —
 * `wama-history.js`) ; une rafale de frappe = un cran (`ctx.edit(fn, {burst: true})`), quitter
 * une section ferme la rafale. C'est la règle de la page de correction du Transcriber.
 */
(function (global) {
    'use strict';

    var HEADING = /^#{1,6}\s/;
    var FENCE = /^\s*(```|~~~)/;

    /** Les sections d'un texte, sans rien perdre : leur concaténation EST le texte. */
    function split(text) {
        var lines = String(text || '').match(/[^\n]*\n|[^\n]+$/g) || [];
        var out = [], cur = '', fenced = false;
        lines.forEach(function (line) {
            if (FENCE.test(line)) fenced = !fenced;
            else if (!fenced && HEADING.test(line) && cur) { out.push(cur); cur = ''; }
            cur += line;
        });
        if (cur || !out.length) out.push(cur);
        return out;
    }

    /** Le texte affiché d'une section (sans ses fins de ligne finales) et ce qu'elle garde à part. */
    function parts(chunk) {
        var body = chunk.replace(/\n+$/, '');
        return { body: body, tail: chunk.slice(body.length) };
    }

    function mount(body, ctx) {
        body.classList.add('wama-brick-text');
        var list = document.createElement('div');
        list.className = 'wama-text-sections';
        body.appendChild(list);
        var tails = [];

        function readText(el) {
            // `innerText` rend les retours à la ligne quelle que soit la façon dont le navigateur
            // les a écrits (nœud texte, <br>, <div> en repli `contenteditable=true`).
            return (el.innerText || '').replace(/\n+$/, '');
        }

        /** La valeur reconstruite depuis les sections affichées. */
        function rebuild() {
            var els = list.querySelectorAll('.wama-section-text');
            var out = '';
            els.forEach(function (el, i) {
                var tail = tails[i] || '';
                // Une section suivie d'une autre finit par une fin de ligne : sinon le titre
                // suivant se collerait à sa dernière ligne.
                if (!tail && i < els.length - 1) tail = '\n';
                out += readText(el) + tail;
            });
            return out;
        }

        function caret(el) {
            var sel = global.getSelection();
            if (!sel.rangeCount || !el.contains(sel.anchorNode)) return null;
            var r = sel.getRangeAt(0).cloneRange();
            r.selectNodeContents(el);
            r.setEnd(sel.getRangeAt(0).endContainer, sel.getRangeAt(0).endOffset);
            return r.toString().length;
        }

        function placeCaret(el, offset) {
            var walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
            var node, left = offset;
            while ((node = walker.nextNode())) {
                if (left <= node.length) {
                    var r = document.createRange();
                    r.setStart(node, left);
                    r.collapse(true);
                    var sel = global.getSelection();
                    sel.removeAllRanges();
                    sel.addRange(r);
                    return;
                }
                left -= node.length;
            }
        }

        function render() {
            // Garder la place du curseur à travers un re-rendu (annuler, rétablir, enregistrer).
            var active = document.activeElement;
            var at = active && list.contains(active) ? [Number(active.dataset.i), caret(active)] : null;
            var chunks = split(typeof ctx.value() === 'string' ? ctx.value() : '');
            tails = [];
            list.innerHTML = '';
            chunks.forEach(function (chunk, i) {
                var p = parts(chunk);
                tails.push(p.tail);
                var el = document.createElement('div');
                el.className = 'wama-section-text' + (HEADING.test(p.body) ? ' has-heading' : '');
                el.dataset.i = i;
                el.spellcheck = true;
                if (ctx.canEdit) {
                    el.contentEditable = 'plaintext-only';
                    if (el.contentEditable !== 'plaintext-only') el.contentEditable = 'true';
                }
                el.textContent = p.body;
                list.appendChild(el);
            });
            if (at) {
                var el = list.querySelector('.wama-section-text[data-i="' + at[0] + '"]');
                if (el) { el.focus(); if (at[1] != null) placeCaret(el, at[1]); }
            }
        }

        list.addEventListener('input', function () {
            ctx.edit(function () { return rebuild(); }, { burst: true });
        });
        // Coller : du TEXTE seul — un collage riche (repli `contenteditable=true`) apporterait
        // une mise en forme que le fond ne porte pas.
        list.addEventListener('paste', function (ev) {
            if (!ev.clipboardData) return;
            ev.preventDefault();
            document.execCommand('insertText', false, ev.clipboardData.getData('text/plain'));
        });
        list.addEventListener('focusout', function () {
            ctx.history.endBurst();
            // Un titre tapé au milieu d'une section en commence une nouvelle : le découpage se
            // refait en sortant de la section, jamais pendant la frappe.
            if (split(ctx.value()).length !== list.children.length) render();
        });

        function refresh() {
            // Pendant la frappe la valeur EST ce qu'affichent les sections : ne rien reconstruire
            // (le curseur sauterait). Seul un changement venu d'ailleurs — annuler, rétablir,
            // chargement, enregistrement — redessine.
            if (typeof ctx.value() !== 'string' || rebuild() !== ctx.value()) render();
        }

        render();
        return {
            refresh: refresh,
            help: 'Cliquer dans une section pour la corriger · un titre « # … » commence une section · Ctrl+Z / Ctrl+Maj+Z : annuler / rétablir',
        };
    }

    global.WamaSurface.registerBrick('text_sections', { title: 'Texte', mount: mount, split: split });
})(window);
