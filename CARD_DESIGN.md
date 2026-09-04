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

> ✅ **LIVRÉ le 2026-09-04** — brique commune `wama/common/static/common/js/wama-queue-dnd.js`,
> montée globalement par `base.html`, auto-active sur toute file portant `{% queue_dnd_attrs %}`.
> **Les 12 apps en héritent sans écrire une ligne.** Ce qui suit décrit l'état RÉEL.

### Les quatre gestes, et la règle qui les sépare

> **Déposer SUR une card change l'APPARTENANCE ; déposer ENTRE deux cards change l'ORDRE.**
> Tout le reste (multi-sélection, lot d'origine, niveau) n'est que du contexte. C'est ce qui
> permet d'offrir quatre opérations sans un seul mode, bouton ou modificateur à retenir.
> Le seuil est le **tiers médian** de la card pour « sur », les tiers haut/bas pour « entre » —
> un demi/demi ne laisserait aucune zone au geste de fusion, le plus demandé des quatre.

| geste | endpoint | retour visuel |
|---|---|---|
| card(s) → **sur** une card de lot | `move_to_batch` | cadre cyan autour de la card |
| card(s) → **sur** une card unitaire | **`merge`** | cadre cyan |
| fille(s) → **entre** deux entrées de file | `remove_from_batch` | barre d'insertion pleine largeur |
| card(s) → **entre** deux cards | `reorder_queue` (file) / `reorder` (dans un lot) | barre, en retrait dans un lot |

- **Sélection multiple** : clic simple (inchangé — 1 card + inspecteur), **Ctrl** = ajout/retrait,
  **Maj** = plage dans l'ordre visible (lots repliés traversés), **Ctrl+A** = tout sélectionner,
  **Échap** = relâcher. ⚠ Ctrl+A est posé UNE fois sur le document et choisit UNE file (celle qui
  porte déjà une sélection, sinon la file VISIBLE) : un écouteur par file aurait sélectionné aussi
  dans l'onglet caché des apps à deux files. Il ne préempte rien dans un champ de saisie ni sur une
  file vide. *Lire `ev.key`, jamais `ev.code` : en AZERTY le A produit `code = KeyQ`.*
  **UNE seule sélection dans WAMA**
  (arbitrage Fabien, 04/09) : c'est celle de l'inspecteur, qui bascule en « N éléments
  sélectionnés » avec les actions de groupe. La brique **annonce** (`wama:selection-change`),
  l'inspecteur **rend** — deux briques qui décideraient chacune finiraient par diverger.

### 🔴 `merge` ≠ `consolidate` — deux opérations, deux noms

> Le piège de ce chantier, trouvé par une remarque de Fabien puis mesuré par un test le jour même.

- `consolidate` = **l'import** : « range ces éléments déposés ensemble ». **Cinq apps le
  redéfinissent** en version PAR NATURE (`group_into_batches_by_nature`) → 3 images + 2 vidéos
  donnent **deux lots**. C'est le bon comportement quand on vient de déposer un dossier mélangé.
- `merge` = **le drag&drop** : « fusionne ces éléments en UN lot ». On a visé une card précise ;
  si les natures ne cohabitent pas, la réponse est un **refus** (409 + motif au toast).
- Router le geste sur `consolidate` semblait gratuit — même signature, même effet apparent. Le
  résultat réel dans ces cinq apps : déposer une vidéo sur une image répondait
  `{"consolidated": true}` après avoir créé deux lots-de-1, **c'est-à-dire rien de visible, avec
  un accusé de succès**. `merge` vient donc de la fabrique commune et **aucune app ne le
  redéfinit** — c'est ce qui le garde strict partout. (Les cinq `consolidate` locaux ne
  partagent même pas leur contrat d'entrée : le converter lit `job_ids`.)

### La compatibilité de fusion est celle de l'IMPORT — une déclaration, deux consommateurs

- La question « ces deux cards peuvent-elles fusionner ? » avait **déjà** sa réponse :
  `group_into_batches_by_nature(nature_of=…)`, qui décide à l'import de ce qui va ensemble
  (converter, anonymizer, describer, enhancer, avatarizer). La MÊME fonction est passée en
  `group_key=` à la fabrique de manipulation — jamais une seconde règle.
- Cela force à la **nommer** : une lambda inline ne se partage pas, et c'est sous cette forme
  qu'elle vivait dans 3 apps. Vérifié par **AST** (jamais grep) :
  `wama/common/tests_queue_dnd.py::JumelageNatureGroupKeyTest`. Le codegen émet la même paire,
  donc une app générée naît avec la garde.

### Ce qui n'existait pas et qu'il a fallu créer

- **`QueueOrderMixin.queue_index`** (13 modèles de batch, migration additive par app). `reorder`
  ne persistait que `row_index` **DANS** un lot ; au niveau supérieur, `apply_queue_sort_filter`
  n'offrait que cinq tris **calculés** — aucun ordre manuel n'existait. D'où un **6ᵉ tri
  « ✋ Manuel »**, sélectionné tout seul au premier glisser. `queue_index == 0` = « jamais
  ordonné » et passe **en tête par récence** : un import arrivé après un classement manuel
  apparaît en haut, au lieu de se noyer dans un ordre qu'il n'a pas connu.
- **`data-entry-batch-id`** sur la card unitaire (`_queue_entry.html`) : une entrée de file est
  un BATCH même quand elle s'affiche en card simple, mais le gabarit la rendait **sans** son
  enveloppe `.batch-group[data-batch-id]` — l'id du lot n'existait nulle part au DOM et le
  drag&drop aurait sauté toutes les entrées unitaires, en silence.
- **L'anonymizer** était la dernière app hors fabrique (11/12 avaient les routes) : adoptée.

### ⚠ SortableJS est ÉCARTÉ (révision du 2026-09-04)

La ligne d'origine prescrivait SortableJS. Elle date d'**avant** deux exigences qui la périment :
la **multi-sélection** (le plugin MultiDrag ne compose pas avec des listes imbriquées — et nos
lots en sont) et le **dépôt sur une card pour fusionner** (SortableJS modélise le déplacement
entre listes, pas la fusion sur un élément : il aurait fallu l'écrire par-dessus de toute façon).
S'ajoute la règle « pas de CDN » — aucun asset tiers n'est vendorisé dans le dépôt, donc adopter
la lib ouvrait ce chantier-là aussi. Le drag natif HTML5 fait les quatre gestes, sans dépendance.

- **Réordonner** (drag) : persiste `row_index` dans un lot, `queue_index` au niveau de la file.
- **Glisser DANS un batch** = `move_to_batch` ; **glisser HORS** = `remove_from_batch`.
  Endpoints fins : `reorder`, `reorder_queue`, `merge`, `move_to_batch`, `remove_from_batch`.
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
    cours quand le polling re-render. ✅ Tenu : un **pur réordonnancement ne recharge pas** (l'écran
    est déjà juste) ; tout ce qui **change la composition** d'un lot recharge, parce que le serveur
    seul sait recomposer totaux, card mère et disparition d'un lot vidé.
  - *Séquentiel, jamais parallèle* : les endpoints se marchent dessus (`move_to_batch` recalcule le
    total et peut SUPPRIMER un lot qui se vide). Deux POST concurrents sur le même lot donnent un
    total faux, ou un 404 sur le lot que le premier vient d'effacer. Le coût — N allers-retours pour
    N cards — est celui d'un geste rare et délibéré.
- **Brique commune** (pas par app) : `wama-queue-dnd.js` + `wama-queue-dnd.css` + le templatetag
  `{% queue_dnd_attrs app [domain] %}` (les URLs passent par le **DOM**, comme les
  `data-batch-<action>-url` — pas par les `APP.urls`, qui portent un nom de global différent par
  app et forceraient le substrat à connaître 12 noms d'apps).

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
  - ~~⚠ **Préalable mesuré côté générateur** : l'app générée reçoit un seul slot et aucun slot
    de référence~~ ✅ **LEVÉ le 2026-08-30** : les slots se déclarent par DOMAINE
    (`ROUTE §S2bis.6 (b)`), le générateur émet le slot de référence depuis le port. La jumelle
    est redevenue un terrain d'essai valable pour la v3 — cartographie des charges et exigences
    de Fabien : **§11.8 ci-dessous**.
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

### 11.8 CARD D'ENTRÉE v3.5 — cartographie des CHARGES + exigences (mesuré 2026-08-30)

> Demandé par Fabien avant d'attaquer la v3.5 sur `converter_01` : *« bien faire l'état des lieux
> avant d'attaquer pour ne pas se retrouver bloqué plus tard sur une des applications »*. Relevé
> exhaustif des 12 inclusions de `wama/common/templates/common/_new_item_card.html` + tout ce qui
> gravite (balayage dédié du 30/08, ancres vérifiées). **Ceci est LA checklist d'absorption de la
> v3.5** : chaque ligne doit avoir une place dans la nouvelle card — ou une exclusion motivée.

#### Exigences de Fabien (2026-08-30) — le cahier des charges v3.5

1. **Zones distinctes PAR RÔLE de fichier** (travail / référence / batch…), chacune cible de
   drag&drop depuis le filemanager ET l'explorateur Windows. Rôles **très explicites** — un dépôt
   ambigu « braque l'utilisateur à la 1ʳᵉ tentative ».
2. La séparation des rôles **résout l'ambivalence travail/batch** qui a motivé l'exception de
   catégorie `text` — cf. la position consignée à `WAMA_APP_GENERATION_ROUTE.md` §S2bis.6bis
   (le rôle `text` = texte brut, pas les documents).
3. **Le prompt a besoin d'espace** quand l'utilisateur veut être précis — à résoudre sans casser
   la règle v3.5 « les onglets de modalité ne changent jamais la hauteur de la cellule ».
4. **⚙ + bouton de cycle sur la card d'entrée** (état « attente fichier ») : ⚙ = paramètres de
   file par défaut. ⚠ La maquette `docs/card_designs/card_v3.5_maquette.html` ne les montre PAS
   sur la card brouillon (:207-241 — seul `▶ Transcrire`), alors qu'elle y affiche une section
   « Réglages » en chips que rien ne permet d'éditer sur place, et que tous les autres états ont
   ⚙ + cycle. **Mesuré : AUCUNE app n'a aujourd'hui de ⚙ ni de bouton de cycle sur sa card
   d'entrée** (la brique ne rend qu'un `primary_btn_id` ; `WamaCycleButton` n'est câblé que sur
   les conteneurs de FILE, 10 câblages relevés).
5. **L'import MÉDIATHÈQUE porte le rôle lui aussi** (2ᵉ message, 30/08) : l'idée initiale du
   bouton médiathèque visait plutôt les fichiers de RÉFÉRENCE — or le picker injecte aujourd'hui
   le fichier choisi dans l'input de TRAVAIL (`_new_item_card.html:117-121` : `MediaPicker` →
   `file_input_id`), au rôle donc implicite et parfois faux : *« l'utilisateur ne sait pas le
   rôle du fichier qu'il importe depuis la médiathèque »*. En v3.5 : un accès médiathèque **par
   ZONE de rôle** (filtré par l'accept du rôle — `media_library_type` existe déjà comme filtre,
   mais il est GLOBAL à la card), jamais un bouton unique au rôle implicite. Même contrat que le
   D&D par rôle de l'exigence 1 — la médiathèque est une modalité comme les autres.
6. **Le TEMPS RÉEL entre dans la card d'entrée — TRANCHÉ le 30/08, via la PREVIEW.** Question
   de Fabien (*« un champ temps réel au-dessus de la file ? directement dans la card
   d'entrée ? »*), réponse alignée sur ses deux décisions antérieures (`MODES_QUEUE_UX §5`
   25/07 : affordance de card, pas un mode ; maquette : 🎙 = modalité) et PRÉCISÉE par lui :
   **on active la modalité, on parle, et le résultat s'affiche dans la preview « during » de la
   card** — « quelques infos complémentaires pour expliciter le mode preview, quitte à ce que
   la zone soit un peu plus haute et sur plusieurs lignes ». Pas de mode temps réel, pas de
   surface live dédiée, pas de réécriture UI. (La 1ʳᵉ proposition Claude — la card brouillon
   devenant surface live — est ÉCARTÉE : elle réécrivait une UI que la brique `during` rend
   inutile.) ⭐ Convergence avec l'existant : le transcriber STREAME DÉJÀ son texte partiel par
   ce canal (`during_preview=True`, `publish_partial_text` → face `?side=during`, 2026-08-13) —
   Speak crée la card et la session live emprunte le même tuyau que la transcription de
   fichier. ✅ La **tension `MODES_QUEUE_UX §5bis` est CLOSE dans la foulée** : les modes
   `realtime` de synthesizer/transcriber (identiques à leurs jumeaux `normal`, jamais câblés —
   0 `WamaModes` dans les deux apps, mesuré) sont RETIRÉS d'`app_modes.py` le 30/08, leurs
   `inputs` remontés au domaine. Le drapeau déclaratif de la modalité 🎙 (remplaçant du
   littéral `show_live`) s'ajoutera AVEC son lecteur, à l'émission v3.5 — jamais une
   déclaration sans consommateur.
7. **Les fichiers injectés d'une card doivent pouvoir se REMPLACER** (4ᵉ message, 30/08) :
   aujourd'hui on ne peut remplacer ni le fichier de travail ni la référence d'une card
   existante — dupliquer permet « mêmes entrées, autres réglages » mais JAMAIS « autres
   entrées, mêmes réglages ». Position (Claude, à valider) : **tant que la card est PENDING,
   l'entrée est un paramètre du process comme les autres** — remplaçable par les mêmes zones de
   rôle que la card d'entrée (drop / médiathèque / filemanager sur la zone concernée) ; après
   exécution, « remplacer l'entrée » = une NOUVELLE passe → c'est la duplication (qui gagne
   donc ses deux directions) ou le manifeste de PROCESS (`WAMA_MANIFEST_ARCHITECTURE`,
   proposition du même jour — la duplication PAR DESCRIPTION, où remplacer les entrées est
   l'usage nominal). Le domicile UI du remplacement est la section Entrée de l'exigence 8.
8. **Modale ⚙ et inspecteur : sections EXPLICITES Entrée / Réglages / Sortie** (même message),
   comme les cards v3 — avec accordéons, Entrée et Sortie REPLIÉS par défaut (la place aux
   réglages), mais rouvrables pour re-modifier. Position (Claude) : oui, et c'est UN geste de
   brique — la modale est GÉNÉRÉE (`WamaParams.settingsModal`) et le schéma de params déclare
   DÉJÀ la section champ par champ (`chips_by_section` s'en sert pour les chips de card) : les
   10 apps héritent d'un coup, aucune modale à réécrire par app. La section Entrée est aussi le
   domicile du remplacement de fichiers (exigence 7) — même anatomie partout : card, modale,
   inspecteur disent Entrée/Réglages/Sortie dans le même ordre.

#### Les charges à absorber — ce que les 12 cards portent DÉJÀ

| # | Charge | État mesuré | Ancres |
|---|---|---|---|
| 1 | **Modalités d'entrée** : dépôt/clic · dossier récursif (8/12) · URL (avec ou sans bouton) · médiathèque (`MediaPicker`) · lot · live/Speak (transcriber seul) · slot référence typé (3/12) · **manifeste de PROCESS** (à venir — l'importeur du pipeline à 1 nœud est une modalité de la card, précision Fabien 30/08, `WAMA_MANIFEST_ARCHITECTURE.md §8` ; même geste que le fichier de lot : dépôt + détection structurelle + aperçu) | brique commune, la v3.5 change leur PRÉSENTATION (mini-onglets) | `wama/common/templates/common/_new_item_card.html` |
| 2 | **Prompt** primaire (5/12 : composer, synthesizer, avatarizer, imager ×2) + compteur de mots et zone droppable (avatarizer seul) + **prompt négatif** (imager, en zone d'extension) | doctrine écrite : « dans la CARD, pas dans le volet » | `_new_item_card.html:76-77` |
| 3 | **Réglages inline** : voix/vitesse/titre + **aperçu SSE de la voix** (synthesizer) ; **sélecteur de modèle avec Auto** + aide `WamaModelHelp` (imager ×2) | via `extra_zone_template`, sans contrat — 2 apps ont DÉJÀ des réglages dans la card, sans ⚙ | `wama/synthesizer/templates/synthesizer/_new_item_extra.html` ; `wama/imager/templates/imager/_model_zone.html` |
| 4 | **Sélection visuelle d'actif** : galerie d'avatars (grille cliquable) | seul cas du parc | `wama/avatarizer/templates/avatarizer/_new_item_extra.html` |
| 5 | **Enrichissement ✨** : brique 2-états complète (champ `user`/`processed`, barre « voir mon prompt / revenir / ré-enrichir », endpoint générique, pipeline langue→traduction→enrichissement→réf→RAG, kill-switch + préférence user) | ⚠ **la brique n'émet AUCUN déclencheur** : le seul vrai bouton ✨ est FABRIQUÉ par l'imager ; composer et anonymizer attachent la brique **sans pouvoir la déclencher** | `wama/common/static/common/js/wama-prompt-enrich.js` ; `wama/common/utils/prompt_pipeline.py` ; `wama/imager/static/imager/js/input_card.js` |
| 6 | **Chips de mots-clés suggérés** : brique commune + modèle `PromptKeyword` (tronc commun `user=None` + perso, 7 catégories, accordéon, insertion/retrait dans le prompt, glossaire préservé verbatim à l'enrichissement) | **adoption 1/10** (imager) ; le point de montage est bricolé en JS par l'app — la brique card n'offre AUCUN slot chips | `wama/common/static/common/js/wama-prompt-chips.js` ; `wama/media_library/models.py` |
| 7 | **Appariement entrée⇄modèle** : modèles incompatibles désactivés avec raison, slots requis/suggérés surlignés, gate de lancement, chips retirables, slots non-fichier déclaratifs | 7/10 adoptent, mais **3 seulement rendent l'état DANS la card** (imager ×2, composer) — 4 l'affichent au volet, 2 fabriquent l'élément en JS ; **1 seul** (imager) pilote le bouton primaire via `onState` | `wama/common/static/common/js/wama-input-match.js` |
| 8 | **Détection batch** : extension (`txt/md/csv`) → garde MIME → **arbitrage serveur par le CONTENU** (`count=0` ⇒ fichier de travail) ; 1 seul fichier peut être descripteur ; refus ligne-à-ligne visible | ids FIXES ⇒ **une seule barre par page** (d'où le clone `_audio_batch_bar.html` de l'enhancer, hors brique) ; l'URL saisie passe par le MÊME pipeline (`ingestText`) | `wama/common/static/common/js/batch-import.js` ; `wama/common/templates/common/batch_detect_bar.html` |
| 9 | **`data-wama-depot`** : `cree` (défaut, 9/12) vs `attache` (imager ×2, avatarizer) — ce que FAIT un dépôt | décision à re-poser par rôle en v3.5 (un dépôt en zone batch ≠ zone travail) | `_new_item_card.html:59-68` |
| 10 | **Repli/dépli** : dépliage au clic en-tête, au focus/saisie du prompt (`data-nic-primary`), au survol drag ; `deployed=True` (imager seul) | le mécanisme qui répond à « l'espace du prompt » existe DÉJÀ ici | `wama/common/static/common/js/wama-new-item-card.js` |
| 11 | **RAG + fichiers de référence dans la pipeline de prompt** : hook RAG data-gaté (`rag=True`, « aucune app ne l'active à ce jour ») ; hook `reference_files` → compréhension de fichiers, no-op tant qu'aucune app ne déclare `reference_field` | les DEUX points d'accroche existent, 0 app branchée — le slot référence v3.5 a son hook serveur PRÊT | `wama/common/utils/prompt_pipeline.py` ; `wama/common/utils/app_metadata.py` |
| 12 | **Filemanager → card** : menu « Envoyer vers » (croise `input_extensions` × registre serveur des importeurs) + drag jstree (déplie la card repliée au survol) | **le payload n'a PAS de rôle** (`{path,name,mime}`) : le rôle est décidé côté serveur PAR EXTENSION (`import_to_imager` : txt⇒prompt_file, image⇒référence) ; avatarizer et composer n'ont AUCUN importeur (prompt-primaires) ; le vocabulaire de rôle EXISTE et n'est pas branché (`_ports_for_category` de `wama/common/utils/intake.py` rend « quel PORT de quelle app ») | `wama/filemanager/static/filemanager/js/filemanager.js` ; `wama/filemanager/views.py` |

#### Positions de conception (Claude, 2026-08-30 — à valider avec la spec v3.5)

- **Les zones par rôle se GÉNÈRENT des ports déclarés** — depuis le 30/08 les slots sont déclarés
  (`inputs[]` de domaine, `ROUTE §S2bis.6 (b)`) : la v3.5 n'invente pas ses zones, elle rend les
  ports (travail/référence/prompt + lot). Une zone par port, libellé du port, accept dérivé.
- **Le D&D par rôle = ajouter le PORT au contrat d'import** : côté menu, « Envoyer vers ‹app› ›
  ‹port› » servi par `_ports_for_category` (déjà écrit, aucun consommateur UI) ; côté événements,
  un champ `role` dans les payloads. Ça résorbe du même geste les deux trous mesurés : avatarizer
  et composer sans importeur (leur fichier est une RÉFÉRENCE — le contrat actuel ne sait pas le
  dire), et le rôle deviné par extension côté serveur.
- **L'espace du prompt** : le prompt est la cellule PRIMAIRE de la card brouillon des apps
  génératives ; elle grandit au focus (mécanisme `data-nic-primary` DÉJÀ acquis) + autosize (déjà
  dans `wama-prompt-enrich.js`) avec max-height. La règle « hauteur constante » vaut pour les
  onglets de MODALITÉ, pas pour l'édition du prompt : c'est la card entière qui se déploie, comme
  aujourd'hui. En mosaïque : tuile normale repliée, dépliage = passage temporaire pleine largeur.
- **⚙ + cycle : OUI, et les mécanismes existent** — ⚙ ouvre `WamaParams.settingsModal` sur les
  défauts persistés (`user_settings`) : exactement ce que les chips « Réglages » de la maquette
  affichent sans permettre de l'éditer ; le bouton de cycle suit son contrat d'états, INACTIF
  tant que les entrées requises manquent — le gate existe déjà (`wama-input-match.js`, gate de
  lancement + `onState`, piloté par l'imager). ⚠ Nuance à spécifier : pour les apps
  `depot_cree='cree'` le dépôt crée immédiatement — le ▶ de la card brouillon n'a de sens qu'en
  mode « attache » (ou devient « créer + démarrer » ce qui est déjà dans la barre batch).
- **Absorber les extra-zones par la DÉCLARATION, pas par un hook** : les 4 `extra_zone_template`
  sont le symptôme (aucun contrat, 4 natures) ; la v3.5 doit offrir les cases que ces zones
  comblaient — réglages rapides (miroir de N params déclarés), sélecteur de modèle (option de
  card déclarée), galerie (slot « actif visuel » déclaratif) — sinon les 4 apps resteront
  imprortables vers la v3.5.

### 11.9 SPEC card d'entrée v3.5 (PROPOSITION dérivée des exigences §11.8 — à valider par Fabien)

> Écrite le 2026-08-30 pour que le chantier ait sa cible AVANT l'itération de maquette. Rien
> d'implémenté. Pilote : `converter_01` (généré), puis confrontation aux 4 apps à extra-zones.

**A. La clé structurante — RÔLES en zones, MODALITÉS par zone.** La maquette actuelle aligne
des mini-onglets de modalité (📄 📚 🔗 🎙 🗂) À PLAT : c'est un axe unique là où il y en a deux.
La v3.5 les sépare :
- **une ZONE par RÔLE déclaré** (générée des ports : travail / référence(s) / prompt — plus
  le lot, qui est un rôle de la card, pas un port). Libellé du port, accept dérivé, chips des
  fichiers attachés (retirables, `WamaInputMatch`) ;
- **les MODALITÉS sont les gestes d'alimentation d'UNE zone** : dépôt/clic, dossier,
  médiathèque (filtrée par l'accept DU RÔLE — exigence 5), URL, filemanager (D&D par rôle —
  exigence 1). Chaque zone les offre ; plus de bouton global au rôle implicite ;
- ~~3 modalités transverses « parce qu'elles créent »~~ ⚠ **RECTIFIÉ par Fabien (30/08, 5ᵉ
  message) — la bonne classification est remplir / créer, et RIEN ne lance** :
  · le **MANIFESTE DE PROCESS remplit la card** (toutes zones + réglages) — modalité de
    remplissage, à ceci près qu'elle remplit la card ENTIÈRE et non une zone ; il ne lance
    jamais (doctrine « jamais d'apply auto », déjà actée) ;
  · le **LIVE 🎙 remplit aussi** — en **2 TEMPS explicites (décision Fabien)** : le clic
    AMORCE (card créée/armée, la preview guide : *« effectuez vos réglages, ou réglages par
    défaut, puis lancez »*) ; c'est **▶ qui démarre réellement** l'enregistrement et la
    transcription — l'utilisateur peut régler AVANT. Léger coût d'usage, gain d'explicite ;
  · seul le **LOT crée** (N cards) — et le fichier batch DE MANIFESTES crée N cards remplies.
  ⇒ **Règle unifiée qui en sort : toute modalité REMPLIT ou CRÉE, aucune ne LANCE — le
  lancement est toujours le 2ᵉ temps (▶), pour toutes les modalités sans exception.**

**B. Anatomie** = les 5 sections de toute card v3 : **Entrée** (les zones de rôle du A) ·
**Réglages** (chips des défauts persistés `user_settings` ; miroirs rapides DÉCLARÉS —
l'absorption des extra-zones, D) · **Sortie** (format attendu, ~ETA apprise) · **État**
(Brouillon) · **Actions** : **⚙** (modale des défauts — exigence 4) + **▶ cycle** (inactif
tant que les entrées REQUISES manquent — gate `WamaInputMatch`/`onState`, déjà piloté par
l'imager ; sur les apps `depot_cree='cree'` le dépôt en zone travail crée immédiatement, le ▶
du brouillon ne vit que sur les apps « attache »).

**C. Le prompt** (apps génératives) : cellule primaire, dépliage au focus (`data-nic-primary`
acquis) + autosize, max-height — la règle « hauteur constante » vaut pour les bascules de
modalité, pas pour l'édition (exigence 3). Slots NATIFS sous le prompt : chips de mots-clés
(`wama-prompt-chips`, plus jamais montées par l'app) et **déclencheur ✨ porté par la brique**
(`wama-prompt-enrich` gagne son bouton — ferme le défaut « attaché sans déclencheur »).

**D. Absorption des 4 extra-zones par la DÉCLARATION** (le risque de blocage mesuré §11.8) :
réglages rapides = liste de N params DÉCLARÉS `quick=True` (synthesizer voix/vitesse/titre) ;
sélecteur de modèle en card = option DÉCLARÉE (imager, avec Auto + `WamaModelHelp`) ; galerie
d'avatars = slot « actif visuel » déclaratif (modalité médiathèque spécialisée) ; aperçu voix
= affordance de preview de la zone référence. L'`extra_zone_template` reste le repli des
spécificités non déclarables — mais chacune de ces quatre a désormais une case.

**E. Génération** : `templates_gen` émet tout le A-D depuis ports + capabilities + params —
zéro littéral par app. Préalables DÉJÀ livrés le 30/08 : slots par domaine, émission du slot
référence, importeur filemanager des jumelles. Préalable RESTANT : le contrat d'import par
rôle (payload `role`, menu « Envoyer vers ‹app› › ‹port› » via `_ports_for_category`).

**F. Itération de maquette à faire AVANT le code** (skill frontend-design chargé à ce
moment-là) : zones de rôle + les 3 exemples manquants — card en ÉCHEC (due depuis §11), card
LIVE (REC pulsant + chrono dans la preview), card-modèle aux slots vides (file importée sans
fichiers, `ARCHITECTURE §8`).

### 11.10 CARD D'ENTRÉE v4 — la proposition (2026-08-30, demandée par Fabien : « une v4
prometteuse » ; les cards de FILE restent v1/v2/v3 — v4 ne nomme que la card d'entrée)

> Le problème posé : *« la difficulté n'est plus dans le fonctionnement mais dans la
> présentation avec toutes les modalités — rendre les choses limpides et explicites. »*
> La réponse v4 tient en une phrase : **une ligne par rôle, un seul geste, la détection fait
> le reste** — et on SUPPRIME les mini-onglets de modalité (l'étude v3.5-brouillon mélangeait
> les deux axes, cf. la rectification du A).

```
┌─ Nouvel élément ─────────────────────────────────────────────── ⌄ ─┐
│ [ Décrivez ce que vous voulez générer…                    ✨ ] 🏷   │  ← prompt (apps génér.)
│ Entrée                                                             │
│  🎞 Fichier de travail   ⟨glissez, cliquez… ou ✎⟩      📚 🔗 🗂 🎙  │  ← 1 LIGNE = 1 RÔLE
│  🎼 Mélodie (référence)  ⟨melodie_demo.mp3 ✕⟩          📚 🔗       │     = 1 vraie dropzone
│ Réglages  ⟨whisper l-v3⟩⟨fr⟩⟨diarisation⟩              Sortie ⟨.docx⟩⟨~ETA⟩ │
│ État  Brouillon — il manque : fichier de travail       [⚙] [▶ Lancer] │
└────────────────────────────────────────────────────────────────────┘
```

1. **Une SLOT-ROW par rôle déclaré** (générée du port) : la ligne EST la dropzone — libellé du
   port, chip du fichier attaché (✕ retirable) ou invite, et en bout de ligne les modalités DE
   CETTE zone en icônes discrètes : 📚 médiathèque (ouverte PRÉ-FILTRÉE par l'accept du rôle),
   🔗 URL, 🗂 dossier, 🎙 live (seulement sur la ligne travail des apps à capacité live). Le
   D&D filemanager a enfin une cible visuelle PAR PORT ; l'appariement teinte la ligne requise
   (ambre) / suggérée (cyan) — brique existante.
2. **Aucune affordance pour lot et manifeste** — c'est ça, la limpidité : on DÉPOSE sur la
   ligne travail, la détection structurelle reconnaît un fichier de lot ou un manifeste de
   process (mécanisme batch-detect existant, étendu) et ouvre le bandeau d'aperçu. Un geste
   unique, expliqué APRÈS coup par l'aperçu, plutôt que N boutons à comprendre AVANT.
3. **Deux temps partout** (règle du A) : la card d'entrée ne lance jamais rien. La ligne
   d'État dit toujours OÙ on en est et CE QUI MANQUE (« il manque : fichier de travail » /
   « armé 🎙 — réglez puis lancez » / « prêt ») ; ▶ est le seul lanceur, inactif tant qu'un
   requis manque.
4. **Une seule grammaire visuelle partout** : la même slot-row sert la section Entrée de la
   MODALE ⚙ et de l'inspecteur (exigence 8) et donc le REMPLACEMENT des fichiers d'une card
   PENDING (exigence 7), et la card-MODÈLE d'une file importée sans fichiers (slots vides =
   les mêmes lignes, invites actives). L'utilisateur n'apprend qu'un objet.
5. **Densités** : la card d'entrée suit v1/v2/v3 comme les autres (sections nommées) ; en
   Compact les slot-rows se condensent en chips sur une ligne.

⏳ Prochain geste : l'itération de MAQUETTE (F ci-dessus) rend cette proposition jugeable à
l'œil — c'est elle qui vaut validation, pas ce texte.

#### Défauts SILENCIEUX relevés par le balayage (à corriger indépendamment de la v3.5)

1. `wama/filemanager/static/filemanager/js/filemanager.js:1780` route l'imager vers l'événement
   `filemanager:filedrop`… **qu'aucun JS de l'imager n'écoute** (seuls avatarizer et
   cam_analyzer ont un listener) : glisser un fichier du filemanager vers la card imager ne fait
   RIEN, sans un mot.
2. `WamaPromptEnrich` attaché sans déclencheur chez composer et anonymizer (le ✨ n'existe que
   chez l'imager, fabriqué par l'app) — soit la brique gagne son bouton, soit ces attaches sont
   décoratives.
3. La barre batch commune est mono-instance par construction (ids fixes) — le clone audio de
   l'enhancer en découle ; une v3.5 par rôle devra la paramétrer par instance.
