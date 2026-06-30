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

  // Met à jour un bouton de cycle déjà présent dans une card selon card.dataset.status (icône+action+titre).
  function refresh(card) {
    if (!card) return;
    var btn = card.querySelector('.wama-cycle-btn');
    if (!btn) return;
    var st = stateFor(card.dataset.status || card.getAttribute('data-status'));
    btn.setAttribute('data-cycle-action', st.action);
    btn.setAttribute('title', st.title);
    var icon = btn.querySelector('i');
    if (icon) icon.className = 'fas ' + st.icon;
  }

  // Déploiement PLUG-AND-PLAY : observe les changements de data-status des cards et rafraîchit leur
  // bouton de cycle. L'app n'a plus qu'à (1) rendre le bouton une fois via html(), (2) mettre à jour
  // card.dataset.status (ce que la plupart font déjà au poll) — l'icône ▶/⏹/↻ suit automatiquement.
  function autoSync(opts) {
    opts = opts || {};
    var container = opts.container;
    var cardSelector = opts.cardSelector || '.card[data-id], [data-id]';
    if (!container || container._wamaCycleSync || !global.MutationObserver) return;
    container._wamaCycleSync = true;
    new MutationObserver(function (muts) {
      muts.forEach(function (m) {
        if (m.type === 'attributes' && m.attributeName === 'data-status') refresh(m.target);
      });
    }).observe(container, { attributes: true, attributeFilter: ['data-status'], subtree: true });
    container.querySelectorAll(cardSelector).forEach(refresh);  // état initial
  }

  global.WamaCycleButton = { stateFor: stateFor, html: html, wire: wire, refresh: refresh, autoSync: autoSync };
})(window);
