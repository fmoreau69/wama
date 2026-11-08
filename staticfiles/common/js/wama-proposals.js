/**
 * WAMA — WamaProposals : la file « Propositions à valider » d'une page de registre, la MÊME pour
 * toutes les familles (décision de Fabien, 2026-11-07, `WAMA_VOLETS §2` : une proposition se valide
 * sur la page de SON registre — un modèle au model manager, une librairie au registre des
 * librairies).
 *
 * Sortie du model manager (`mmLoadProposals`, 2026-09-29) : le PLAN vient du serveur
 * (`proposals.plan` — champs comblés, divergences NON appliquées, erreurs) ; « Valider » =
 * superposition + write-back + promotion + corpus ; « Rejeter » ne défait rien. Seul un
 * administrateur décide (`api_manifest_proposal_decide`, 403 sinon) : un développeur voit la file
 * où il propose, sans les boutons.
 *
 * Montée par le gabarit commun `common/_proposals_queue.html` :
 *
 *   <div data-wama-proposals data-list-url="…?kind=library" data-decide-url="…"
 *        data-backends="0" data-reload="1">…</div>
 *
 * `data-backends="1"` montre aussi les BACKENDS proposés (rôle `backend`, du code que « Valider »
 * écrit dans wama/common/backends/) ; `data-reload="1"` recharge la page après une décision (une
 * page rendue par le serveur). Toute décision émet `wama:proposals-decided` sur le document.
 */
(function (global) {
    'use strict';

    function csrf() {
        var m = document.cookie.match(/csrftoken=([^;]+)/);
        return m ? m[1] : '';
    }

    function esc(value) {
        if (global.WamaApp && global.WamaApp.escapeHtml) { return global.WamaApp.escapeHtml(value); }
        return String(value == null ? '' : value).replace(/[&<>"']/g, function (c) {
            return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
        });
    }

    function say(msg, tone) {
        if (global.WamaApp && global.WamaApp.toast) { global.WamaApp.toast(msg, tone); }
    }

    function decisionButtons(attr, value, disabled, title, hidden) {
        return '<div class="d-flex gap-1 mt-1' + (hidden ? ' d-none' : '') + '">'
            + '<button type="button" class="btn btn-sm btn-success py-0" ' + attr + '="' + esc(value) + '"'
            + ' data-decision="apply"' + (disabled ? ' disabled' : '') + ' title="' + esc(title) + '">'
            + '<i class="fas fa-check me-1"></i>Valider</button>'
            + '<button type="button" class="btn btn-sm btn-outline-secondary py-0" ' + attr + '="' + esc(value) + '"'
            + ' data-decision="reject"><i class="fas fa-xmark me-1"></i>Rejeter</button></div>';
    }

    /** Un backend proposé (marche B2). Aucun contrôle ne juge la QUALITÉ d'une sortie : le smoke
     *  dit seulement qu'elle existe. */
    function backendHtml(b, waiting, hidden) {
        var c = b.checks || {}, errors = c.errors || [], s = b.smoke || {}, r = b.resolution || {};
        return '<div class="border-top border-secondary pt-1 mt-1 small">'
            + '<div class="text-body-emphasis text-break">backend · <code>' + esc(b.module || '') + '</code></div>'
            + '<div class="text-muted text-break">' + esc(b.model_key || '') + ' — moteur ' + esc(b.engine || '?')
            + ', écrit par ' + esc(b.model || '?') + '</div>'
            + errors.map(function (e) { return '<div class="text-danger text-break">' + esc(e) + '</div>'; }).join('')
            + (c.warnings || []).map(function (w) { return '<div class="text-warning text-break">' + esc(w) + '</div>'; }).join('')
            + (r.resolved !== undefined
                ? '<div class="' + (r.resolved ? 'text-success' : 'text-danger') + '">Résolution : '
                  + (r.resolved ? 'ce backend sera choisi' : 'NON choisi (' + esc(String(r.chosen)) + ')') + '</div>' : '')
            + (s.ran
                ? '<div class="' + (s.ok ? 'text-success' : 'text-danger') + ' text-break">Smoke CPU : '
                  + (s.ok ? 'image ' + esc((s.size || []).join('×')) + ' en ' + esc(String(s.seconds)) + ' s — ' + esc(s.image || '')
                          : esc(s.error || 'échec')) + '</div>'
                : '<div class="text-muted">Smoke : ' + esc(s.reason || 'non joué') + '</div>')
            + waiting
            + decisionButtons('data-file', b.file, errors.length,
                              'Écrire le module dans wama/common/backends/ (jamais par-dessus un existant)', hidden)
            + '</div>';
    }

    /** Un manifeste proposé, avec son plan. */
    function manifestHtml(p, waiting, hidden) {
        var errors = p.errors || [], filled = p.filled || [], div = p.divergences || [];
        var title = errors.length ? 'Invalide : corriger la proposition'
            : (filled.length ? 'Appliquer au registre et au corpus' : 'Rien à combler');
        return '<div class="border-top border-secondary pt-1 mt-1 small">'
            + '<div class="text-body-emphasis text-break">' + esc(p.kind || '') + ' · <code>' + esc(p.key || '') + '</code></div>'
            + '<div class="text-muted text-break">' + (p.origin ? 'Origine : ' + esc(p.origin) : '') + '</div>'
            + (filled.length ? '<div class="text-success">Comblé : ' + filled.map(esc).join(', ') + '</div>' : '')
            + div.map(function (d) {
                return '<div class="text-warning text-break">Divergence ' + esc(d.path) + ' : établi <code>'
                    + esc(JSON.stringify(d.current)) + '</code>, proposé <code>' + esc(JSON.stringify(d.proposed))
                    + '</code> — non appliqué</div>';
            }).join('')
            + errors.map(function (e) { return '<div class="text-danger text-break">' + esc(e) + '</div>'; }).join('')
            + waiting
            + decisionButtons('data-proposal', p.id, errors.length || !filled.length, title, hidden)
            + '</div>';
    }

    /** Le message d'une décision réussie — l'étape suivante de la route quand la vue la sert. */
    function doneMessage(decision, data) {
        if (decision !== 'apply') { return 'Proposition rejetée.'; }
        return 'Proposition appliquée.'
            + (data.written ? ' ' + data.written + ' écrit — ' + (data.note || '') : '')
            + (data.human_gesture ? ' Étape suivante : ' + data.next_step + ' → ' + data.human_gesture : '');
    }

    function load(box) {
        var list = box.querySelector('[data-wama-proposals-list]');
        var count = box.querySelector('[data-wama-proposals-count]');
        var withBackends = box.dataset.backends === '1';
        return fetch(box.dataset.listUrl, { headers: { 'Accept': 'application/json' } })
            .then(function (r) { return r.json(); })
            .catch(function (e) { console.error('Propositions indisponibles :', e); return {}; })
            .then(function (data) {
                var items = data.proposals || [];
                var backends = withBackends ? (data.backends || []) : [];
                var canDecide = data.can_decide !== false;
                var total = items.length + backends.length;
                if (count) { count.textContent = total; }
                box.classList.toggle('d-none', total === 0);
                var waiting = canDecide ? '' : '<div class="text-muted fst-italic">En attente de validation par un administrateur.</div>';
                list.innerHTML = backends.map(function (b) { return backendHtml(b, waiting, !canDecide); }).join('')
                    + items.map(function (p) { return manifestHtml(p, waiting, !canDecide); }).join('');
                // L'ancre d'une fin de tâche qui a proposé : la file n'apparaît qu'une fois chargée.
                if (box.id && location.hash === '#' + box.id && total) {
                    box.scrollIntoView({ block: 'start', behavior: 'smooth' });
                    history.replaceState(null, '', location.pathname + location.search);
                }
            });
    }

    function decide(box, button) {
        button.disabled = true;
        var target = button.dataset.file ? { file: button.dataset.file } : { id: Number(button.dataset.proposal) };
        var decision = button.dataset.decision;
        return fetch(box.dataset.decideUrl, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf() },
            body: JSON.stringify(Object.assign({}, target, { decision: decision }))
        }).then(function (r) { return r.json(); }).then(function (data) {
            if (!data.success) {
                say((data.errors || [data.error || 'Échec']).join(' ; '), 'danger');
            } else {
                say(doneMessage(decision, data), 'success');
            }
            document.dispatchEvent(new CustomEvent('wama:proposals-decided',
                { detail: { decision: decision, target: target, data: data } }));
            if (data.success && box.dataset.reload === '1') { global.location.reload(); return; }
            return load(box);
        }).catch(function (e) {
            say('Échec : ' + e, 'danger');
            return load(box);
        });
    }

    function mount(box) {
        if (box.dataset.wamaProposalsMounted) { return; }
        box.dataset.wamaProposalsMounted = '1';
        box.addEventListener('click', function (ev) {
            var b = ev.target.closest && ev.target.closest('button[data-decision]');
            if (b && box.contains(b)) { decide(box, b); }
        });
        load(box);
    }

    function mountAll() {
        document.querySelectorAll('[data-wama-proposals]').forEach(mount);
    }

    if (document.readyState === 'loading') { document.addEventListener('DOMContentLoaded', mountAll); }
    else { mountAll(); }

    global.WamaProposals = { mount: mount, reload: load, manifestHtml: manifestHtml, backendHtml: backendHtml };
})(window);
