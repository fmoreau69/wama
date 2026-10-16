/**
 * WamaInstant — le résultat INSTANTANÉ de la saisie (CARD_DESIGN §11.11 D bis, 2026-10-16).
 *
 * Une app qui DÉCLARE `has_instant_result` (le Translator « à la DeepL ») reçoit, sous la consigne
 * de sa card d'entrée, une zone `[data-wama-instant]` (`_new_item_card_v4.html`, tag
 * `instant_result_url`). Pendant la frappe, la saisie part à la route `instant` de l'app, qui
 * joue sa glu `instant_result(item)` sur un élément NON enregistré : rien en file, rien en base.
 *
 * Contrat avec la vue générée (`views_gen`, corps `instant`) : la saisie est postée sous
 * `instant_text` ; la réponse est `{text}` ou `{error}`. Les réglages du volet sont postés quand la
 * card nomme leur hôte (`data-instant-params`, lu par `WamaParams.read`) ; sinon la vue applique la
 * cascade de l'ajout (réglages enregistrés, puis défauts).
 *
 * Trois règles, parce qu'on tape plus vite qu'un modèle ne répond :
 *  - un DÉLAI de saisie (DELAY_MS) : on n'envoie pas à chaque touche ;
 *  - seule la DERNIÈRE réponse s'affiche (numéro de demande) : une réponse lente d'une saisie
 *    périmée n'écrase jamais celle d'une saisie plus récente ;
 *  - une saisie vide efface le résultat, sans appel.
 */
(function (global) {
  'use strict';

  var DELAY_MS = 600;

  function wire(zone) {
    var input = document.getElementById(zone.dataset.instantInput);
    var out = zone.querySelector('[data-instant-text]');
    var state = zone.querySelector('[data-instant-state]');
    if (!input || !out || !zone.dataset.instantUrl || zone.dataset.instantWired) return;
    zone.dataset.instantWired = '1';
    var timer = null;
    var asked = 0;

    function say(text) { if (state) state.textContent = text || ''; }

    function send() {
      var text = (input.value || '').trim();
      var ticket = ++asked;
      if (!text) { out.textContent = ''; say(''); return; }
      var fd = new FormData();
      var host = zone.dataset.instantParams && document.getElementById(zone.dataset.instantParams);
      if (host && global.WamaParams && global.WamaParams.read) {
        var values = global.WamaParams.read(host);
        Object.keys(values).forEach(function (k) {
          if (values[k] !== '' && values[k] != null) fd.append(k, values[k]);
        });
      }
      fd.set('instant_text', text);
      say('…');
      var app = global.WamaApp || {};
      app.csrfFetch(zone.dataset.instantUrl, app.csrfToken(), { method: 'POST', body: fd })
        .then(function (r) {
          return r.json().catch(function () { return { error: 'réponse illisible (' + r.status + ')' }; });
        })
        .then(function (data) {
          if (ticket !== asked) return;              // une saisie plus récente est partie
          if (data && data.error) { say(data.error); return; }
          out.textContent = (data && data.text) || '';
          say('');
        })
        .catch(function (err) {
          if (ticket === asked) say('Résultat indisponible : ' + (err && err.message || err));
        });
    }

    input.addEventListener('input', function () {
      clearTimeout(timer);
      timer = setTimeout(send, DELAY_MS);
    });
  }

  function wireAll(root) {
    Array.prototype.forEach.call((root || document).querySelectorAll('[data-wama-instant]'), wire);
  }

  global.WamaInstant = { wireAll: wireAll, DELAY_MS: DELAY_MS };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', function () { wireAll(); });
  else wireAll();
})(window);
