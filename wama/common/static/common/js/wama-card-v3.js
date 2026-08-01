/**
 * WAMA — Dimensionnement des pistes de la card v3 (CARD_DESIGN §11).
 *
 * POURQUOI : les largeurs de pistes ne peuvent pas être écrites en dur. Ce qu'une piste doit
 * contenir dépend de l'app (le reader n'affiche pas ce qu'affiche le synthesizer), du nombre
 * de boutons d'action de chaque card (un item terminé a un menu de téléchargement, pas un item
 * en attente) et de la longueur des libellés. Une constante juste pour une app est fausse pour
 * les neuf autres — c'est ce qui faisait déborder les actions malgré plusieurs ajustements.
 *
 * CE QUE ÇA FAIT : mesurer le contenu réel de la file, puis poser les largeurs en variables CSS
 * sur le conteneur. Les pistes deviennent identiques pour TOUTES les cards d'une même file
 * (c'est l'alignement, raison d'être de la v3) tout en étant PROPRES à chaque app.
 *
 * Pourquoi pas `subgrid`, qui ferait ça nativement : il exige que chaque card soit enfant
 * DIRECT de la grille. Les filles de lot vivent dans un `.collapse` intercalé — la hiérarchie
 * de la file n'est pas plate, subgrid ne s'y applique pas.
 *
 * Sections MESURÉES (piste au plus juste) : ÉTAT et ACTIONS, dont le contenu a une largeur
 * naturelle nette et non compressible. Les trois autres (Entrée, Réglages, Sortie) restent
 * élastiques et se partagent la place restante : leur contenu est du texte, qui tronque.
 */
(function () {
  'use strict';

  var SEL_QUEUE = '.wama-queue-list, .wama-queue-grid';
  var MIN_ELASTIC = 132;   // en deçà, une piste de texte n'affiche plus rien d'utile
  var SAFETY = 10;         // jeu absorbant l'élargissement des boutons au chargement des icônes

  /** Largeur réellement occupée par les boutons d'une rangée d'actions, wrap ignoré. */
  function actionsWidth(box) {
    var kids = box.querySelectorAll(':scope > .btn, :scope > .btn-group');
    if (!kids.length) return 0;
    var gap = parseFloat(getComputedStyle(box).columnGap) || 0;
    var w = 0;
    for (var i = 0; i < kids.length; i++) w += kids[i].getBoundingClientRect().width;
    return w + gap * (kids.length - 1);
  }

  /**
   * Largeur du contenu d'une section si rien ne le contraignait.
   *
   * ⚠ La mesure DOIT être idempotente : elle sert à calculer une largeur qu'on applique
   * ensuite à la piste. Toute mesure qui dépend de la largeur ACTUELLE crée une boucle de
   * rétroaction — mesurer, élargir, remesurer plus grand, élargir encore… La première version
   * lisait `scrollWidth` des enfants : pour un bloc, il vaut la largeur déjà contrainte, donc
   * chaque passage reposait « piste + marge » et la colonne avançait de 10 px par
   * rafraîchissement (mesuré : 126 → 176 px en six passages, sans qu'aucun contenu ne change).
   *
   * On mesure donc sur un CLONE détaché en `width: max-content`, dont la largeur ne doit rien
   * à la piste courante. Même contenu → même résultat, indéfiniment.
   */
  function naturalWidth(sec) {
    var clone = sec.cloneNode(true);
    clone.style.cssText = 'position:absolute;left:-9999px;top:0;visibility:hidden;' +
                          'width:max-content;max-width:none;border-left:0;padding-left:0';
    document.body.appendChild(clone);
    var w = clone.getBoundingClientRect().width;
    document.body.removeChild(clone);
    return w;
  }

  /**
   * Pose une piste — sans réécrire une valeur identique.
   *
   * Deuxième garde-fou contre la dérive : écrire dans `style` déclenche l'observateur de
   * mutations, donc une nouvelle mesure. Si l'écriture n'apporte rien, on ne l'émet pas, et
   * la boucle s'arrête d'elle-même au lieu de tourner à chaque frame. Le seuil de 1 px absorbe
   * les arrondis sub-pixels (un écart de 0,4 px ne doit pas relancer le cycle).
   */
  function setTrack(queue, name, px) {
    var prev = parseFloat(queue.style.getPropertyValue(name));
    if (!isNaN(prev) && Math.abs(prev - px) < 1) return;
    queue.style.setProperty(name, px + 'px');
  }

  function measure(queue) {
    var cards = queue.querySelectorAll('.wcv3');
    if (!cards.length) return;

    var maxState = 0, maxActions = 0, hidden = 0;
    for (var i = 0; i < cards.length; i++) {
      // Une card dans un lot REPLIÉ mesure 0 : la compter fausserait tout dans un sens comme
      // dans l'autre. On l'ignore, et on remesure au dépli (voir l'écoute de collapse).
      if (!cards[i].getBoundingClientRect().width) { hidden++; continue; }
      var st = cards[i].querySelector('.wcv3-sec--state');
      var ac = cards[i].querySelector('.wcv3-actions');
      if (st) maxState = Math.max(maxState, naturalWidth(st));
      if (ac) maxActions = Math.max(maxActions, actionsWidth(ac));
    }
    if (!maxActions) return;

    // Le padding du séparateur est INCLUS dans la piste (box-sizing: border-box) : une piste
    // chiffrée sur le seul contenu est trop étroite de ~10 px, et les boutons repassent à la
    // ligne. On l'ajoute explicitement plutôt que de le compenser par une marge magique.
    var probe = queue.querySelector('.wcv3-sec--actions');
    var extra = 0;
    if (probe) {
      var cs = getComputedStyle(probe);
      extra = (parseFloat(cs.paddingLeft) || 0) + (parseFloat(cs.borderLeftWidth) || 0);
    }

    // Si la file est étroite, les pistes mesurées mangeraient toute la place : on laisse alors
    // le CSS reprendre la main (les paliers @container empilent les sections).
    var avail = queue.getBoundingClientRect().width;
    var fixed = maxState + maxActions + 2 * extra;
    if (avail && fixed > avail - 3 * MIN_ELASTIC) {
      queue.style.removeProperty('--wcv3-c-state');
      queue.style.removeProperty('--wcv3-c-actions');
      return;
    }

    // Marge de sécurité : les icônes FontAwesome arrivent APRÈS le premier rendu et élargissent
    // les boutons. Une piste calibrée au pixel près sur la mesure d'avant-polices laissait donc
    // la corbeille passer à la ligne pendant ~1 s au chargement, avant que `fonts.ready` ne
    // corrige. Mieux vaut 10 px de jeu qu'un affichage juste-puis-faux-puis-juste.
    setTrack(queue, '--wcv3-c-state', Math.ceil(maxState + extra + SAFETY));
    setTrack(queue, '--wcv3-c-actions', Math.ceil(maxActions + extra + SAFETY));
  }

  var pending = null;
  function schedule() {
    if (pending) return;
    pending = requestAnimationFrame(function () {
      pending = null;
      document.querySelectorAll(SEL_QUEUE).forEach(measure);
    });
  }

  function init() {
    var queues = document.querySelectorAll(SEL_QUEUE);
    if (!queues.length) return;
    schedule();

    // Les cards sont remplacées entières par upsertCard (rendu serveur) : on remesure quand
    // la file change, sinon une card terminée (qui gagne un menu de téléchargement) déborde.
    // On observe aussi les ATTRIBUTS : le collapse d'un lot ne touche pas childList, il change
    // `class` et `style.height` — sans ça la mesure rate l'ouverture du lot.
    // ⚠ measure() écrit lui-même dans queue.style : réagir aux mutations DU CONTENEUR créerait
    // une boucle (mesure → setProperty → mutation → mesure…) à chaque frame. On ignore donc les
    // mutations dont la cible EST le conteneur.
    var obs = new MutationObserver(function (records) {
      for (var i = 0; i < records.length; i++) {
        var t = records[i].target;
        if (!(t.matches && t.matches(SEL_QUEUE))) { schedule(); return; }
      }
    });
    queues.forEach(function (q) {
      obs.observe(q, { childList: true, subtree: true,
                       attributes: true, attributeFilter: ['class', 'style'] });
    });

    // Dépli d'un lot : ses cards passent de 0 à leur vraie largeur, et ce sont souvent les plus
    // larges (une card terminée porte un menu de téléchargement que les autres n'ont pas). Sans
    // cette écoute, les pistes restaient calibrées sur les seules cards visibles au chargement
    // et les actions débordaient dès l'ouverture du lot. Le collapse Bootstrap ne touche pas
    // childList : le MutationObserver ci-dessus ne suffit PAS.
    document.addEventListener('shown.bs.collapse', schedule);
    document.addEventListener('hidden.bs.collapse', schedule);

    window.addEventListener('resize', schedule);
    // Les polices d'icônes arrivent après le premier rendu et changent la largeur des boutons.
    if (document.fonts && document.fonts.ready) document.fonts.ready.then(schedule);
    // Filet : au tout premier rendu, un lot ouvert par défaut peut n'avoir pas encore sa
    // hauteur (init Bootstrap), et ses cards mesurent 0. Une passe différée les rattrape.
    setTimeout(schedule, 400);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  window.WamaCardV3 = { measure: schedule };
})();
