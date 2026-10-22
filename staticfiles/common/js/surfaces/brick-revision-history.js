/**
 * Brique `revision_history` — les VERSIONS gardées du fichier édité (chantier SURFACES,
 * 2026-10-13 ; marche 8a, `WAMA_COLLABORATION §7.2` restes 2-3, 1ʳᵉ surface : le fond du Writer).
 *
 * Universelle : elle liste les révisions de l'élément (`…/revisions/`), la plus récente d'abord —
 * d'où vient l'état (traitement ou correction à la main), quand, par qui —, et pour celles dont
 * le fichier édité a été GARDÉ, « Reprendre » charge son texte dans la page.
 *
 * Reprendre n'est PAS un retour en arrière destructif (§7.1 : « restaurer ne détruit rien ») :
 * c'est un geste d'édition comme une frappe — `ctx.edit()`, donc un cran de l'historique commun
 * (Ctrl+Z l'annule) —, et c'est l'enregistrement qui en fait une révision NOUVELLE. Les versions
 * plus récentes restent dans la liste.
 *
 * Elle suit le champ ÉDITÉ (2026-10-22, `ctx.target()` — la partition complète du composer a ses
 * propres copies) : la liste se relit quand la page en change (`target`).
 */
(function (global) {
    'use strict';

    function when(iso) {
        try {
            return new Date(iso).toLocaleString('fr-FR', { dateStyle: 'short', timeStyle: 'short' });
        } catch (e) { return iso || ''; }
    }

    function mount(body, ctx) {
        var App = global.WamaApp || {};
        var url = ctx.config.revisions_url || '';
        /** `?field=` du champ édité, quand ce n'est pas le principal. */
        function query() {
            var field = ctx.target ? ctx.target() : '';
            return field ? '?field=' + encodeURIComponent(field) : '';
        }
        body.classList.add('wama-brick-revisions');
        var list = document.createElement('div');
        list.className = 'wama-revision-list';
        body.appendChild(list);

        function note(text) {
            list.innerHTML = '';
            var p = document.createElement('div');
            p.className = 'wama-revision-empty';
            p.textContent = text;
            list.appendChild(p);
        }

        function row(r) {
            var el = document.createElement('div');
            el.className = 'wama-revision-row';
            var head = document.createElement('div');
            head.className = 'wama-revision-head';
            var num = document.createElement('b');
            num.textContent = 'v' + r.number;
            var meta = document.createElement('span');
            meta.className = 'wama-revision-meta';
            meta.textContent = [r.origin_label, when(r.created_at), r.user].filter(Boolean).join(' · ');
            head.appendChild(num);
            head.appendChild(meta);
            if (r.published) {
                var pub = document.createElement('span');
                pub.className = 'badge text-bg-success';
                pub.textContent = 'publiée';
                head.appendChild(pub);
            }
            var btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'btn btn-xs btn-outline-emphasis';
            btn.dataset.number = String(r.number);
            btn.textContent = 'Reprendre';
            btn.disabled = !r.kept || !ctx.canEdit;
            btn.title = !r.kept ? 'Le fichier de cette version n’est plus gardé (ou elle ne l’a pas modifié)'
                : (ctx.canEdit ? 'Charger le texte de cette version dans la page' : 'Lecture seule');
            el.appendChild(head);
            el.appendChild(btn);
            return el;
        }

        function load() {
            if (!url) { note('Versions indisponibles ici.'); return; }
            fetch(url + query(), { credentials: 'same-origin' }).then(App.jsonOrExplain).then(function (res) {
                if (!res.keeps) { note('Cette app ne garde pas les versions de ce fichier.'); return; }
                if (!(res.revisions || []).length) { note('Aucune version pour l’instant.'); return; }
                list.innerHTML = '';
                res.revisions.forEach(function (r) { list.appendChild(row(r)); });
            }).catch(function (e) { note('Versions illisibles : ' + e.message); });
        }

        list.addEventListener('mousedown', function (e) { e.stopPropagation(); });
        list.addEventListener('click', function (e) {
            var btn = e.target.closest('button[data-number]');
            if (!btn || btn.disabled) return;
            var n = btn.dataset.number;
            btn.disabled = true;
            fetch(url + n + '/' + query(), { credentials: 'same-origin' }).then(App.jsonOrExplain).then(function (res) {
                if (res.error) throw new Error(res.error);
                ctx.edit(function () { return res.value; });
                ctx.status('Version ' + n + ' reprise — « Enregistrer » en fait une révision nouvelle', 'dirty');
            }).catch(function (e2) {
                ctx.status('Version ' + n + ' illisible : ' + e2.message, 'error');
            }).then(function () { btn.disabled = false; });
        });

        // Une révision NAÎT d'un enregistrement (correction à la main) ou d'un process qui finit.
        var lastStates = JSON.stringify(ctx.processes());
        ctx.on('saved', load);
        ctx.on('target', load);
        ctx.on('processes', function (states) {
            var now = JSON.stringify(states || {});
            var finished = Object.keys(states || {}).some(function (k) { return states[k] === 'SUCCESS'; });
            if (now !== lastStates && finished) load();
            lastStates = now;
        });
        load();
        return {
            help: 'Versions : « Reprendre » charge le texte d’une version dans la page (Ctrl+Z l’annule) ; ' +
                  '« Enregistrer » en fait une révision nouvelle, sans rien effacer.',
        };
    }

    global.WamaSurface.registerBrick('revision_history', { title: 'Versions', mount: mount });
})(window);
