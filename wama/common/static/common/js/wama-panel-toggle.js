/*
 * WamaPanels — replier / rouvrir un volet latéral d'un clic sur sa FRONTIÈRE (2026-10-10).
 *
 * Global, monté par base.html sur TOUTE page : aucune app n'écrit une ligne. Une frontière n'est
 * créée que pour un volet présent dans la page — pas de volet droit (`volet.actif` faux, classe
 * `wama-sans-volet`) = pas de frontière droite.
 *
 * LES DEUX D'UN GESTE (2026-10-27, décision de Fabien) : le bouton de l'en-tête
 * (`[data-wama-panels-switch]`, une icône) replie les deux volets, puis chacun se rouvre seul par
 * sa frontière ; les deux rouverts, le bouton reprend sa forme « déployés ». Il REMPLACE le mode
 * simplifié, qui masquait les volets sans pouvoir en rouvrir un seul (retiré le même jour).
 * L'assistant passe par le même geste (`fold_side_panels`).
 *
 * L'ÉTAT est une préférence de NAVIGATEUR (localStorage), pas de profil : replier un volet sur
 * une tablette ne doit pas le replier sur le poste de bureau. Il est appliqué AVANT le premier
 * rendu par le script en tête de `<body>` (base.html) — sans quoi la page
 * s'afficherait volets ouverts puis se replierait sous les yeux.
 *
 * DEUX CONTEXTES DE LARGEUR (2026-10-12, ROADMAP §27 étape 2). Sous le point de rupture `lg` de
 * Bootstrap — tablette en portrait, fenêtre étroite —, deux volets ouverts ne laissent au centre
 * que 364 à 394 px (mesuré). Le contexte ÉTROIT (classe `wama-narrow`) : volets repliés
 * d'office, UN SEUL ouvert à la fois (en ouvrir un replie l'autre), mémoire à part
 * (`wama_panel_<côté>_narrow`). Le choix fait en grand n'est donc jamais écrasé : il revient tel
 * quel quand la fenêtre s'élargit (rotation de la tablette comprise). Le contexte, la clé et
 * l'application vivent dans `WamaPanelsContext` (base.html), qui sert aussi avant le premier
 * rendu : une seule écriture de la règle.
 * Ouvrir un volet POUSSE la zone centrale, il ne la recouvre pas : le glisser de l'explorateur
 * vers une app et le clic sur une card qui remplit l'inspecteur exigent un centre VIVANT pendant
 * que le volet est ouvert. Aussi aucun voile ni fermeture « au clic dehors ».
 *
 * Après chaque bascule, une fois l'animation finie : un `resize` (tout ce qui mesure sa largeur
 * — cards v3, liens du studio, carte Leaflet — se recale sans rien connaître de cette brique)
 * et un événement `wama:panels` {side, collapsed} pour qui veut réagir précisément.
 *
 * API :
 *   WamaPanels.toggle('left' | 'right')
 *   WamaPanels.setCollapsed(side, bool)
 *   WamaPanels.isCollapsed(side)
 *   WamaPanels.setAll(bool)         — les deux volets d'un geste (en étroit : n'en rouvre qu'un)
 *   WamaPanels.allOpen()            — « déployés » : aucun volet présent n'est replié
 *   WamaPanels.isNarrow()           — le contexte étroit est-il actif ?
 */
(function (global) {
  'use strict';

  var SIDES = {
    left:  { panel: 'filemanager-sidebar', cls: 'wama-left-collapsed',  other: 'right',
             what: 'l’explorateur', closeIcon: 'fa-chevron-left',  openIcon: 'fa-chevron-right' },
    right: { panel: 'wama-right-panel',    cls: 'wama-right-collapsed', other: 'left',
             what: 'le panneau',     closeIcon: 'fa-chevron-right', openIcon: 'fa-chevron-left' },
  };
  var ANIM_MS = 240;   // un peu plus que la transition CSS (.22 s)
  var edges = {};
  var context = global.WamaPanelsContext;   // posé par base.html, avant le premier rendu

  function isNarrow() { return !!(context && context.narrow()); }

  function isCollapsed(side) {
    return document.body.classList.contains(SIDES[side].cls);
  }

  function remember(side, collapsed) {
    if (!context) return;
    try { localStorage.setItem(context.key(side, isNarrow()), collapsed ? 'collapsed' : 'open'); }
    catch (e) { /* navigation privée : l'état vaut pour la page */ }
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

  // Une fois l'animation finie : la page se recale, et qui veut réagir est prévenu.
  function announce(sides) {
    // Le volet droit porte l'avatar : il ne se charge que si le volet est visible.
    if (sides.indexOf('right') >= 0 && global.WamaAvatarPanel) global.WamaAvatarPanel.refresh();
    setTimeout(function () {
      global.dispatchEvent(new Event('resize'));
      sides.forEach(function (side) {
        global.dispatchEvent(new CustomEvent('wama:panels', { detail: { side: side, collapsed: isCollapsed(side) } }));
      });
    }, ANIM_MS);
  }

  function setCollapsed(side, collapsed) {
    var s = SIDES[side];
    if (!s || !document.getElementById(s.panel)) return;
    if (isCollapsed(side) === !!collapsed) return;
    var changed = [side];
    document.body.classList.toggle(s.cls, !!collapsed);
    remember(side, !!collapsed);
    // Contexte étroit : un seul volet ouvert. L'autre est retenu replié même s'il est absent de
    // cette page — la page suivante, qui l'a peut-être, ne doit pas en ouvrir deux.
    if (!collapsed && isNarrow()) {
      if (!isCollapsed(s.other) && document.getElementById(SIDES[s.other].panel)) {
        document.body.classList.add(SIDES[s.other].cls);
        changed.push(s.other);
      }
      remember(s.other, true);
    }
    changed.forEach(paint);
    paintSwitch();
    announce(changed);
  }

  function toggle(side) { setCollapsed(side, !isCollapsed(side)); }

  /** Les volets PRÉSENTS dans la page : un volet absent n'a ni état ni frontière. */
  function present() {
    return ['left', 'right'].filter(function (side) { return !!document.getElementById(SIDES[side].panel); });
  }

  /** Les deux volets d'un geste. Déployer, en contexte étroit, n'en ouvre qu'un — la règle d'un
   *  seul ouvert : le volet droit, celui de l'assistant. */
  function setAll(collapsed) {
    var sides = present();
    if (collapsed) { sides.forEach(function (side) { setCollapsed(side, true); }); return; }
    if (isNarrow()) { if (sides.length) setCollapsed(sides.indexOf('right') >= 0 ? 'right' : sides[0], false); return; }
    sides.forEach(function (side) { setCollapsed(side, false); });
  }

  /** « Déployés » : aucun volet présent n'est replié — en contexte étroit, où un seul s'ouvre,
   *  l'un d'eux est ouvert. */
  function allOpen() {
    var sides = present();
    if (!sides.length) return false;
    return isNarrow() ? sides.some(function (side) { return !isCollapsed(side); })
                      : sides.every(function (side) { return !isCollapsed(side); });
  }

  /** Le bouton de l'en-tête dit l'état : volets déployés (un clic les replie) ou repliés. */
  function paintSwitch() {
    var open = allOpen(), shown = present().length > 0;
    var label = open ? 'Replier les volets' : 'Déployer les volets';
    document.querySelectorAll('[data-wama-panels-switch]').forEach(function (btn) {
      btn.hidden = !shown;
      btn.title = label;
      btn.setAttribute('aria-label', label);
      btn.setAttribute('aria-pressed', open ? 'false' : 'true');
      var icon = btn.querySelector('i');
      if (icon) icon.className = 'fas ' + (open ? 'fa-table-columns' : 'fa-expand');
    });
  }

  // La largeur change de contexte (rotation, fenêtre redimensionnée) : chaque contexte reprend
  // SA mémoire — rien n'est écrit, rien n'est écrasé.
  function onContextChange() {
    var before = { left: isCollapsed('left'), right: isCollapsed('right') };
    context.apply();
    var changed = ['left', 'right'].filter(function (side) { return isCollapsed(side) !== before[side]; });
    ['left', 'right'].forEach(paint);
    paintSwitch();
    if (changed.length) announce(changed);
  }

  function mountEdge(side) {
    var s = SIDES[side];
    if (edges[side] || !document.getElementById(s.panel)) return;
    var edge = document.createElement('button');
    edge.type = 'button';
    // La pastille apparaît au survol de la frontière : convention commune (wama-touch.css).
    edge.className = 'wama-panel-edge wama-reveal-host';
    edge.dataset.side = side;
    edge.setAttribute('aria-controls', s.panel);
    edge.innerHTML = '<span class="wama-panel-edge-pill wama-reveal" aria-hidden="true"><i></i></span>';
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
    document.querySelectorAll('[data-wama-panels-switch]').forEach(function (btn) {
      btn.addEventListener('click', function () { setAll(allOpen()); });
    });
    paintSwitch();
    if (context && global.matchMedia) {
      var mq = global.matchMedia(context.query);
      if (mq.addEventListener) mq.addEventListener('change', onContextChange);
      else if (mq.addListener) mq.addListener(onContextChange);   // Safari < 14
    }
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

  global.WamaPanels = { toggle: toggle, setCollapsed: setCollapsed, isCollapsed: isCollapsed, isNarrow: isNarrow,
                        setAll: setAll, allOpen: allOpen };
})(window);
