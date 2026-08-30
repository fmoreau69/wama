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
| En cours (`RUNNING`) | orange/`warning` « En cours » | barre qui se remplit + **% + ETA** |
| **Terminé** (`DONE`) | vert « Terminé » | **barre PLEINE verte persistante** ou ligne « ✓ Terminé · durée · taille » — **jamais absente** |
| Échec (`ERROR`) | rouge « Échec » | barre/ligne rouge + message |

> ⚠ **Le tricolore a UNE source : §8.5** (gris=brouillon · orange=en cours · vert=fini ·
> rouge=échec, pas d'état « config » distinct). Trois copies de ce code couleur avaient divergé
> (jaune/orange/gris selon la section lue — unifiées le 2026-08-27) ; ici ne vit que la règle
> badge+barre, pas la palette.

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

### 1quinquies. Preview du résultat — modèle à 3 niveaux (divulgation progressive)

> Migré de `CARD_CENTRIC_UI.md §5bis` (2026-07-25, plan doc B1 — décision validée 2026-06, seule
> partie de ce doc non reprise ailleurs). Référencé par `ROADMAP §1.2`.

| Niveau | Geste | Contenu | Rôle |
|--------|-------|---------|------|
| **Card** | toujours visible (sous la barre de progression) | preview **compacte typée par média** : image→miniature · vidéo→miniature+durée · audio→forme d'onde+durée · texte/OCR/transcript→extrait + **ligne de métriques** (« Transcription 77 mots · Diarisation · Résumé 48 mots · Cohérence 88 mots ») | **scanner** la file |
| **Volet droit (inspecteur)** | **clic** sur la card | preview **complète** + paramètres éditables | **détailler** la sélection |
| **Overlay plein écran** | **double-clic** (ou clic sur la miniature) | vue maximisée (transcript intégral, grande image, audio scrubbable) = la modale de preview repositionnée | **inspection approfondie** |

- Card (compact) et volet (complet) se **complètent**, ne se dupliquent pas.
- Le **bouton œil disparaît** : clic = sélection/inspecteur, double-clic = overlay.
- **Coût** : artefacts légers déjà générés (miniature, extrait, forme d'onde) + **lazy-load** des
  vignettes pour ne pas alourdir le rendu de la file.
- Le type de preview compacte est déclaré par app via la brique commune (`preview_registry` /
  `unified_preview` — l'`APP_SPEC.output_preview` du doc d'origine n'a jamais existé).
- **Composant commun (implémenté)** : classe `.wama-card-preview` → `media-preview.js` binde le
  **double-clic** et émet `wama:card-expand` (`detail: {id, url, el}`, *cancelable*). Style dans
  `media-preview.css`. Deux façons d'ouvrir le détail : l'app gère le sien (transcriber/reader :
  le RÉSULTAT — l'événement est alors annulé), sinon comportement par défaut = overlay du média.
- S'articule avec le **cycle avant/pendant/après** de la preview (`preview_utils`, faces
  Entrée/Comparer/Sortie) — c'est CE mécanisme qui remplace la drop zone du volet droit
  (décision 2026-07-25).

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
  Implémenté dans le Transcriber (`transcriber/views.py:1768`) — **À CENTRALISER dans `common/`** (aujourd'hui per-app).

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

## 5. Cartographie des cards existantes → SOURCE VIVANTE, plus de table ici

> **Table supprimée le 2026-08-27** (geste déjà appliqué avec succès dans
> `INSPECTOR_DETAIL_FIELDS.md §État de rollout`, 2026-07-25 : *les tables figées par app
> dérivent*). La table du 2026-07-11 était intégralement périmée — les 6 boutons de card sont
> passés en briques communes en août (`_cycle_button.html` inclus par 11 gabarits, avatarizer
> dans l'ordre et les couleurs canoniques, imager sur UN partial serveur unique — vérifié au
> code le 27/08). **État mesuré = `/apps/` et `python manage.py check_app_conformity`**
> (critères F5 par app).

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

Lié : `WAMA_APP_CONVENTIONS.md` (§boutons, §22 inspecteur), `WAMA_APP_GENERATION_ROUTE.md` (consolide les ex-GENERALIZATION_PLAN et COMMON_REFACTORING, archivés `docs/archive/`), `MODES_QUEUE_UX.md`.

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
- **Carte des zones de dépôt (anti-prolifération — migré de `CARD_CENTRIC_UI.md §4`)** :
  **1 source + 1 destination par app**, + la surface globale. Filemanager (arbre) = bibliothèque
  persistante = **source** (on glisse depuis) ; **card d'import (dans la file)** = **destination**
  unique par app (fichier de travail + référence) ; AI-assistant (accueil) = surface
  conversationnelle, concern distinct. La zone de dépôt du **volet droit est supprimée**
  (cohérent avec la décision 2026-07-25, cf. CONVENTIONS §19).

### 8.4 Lien Axe 3 (hors card, noté ici pour cohérence)
Prospection LLM → router un modèle vers une app existante (capacités vs `APP_CATALOG`) ou faire
**émerger** une app depuis un manifeste. Détail dans `PROJECT_STATUS.md §2`/`§18` et
`WAMA_APP_GENERATION_ROUTE.md` (horizon manifeste). **Phase B gatée** sur la maturité du runtime manifeste.

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

### 10.4 Universalité — le mapping par app vit dans les DÉCLARATIONS

> **Table supprimée le 2026-08-27** (même remède que §5 : une table par app recopie ce que le
> code déclare, et dérive). Le contenu de card par app se lit à la source : **chips** =
> `params.py` de l'app (`chip=True`, `section=`) rendus par `_card_chips.html` ; **identité et
> aperçu** = le partial `_<item>_card.html` de l'app + le mécanisme de préview unifiée (n°30,
> placeholder `data-card-preview`). Le principe qui reste vrai : chaque app exprime identité /
> réglages / sortie avec SES types (texte, vignette, player), dans la MÊME anatomie.

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
- **~~Temps de traitement affiché seulement par transcriber~~ ✅ **RÉSOLU pour les 5 apps portées**
  `ProcessingTimeMixin` (`wama/common/models.py`) : ✅ **10/10** (re-mesuré 2026-08-27 — les 6
  classes des 5 apps restantes de l'audit du 07/11 le portent : `Enhancement`+`AudioEnhancement`,
  `VoiceSynthesis`, `Media`, `ImageGeneration`, `AvatarJob`), affichage via
  `_processing_time.html`/`_card_progress.html` ; critère vivant = `processing_time` dans `/apps/`.

---

## 11. Card v3 « sections × chips » — décisions de maquette (2026-08-01, itérations Fabien×Claude)

> ⚠️ **La maquette est un OUTIL DE RÉFLEXION, PAS du code à porter.** Elle n'est pas
> représentative du fonctionnement réel (repli des lots inactif, dimensions/boutons simulés,
> icônes emoji, données factices). Ce qui se transfère : les DÉCISIONS de ce §11, les pistes de
> grille, les couleurs relevées du réel, l'anatomie des 5 sections, les comportements décrits.
> L'implémentation part des briques EXISTANTES (_batch_card, card_chips, _cycle_button,
> _card_progress, preview_utils, wama-queue…) — traduire, jamais recopier la maquette.
> Maquette de référence : [docs/card_designs/card_v3.5_maquette.html](docs/card_designs/card_v3.5_maquette.html) — archivée dans le dépôt le 2026-08-21 (v3.5 ; les arbitrages du 2026-08-01 y sont intégrés). ⚠ v3.4 : l exemple de card en ÉCHEC (barre figée) manque encore dans la maquette — à ajouter. Fusion
> v1 Transcriber (sections nommées) × v2 chips (compacité). RIEN de nouveau côté mécanismes :
> déclaratif → briques → UI. Pilote de portage : **SYNTHESIZER** (décision 2026-08-01 —
> pas le Transcriber), puis composer.

### Décisions ACTÉES
- **Grille à pistes alignées** — ⚠ depuis le 2026-08-23, les pistes sont **MESURÉES par
  `wama-card-v3.js` et PROPRES à chaque app** (recalculées quand le contenu change) ; les valeurs
  CSS (232px · 1fr · 1,15fr · 118px · 186px) ne sont que des **replis avant le premier passage du
  JS** — les lire comme des largeurs est un piège vécu (`wama-card-v3.css:158-166`). Les 5 sections
  (Entrée · Réglages · Sortie · État · Actions) s'alignent verticalement dans la pile.
  Micro-étiquettes 0,55rem uppercase par section.
- **Entrée sur sous-lignes** : nom → propriétés réelles du média (mp3 · 44,1 kHz · stéréo ·
  durée) → #id · date. Miniature 48px pour les apps à entrée visuelle.
- **Section SORTIE temporelle** : chips « blueprint » (pointillés, ~estimations, dérivées des
  réglages + ETA apprise) AVANT → étape live + % PENDANT → chips solides (propriétés réelles,
  détail par étape façon Transcriber : « 8 742 mots · 3 locuteurs · cohérence 85/100 ») APRÈS ;
  l'erreur remplace la sortie au même endroit en échec. Chips = brique card_chips, attribut
  `section=` (input/settings/output) sur les Param `chip=True` — ✅ **livré** (converter/reader,
  `_card_chips.html`) ; reste le hook `predicted_output()` par app (prototype reader).
- **Zone de PREVIEW PERMANENTE** (jamais retirée) : récapitulatif de sortie dès l'ajout (fond
  légèrement distinct, ex. « Transcription (texte) + diarisation · formats après traitement :
  TXT · SRT · PDF · DOCX ») → PENDANT : préviz de process si disponible → APRÈS : préviz réelle.
  **Orientation : réutiliser le système de faces de l'inspecteur** (`preview_utils`
  entrée / pendant `?side=during` / sortie, clic pour switcher) — un seul système de preview,
  la card en devient un consommateur compact. Étude des meilleures préviz par app = 2e temps.
- **Barre de progression : VERTE (dégradé reader) sur tout le cycle** (décision Fabien —
  « trop de couleurs » sinon ; l'état est déjà porté par liseré + point + badge). Réversible.
- **ÉCHEC : la barre reste FIGÉE au % atteint** (comportement observé sur les batchs actuels,
  jugé PRÉCIEUX : on voit où le process est mort). Ne jamais vider/compléter la barre en échec.
- **Boutons : slot d'actions SPÉCIFIQUES d'app** entre ▶ et ⬇ (ex. ✏️ correction Transcriber).
  ⚠ Les actions doivent TENIR dans leur piste (wrap autorisé, jamais de débordement).
- **PILE (jeu de cartes) = MODIFICATEUR orthogonal, PAS un 3e mode** : un sélecteur on/off qui
  s'applique à la file ET à la mosaïque — compression progressive selon la distance au focus
  (46px → 28px → lamelles), navigation clic + flèches (WamaQueue.focusCard). En mosaïque :
  atténuation/scale plutôt que reflow (éviter les sauts de grille).
  **La card d'entrée n'est JAMAIS compressée par la pile** (sinon remonter toute la pile pour
  ajouter).
- **Mosaïque : le lot ne déforme pas la grille** (PAS de bande pleine largeur — rejetée) :
  mère = tuile normale, filles À LA SUITE dans le flux (liseré haut pointillé + fond #1e2124),
  cards hors lot ensuite sans marqueur.

### Points OUVERTS
- **TRANCHÉ 2026-08-01 (v3.5)** : famille de lot = CYAN du réel ( :
  fond #0d1a1a, bordure #0dcaf0) — mère bord cyan, filles fond teinté + liaison cyan (rail en
  ligne / liseré haut en mosaïque), survol-famille en trait PLEIN cyan (pointillés réservés à la
  card d'entrée). **Pile × mosaïque : OUVERT** (v3.4 atténuation/scale REJETÉE — à re-imaginer ;
  la pile ne s'applique qu'à la file pour l'instant).
- **Raccord mère↔filles en mosaïque insuffisant** (surtout mère en bout de ligne). Pistes :
  survol/sélection de la mère → surbrillance des filles (cohérent « une pile ouverte à la
  fois ») ; chip 📦 lot-#id sur les filles ; couleur d'identité par lot (⚠ collision avec les
  codes d'état — prudence).
- **Card d'entrée : NE PAS TOUCHER à l'existant** (elles vivent hors file volontairement ;
  réintégration en 1re card = chantier ultérieur). La maquette garde la proposition « card v3
  brouillon + mini-onglets de modalité » à titre d'étude ; en mosaïque elle devra avoir la MÊME
  forme que les autres tuiles (pas pleine largeur) + contour pointillé.
  - 🎯 **TERRAIN D'ESSAI DÉSIGNÉ : la jumelle de bac à sable `converter_01`** (rappelé par Fabien
    le 2026-08-30 ; **le lien n'était consigné nulle part** avant cette ligne, alors que la
    proposition l'est depuis le 21/08 — un chantier dont le lieu d'essai n'est pas écrit ne
    redémarre pas). **C'est ce qui lève l'interdit ci-dessus sans le contredire** : la jumelle est
    la seule app dont la card d'entrée ne peut mettre AUCUNE app réelle en risque (source jamais
    modifiée, cf. `WAMA_APP_GENERATION_ROUTE §S2bis`). L'existant reste intouché ; la v3 se juge
    à côté, sur une app régénérable à volonté.
  - **Ce qui existe déjà et sert de socle** : la card d'entrée est une **brique COMMUNE**
    (`common/_new_item_card.html`), fonctionnelle dans les 10 apps, et elle porte **déjà** les
    modalités que les mini-onglets doivent regrouper — dépôt/dossier, URL, médiathèque, lot
    (`show_batch_bar`), live (`show_live`), prompt, et un **slot de référence typé**
    (`reference_accept`). La v3 n'a donc pas à réinventer les modalités : **elle change leur
    PRÉSENTATION** (une visible à la fois, hauteur constante) — cf. `docs/card_designs/
    card_v3.5_maquette.html` (état brouillon, liseré cyan pointillé, `.card3.draft`).
  - ⚠ **Préalable mesuré côté générateur** : l'app générée reçoit aujourd'hui **un seul slot**
    et **aucun slot de référence** (`templates_gen.py:46/300` compose sur la liste PLATE
    `input_extensions`). Tant que ce n'est pas réparé, la jumelle est un terrain d'essai **plus
    pauvre que les apps manuelles** — c'est le point (b) de `§S2bis.6`, à traiter **avant** d'y
    juger la v3.
- Choix barre verte vs barre couleur-d'état : tranché vert, à réévaluer après usage.

### 11.3 PORTAGE PILOTE — Reader (2026-08-01, session d'implémentation)

> **Le Reader était le pilote de la v2 (§10) : il est donc le pilote de la v3.** Choix de Fabien —
> porter là où la v2 vivait déjà, plutôt que sur une app en v1 : on remplace un formalisme obsolète
> au lieu d'en superposer un troisième, et **aucune app en v1 n'est mise en risque**.
> `reader/_item_card.html` n'est inclus que par `reader/index.html` (autonome + fille de lot) et
> l'endpoint `reader:card_html` — périmètre de casse strictement nul.

**Fait.** Les 5 sections à pistes fixes (alignement vérifié au navigateur : piste ÉTAT à la même
abscisse sur les 4 cards), section Sortie temporelle (blueprint pointillés → étape live → chips
solides), preview permanente, barre verte sur tout le cycle, échec figé au % atteint, famille de lot
cyan (mère `wcv3--batch-parent`, filles fond `#0d1a1a`).

**Où vit quoi** — CSS = brique commune `common/static/common/css/wama-card-v3.css` (chargée par
`base.html`) ; markup = `reader/_item_card.html` (pilote). Remontée du markup en gabarit commun
(cible : _card_v3 dans `common/templates/common/`, à créer) **après** validation d'usage, comme le prévoyait déjà §10.4 pour la v2 : on ne
fige pas une anatomie avant de l'avoir vue tourner. La brique `_card_chips.html` n'a PAS été touchée
(elle sert aussi l'avatarizer) — l'attribut `section=` du §11 reste à faire.

**Ce que la maquette ne pouvait pas révéler** (et qui a coûté 4 itérations mesurées) :

1. **Container queries, PAS media queries.** La largeur utile de la file ne découle pas de celle de
   la fenêtre : **fenêtre 1600 px → file 888 px** une fois l'explorateur et l'inspecteur ouverts. Un
   `@media (max-width:1400px)` ne se déclenche donc JAMAIS alors que les pistes débordent déjà. La
   card se déclare `container-type: inline-size` et se mesure à elle-même. **Les volets sont la
   norme dans WAMA, pas l'exception** — toute future brique de card doit partir de là.
2. **La piste ACTIONS est MESURÉE, jamais devinée** (`actionsWidth()` de `wama-card-v3.js` ; le
   `186px` du CSS est un repli, pas un plancher — piège vécu le 2026-08-23, les **six** boutons
   tiennent). La resserrer avec les autres faisait passer la corbeille à la ligne — le débordement
   que §11 interdit. Ce sont les pistes de CONTENU qui absorbent la contrainte, jamais celle des
   actions.
3. **Les seuils de repli se mesurent, ils ne se devinent pas.** Premier jet à 980 px : la file réelle
   (888 px) tombait toujours dans le repli, donc le formalisme canonique n'était JAMAIS visible dans
   la configuration la plus courante. Seuil ramené à 760 px après mesure.
4. **Ellipsis des chips** : `text-overflow` ne s'applique qu'en `inline-block` (le libellé est un
   nœud texte direct du chip, pas un élément). Scopé à `.wcv3-out` pour ne pas toucher la brique.
5. **En échec, la preview permanente ne doit plus annoncer les formats de sortie.** Elle reste
   (§11 : jamais retirée) mais promettre « TXT · MD · PDF · DOCX » après un échec est pire que se
   taire. Attrapé par une assertion, pas par l'œil.

> ⚠ **7e récidive du piège `{# … #}` multi-lignes.** Django ne gère pas les commentaires dièse
> multi-lignes : le texte est rendu tel quel. **Dans une grille c'est pire qu'ailleurs** — le texte
> crée une boîte anonyme de grille, donc une LIGNE FANTÔME (mesuré : +168 px de vide sur chaque
> card, invisible à la lecture du template). Toujours `{% comment %}`.

**Exemple d'échec** — le cas manquant de la maquette est désormais couvert et testé (barre figée à
43 %, verte, non animée ; erreur en piste SORTIE remplaçant le blueprint).

**Reste ouvert** : hook commun `predicted_output()` (prototypé dans `reader/views.py::_output_chips`) ;
miniature réelle au lieu de l'icône typée ; pile × mosaïque (toujours non tranché) ; remontée du
markup en brique commune. *(L'attribut `section=` sur les `Param chip=True` est LIVRÉ —
converter/reader, re-mesuré 2026-08-27.)*

### 11.4 TROIS DESIGNS COEXISTANTS — v1 · v2 · v3 (décision 2026-08-01, précisée le même jour)

**Décision** : on ne remplace pas un design par l'autre, on garde les DEUX, sélectionnables.
Le second n'est pas une variante esthétique du premier : c'est un **design MINIMALISTE**, dont
la règle de conception est explicite —

> **Tout ce qui est déjà accessible dans l'inspecteur sort de la card.**

Concrètement, la card minimaliste **retire** les informations et l'aperçu que le volet droit
donne déjà au clic, pour ne garder que ce qui sert à *identifier, situer et agir* sans ouvrir
quoi que ce soit. Elle est donc nettement plus courte — c'est le but : voir beaucoup d'éléments
d'un coup d'œil. Le design v1 (riche) reste pour qui veut tout lire sans cliquer.

**Ce que cela suppose, et qui n'est pas négociable** : les deux designs doivent être alimentés
par la MÊME source générée (schéma de params → `chips_by_section`), sinon ils divergeront et on
aura sanctuarisé du HTML écrit à la main sous le nom de « design v1 ».

> ⚠ Garde-fou : **aucun `{% if design == … %}` dans les templates.** Si une différence entre les
> deux designs réclame une condition côté serveur, c'est qu'elle n'est PAS esthétique — et il
> faut alors la traiter comme une capacité déclarée, pas comme un branchement. Un chip et une
> ligne de réglage portent la même donnée (icône + libellé + title) : la différence entre les
> deux designs est un `display`, donc une feuille de style.

**État du prérequis (audité 2026-08-01)** : le Transcriber a déjà un registre complet
(`transcriber/params.py` : backend, hotwords, preprocess_audio, enable_diarization,
generate_summary, summary_type, verify_coherence — avec labels, ordre, dom_id). Il lui manque
UNIQUEMENT les attributs déclaratifs `chip=True` / `section=` pour que sa card se génère au lieu
d'être écrite à la main. **Le portage n'est pas une réécriture, c'est une déclaration.**

### 11.5 MODE PILE — câblé (2026-08-01)

Conforme au comportement de la maquette v3.5, vérifié au navigateur. Modificateur **on/off**
orthogonal au layout (pas une 3e disposition) : `card_stacked` au profil, bouton dans le toolbar
commun, donc présent d'emblée dans les 10 apps.

- Compression par distance au focus : **0 = entière · 1 = 46 px · 2 = 28 px · 3+ = lamelle**.
- Card d'entrée JAMAIS compressée.
- **La navigation traverse les lots** : le lot s'ouvre quand on y entre, se replie quand on en
  sort, un seul ouvert à la fois (l'accordéon vient de `initOnePileOpen`, déjà existant).

Deux pièges, tous deux trouvés par la mesure et invisibles à la lecture du code :

1. **Ne pas filtrer la liste de navigation sur la visibilité.** Une première version excluait les
   cards masquées : les filles d'un lot replié sortaient de la liste, le lot entier était sauté
   et ses cards injoignables au clavier — la pile n'avait aucun usage. Deux listes, deux rôles :
   on NAVIGUE sur toutes les cards, on COMPRIME sur les seules visibles (sinon un lot replié de
   8 items compte 8 crans et la card suivante est déjà en lamelle).
2. **Le focus doit survivre au rendu serveur.** `upsertCard` remplace le nœud entier, la classe
   de focus part avec : à chaque tour de polling la pile se repliait sur sa première card. Le
   focus est donc mémorisé par `data-id` et rétabli après remplacement.


### 11.6 TROIS DENSITÉS — implémentation (2026-08-01)

La décision §11.4 s'est précisée : **trois** designs coexistants, pas deux.

| | Design | Ce qu'il montre | Hauteur mesurée (reader) |
|---|---|---|---|
| **v1** | Détaillé | tout lisible sans cliquer ; réglages en liste verticale à icônes | 143 px |
| **v2** | Compact | *minimaliste* — sans étiquettes, bandeau d'identité, propriétés média ni aperçu | **62 px** |
| **v3** | Affiné | 5 sections alignées d'une card à l'autre (défaut) | 143 px |

**La v2 n'était pas perdue** : elle avait été écrasée dans `reader/_item_card.html` au premier
commit v3, mais git l'avait. Restaurée pour référence en `docs/card_designs/reader_card_v2_reference.html`
(129 l.) — c'est la card « §10.3 » : identité + chips sur une ligne, barre, aperçu.

**Mise en œuvre** : `card_design` au profil (migration 0014), diffusé par le context processor
existant donc disponible dans les 10 apps ; menu dans le toolbar commun ; attribut
`data-card-design` sur la file ; **trois blocs CSS**. Le markup ne change pas — ce sont les
5 sections nommées émises par le template d'app. Aucun `{% if design %}` : le garde-fou tient.

Deux pièges rencontrés, tous deux visibles seulement à l'écran :

1. **Ne pas replier deux sections dans la MÊME cellule de grille.** Une première version de la
   v2 mettait Réglages et Sortie en `grid-column: 2; grid-row: 1` pour gagner de la hauteur :
   elles ne se suivaient pas, elles se **superposaient** — les libellés se chevauchaient. En v2
   la compacité vient de ce qu'on RETIRE, pas d'un repli de colonnes. Les 5 pistes restent.
2. **Le toolbar commun est un espace fini.** Le sélecteur de densité en liste déroulante à
   libellés poussait « Démarrer tout / Télécharger tout / Tout effacer » à la ligne sur les
   10 apps. Remplacé par un bouton-icône à menu, qui tient dans la place d'un bouton.

> ⚠ **v1 et v3 font la même hauteur sur le reader** (143 px) : cette app n'a pas plus à montrer
> en détaillé. La distinction v1/v3 ne se voit que sur les apps riches (Transcriber : badges
> temps réel/prétraité, propriétés audio, métriques de sortie). Ne pas conclure de l'écart nul
> sur le reader que les deux designs se valent — le comparer sur le Transcriber.

### 11.7 TRANSCRIBER — émission des 5 sections (2026-08-01)

Le Transcriber émet désormais les 5 sections nommées : il peut donc basculer entre les trois
densités, ce qui était le dernier verrou. Portage **chirurgical** (remplacement des balises de
structure `row`/`col-md-*`, contenu intact) et non réécriture — aucun des ~19 éléments
d'information de la card n'a été retouché.

**Section SORTIE créée** : le contrat (« Transcription + diarisation · formats… ») et les
métriques réelles (mots, voix, résumé, cohérence) vivaient dans le bloc d'aperçu ; ils rejoignent
leur section, où les trois designs savent les placer. L'extrait de texte reste à l'aperçu : c'est
un CONTENU, pas une propriété de sortie.

Hauteurs mesurées (card réelle, un transcript SUCCESS complet) : **v1 301 px · v2 242 px · v3 332 px**.

Trois pièges, tous rencontrés :

1. **Le template ne doit JAMAIS imposer le style des chips.** Le transcriber portait
   `.wama-chips--list` en dur : ses chips restaient en liste verticale même en v2/v3, où ils
   doivent tenir sur une ligne. C'est le sélecteur `[data-card-design="v1"]` qui applique ce
   rendu — à toutes les apps d'un coup. Une classe de présentation dans un template d'app est
   le premier pas vers la divergence que §11.4 interdit.
2. **Placer explicitement les sections en v1.** Sans `grid-row`, la Sortie (`grid-column: 1/-1`)
   coupait la première ligne et repoussait État puis Actions sur des rangées suivantes : la card
   s'étirait au lieu de reproduire l'agencement d'origine. L'ordre DOM reste le même pour les
   trois designs ; seul le PLACEMENT change — c'est précisément ce qui permet un markup unique.
3. **Uniformiser ce qui doit disparaître en v2.** L'identité (`#id · date`) et l'aperçu du
   transcriber n'utilisaient pas les classes communes : ils survivaient en mode Compact alors
   qu'ils doivent en sortir. Portés sur `.wcv3-head` et `.wama-card-preview`.

> ⚠ **`speaker_count` est une `@property`, pas un champ.** Interroger `_meta.get_fields()` le
> déclare absent — faux négatif : « Diarisation (2 voix) » s'affiche bien. Vérifier une donnée de
> modèle par `hasattr()` sur une instance, jamais par la seule liste des champs.
