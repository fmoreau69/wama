/**
 * wama-key-settings.js — RÉGLER LES TOUCHES D'UNE BRIQUE, pour son compte (`WAMA_VOLETS §3-ter`,
 * 2026-11-15 ; décision de Fabien du 12/11 : « les touches d'une brique se règlent sur la page des
 * briques UI, brique par brique »).
 *
 * La page sert, par brique réglable, ses raccourcis RÉSOLUS pour ce compte et ce qu'il a déjà
 * posé (`<script type="application/json" id="wama-key-settings">` : `{url, bricks: {clé: {rows,
 * keys}}}`). Ce module rend la ligne « Clavier » de chaque tuile (`[data-key-settings="<clé>"]`)
 * avec une touche CLIQUABLE par action : un clic, puis la frappe voulue. Le serveur valide
 * (`surfaces.override_problems`), garde, et rend les raccourcis tels qu'ils se lisent désormais.
 *
 * Une touche se dit comme au registre : par sa POSITION (`KeyJ`, `Shift+ArrowLeft` —
 * `WamaKeys.combo`), ou par le CARACTÈRE qu'elle produit quand ce n'est ni une lettre ni un
 * chiffre (`,`, `?` — la disposition du clavier décide où il est).
 */
(function (global) {
    'use strict';

    var source = document.getElementById('wama-key-settings');
    if (!source || !global.WamaKeys || !global.WamaApp) return;
    var config;
    try { config = JSON.parse(source.textContent) || {}; } catch (e) { return; }
    var App = global.WamaApp, esc = App.escapeHtml;
    var waiting = null;                     // {brick, name, el} : la touche qui attend sa frappe

    /** Le nom d'une frappe, tel que le registre le dirait : la règle du clavier commun. */
    var nameOf = global.WamaKeys.nameOf;

    function render(brick) {
        var row = document.querySelector('[data-key-settings="' + brick + '"]');
        var state = config.bricks[brick];
        if (!row || !state) return;
        var html = '<b>Clavier</b>', conflicts = [];
        state.rows.forEach(function (r) {
            html += '<span class="ub-chip" title="' + esc(r.where || '') + '">';
            r.keys.forEach(function (k, i) {
                // Une touche en CONFLIT (deux briques d'une même page la prennent) se voit, dit
                // avec qui, et se corrige comme elle se règle : un clic, une autre frappe.
                var clash = k.conflict ? ' is-conflict' : '';
                if (k.conflict) conflicts.push({ label: k.label, said: k.conflict, fixable: !!k.name });
                html += (i ? ' / ' : '') + (k.name
                    ? '<kbd class="wama-key-edit' + clash + '" role="button" tabindex="0" data-name="'
                      + esc(k.name) + '" title="' + esc(k.conflict ? 'Conflit : ' + k.conflict + ' — '
                      : '') + 'Cliquer, puis frapper la touche voulue (Échap : annuler)">'
                      + esc(k.label) + '</kbd>'
                    : '<kbd class="' + clash.trim() + '"' + (k.conflict ? ' title="Conflit : '
                      + esc(k.conflict) + '"' : '') + '>' + esc(k.label) + '</kbd>');
            });
            html += ' ' + esc(r.action) + '</span>';
        });
        conflicts.forEach(function (c) {
            html += '<div class="wama-key-conflict"><i class="fas fa-triangle-exclamation"></i> '
                  + '<kbd>' + esc(c.label) + '</kbd> ' + esc(c.said) + ' — '
                  + (c.fixable ? 'cliquez la touche pour en choisir une autre.'
                               : 'changez la touche de l\'autre brique.') + '</div>';
        });
        // Une action que le compte a tue n'a plus de touche à cliquer : la rétablir la rend.
        if (Object.keys(state.keys || {}).length) {
            html += '<button type="button" class="btn btn-sm btn-link wama-key-reset p-0 ms-1">'
                  + 'Rétablir les touches par défaut</button>';
        }
        row.innerHTML = html;
    }

    function send(brick, keys) {
        return App.csrfFetch(config.url, App.csrfToken(), {
            method: 'POST', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ brick: brick, keys: keys }),
        }).then(function (r) { return r.json().then(function (d) { return { ok: r.ok, data: d }; }); })
          .then(function (res) {
            if (!res.ok || !res.data.ok) {
                App.toast('Touche refusée : ' + ((res.data.problems || []).join(' ; ') || 'erreur'), 'error');
                return;
            }
            // Toutes les briques reviennent : un conflit se dit sur les deux qu'il touche.
            config.bricks = res.data.bricks;
            // Cette page elle-même lit désormais ces touches.
            global.WamaKeys.remap(brick, Object.keys(res.data.keys).length ? res.data.keys : null);
            var clash = res.data.rows.some(function (r) {
                return r.keys.some(function (k) { return k.conflict; }); });
            if (clash) App.toast('Enregistré, mais une touche est en conflit avec une autre brique : '
                                 + 'elle est signalée sur les deux.', 'warning');
            else App.toast('Touches enregistrées pour votre compte.', 'success');
        }).catch(function () { App.toast('Enregistrement impossible.', 'error'); })
          .then(function () { Object.keys(config.bricks).forEach(render); });
    }

    function stop() {
        if (waiting && waiting.el) waiting.el.classList.remove('is-waiting');
        waiting = null;
    }

    document.addEventListener('click', function (e) {
        var key = e.target.closest ? e.target.closest('.wama-key-edit') : null;
        var reset = e.target.closest ? e.target.closest('.wama-key-reset') : null;
        var row = (key || reset) ? (key || reset).closest('[data-key-settings]') : null;
        if (!row) { stop(); return; }
        e.stopPropagation();                // la tuile ne s'ouvre pas dans le volet
        var brick = row.getAttribute('data-key-settings');
        stop();
        if (reset) { send(brick, {}); return; }
        waiting = { brick: brick, name: key.getAttribute('data-name'), el: key };
        key.classList.add('is-waiting');
        key.textContent = '…';
    }, true);

    // La frappe attendue : une COUCHE du clavier commun, ouverte tant qu'une touche attend — elle
    // seule reçoit alors les frappes, aucune brique n'est actionnée (saisie comprise).
    global.WamaKeys.register({
        owner: 'key_settings', scope: 'layer',
        open: function () { return !!waiting; },
        typing: function () { return true; },
        handle: function (e) {
            var name = nameOf(e);
            if (name === null) return false;
            var w = waiting; stop();
            if (e.key === 'Escape') { render(w.brick); return true; }
            var keys = Object.assign({}, config.bricks[w.brick].keys || {});
            keys[w.name] = [name];
            send(w.brick, keys);
            return true;
        },
    });

    Object.keys(config.bricks || {}).forEach(render);
})(window);
