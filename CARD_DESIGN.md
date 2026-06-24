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

## 3bis. Manipulation directe de la file : réorganiser, batcher, filtrer/trier

> Expression la plus **intuitive du modèle batch unifié** (batch-of-1 ↔ batch-of-N) : glisser une card
> sur une autre → forme un batch ; la sortir → redevient autonome. Briques **déjà existantes** → surtout
> de l'UI + des endpoints fins.

- **Réordonner** (drag) : **SortableJS** ; persiste `row_index` (champ déjà présent sur les items de batch).
- **Glisser DANS un batch** = `consolidate_into_batch` ; **glisser HORS** = `_unwrap` (ops existantes).
  Endpoints fins : `reorder`, `move_to_batch`, `remove_from_batch`.
- **Filtrer / trier** : barre d'outils de file (statut / date / nom / type / durée), préférence persistée.
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

Lié : `WAMA_APP_CONVENTIONS.md` (§boutons, §22 inspecteur), `GENERALIZATION_PLAN.md` (axe B), `COMMON_REFACTORING.md`.
