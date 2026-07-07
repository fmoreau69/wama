# CARD_DESIGN.md — Formalisme harmonisé des cards WAMA

> **Décision (Fabien, 2026-06).** Figer le formalisme de card **maintenant** (avant la généralisation
> des files), pour éviter des refontes. Priorité : **fonctionnel d'abord, esthétique ensuite** — mais le
> squelette + le code couleur sont arrêtés ici.
>
> **Carte de référence : `wama/converter/templates/converter/_job_card.html`** — la plus aboutie
> (partial Django server-rendered, compacte, sections claires, couleurs distinctes). Toutes les apps
> convergent vers ce formalisme.

## 1. Anatomie d'une card (de haut en bas = ordre chronologique du flux)

```
┌─────────────────────────────────────────────────────────────────────────┐
│ [icône type] Nom du média (clic → aperçu entrée)  [badge cible]           │  ← en-tête (1 ligne)
│                              [ETA] [badge statut]   ⚙ ▶ ⬇ ⧉ 🗑           │  ← + actions (ms-auto)
│ ▓▓▓▓▓▓▓▓▓▓▓▓▓░░░░░░░  67 %  · 0:42 / ~1:10                                 │  ← barre PLEINE LARGEUR
│ [aperçu du résultat : miniature / onde / texte tronqué — clic = développer]│  ← aperçu (si terminé)
└─────────────────────────────────────────────────────────────────────────┘
```

1. **En-tête** (compacte, une ligne `d-flex flex-wrap`) :
   - icône type média + **nom** (cliquable → aperçu de l'entrée, via `preview-media-link` commun) + badge cible/format
   - **ETA** (`wama-eta`, `data-eta-card`) + **badge statut** (En attente / En cours / Terminé / Échec)
   - **boutons d'action** (`ms-auto`) — ordre + couleurs canoniques (§2)
2. **Barre de progression PLEINE LARGEUR** (`wama-progress-track` + `wama-progress-fill`) quand
   `RUNNING`/`PENDING` : **% + ETA + durée écoulée**. État `ERROR` → message rouge ; `DONE` → nom de
   sortie (vert) ou aperçu.
3. **Aperçu du résultat** (sous la barre, si terminé) : miniature/onde/texte tronqué, clic → développer.
4. **Réglages : PAS dans la card** (la garder compacte). Le bouton ⚙ **ouvre l'inspecteur volet droit**
   (réglages item / batch / général — cf. `WAMA_APP_CONVENTIONS §22`). Un résumé lecture-seule des
   réglages-clés peut éventuellement s'afficher, mais le détail vit dans l'inspecteur.

### 1bis. Cycle de vie état/progression — NON AMBIGU (la barre se transforme, ne disparaît pas)

Problème observé (converter) : la barre n'apparaît qu'en `RUNNING`/`PENDING` → à « Terminé » elle
**disparaît**, et « barre vide (en attente) » vs « barre absente (terminé) » se confond au coup d'œil.

**Règle** : l'état est lisible **à la fois par le badge ET par la barre** (redondance volontaire) :
| État | Badge | Barre / ligne |
|------|-------|---------------|
| En attente (`PENDING`) | gris « En attente » | barre 0 % atténuée (ou absente + badge) |
| En cours (`RUNNING`) | jaune « En cours » | barre qui se remplit + **% + ETA** |
| **Terminé** (`DONE`) | vert « Terminé » | **barre PLEINE verte persistante** ou ligne « ✓ Terminé · durée · taille » — **jamais absente** |
| Échec (`ERROR`) | rouge « Échec » | barre/ligne rouge + message |

### 1ter. Card à DEUX ÉTATS (concis ↔ étendu) — universel, mêmes règles partout

**État CONCIS (défaut)** — card légère, scannable :
- en-tête 1 ligne (identité + mini-aperçu entrée + badge statut + ETA + actions) ;
- barre de progression pleine largeur (§1bis) ;
- **aperçu de sortie SYSTÉMATIQUE** : 1 ligne (miniature/onde/extrait) + **infos sortie en-dessous**
  (durée/taille/dimensions… selon l'app) — compact, n'épaissit pas trop (style Transcriber).

**État ÉTENDU (au clic / Entrée)** — la card grandit et révèle les **sections chronologiques communes** :
`Entrée (props complètes)` → `Réglages/options (résumé)` → `Sortie (props + aperçu agrandi)` →
`État/process (avancement, durée, logs courts)` → Actions. **Mêmes sections pour toutes les apps** ;
chaque app remplit ce que son média contient → **cartographier par app pour ne rien perdre**.

### 1quater. Interaction — marche AVEC ou SANS le volet droit

Un **clic** sur une card = 3 effets cohérents : (a) **étend** la card (concis→étendu), (b) la
**sélectionne** (highlight), (c) si le **volet droit** est présent → met à jour l'**inspecteur**
(réglages éditables, §22).
- **Mode avancé** (volet ouvert) : card étendue (lire les infos) + inspecteur (éditer les réglages).
- **Mode simplifié** (volet masqué) : la card étendue porte tout.

**Navigation clavier** : `↑↓←→` déplacent la sélection (pile ET mosaïque), `Entrée/Espace` étend/replie,
`Échap` replie. → exploration rapide du contenu sans souris (réutilise la garde clavier
input/textarea/select déjà posée pour l'éditeur transcriber).

## 2. Boutons d'action — ordre + code couleur (schéma CONVERTER, adopté)

Ordre canonique (conventions UI) · style **sobre** : `btn btn-outline-X btn-sm py-0 px-2`, **icône seule + `title`**.

| Action | Couleur | Icône | Notes |
|--------|---------|-------|-------|
| **Paramètres** | `secondary` (gris) | `fa-cog` | ouvre l'inspecteur volet droit |
| **Lancer / Relancer** | `success` (vert) | `fa-play` ▶ / **`fa-redo` ↻** | état : ▶ Démarrer · ⏳`fa-spinner` En cours (disabled) · ↻ Relancer (si terminé) |
| **Télécharger** | `info` (bleu) | `fa-download` | `<a>` si sortie dispo, sinon `<button disabled>` ; split ▾ formats si pertinent |
| **Dupliquer** | `warning` (jaune) | `fa-copy` | **jaune** → distinct du Télécharger (bleu) et du Paramètres (gris), zéro collision |
| **Supprimer** | `danger` (rouge) | `fa-trash` | |

> **Pourquoi le converter gagne le débat « couleur dupliquer »** : chaque action a **sa** couleur → reconnaissable
> d'un coup d'œil, sans deux boutons de même teinte côte à côte (≠ reader gris+gris, ≠ enhancer bleu+bleu).

## 3. Rendu : server-side (partial) + update en place — PAS de rebuild JS

- **Source de vérité = un partial Django** (`_card.html`, paramétré) — comme le converter et le transcriber.
- Le JS **met à jour les valeurs en place** (largeur de la barre, badge statut, ETA) — il ne **reconstruit
  pas** toute la card à chaque poll. (Le rebuild JS = anti-pattern enhancer, source de bugs : handlers
  multiples, double-fire.)
- **Délégation par `data-action`** (un seul handler `[data-action]` par file) plutôt que N handlers par
  classe → supprime la classe de bugs « double-fire ».

## 3ter. Apparence des batchs : card EMPILÉE (style Solitaire) + désempilage au clic

- **Batch unitaire (1 élément)** = card simple. **Batch multi-éléments** = **pile de cards** (effet
  Solitaire) → signal visuel immédiat du batch ; **état + boutons d'action sur la card du dessus**.
  Uniformise « batch-1 » et « batch-N » (toutes deux des cards, l'une simple, l'autre empilée).
- **Interaction (Solution 1, retenue)** : clic sur la pile → **désempilage animé** des items.
  **Une seule pile ouverte à la fois** (cliquer une autre referme la précédente ; à l'arrivée sur la
  file, **toutes repliées** → lisible). Items désempilés = **concis** → clic item = **étendu** (§1ter).
  L'inspecteur suit par **contexte** (clic batch / item / file — cf. §22). Beaucoup d'items → **chevauchement
  partiel** (concis) + clic = étendu.
- *Écartée* — Solution 2 (contenu du batch uniquement dans modale/inspecteur, sans désempilage) : moins
  moderne, accès indirect au contenu/preview, diverge du modèle concis↔étendu.
- **Héritage des réglages batch→item** : règle « override + héritage » (conventions **§9.9**) — un item
  hérite des réglages du batch SAUF ceux modifiés au niveau item (y compris fichier de référence).
  Implémenté dans le Transcriber (`views.py:1767`) — **À CENTRALISER dans `common/`** (aujourd'hui per-app).

## 3bis. Manipulation directe de la file : réorganiser, batcher, filtrer/trier

> Expression la plus **intuitive du modèle batch unifié** (batch-of-1 ↔ batch-of-N) : glisser une card
> sur une autre → forme un batch ; la sortir → redevient autonome. Briques **déjà existantes** → surtout
> de l'UI + des endpoints fins.

- **Réordonner** (drag) : **SortableJS** ; persiste `row_index` (champ déjà présent sur les items de batch).
- **Glisser DANS un batch** = `consolidate_into_batch` ; **glisser HORS** = `_unwrap` (ops existantes).
  Endpoints fins : `reorder`, `move_to_batch`, `remove_from_batch`.
- **Filtrer / trier** : barre d'outils de file (statut / date / nom / type / durée), préférence persistée.
- **Pourquoi c'est IMPORTANT (pas optionnel)** : laisse l'utilisateur **corriger une erreur d'import**
  sans repartir de zéro (sortir une card d'un batch, la déplacer) et **isoler un élément** pour le
  traiter séparément. Phasable si trop complexe, mais à garder en ligne de mire dès le départ.
  - *Cas d'usage clé — duplication* : on **duplique** une card dans un batch → on peut la **relancer
    telle quelle dans le batch**, OU la **sortir du batch** pour l'isoler/la repérer sans tout
    réimporter. Le déplacement in/out est la réponse directe à ce besoin.
- **Vigilance** :
  - *Items en cours* : l'appartenance batch est **organisationnelle** (groupement pour démarrer/télécharger
    en lot) → déplacer un item `RUNNING` n'affecte pas sa tâche ; encadrer (pas de réordre destructif).
  - *Clavier / tactile* : le drag est souris-centré → **menu contextuel** + commandes clavier
    (« déplacer vers batch X ») en lien avec la nav clavier (§1quater).
  - *Persistance / concurrence* : ordre + appartenance en DB, **UI optimiste**, ne pas écraser un drag en
    cours quand le polling re-render.
- **Brique commune** (pas par app) : init SortableJS + endpoints + barre filtre/tri dans `common/`.

## 4. Disposition : mode d'affichage pile ↔ mosaïque (toggle, comme les apps média)

- **`UserProfile.card_layout`** = `stack` (1 card fine **par ligne**, **défaut**) | `mosaic` (grille de
  cards plus hautes, plusieurs par ligne).
- **Géométrie, pas densité** : c'est l'**agencement** des cards sur la page qui change ; l'agencement
  INTERNE de la card se **reformate** (en `mosaic`, les éléments de l'en-tête + l'aperçu s'empilent dans
  la tuile ; en `stack`, ils s'étalent sur la ligne). **Même card, deux géométries** (responsive/reflow).
- Toggle dans la barre de file (boutons « liste / mosaïque ») + réglage par défaut sur la page profil
  (comme `ui_mode`/`preferred_language`).
- Orthogonal aux 2 états §1ter (concis/étendu) : on peut étendre une card en pile comme en mosaïque.

## 5. Cartographie des cards existantes (conformité au formalisme)

| App | Rendu | Boutons (couleurs) | Barre pleine largeur | Aperçu | Conformité |
|-----|-------|--------------------|----------------------|--------|------------|
| **converter** (RÉF) | partial server | ✅ schéma complet | ✅ `wama-progress-track` | sortie (texte) | **~95 %** |
| transcriber | partial server (`_card_*`) | ~ (à aligner couleurs) | ✅ | onde/texte | ~80 % |
| reader | JS buildCard | sobre outline (dupliquer gris) | ~ | texte OCR | ~70 % (couleur dupliquer + rebuild JS) |
| enhancer | **JS buildCard (rebuild)** | mélange (dupliquer bleu) | partiel | miniature | ~50 % (rebuild JS, couleurs) |
| synthesizer / describer / imager / anonymizer / composer / avatarizer | à cartographier | à vérifier | à vérifier | à vérifier | ⏳ |

> **À compléter** : cartographier finement les 6 dernières (quelles infos chaque card montre) avant de
> migrer, pour **ne rien perdre** (durée, taille, dimensions, locuteurs, etc. selon l'app).

## 6. Plan d'adoption
1. **Extraire la brique commune** `_card.html` (+ helper update-en-place) **du converter** (référence).
2. Aligner les **couleurs de boutons** sur le schéma §2 partout (changement à faible risque, visuel).
3. Migrer les apps **JS-rebuild → server-partial + update-en-place** (enhancer en premier : tue le
   bug-class). 
4. Brancher le ⚙ sur l'**inspecteur volet droit** (cf. §22).
5. **Stack/mosaïque** : champ `UserProfile.card_layout` + CSS, quand le formalisme est stabilisé.

## 7. Langue de design : thème « jeu de cartes » 🃏 (ludique, cohérent)

Fil rouge esthétique assumé : dans WAMA, **l'utilisateur « joue des cartes »**. Le batch empilé (style
Solitaire §3ter), le **dé** comme symbole de lancement (déjà utilisé dans l'anonymizer), et de petits
**clins d'œil ludiques** disséminés — **purement esthétiques**, jamais au détriment de la lisibilité ni
de la fonction. Donne une identité fraîche et cohérente à l'UI.

Lié : `WAMA_APP_CONVENTIONS.md` (§boutons, §22 inspecteur), `GENERALIZATION_PLAN.md` (axe B), `COMMON_REFACTORING.md`, `MODES_QUEUE_UX.md`.

---

## 8. Chantier file Solitaire — focus, card mère, animation (décidé 2026-06-29)

> Affinage de §3ter (pile Solitaire) + §3 (2 états). Objectif : naviguer/ajouter sans jamais
> « chercher » une card, et rendre la card mère du batch **homogène** avec les filles.

### 8.1 Focus à l'ajout et à la navigation — `WamaQueue.focusCard()`
- **Un seul mécanisme** de mise au point, partagé par l'ajout ET la nav clavier ↑↓←→ :
  `focusCard(id, { scroll:'center', select:true, pulse:true })` →
  `scrollIntoView({ block:'center', behavior:'smooth' })` + halo **pulse** bref + **sélection**
  (remplit l'inspecteur). Vaut pour une card unique **ou** la card mère d'un batch.
- **Ne PAS ouvrir de modale bloquante à l'ajout** (intrusif, et un batch de N n'ouvre pas N modales).
  La config se fait dans l'**inspecteur non bloquant** (surface universelle) ; la modale reste sur
  clic explicite. (Option `UserProfile` si un utilisateur préfère la modale.)
- **Tri par défaut = CHRONOLOGIQUE.** PAS « batchs d'abord » : ce tri existait **dans le reader**
  (app-spécifique) et n'a plus lieu d'être maintenant que la card mère est **homogène** (cf. 8.2) ; il
  devient une simple **option** de la barre de tri (§3bis), jamais le défaut.
- **Bug « card en bas de pile » = app-spécifique** (PAS dans le commun, confirmé 2026-06-29). Remède :
  **centraliser une insertion déterministe chronologique** dans la logique commune (en tête de file,
  sous la card « Nouveau ») → les apps qui l'adoptent perdent le bug. Le scroll-center reste un filet,
  pas le remède.
- **Bug header collant** : `scroll-margin-top` = hauteur du header sur les cards + `block:'nearest'`
  en nav → la card du haut n'est plus masquée.

### 8.2 Card mère = squelette des filles (brique commune `_batch_card.html`)
- La mère réutilise le **même squelette** que la card unitaire (briques `_card_progress.html` +
  `_card_state.html`) → **même forme** ligne/mosaïque automatiquement. Elle ne diffère que par :
  un **modificateur CSS `.is-batch`** (couleur), les **méta-infos du batch** et ses **actions propres**.
- **Tue la duplication** : le rendu de la card mère est aujourd'hui copié dans chaque template d'app
  → extraction unique dans `common/templates/common/_batch_card.html`.

### 8.3 Dépliage Solitaire « éventail » + animation (phasé)
- **P1** : mère `.is-batch` + dépliage propre (réutilise le collapse Solitaire existant de
  `wama-queue.js`, une pile ouverte à la fois). Faible risque, gain immédiat.
- **P2** : effet éventail — overlap `translateY` proportionnel à la **distance à la card sélectionnée**
  (la sélectionnée la moins chevauchée), animation **étagée** (stagger).
- **P3** : polish. **Durée de dépliage portée à ~0,35–0,45 s** avec easing (le collapse Bootstrap par
  défaut est trop rapide → on ne voit pas l'animation) + stagger des filles = sensation « Solitaire ».

### 8.5 PAS de card/zone de config-attente intermédiaire (« staging ») — décidé Q2, 2026-06-29
> Décision validée puis perdue une fois (cf. [[feedback-consignment-exhaustive]]) → consignée ici en entier.

- **Décision** : supprimer la card/zone de **config-attente intermédiaire** (le « staging » : un item ajouté
  attend dans une zone « à valider » avant d'être committé à la file).
- **Pourquoi** : doublon avec l'**inspecteur universel** (volet droit) + modale ; alourdit l'UI (la zone
  « à valider » s'empile sous la card d'entrée) sans valeur réelle. La valeur de guidage est déjà portée
  par l'inspecteur **métadonnée-driven** (WamaDetails) + des défauts sensés.
- **Comportement cible** : un fichier déposé/ajouté (ou un lot) devient **directement une/des card(s) de
  file en état BROUILLON (gris)** — pas de zone « à valider », pas d'étape « committer ».
- **Config** : via inspecteur (volet droit) / modale, comme toute card (par item ou par batch).
- **Lancement** : bouton **Lancer** de la card / **Démarrer tout** de la file. La fonction du staging
  « configurer N puis lancer tout » est **reprise sans perte** par batch-settings + start-all + inspecteur.
- **Feux tricolores** : gris=brouillon (configurable, bouton Lancer) · orange=en cours · vert=fini ·
  rouge=échec. **Pas d'état « config/staging » distinct.**
- **À l'ajout** : `focusCard` (scroll-center + pulse + sélection inspecteur), **PAS de modale bloquante**.
- **Supersede** : la note antérieure « card nouveau → devient orange pour config » (plus besoin).
- **Concrètement (Transcriber, ⏳)** : retirer le sous-système **staging** — vues `stage_commit`/
  `stage_commit_all`/`stage_clear`/`stage_update_all` + URLs, `#stagingZone` + JS `stagePost`/`stageCommit`…,
  le flag `staged` (l'upload crée directement un **brouillon en file**). Vérifier que start-all / batch-settings
  / inspecteur couvrent l'usage « configurer N puis lancer ».

### 8.6 Card d'import homogène (DIFFÉRÉ — passe visuelle / globalisation, décidé 2026-06-29)
> Choix esthétique qui s'appliquera PARTOUT → à décider/implémenter **une seule fois** dans la brique
> commune `_new_item_card`, **après** la globalisation. Visuel → nécessite l'œil de Fabien + itération.

- **Problème** : la card d'import est aujourd'hui *différente* des autres cards ET *incorporée* dans la
  file → incohérent. À résoudre.
- **Décision (orientation)** : la rendre **card-like et la garder 1ʳᵉ card de la file** (pas au-dessus —
  remonter = surface séparée, contre `MODES_QUEUE_UX` « une seule surface = la file »).
- **Mécanique = accordéon (déjà prototypé Synthesizer)** : **replié** = card compacte « ＋ Nouvel
  élément » + modalité primaire, suit ligne/mosaïque (homogène) ; **déplié à la demande** (bouton
  d'élargissement) = toutes les modalités d'import (drop/URL/batch/Speak/texte) **avec de la place**.
- **Critique clé** : NE PAS miniaturiser les vrais champs de saisie (forme-sur-fonction, nuit à
  l'usage) → la clarté vit dans l'état **déplié** (divulgation progressive), pas dans le replié.
- **Détail lié** : si la card d'import est toujours 1ʳᵉ card, retirer la **répétition « File d'attente »**
  de l'en-tête (garder « File d'attente + nb » sur l'onglet). Polish.

### 8.4 Lien Axe 3 (hors card, noté ici pour cohérence)
Prospection LLM → router un modèle vers une app existante (capacités vs `APP_CATALOG`) ou faire
**émerger** une app depuis un manifeste. Détail dans `PROJECT_STATUS.md §2`/`§18` et
`GENERALIZATION_PLAN.md` (horizon manifeste). **Phase B gatée** sur la maturité du runtime manifeste.

## 9. Couleurs par CATÉGORIE + homogénéisation des tuiles (consigné 2026-07-05 — §9.1 + surfaces 1 et 3 IMPLÉMENTÉS le jour même ; filemanager (§9.2-2) et tuiles (§9.3) différés)

> Proposition Fabien : code couleur par catégorie d'apps (APP_CATEGORIES) avec **dégradé/variation
> par app** dans la catégorie, appliqué aux icônes (menu, dossiers du filemanager, cards…).
> Décision : **on consigne d'abord, on discute avant d'implémenter**.

### 9.1 Cadre proposé (position Claude)
- **Identité ≠ état.** Le tricolore des cards (gris nouveau · orange en cours · vert fini · rouge
  échec) et les couleurs FONCTIONNELLES des boutons (▶ vert · ⧉ jaune · 🗑 rouge, §2) sont des codes
  d'ÉTAT/ACTION : la couleur d'identité (app/catégorie) ne doit JAMAIS entrer en concurrence avec
  eux. Zones sûres pour l'identité : icônes, liserés discrets (border-left de card), en-têtes de
  section, dossiers du filemanager. Zones interdites : barres de progression, badges de statut,
  boutons d'action.
- **Déclaratif et dérivé, pas 10 hex à la main** : déclarer UNE teinte de base par catégorie dans
  `APP_CATEGORIES` (`hue`), et DÉRIVER la couleur de chaque app par variation automatique
  (HSL : lightness/saturation étagées selon l'index dans la catégorie). `APP_CATALOG.color`
  devient alors un override optionnel. Zéro hardcode, évolutif (une 11ᵉ app hérite sa nuance).
- **Accessibilité/thème sombre** : variations sur la LUMINOSITÉ plutôt que la teinte pour rester
  distinguables (daltonisme) ; contraste ≥ 3:1 sur #212529 (feedback_text_contrast).
- Teintes candidates : Comprendre=cyan/bleu (analyse), Créer=violet/magenta (génération),
  Transformer=vert/teal (traitement), Données=ambre, Lab=orange, Transversal=gris-bleu.

### 9.2 Surfaces d'application (ordre suggéré si validé)
1. ✅ Icônes du menu Applications + page d'accueil + /apps/ — via la dérivation au chargement du registre (`_assign_derived_colors`), tous les consommateurs de `spec.color` héritent sans changement.
2. Dossiers d'apps du filemanager (tri par catégorie + icône teintée — PAS de changement disque,
   décision 2026-07-05 : l'arborescence physique est un contrat, la catégorie est de la présentation).
3. ✅ Liseré gauche des cards de travail — `--wama-app-color` posée par base.html (app courante via le catalogue), règle `.wama-card` dans wama-inspector.css.

### 9.3 Homogénéisation des « tuiles » (cards accueil / app manager / model manager / cards de travail)
Consigné : unifier l'apparence de TOUTES les surfaces en carte (fond, bordure, radius, hover,
densité) via des **tokens CSS communs** (`.wama-tile` ou variables `--wama-card-*` dans un CSS
global) — chaque surface les adopte sans se faire imposer sa structure interne. À traiter dans la
continuité de la brique card commune (le formalisme de CE document) ; **différé** tant que le
schéma-driven des apps n'est pas fini (priorité Fabien : fonctionnel d'abord, passe UI ensuite).

---

## 10. Card UNIVERSELLE v2 « synthétique » — chips + barre pleine largeur (proposé 2026-07-06, pilote = READER)

> Demande Fabien : les cards des apps non portées (reader, converter, anonymizer) ont un style
> plus ÉPURÉ (tags/chips, barre individuelle pleine largeur) qui sera PERDU à l'uniformisation si
> on ne le consigne pas ; proposer LA meilleure version en s'inspirant aussi des meilleures UI/UX
> équivalentes ; **tester dans Reader avant de porter dans la brique commune** ; garantir
> l'universalité (inspecter les capacités de toutes les apps). Non prioritaire sur le portage —
> on avance les deux ensemble (Reader = pilote port + design).

### 10.1 CONSIGNATION — les « petites différences » à CONSERVER (relevé du 2026-07-06)

| Différence | Où | Pourquoi la garder |
|---|---|---|
| **Chips/tags méta inline** (`.job-chip` : statut, moteur, mode, « X pages », préréglage) | converter `_job_card.html`, reader `_item_card.html` | 5 infos scannables en 1 ligne là où la grille T/D/C consomme 2 colonnes de petites lignes ; la couleur/bordure du chip porte du sens |
| **Chip « format cible → .mp3 »** | converter | déclare la SORTIE ATTENDUE avant traitement — info-forte qui manque aux cards portées (le « vers quoi » du flux entrée→sortie) |
| **Barre de progression PLEINE LARGEUR sous la ligne d'en-tête** | converter, reader | déjà la DOCTRINE (§1 !) — jamais appliquée aux ports T/D/C qui l'ont confinée dans une colonne `col-md-2` ; pleine largeur = lisibilité + geste visuel du flux |
| **Ligne unique flex** (icône + nom + chips + état + actions), PAS de grille `col-md-*` | converter, reader | densité : ~48 px de haut en concis vs ~90 px pour la grille ; c'est la géométrie « pile » du §4 |
| **Erreur inline compacte** (1 ligne rouge repliée sous la card) | reader | vs alert pleine boîte ; cohérent avec « la barre se transforme » |
| **Miniature du média en tête de ligne** (vignette cliquable) | anonymizer (JS legacy), converter (icône type) | pour les apps à sortie visuelle (imager/enhancer/anonymizer/avatarizer), la vignette EST l'aperçu concis |

### 10.2 Inspirations externes retenues (apps équivalentes, patterns éprouvés)

- **Vercel/Netlify (deployments)** : ligne unique, POINT de statut coloré + libellé court, durée
  relative (« il y a 2 min »), actions révélées au survol → notre tricolore existe déjà, on adopte
  le point coloré compact en concis (le badge plein reste en étendu).
- **GitHub Actions (runs)** : icône de statut animée pendant RUN, titre + chips contexte, durée à
  droite, ligne EXTENSIBLE → conforte nos 2 états concis/étendu (§1) et la nav clavier.
- **Linear (issues)** : chips à icône, densité, sélection = bordure discrète (pas de fond criard)
  → guide le style des chips et de l'état sélectionné (sync inspecteur).
- **Transmission/downloads managers** : barre pleine largeur fine SOUS le titre, % + débit + ETA
  dans la même ligne fine → notre WamaEta s'y insère tel quel.

### 10.3 SPEC card v2 (état CONCIS) — universelle, métadonnée-driven

```
┌───────────────────────────────────────────────────────────────────────────┐
│ [vignette|icône] Nom-ou-extrait-prompt      ⌄chips⌄        ● état  ⚙▶⬇⧉🗑 │  ligne 1 (flex, ~44px)
│    #id · il y a 12 min   [moteur][langue][option…][→ format]  ~2 min      │  chips + ETA (même ligne si place)
│ ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓░░░░░░░░░░░░░░░░ 62 %                                     │  ligne 2 : barre PLEINE LARGEUR (se transforme, jamais absente)
│ « Aperçu de la sortie sur une ligne… »                        [♪ player]  │  ligne 3 : aperçu sortie SYSTÉMATIQUE (polymorphe)
└───────────────────────────────────────────────────────────────────────────┘
```

1. **Ligne 1 — identité + chips + état + actions** (flex, une seule ligne, wrap toléré en étroit) :
   - *Identité* : vignette (sortie/entrée visuelle) OU icône type média OU 💬 extrait de prompt
     (apps à entrée texte : composer/imager/synthesizer) ; sous-ligne `#id · date relative`.
   - *Chips méta* : **GÉNÉRÉS depuis params.py/PARAMS_JSON + capabilities — jamais écrits à la
     main par app** (règle metadata-driven). Un champ marqué `chip=True` dans le schéma produit
     son chip (valeur courte, icône du schéma). Chip spécial « → {format cible} » si
     export_binding='early'. Max ~4 chips en concis + chip « +N » qui déplie.
   - *État* : POINT coloré (tricolore §8/9 : gris/orange pulsé/vert/rouge) + libellé court ;
     ETA `wama-eta` à côté pendant RUN ; durée totale une fois fini.
   - *Actions* : ordre conventionnel ⚙ ▶(cycle) ⬇ ⧉ 🗑 inchangé (§2), compactes.
2. **Ligne 2 — barre PLEINE LARGEUR** (`wama-progress-track/fill` existants) : enfin conforme à la
   doctrine §1. Se TRANSFORME : pleine verte persistante en SUCCESS, rouge en FAILURE.
3. **Ligne 3 — aperçu sortie systématique, POLYMORPHE selon output_types** (universalité) :
   - texte (transcriber/describer/reader) : 1 ligne tronquée, clic = étendu ;
   - audio (composer/synthesizer) : mini-player waveform (brique existante) ;
   - image/vidéo (imager/enhancer/anonymizer/avatarizer/converter) : vignette (déjà en tête de
     ligne → la ligne 3 peut alors porter le nom de fichier de sortie/poids) ;
   - fichier (converter) : nom + poids + format.
4. **État ÉTENDU** (clic/Entrée) : inchangé — sections chronologiques Entrée→Réglages→Sortie→État
   →Actions (§1) ; les chips se déplient en liste complète des réglages.
5. **Invariants conservés** : partial serveur + card_html + update en place (§3), data-status +
   data-action, 2 états, tricolore, mosaïque = géométrie (§4), Solitaire batchs (§3ter), couleurs
   de catégorie + liseré d'app (§9), nav clavier. **AUCUNE information supprimée** : tout ce que
   la grille montrait passe en chips (concis) ou en étendu.

### 10.4 Universalité — mapping par app (vérifié sur les capacités)

| App | Identité ligne 1 | Chips typiques | Aperçu ligne 3 |
|---|---|---|---|
| transcriber | icône audio/vidéo + nom | moteur, langue, diarisation, résumé | texte + badge correction |
| describer | icône type détecté + nom/URL | style, langue, longueur | texte |
| reader (PILOTE) | vignette page/PDF + nom | moteur OCR, langue, « X pages » | texte |
| composer | 💬 extrait prompt | modèle, durée, → wav/mp3 | player waveform |
| synthesizer | 💬 extrait texte | moteur, voix, langue | player |
| converter | icône type + nom | → format cible, préréglage | fichier (nom+poids) |
| enhancer | vignette avant | modèle, ×upscale, domaine | vignette après (slider A/B à venir) |
| anonymizer | vignette | modèles détection, classes, flou | vignette floutée |
| imager | 💬 extrait prompt | modèle, résolution, seed, mode | vignette image/vidéo |
| avatarizer | vignette visage | pipeline, qualité | vignette vidéo |

### 10.5 Plan (Reader = pilote)

1. Port Reader sur les briques (recette T/D/C) **avec la card v2 directement** (`reader/_item_card.html`
   réécrit au format v2 ; brique CSS `.wama-chip` + helper chips-depuis-schéma dans common dès le
   pilote, consommés par reader seul d'abord).
2. Validation navigateur Fabien sur Reader (esthétique = SA décision, cf. « apparence non figée »).
3. Si validé : remonter le layout v2 dans le formalisme (adapter `_batch_card.html` au même style,
   puis migrer T/D/C — mécanique, les données sont déjà serveur+schéma).

### 10.6 Divergences relevées pendant le pilote (à trancher à la passe UI unique)

Ces points sont **de l'apparence** (question UI 2) → NE PAS les régler app par app, ils se
tranchent une fois sur les briques communes et se propagent. Consignés au fil du pilote Reader :

- **Fond de card = décision COMMUNE, pas par app.** Aujourd'hui chaque app pose son fond dans son
  propre CSS (`composer/index.css:.generation-card{background:#1e2124}`, transcriber/describer/reader
  ailleurs) → rendus incohérents, dont un **fond quasi transparent** (contour seul) qui rend la file
  peu lisible et les **boutons discrets (hover à peine visible)**. Cible : porter le fond sur la
  classe commune `.wama-card` (wama-inspector.css) avec une **opacité choisie pour le contraste des
  boutons** ; retirer les fonds par app. (Signalé Fabien 2026-07-07.)
- **Temps de traitement affiché seulement par transcriber (écart FONCTIONNEL, pas UI).** La card doit
  transformer l'ETA en **durée de traitement** à la fin (SUCCESS). Seul transcriber le fait
  (`_card_progress.html` + `Transcript.processing_display` + `processing_seconds` posé par le worker).
  describer / composer / reader n'ont NI le champ, NI l'affichage. **Fix universel** (hors passe UI) :
  mixin commun `ProcessingTimeMixin` (`processing_seconds` + propriété `processing_display`),
  workers qui enregistrent `fin - début`, cards qui affichent la durée sur SUCCESS. Migrations ×3
  → à valider avant de générer. (Signalé Fabien 2026-07-07, tâche ouverte.)
