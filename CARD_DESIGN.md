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
