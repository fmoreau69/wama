# MODES_QUEUE_UX.md — Vision unificatrice : file unique pilotée par MODES (générée par description)

> **Décision (Fabien, 2026-06).** Unifier et épurer l'UX de file de WAMA autour de **deux idées** :
> (1) **une seule surface** = la file, terminée par une **card « nouveau » persistante** ;
> (2) **le MODE comme norme applicative** (couche d'abstraction) → l'UI se **génère depuis la
> description des modes**. **On ne réinvente rien** : on réutilise tout l'existant + on ajoute la couche MODE.
>
> Complète : `CARD_DESIGN.md` (formalisme de card), `WAMA_APP_CONVENTIONS.md §22` (inspecteur volet droit
> GLOBAL), `GENERALIZATION_PLAN.md` (axes). Philosophie : `CLAUDE.md §Philosophie` (métadonnée-driven).

## 1. Une seule surface : la file + card « nouveau » persistante
- Plus de 3 surfaces (temps-réel + import-card + card-orange-config). **UNE file**, terminée par une
  **card « nouveau »** (pointillés, **contour gris = en attente d'entrée**) suivant la **géométrie
  courante** (ligne/mosaïque, cf. CARD_DESIGN §4).
- Point d'entrée unique : **glisser des fichiers** dessus OU **cliquer** pour configurer. La card
  « nouveau » EST l'import + la config.
- « File d'attente » + **compteur d'éléments** → **à côté du titre d'onglet** (visible même en
  console/à-propos/aide). Zéro répétition du label.

## 2. Code couleur « feux tricolores » (contour + opacité)
| État | Contour | Opacité |
|------|---------|---------|
| Card « nouveau » (vide) | **gris pointillés** | — |
| Config / en attente de lancement / **en cours** | **orange** | pulse pendant le process (comme Transcriber) |
| Terminé | **vert** | plein |
| Échoué | **rouge** | plein |

(À affiner : distinguer *config* de *running* par l'opacité/pulse plutôt qu'une 4ᵉ couleur → lisibilité.)

## 3. Le MODE = norme applicative (LA couche d'abstraction ajoutée)
- Chaque app **déclare ses modes** en métadonnée :
  `modes = [{id, label, icône, temps_réel?, entrées:[prompt|fichiers|références|url], sections_réglages:[…], capacités}]`.
- Exemples : Anonymizer `[yolo, sam3]` · Imager `[prompt, edit, style, (2D→3D)]` ·
  Transcriber/Synthesizer `[normal, temps_réel]`.
- **L'UI se génère depuis ces descriptions** (sélecteur de mode + champs d'entrée + sections de réglages),
  comme `WamaAutofill` génère l'inspecteur. **Zéro spécificité hardcodée** au-delà de la description.
- **Faire évoluer une app = décrire un mode** (ex. Imager 2D→3D) sans code UI neuf. (2D→3D : mode si la
  sortie 3D peut être décrite + un visualiseur 3D ; sinon nouvelle app — à trancher, cf. `MEDIA`/3D.)

## 4. Clic sur la card « nouveau » → modale + inspecteur EN SYNC
- Clic → card **orange** (config) ; **modale** + **inspecteur** (volet droit GLOBAL) affichent **les mêmes
  infos** (mode **simple/avancé cohérent**).
- Contenu **généré depuis le mode** : switch de mode + entrées (prompt/fichiers/références/url selon le
  mode) + réglages (modèle, options, format de sortie) en **sections distinctes**. Modale = config
  focalisée (mobile-friendly) ; inspecteur = miroir desktop ; les deux **éditent, synchronisés**.

## 5. Temps réel = un MODE (pas un onglet)
- Devient le **mode « temps réel »** d'une app qui le déclare → intégré au switch, **généré par
  description**, homogène. Card **unitaire**.
- Flux : `entrée (prompt / bouton Speak) → réglages ↔ preview live → [Ajouter à la file]`.
  Sous-états : **test** (preview seul, pour régler) → **ajout file** (devient card normale).
- Synthesizer (prompt→réglages↔preview→file) · Transcriber (Speak→preview→file).

## Ce qu'on RÉUTILISE (on ne réinvente rien)
Card formalism (`CARD_DESIGN.md`) · inspecteur **global** (§22) · `WamaAutofill` (description→UI) ·
capacités d'app · **switches de mode existants** (anonymizer yolo/sam3, imager) · **temps réel existant**
(Speak) · batch + manipulation directe · contrat backend. **Ajout unique = la couche MODE** (schéma
déclaratif + générateur d'UI `WamaModes`).

## Plan d'implémentation (importance × déblocage × difficulté)

| Phase | Quoi | Ordre / pourquoi | Difficulté |
|-------|------|------------------|------------|
| **0** ✅ | Fondations (CARD_DESIGN, inspecteur global, WamaAutofill, capacités, contrat backend) | posées | — |
| **P1 — clé de voûte** | Schéma `app_metadata.modes` + cartographie des modes existants + générateur commun `WamaModes` (étend WamaAutofill) | **débloque P2-P6** ; déclaratif | moyenne, risque faible |
| **P2 — le + visible** | File unique + card « nouveau » persistante + code couleur + compteur sur l'onglet (1 app réf) | gain UX immédiat | moyenne |
| **P3 — cœur** | Config générée par mode (modale ↔ inspecteur en sync, sections distinctes, simple/avancé) | file pilotée par description | moyenne-haute |
| **P4** | Temps réel = mode (migrer Speak transcriber/synthesizer) | homogénéise, -1 surface | moyenne |
| **P5** | Détails card (concis↔étendu, drag/batch, filtre/tri, mosaïque) — cf. CARD_DESIGN | confort, incrémental | variable |
| **P6 — payoff** | Évolutivité par description (prouver : ajouter un mode, ex. Imager 2D→3D) | la promesse réalisée | faible une fois P1-3 |

**Prérequis transverse (tôt, P1-P2)** : **séparer le volet droit du filemanager** (roadmap) → l'inspecteur
vit dans le volet droit GLOBAL, pas embarqué dans le filemanager.

## 6. Unification avec la MÉTA-APP (chaînage graphique) — anticiper dès maintenant

> **Insight magique** : **la card est un composant universel ; la FILE = une méta-app à UNE app, rendue
> en liste.** On construit la card (unitaire ↔ batch-empilé, concis↔étendu, feux tricolores, actions) +
> la file **une fois** ; la méta-app **réutilise le même composant**, en ajoutant canvas + connecteurs +
> nœuds-app. Les deux chantiers **convergent** → ne pas réinventer.

- **File** = N cards d'entrée alimentant **UNE app implicite** (l'app courante), en liste. Référence =
  param au niveau batch ou card (héritage §9.9, cf. CARD_DESIGN §3ter).
- **Méta-app** = les **mêmes** cards sur un **canvas**, avec **connecteurs** (ports), alimentant des
  **nœuds-app explicites**. Un nœud-app = un nœud card-like avec **ports d'entrée typés**
  (travail / référence / prompt / url) + un port de sortie (→ nœud suivant).
- **Typage par CONNEXION (on retire la notion de « type de card »)** : le rôle d'une card = le **port
  auquel elle est connectée**. Card **batch** → port « travail » (multi) ; card **unitaire** → port
  « référence » (mono). La référence s'applique batch-level ou card-level — **comme dans la file**.
- **Le batch empilé se désempile au clic** dans le canvas aussi (même composant, Solution 1).

**Stratégie de validation (Fabien)** : **aller au bout sur 1 app + lancer la méta-app AVANT de
généraliser** → valide le **composant card** ET le **modèle de connecteurs** sur du réel (comme on a
validé le contrat backend sur 1 app avant le rollout). Ensuite seulement, propager à toutes les apps.

**App de référence = IMAGER** (Fabien) : le plus de **modes** (prompt/edit/style…, appelée à en gagner
dont 2D→3D), et **point dur d'harmonisation** de longue date → si on la résout avec la méta-app + le
**Synthesizer** (mode temps réel), on tient la méthode pour **finir l'harmonisation des apps généralistes**.
Cible de fin d'harmonisation : **Imager (réf) + méta-app + Synthesizer (temps réel)**.
