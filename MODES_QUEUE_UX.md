# MODES_QUEUE_UX.md — Vision unificatrice : file unique pilotée par MODES (générée par description)

> **Décision (Fabien, 2026-06).** Unifier et épurer l'UX de file de WAMA autour de **deux idées** :
> (1) **une seule surface** = la file, terminée par une **card « nouveau » persistante** ;
> (2) **le MODE comme norme applicative** (couche d'abstraction) → l'UI se **génère depuis la
> description des modes**. **On ne réinvente rien** : on réutilise tout l'existant + on ajoute la couche MODE.
>
> Complète : `CARD_DESIGN.md` (formalisme de card), `WAMA_APP_CONVENTIONS.md §22` (inspecteur volet droit
> GLOBAL), `WAMA_APP_GENERATION_ROUTE.md` (axes — ex-GENERALIZATION_PLAN, archivé). Philosophie : `CLAUDE.md §Philosophie` (métadonnée-driven).

## 1. Une seule surface : la file + card « nouveau » persistante
- Plus de 3 surfaces (temps-réel + import-card + card-orange-config). **UNE file**, terminée par une
  **card « nouveau »** (pointillés, **contour gris = en attente d'entrée**) suivant la **géométrie
  courante** (ligne/mosaïque, cf. CARD_DESIGN §4).
- Point d'entrée unique : **glisser des fichiers** dessus OU **cliquer** pour configurer. La card
  « nouveau » EST l'import + la config.
- « File d'attente » + **compteur d'éléments** → **à côté du titre d'onglet** (visible même en
  console/à-propos/aide). Zéro répétition du label.

## 2. Code couleur « feux tricolores » → source unique : `CARD_DESIGN.md §8.5`

> **Table supprimée le 2026-08-27** — trois copies du tricolore avaient divergé entre les deux
> docs. La source unique est **`CARD_DESIGN.md §8.5`** : gris=brouillon · orange=en cours ·
> vert=fini · rouge=échec, **pas d'état « config » distinct** (ce qui tranche aussi le « à
> affiner » qui vivait ici). Spécificité conservée d'ici : la card « nouveau » vide se dessine en
> **gris pointillés**, et le pulse d'opacité marque le process.

## 2bis. DEUX niveaux : Domaine (onglet) → Mode (switch) — ne pas confondre les axes

Question (Fabien) : faut-il un niveau au-DESSUS des modes, en **onglets** ? **Oui — mais c'est un axe
distinct.** Il y a **deux axes** à ne pas mélanger :

1. **Domaine** = un **WORKFLOW distinct**. → **vrai niveau utilisateur = ONGLET**.

   ⚠⚠ **CORRIGÉ LE 2026-08-23 — ce n'est PAS « le type d'entrée/sortie ».** Cette formulation
   initiale a produit deux erreurs de modélisation opposées, mesurées le même jour :
   - le **converter** déclarait **5 domaines** = ses 5 natures d'entrée, et ne rendait AUCUN
     onglet (aucun `WamaModes` dans son gabarit). Il ne doit pas en rendre : l'utilisateur y
     dépose n'importe quel fichier, le type est **détecté**, les réglages s'adaptent. Cinq
     onglets lui feraient classer son fichier à la main — un travail que la machine fait mieux ;
   - le **describer** ne déclarait AUCUN domaine alors qu'il en a bien un (« décrire »),
     simplement mono — donc rien à nommer, rien à porter au DOM.

   **Le critère qui tranche : le domaine se justifie quand la surface de RÉGLAGES et le workflow
   divergent, pas quand la nature du fichier diverge.** Décrire une image, un PDF ou un audio se
   règle pareil (style, langue, longueur) → **un** domaine. Produire une image ou une vidéo n'a
   ni les mêmes réglages ni le même moteur → **deux** domaines.

   Deux faits mesurés le confirment : le **transcriber** a un domaine `audio` qui accepte aussi
   la **vidéo** (source audio), et les domaines `image`/`video` de l'**imager** acceptent tous
   deux `text`+`image` — leur nom dit la **SORTIE**, pas l'entrée.

   **Corollaires actés (arbitrages Fabien, 2026-08-23) :**
   - **Toujours déclaré et NOMMÉ, même seul** — jamais de `default` implicite : le jour d'un
     second domaine on aurait `default` + `audio` + `document`, et le nommage perdrait sa
     cohérence pour toujours.
   - **Nommage** : mono-domaine → le workflow (`conversion`, `description`, `lecture`) ;
     multi-domaines → l'axe qui les sépare, le plus souvent les catégories média jointes par `_`.
     **`image_video`** et non `media` (qui englobe l'audio) ni `visuel` (la 3D, les documents et
     le texte le sont aussi). Raison structurelle : le nom est **composé de la taxonomie**, donc
     il EST la liste `accepts` — dérivable, vérifiable, jamais à re-débattre.
   - **`accepts`** déclare les catégories média (`MEDIA_CATEGORIES`) que le domaine prend en
     ENTRÉE. C'est la base du **routage automatique** d'un fichier déposé vers le bon domaine
     (`domain_for_category()`), que chaque app refait aujourd'hui à la main.
2. **Mode** = la façon de produire **dans** un domaine (texte→image, image→image, yolo/sam3). Vit **dans**
   le domaine.

→ Hiérarchie : **App → Domaine (onglet) → Mode (switch) → Entrées + Réglages (générés)**.

- **Métadonnée-driven** : l'app déclare `domains=[…]`, chaque domaine a ses `modes`. Onglets générés depuis
  `domains`, switch depuis `domain.modes`. Zéro code par app.
- **Niveau domaine CONDITIONNEL** : onglets seulement si **>1 domaine**. Mono-domaine (transcriber,
  synthesizer, reader, describer, composer) → pas d'onglet, directement les modes.
- La **file est scopée par le domaine actif** (cf. enhancer : file image/vidéo + file audio déjà en onglets).
- **⚠️ Piège avatarizer** : `pipeline / standalone` n'est **PAS un domaine** — c'est un axe **WORKFLOW** →
  se résout par la **méta-app** (pipeline = chaînage ; standalone = mode normal). NE PAS le modéliser en
  onglet-domaine. → ✅ **SOLDÉ le 2026-08-23** : le mode `standalone` a été PURGÉ (résidu de l'époque à
  deux modes TTS→audio→avatar ; le TTS relève du synthesizer depuis le 2026-07-15). Avatarizer est
  mono-domaine `avatar`, `modes: []`.

- **⚠️ UN MODE EST UN SWITCH — donc `[]` quand il n'y a pas de variante.** Un mode ne se déclare que si
  l'UTILISATEUR a un choix à faire ; `wama-modes.js` ne rend le groupe de boutons que
  `if (modes.length > 1)`. Déclarer un mode unique n'affiche donc **rien** : c'est de la taxonomie morte.
  Purgés le 2026-08-23 : `standalone` (avatarizer), `convert` répété 5 fois (converter), et **les 7 modes
  de l'imager**.

- **⚠️⚠️ NE PAS CONFONDRE MODE D'UI ET WORKFLOW DE BACKEND.** L'imager choisit txt2img / img2img /
  style2img d'après les entrées fournies et les réglages : c'est une décision de **moteur**, prise sans
  switch à l'écran (une seule card d'entrée par domaine + appariement bidirectionnel `WamaInputMatch`).
  Ces 7 « modes » sont restés déclarés longtemps après le retrait des switches, et le JS qui les rendait
  visait **quatre ancres DOM supprimées** — 36 lignes mortes, sans erreur ni trace. Leçon :
  **ce qui ne plante pas ne se signale pas.**
  **2ᵉ application (2026-08-28, validation Fabien) : le pipeline TTS→avatar de l'avatarizer.**
  Rejeté comme MODE en 2026-07-11 (« le pipeline = composition studio »), il revient en WORKFLOW
  DÉRIVÉ : la card accepte audio, URL ou texte à dire, et le serveur dérive — règle UNIQUE aux
  trois points d'écriture (`create`, ligne de batch, tool_api) : **l'audio (matériau explicite)
  prime, sinon le texte déclenche TTS→animation**. Zéro switch ; l'étape TTS est EMPRUNTÉE
  (brique `common/tts/service_client.py` + voix `resolve_speaker_wav` du synthesizer), l'audio
  généré est PERSISTÉ dans `audio_input` (artefact vérifiable, ré-exécutable) ; la composition
  studio Synthesizer→Avatarizer reste valable pour l'orchestration visible.

- **État au 2026-08-23** : seules **3 apps ont de vrais modes** — anonymizer (yolo/sam3), synthesizer et
  transcriber (normal/temps réel) — et toutes trois les rendent **depuis la déclaration**. Anonymizer a
  été la dernière branchée : elle déclarait ses modes ET les rendait à la main (deux sources non reliées).

## 3. Le MODE = norme applicative (LA couche d'abstraction ajoutée)
- Chaque app **déclare ses modes** en métadonnée :
  `modes = [{id, label, icône, temps_réel?, entrées:[prompt|fichiers|références|url], sections_réglages:[…], capacités}]`.
- Exemples : Anonymizer `[yolo, sam3]` · Imager `[prompt, edit, style, (2D→3D)]` ·
  Transcriber/Synthesizer `[normal, temps_réel]`.
- **L'UI se génère depuis ces descriptions** (sélecteur de mode + champs d'entrée + sections de réglages),
  comme `WamaDetails` génère l'inspecteur. **Zéro spécificité hardcodée** au-delà de la description.
- **Sources d'une entrée fichier = upload OU MÉDIATHÈQUE (déjà en place, composé auto)** : brique commune
  **`MediaPicker`** (`common/js/media-picker.js` + endpoint `media_library:api_list`) ouvre une modale
  filtrée par `asset_type` et renvoie un **`File`** (drop-in de l'upload). Déjà consommée par imager/
  synthesizer/composer/avatarizer. `WamaModes` ajoute **automatiquement** un bouton « médiathèque » sur
  tout champ fichier (filtré par son `accept`). Zéro code par app. (3ᵉ source : `url`.) Ex. style
  transfert : image de référence = upload **ou** médiathèque.
- **Faire évoluer une app = décrire un mode** (ex. Imager 2D→3D) sans code UI neuf. (2D→3D : mode si la
  sortie 3D peut être décrite + un visualiseur 3D ; sinon nouvelle app — à trancher, cf. `MEDIA`/3D.)

## 4. Clic sur la card « nouveau » → modale + inspecteur EN SYNC
- Clic → card **orange** (config) ; **modale** + **inspecteur** (volet droit GLOBAL) affichent **les mêmes
  infos** (mode **simple/avancé cohérent**).
- Contenu **généré depuis le mode** : switch de mode + entrées (prompt/fichiers/références/url selon le
  mode) + réglages (modèle, options, format de sortie) en **sections distinctes**. Modale = config
  focalisée (mobile-friendly) ; inspecteur = miroir desktop ; les deux **éditent, synchronisés**.

## 5. Temps réel = un MODE (pas un onglet)

> ⚠ **SUPERSEDED — tranché AUTREMENT dans le code commun (confirmé Fabien 2026-07-25)** : le temps
> réel n'est PAS un mode ; c'est une **affordance de la card d'entrée** (`show_live` de
> `_new_item_card`, Speak transcriber). Cf. `REMOVAL_LEDGER F6` + `TRANSCRIBER_REFERENCE_AUDIT §1`.
> Le P4 du plan ci-dessous est donc caduc. Section conservée comme historique du raisonnement.
- Devient le **mode « temps réel »** d'une app qui le déclare → intégré au switch, **généré par
  description**, homogène. Card **unitaire**.
- Flux : `entrée (prompt / bouton Speak) → réglages ↔ preview live → [Ajouter à la file]`.
  Sous-états : **test** (preview seul, pour régler) → **ajout file** (devient card normale).
- Synthesizer (prompt→réglages↔preview→file) · Transcriber (Speak→preview→file).

## Ce qu'on RÉUTILISE (on ne réinvente rien)
Card formalism (`CARD_DESIGN.md`) · inspecteur **global** (§22) · `WamaDetails` (description→UI) ·
capacités d'app · **switches de mode existants** (anonymizer yolo/sam3, imager) · **temps réel existant**
(Speak) · batch + manipulation directe · contrat backend. **Ajout unique = la couche MODE** (schéma
déclaratif + générateur d'UI `WamaModes`).

## Plan d'implémentation (importance × déblocage × difficulté)

| Phase | Quoi | Ordre / pourquoi | Difficulté |
|-------|------|------------------|------------|
| **0** ✅ | Fondations (CARD_DESIGN, inspecteur global, WamaDetails, capacités, contrat backend) | posées | — |
| **P1** ✅ | Schéma `app_metadata.modes` (`common/utils/app_modes.py`) + générateur commun `WamaModes` (`wama-modes.js`, étend WamaDetails) — **fait et câblé** (imager, composer, studio, endpoint `/common/api/app-modes/<app>/`) ; vérifié 2026-07-09, corrige le retard de ce doc sur le code | **débloque P2-P6** ; déclaratif | moyenne, risque faible |
| **P2** ✅ | File unique + card « nouveau » persistante + code couleur — **fait et généralisé** : briques `common/_new_item_card.html` + `common/_queue_entry.html`, **9 files sur 9** (relevé 2026-08-27, cf. commit « l'entrée de file adoptée par l'avatarizer »). Reste le **compteur sur l'onglet** | gain UX immédiat | — |
| **P3 — cœur** | Config générée par mode (modale ↔ inspecteur en sync, sections distinctes, simple/avancé) | file pilotée par description | moyenne-haute |
| **P4** | Temps réel = mode (migrer Speak transcriber/synthesizer) | homogénéise, -1 surface | moyenne |
| **P5** | Détails card (concis↔étendu, drag/batch, filtre/tri, mosaïque) — cf. CARD_DESIGN | confort, incrémental | variable |
| **P6 — payoff** | Évolutivité par description (prouver : ajouter un mode, ex. Imager 2D→3D) | la promesse réalisée | faible une fois P1-3 |

**Prérequis transverse (tôt, P1-P2)** : **séparer le volet droit du filemanager** (roadmap) → l'inspecteur
vit dans le volet droit GLOBAL, pas embarqué dans le filemanager.

## 7. Horizon : une app = un MANIFESTE (auto-génération sur description)

Culmination de toutes les briques métadonnée-driven : **déclarer une app = remplir des schémas**, la couche
commune **génère** l'UI, la file, l'inspecteur, l'API outil, les tests.

| Préoccupation | Déclaratif via | Génère |
|---|---|---|
| Domaines / modes / entrées | `app_modes.py` (P1) | onglets + switch + champs (WamaModes) |
| Réglages par mode | `param_schema.py` (à brancher) | inspecteur + modale |
| Inspecteur | `WamaDetails` | volet droit |
| Backend (cycle de vie + deps) | `BaseModelBackend` | load/unload + install libs |
| Card / file | CARD_DESIGN → brique commune | queue + cards |
| Exposition assistant | `tool_api` | outil chat |
| Tests | charpente nocturne | scénarios |

→ **Code app-spécifique restant = `process()` (l'inférence)** + (voir ci-dessous) les **pages d'édition
dédiées**. L'assistant IA pourra **générer le manifeste depuis une description** (« app qui fait X »),
la prospection trouve le modèle → l'app **se génère** (auto-génération sur description, sans hardcoding).

### ⚠️ Garde-fou (Fabien) : les PAGES D'ÉDITION dédiées ne se réduisent PAS au manifeste
Certaines apps ont une **surface de « deep work »** app-spécifique, qui s'ajoutera progressivement :
- Transcriber : **correction manuelle assistée IA** (fait). Anonymizer/Imager : dessin de masque / inpaint.
  Avatarizer : timeline lip-sync. 3D (futur) : visualiseur/éditeur.
- **Mais bâties sur briques communes** (le transcriber a extrait `WamaInspector`, lecteur audio, onde,
  garde clavier, timecode) → seule la **logique d'édition vraiment spécifique** est bespoke.
- **Intégrées au manifeste comme CAPACITÉ** : `capabilities.edit_page = {route, label, icon}` → la couche
  commune affiche un **bouton « Éditer » générique** (card/inspecteur) quand déclaré. Le manifeste déclare
  l'EXISTENCE + le point d'entrée ; l'app fournit la page.

→ **Modèle affiné** : *code app-spécifique = `process()` + pages d'édition dédiées (déclarées en capacité,
sur briques communes)* ; tout le reste se génère.

## 5bis. Cartographie domaines → modes → SOURCE VIVANTE : `wama/common/utils/app_modes.py`

> **Table supprimée le 2026-08-27** — elle contredisait le §2bis du même document : les modes
> qu'elle prêtait à imager/avatarizer/reader/composer ont été **purgés** le 2026-08-23
> (`app_modes.py` les déclare `'modes': []`, avec le pourquoi commenté ligne à ligne — « quatre
> ancres qui n'existent plus dans le DOM », « backend/langue sont des PARAMS, pas des modes »).
> **Lire la déclaration, pas une copie.** Seule information sans source machine, conservée :
> l'axe *Workflow → méta-app* — synthesizer/transcriber sont pipeline-ready ; le pipeline de
> l'avatarizer (TTS→lip-sync) **est** la méta-app (studio), pas un mode.
>
> ⚠ Tension ouverte (relevée 27/08, non tranchée) : `app_modes.py` déclare encore un mode
> `realtime` pour synthesizer/transcriber alors que §5 le requalifie en **affordance
> `show_live`** de la card d'entrée — deux sections ne peuvent pas avoir raison ensemble ;
> à trancher avec Fabien avant tout code qui s'appuierait sur l'un ou l'autre.
> **MAJ 2026-08-30** : la question est revenue par la card v3.5 (Fabien : « un champ temps réel
> au-dessus de la file ? dans la card d'entrée ? ») — cadre de résolution proposé et consigné à
> `CARD_DESIGN.md §11.8` exigence 6 : modalité 🎙 de la card, session live DANS la card
> brouillon, et un drapeau de DOMAINE `live` qui remplacerait les deux modes `realtime`
> (fermant cette tension). Toujours réservé à l'arbitrage de Fabien.

**Lecture** : axe **domaine (onglet)** = Imager/Enhancer/Anonymizer (multi-domaine) uniquement ; axe
**temps réel** (mode) = Synthesizer/Transcriber/Avatarizer ; axe **pipeline/standalone** = transversal
(via tool_api) = le **workflow méta-app**, à NE PAS modéliser en domaine. → valide les **3 axes distincts**
(domaine / mode / workflow).

## 5ter. Promotion fille ↔ mère des réglages (décidé 2026-08-25 — venu du monde Data, bénéfice COMMUN) ⏳

> Origine : l'UI du monde Data (`WAMA_DATA_WORLD.md §11.8 ③`) — transposer le « trip de référence »
> de BIND_GUI **sans créer de card marquée**. Le mécanisme vaut pour TOUTES les files, Médias compris
> (régler une card, puis appliquer au batch).

- **Existant (rappel)** : les paramètres de la card mère s'appliquent à toutes les filles, SAUF si
  un paramètre a été modifié individuellement sur une fille (l'override la détache).
- **À ajouter — deux gestes symétriques** :
  - **↑ promouvoir** : depuis une card fille, faire remonter SES réglages à la mère, qui les
    applique à tout le batch ;
  - **↓ réaligner** : depuis la mère, réaligner toutes les filles (effacer les overrides).
- **Conséquences** : n'importe quelle card peut servir de référence ; on peut régler PLUSIEURS
  filles en parallèle (comparaison A/B) puis promouvoir la gagnante.
- ⚠ **Charge utile DÉCLARÉE, pas codée en dur** : monde Médias = le dict de paramètres ; monde
  Data = le **protocole** accumulé sur la card (`WAMA_DATA_WORLD §9undecies`), qui subsume les
  paramètres. Même geste, deux payloads — une capacité d'app, pas deux mécanismes.
- ⚠ **Garde-fou à la promotion (Data)** : promouvoir exige que chaque fille porte les données
  requises (entrées typées de la fonction ⊆ ∩ des catalogues des filles) — et le refus **dit
  quelle fille manque de quoi**, jamais un grisage muet.

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
