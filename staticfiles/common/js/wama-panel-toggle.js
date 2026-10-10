/*
 * WamaPanels — replier / rouvrir un volet latéral d'un clic sur sa FRONTIÈRE (2026-10-10).
 *
 * Global, monté par base.html sur TOUTE page : aucune app n'écrit une ligne. Une frontière n'est
 * créée que pour un volet présent dans la page — pas de volet droit (`volet.actif` faux, classe
 * `wama-sans-volet`) = pas de frontière droite. Le mode simplifié masque les volets ET leurs
 * frontières (CSS) : c'est un autre usage, qui ne passe pas par ici.
 *
 * L'ÉTAT est une préférence de NAVIGATEUR (localStorage), pas de profil : replier un volet sur
 * une tablette ne doit pas le replier sur le poste de bureau. Il est appliqué AVANT le premier
 * rendu par le script en tête de `<body>` (base.html), comme `wama-simple` — sans quoi la page
 * s'afficherait volets ouverts puis se replierait sous les yeux.
 *
 * Après chaque bascule, une fois l'animation finie : un `resize` (tout ce qui mesure sa largeur
 * — cards v3, liens du studio, carte Leaflet — se recale sans rien connaître de cette brique)
 * et un événement `wama:panels` {side, collapsed} pour qui veut réagir précisément.
 *
 * API :
 *   WamaPanels.toggle('left' | 'right')
 *   WamaPanels.setCollapsed(side, bool)
 *   WamaPanels.isCollapsed(side)
 */
(function (global) {
  'use strict';

  var SIDES = {
    left:  { panel: 'filemanager-sidebar', cls: 'wama-left-collapsed',  key: 'wama_panel_left',
             what: 'l’explorateur', closeIcon: 'fa-chevron-left',  openIcon: 'fa-chevron-right' },
    right: { panel: 'wama-right-panel',    cls: 'wama-right-collapsed', key: 'wama_panel_right',
             what: 'le panneau',     closeIcon: 'fa-chevron-right', openIcon: 'fa-chevron-left' },
  };
  var ANIM_MS = 240;   // un peu plus que la transition CSS (.22 s)
  var edges = {};

  function isCollapsed(side) {
    return document.body.classList.contains(SIDES[side].cls);
  }

  function paint(side) {
    var edge = edges[side];
    if (!edge) return;
    var s = SIDES[side], collapsed = isCollapsed(side);
    var label = (collapsed ? 'Afficher ' : 'Masquer ') + s.what;
    edge.title = label;
    edge.setAttribute('aria-label', label);
    edge.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
    edge.querySelector('i').className = 'fas ' + (collapsed ? s.openIcon : s.closeIcon);
  }

  function setCollapsed(side, collapsed) {
    var s = SIDES[side];
    if (!s || !document.getElementById(s.panel)) return;
    if (isCollapsed(side) === !!collapsed) return;
    document.body.classList.toggle(s.cls, !!collapsed);
    try { localStorage.setItem(s.key, collapsed ? 'collapsed' : 'open'); } catch (e) { /* privé */ }
    paint(side);
    // Le volet droit porte l'avatar : il ne se charge que si le volet est visible.
    if (side === 'right' && global.WamaAvatarPanel) global.WamaAvatarPanel.refresh();
    setTimeout(function () {
      global.dispatchEvent(new Event('resize'));
      global.dispatchEvent(new CustomEvent('wama:panels', { detail: { side: side, collapsed: !!collapsed } }));
    }, ANIM_MS);
  }

  function toggle(side) { setCollapsed(side, !isCollapsed(side)); }

  function mountEdge(side) {
    var s = SIDES[side];
    if (edges[side] || !document.getElementById(s.panel)) return;
    var edge = document.createElement('button');
    edge.type = 'button';
    edge.className = 'wama-panel-edge';
    edge.dataset.side = side;
    edge.setAttribute('aria-controls', s.panel);
    edge.innerHTML = '<span class="wama-panel-edge-pill" aria-hidden="true"><i></i></span>';
    // La pastille suit le pointeur le long de la frontière : elle apparaît là où l'on regarde.
    edge.addEventListener('pointermove', function (e) {
      var r = edge.getBoundingClientRect();
      var y = Math.min(Math.max(e.clientY - r.top, 24), r.height - 24);
      edge.style.setProperty('--y', y + 'px');
    });
    edge.addEventListener('click', function () { toggle(side); });
    document.body.appendChild(edge);
    edges[side] = edge;
    paint(side);
  }

  function mount() {
    mountEdge('left');
    mountEdge('right');
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', mount);
  else mount();

  // Un lien qui ROUVRE un volet (`data-wama-panel-open="right"`), ex. l'indication « Réglages »
  // de la card d'entrée quand le volet droit est replié. En CAPTURE : la card se déplie au clic
  // sur son en-tête, et ce lien vit dans cet en-tête.
  document.addEventListener('click', function (e) {
    var link = e.target.closest && e.target.closest('[data-wama-panel-open]');
    if (!link) return;
    e.preventDefault();
    e.stopPropagation();
    setCollapsed(link.getAttribute('data-wama-panel-open'), false);
  }, true);

  global.WamaPanels = { toggle: toggle, setCollapsed: setCollapsed, isCollapsed: isCollapsed };
})(window);
