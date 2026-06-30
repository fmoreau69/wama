/*
 * WamaCycleButton — bouton de CYCLE commun ▶ Lancer / ⏹ Stop / ↻ Relancer.
 * (cf. memory project_process_button_lifecycle)
 *
 * Principe : le bouton est TOUJOURS VERT (outline-success) ; SEULE L'ICÔNE change selon le statut.
 * L'ÉTAT (en cours/fini/échoué) est porté par le tricolore de la card/barre, pas par le bouton.
 * Source unique pour cards rendues en JS ET (potentiellement) partials serveur générés via JS.
 *
 * Usage :
 *   container.innerHTML += WamaCycleButton.html(status, id);
 *   WamaCycleButton.wire(root, {
 *     start:   (id) => {...},   // ▶ et ↻ (relancer = même endpoint que démarrer)
 *     stop:    (id) => {...},   // ⏹
 *   });
 */
(function (global) {
  // Statut applicatif → action effective + icône + libellé. Bouton toujours vert.
  function stateFor(status) {
    var s = (status || 'PENDING').toUpperCase();
    if (s === 'RUNNING') return { action: 'stop', icon: 'fa-stop', title: 'Arrêter' };
    if (s === 'SUCCESS' || s === 'FAILURE') return { action: 'restart', icon: 'fa-rotate-right', title: 'Relancer' };
    return { action: 'start', icon: 'fa-play', title: 'Démarrer' };  // PENDING / DRAFT / neuf
  }

  // Markup du bouton. data-cycle-action = action effective ; data-id = item. classe .wama-cycle-btn
  // pour le câblage commun. btnClass surchargable (défaut outline-success = vert).
  function html(status, id, opts) {
    opts = opts || {};
    var st = stateFor(status);
    var cls = (opts.btnClass || 'btn btn-sm btn-outline-success') + ' wama-cycle-btn' +
      (opts.extraClass ? (' ' + opts.extraClass) : '');
    return '<button type="button" class="' + cls + '" data-cycle-action="' + st.action +
      '" data-id="' + id + '" title="' + st.title + '"><i class="fas ' + st.icon + '"></i></button>';
  }

  // Câblage délégué (un seul listener par root). handlers.start gère start ET restart (même endpoint),
  // handlers.stop gère l'arrêt. Lié UNE fois par root (pas d'accumulation au re-render).
  function wire(root, handlers) {
    if (!root || root._wamaCycleBound) return;
    root._wamaCycleBound = true;
    root.addEventListener('click', function (e) {
      var btn = e.target.closest('.wama-cycle-btn');
      if (!btn || !root.contains(btn)) return;
      var action = btn.getAttribute('data-cycle-action');
      var id = btn.getAttribute('data-id');
      if (action === 'stop') { if (handlers.stop) handlers.stop(id, btn); }
      else { if (handlers.start) handlers.start(id, btn); }   // start + restart
    });
  }

  global.WamaCycleButton = { stateFor: stateFor, html: html, wire: wire };
})(window);
