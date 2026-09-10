# INPUT_MODEL_MATCHING.md — Card d'entrée ↔ modèles : le mécanisme d'appariement

> **Le nœud (Fabien, 2026-07-03)** : la card d'entrée doit porter TOUTES les entrées possibles de
> l'app (prompt — vide = génération aléatoire —, fichiers batch, fichier de référence, médiathèque).
> Question stratégique : le CHOIX DU MODÈLE pilote-t-il les entrées affichées, ou les ENTRÉES
> FOURNIES filtrent-elles les modèles ? Exigences : global (toutes apps + studio), naturel, guidé
> sans bloquer, réversible et COMPRÉHENSIBLE (retirer la référence doit visiblement « rouvrir »
> les modèles).

## 1. Ce que font les meilleures apps du domaine (état de l'art)

| App | Pattern |
|---|---|
| **Suno / Udio** (musique) | UNE box de composition ; **ajouter un audio** (cover/extend) **reconfigure les options** — l'entrée pilote. L'audio ajouté = vignette retirable. |
| **Midjourney** | prompt + refs d'images GLISSÉES = enrichissement ; le « modèle » (version) est un réglage séparé jamais bloquant. |
| **Kling / Pika / Runway** (vidéo) | déposer une image **bascule automatiquement** en image-to-video, avec feedback visible du mode. Entrée-d'abord. |
| **ComfyUI** (nœuds) | **typage par connexion** : brancher un type d'entrée filtre les nœuds compatibles — exactement le choix déjà acté pour le studio WAMA. |
| **ChatGPT / Claude** (pièces jointes) | on attache n'importe quoi, le système s'adapte ; les capacités gatent les traitements. |
| **Canva / CapCut** | partir de l'asset → les outils proposés se filtrent. |

**Constat** : l'industrie a convergé vers **« entrée-d'abord »** (*bring your stuff, the tool adapts*),
MAIS jamais en **cachant** les options — en les **désactivant avec explication**.

## 2. LA DÉCISION : bidirectionnel, ancré entrée-d'abord

Ni (A) pur ni (B) pur — les deux directions se rencontrent, avec une dominante :

### Direction principale — les ENTRÉES filtrent les modèles (B)
- Chaque entrée fournie apparaît en **CHIP retirable** (vignette + ✕) dans la card.
- Un modèle incompatible avec les entrées fournies n'est **PAS caché** : il est **désactivé avec la
  raison** (option grisée + tooltip « Incompatible avec votre fichier de référence »).
- Une ligne d'état explicite la causalité : *« 3 modèles désactivés par la mélodie de référence —
  retirez-la (✕) pour les retrouver »* → **réversibilité comprise d'un coup d'œil**.

### Direction complémentaire — le MODÈLE éclaire les entrées (A)
- Sélectionner un modèle qui **attend** une entrée (Melody → mélodie) ne bloque pas : le **slot
  correspondant s'allume** (badge « requis »/« recommandé », pulse discret) avec le texte déclaré
  (« Ce modèle suit une mélodie de référence — ajoutez un audio »).
- Le lancement sans l'entrée requise = bouton désactivé avec la raison (jamais d'échec silencieux).

### Invariants UX (les garde-fous du « guidé sans bloquer »)
1. **Ne jamais cacher, désactiver + expliquer** (statut visible, pas d'impasse).
2. **Cause → effet visible** : chaque restriction pointe l'entrée qui la cause ; le ✕ de la chip
   est l'annulation évidente.
3. **Divulgation progressive** : la card montre les *affordances* (prompt, + fichier, référence,
   médiathèque) légères — pas tous les champs conditionnels dépliés.
4. **Prompt vide = explicite** : placeholder « Vide = génération aléatoire (le modèle improvise) ».

## 3. Architecture déclarative (globale — rien par app)

Tout existe déjà en germe ; il manque UNE couche d'appariement :

| Élément | Où (existant) | Ajout |
|---|---|---|
| **Slots d'entrée** d'une app | `APP_MODES` + `INPUT_TYPES` (ports work/reference/prompt — déjà consommés par `studio_node_ports`) | déclarer composer (prompt, batch, `reference_melody`: accept audio, port reference) |
| **Besoins des modèles** | `AIModel.capabilities` (canonique) | nouveau vocabulaire : `inputs_required` / `inputs_optional` (ids d'INPUT_TYPES). Ex. musicgen-melody : `inputs_optional: ['reference_melody']`… ou `required` selon le comportement réel |
| **Rendu des slots** | `_new_item_card` | slot « référence » paramétrable (chip + accept + médiathèque) |
| **Appariement** | — | **nouvelle brique `wama-input-match.js`** : état = {entrées fournies} × {modèle choisi} → désactive/raisonne les options (extension du pattern `WamaModelCaps`), allume les slots, gère la ligne d'état |
| Studio | `studio_node_ports` (typage par connexion) | consomme les MÊMES déclarations — cohérence card ↔ nœud garantie |

**Chaîne** : INPUT_TYPES/APP_MODES (slots) + capabilities (besoins) → `wama-input-match` (logique) →
card commune + select modèle (surfaces). Zéro hardcode par app ; composer = pilote.

## 4. Plan d'implémentation (pilote composer)
1. Vocabulaire : `inputs_required/optional` ajoutés à `CANONICAL_CAPABILITIES` + déclarés sur les
   4 modèles composer (melody seul avec référence). `INPUT_TYPES` += `reference_melody`.
2. `APP_MODES['composer']` déclaré (slots : prompt, batch_file, reference_melody).
3. `_new_item_card` : slot référence (chip/accept/médiathèque) piloté par paramètre.
4. Brique `wama-input-match.js` (désactiver+raison, allumer slot, ligne d'état, réversibilité).
5. Composer : retirer le `melodyGroup` hardcodé du volet (remplacé par le slot de card déclaré) —
   la « disparition » actuelle devient sans objet.
6. Étendre : imager (image de référence img2img — même mécanique), puis studio (mêmes ports).

## 5. État mesuré (2026-08-17 — adoption SOLDÉE)

| Surface | État |
|---|---|
| `wama-input-match.js` | ✅ commune ; **crochets déclaratifs de slot non-fichier** (`isProvided`/`describe`/`clear`, 17/08 — 1er cas : voix clonée du synthesizer choisie dans un `<select>`) |
| **Côté serveur** | ✅ brique `common/utils/input_match.py` (17/08) : `input_match_meta(source, key=)` (meta du CATALOGUE par `AIModel.source`, re-clé par app), `auto_entry()` (pseudo-choix « auto »), `input_labels()` — extraite de composer/imager au moment de l'adoption ×7 |
| Brique **câblée** (grille `input_match_ui`) | ✅ **8/8 applicables** : composer, imager, synthesizer (grisage RÉEL : voix clonée → bark/kokoro grisés + chip ✕), enhancer (2 selects, un par domaine), transcriber, reader, anonymizer (+ converter N/A sans moteur IA) |
| **describer, avatarizer** | **N/A mesuré** (verdict Fabien 17/08, gate commun `_has_engine_select`) : aucun sélecteur de modèle — describer route AUTO par type de média, avatarizer = MuseTalk fixe. Pas d'hôte → pas de grisage exigible. ⚠ Mise à jour 2026-08-28 : le pipeline texte→TTS→avatar est REVENU dans l'avatarizer (mode DÉRIVÉ des entrées, MODES_QUEUE_UX §2bis) — le N/A tient tant que MuseTalk reste le seul moteur d'ANIMATION ; le « Modèle TTS » de la modale n'est pas un sélecteur de moteur d'app (la voix vient de la brique synthesizer). Si un 2ᵉ moteur d'animation arrive (EchoMimicV3, StableAvatar…), le verdict ROUVRE automatiquement (gate mesuré). |

> ⚠ **2026-08-31 — ces re-clés sont une CICATRICE, pas une pièce d'architecture.** Elles n'existent
> que parce que les valeurs d'option des selects ne sont PAS les clés du catalogue : les apps
> peuplent leur liste depuis une constante en dur (mesuré : **1 app sur 10** dérive ses options du
> catalogue). Quand la dernière jambe sera câblée — options tirées du catalogue, filtrées par
> CAPACITÉ — il n'y aura plus rien à re-clé et cette table disparaîtra. Le mécanisme d'appariement
> lui-même (bidirectionnel, 8/8) n'est pas concerné : il est *simplifié*, pas remis en cause.
> Route, mesure et ordre de portage : `WAMA_APP_GENERATION_ROUTE.md §F4b`.

Re-clés par app (l'accesseur PRIME, jamais de déduction) : synthesizer `ENGINE_CATALOG_KEYS`
(xtts_v2↔coqui-xtts), enhancer suffixe `_fp16` (stems ONNX), transcriber
`_backend_for_model_key` (qwen3-asr-* → qwen_asr), anonymizer valeurs d'option `type/fichier`
(double clé, même contrat que `_model_help_meta`).

Pour les apps à FILE (fichiers consommés au dépôt), la direction VIVANTE est MODÈLE→ENTRÉES
(ligne d'état sous le select) ; le grisage entrée-d'abord s'activera avec les slots RETENUS
(références). Le serveur (`matches_inputs()`) et l'UI partagent la même déclaration catalogue :
le grisage d'une entrée et l'exclusion d'un modèle disent la même chose.

---

## 6. LES QUATRE AXES D'ENTRÉE — et l'auto-adaptation aux modèles (2026-09-10)

> Section née d'une question de Fabien : *« la solution est l'auto-adaptation de la card
> d'entrée aux capacités des modèles d'une application. Sinon, à l'ajout d'un nouveau modèle
> proposant plus de modalités d'entrée, on sera bloqué. »* Elle ne décide rien de neuf : elle
> SÉPARE ce qui était mélangé, et rend implémentable une règle déjà écrite.

### 6.1 Le mélange qui bloquait

`INPUT_TYPES` confondait **quatre axes orthogonaux**. C'est ce qui rendait toute discussion
« travail vs référence » insoluble : on cherchait à faire trancher par une catégorie ce qui
relève de trois autres plans.

| axe | ce qu'il décrit | où il vit |
|---|---|---|
| **A — jeton d'entrée** | ce que l'ÉLÉMENT consomme (`prompt`, `work_image`, `reference_melody`…) | `INPUT_TYPES` |
| **B — modalité** | comment un fichier ATTEINT un slot (import, médiathèque, url, live) | `input_slots` → `mods` |
| **C — voie** | par où le fichier entre dans WAMA (13 lignes mesurées) | `MEDIA_STORAGE_TIERING §8.2` |
| **D — lot** | un GESTE qui crée N éléments — **jamais un port** (décision Fabien 05/09) | brique batch commune |

**Retiré le 2026-09-10** : `prompt_file` (axe D déguisé en axe A — libellé « Fichier de prompts
(batch) »). Il était de surcroît INERTE : `studio_node_ports` ne retient des `inputs` d'une app
que les jetons `port == 'reference'`, donc un jeton `travail` déclaré là était ignoré en
silence. imager et composer le déclaraient ; ni port ni slot n'en sortait.
**Restent à traiter** : `url` (axe B — déjà présent dans `mods`) et `negative_prompt` (réglage,
`port: None`).

### 6.2 Ce que dit l'état de l'art — et ce qu'il ne dit pas

| outil | modèle d'entrée |
|---|---|
| **ComfyUI** | `INPUT_TYPES()` → `{required, optional, hidden}`, chaque entrée = `(TYPE_DE_DONNÉE, options)`. **Aucune catégorie travail/référence** : le rôle est porté par le NOM du socket |
| **diffusers** | trois paramètres NOMMÉS distincts : `image` (init, transformé), `ip_adapter_image` (style, conditionne), `control_image` (structure) |
| **Suno** | prompt de style + paroles + audio, **rien n'est bloquant** ; le rôle de l'audio dépend du MODE (« Add Vocals » = travail ; style = référence) |

**Conclusion opératoire** : la distinction travail/référence est RÉELLE (diffusers la nomme),
mais ce n'est pas un axe de STRUCTURE. Un onglet de card = **un jeton nommé**, pas une
catégorie. `group` est rétrogradé au rang d'ATTRIBUT, utile à deux choses et deux seulement :
le bind de la preview d'entrée (`WAMA_MANIFEST_SPEC §141-147` — jamais sur une référence) et
l'ordre des onglets.

⚠ **Corollaire qui règle le cas « deux références de rôles différents »** (style + décor) :
deux jetons nommés, deux onglets, deux libellés. Le système est universel *parce qu'*il nomme
au lieu de catégoriser. Aucune règle nouvelle n'est requise.

### 6.3 La règle d'auto-adaptation — déjà écrite, pas encore implémentée

`app_modes.py` la porte depuis l'origine : **slots d'une app = ses `inputs` de niveau APP ∪
l'union des `inputs_required`/`inputs_optional` de ses MODÈLES**. Mesuré le 2026-09-10 : le
vocabulaire est peuplé sur **100 % des modèles d'app** (48/48 anonymizer, 12/12 imager, 5/5
composer, 9/9 enhancer…), et **aucun jeton employé par un modèle n'est absent d'`INPUT_TYPES`**.

Ce qui manque est le CONSOMMATEUR : `studio_node_ports` dérive encore le port travail des
catégories grossières d'`APP_CATALOG.input_types`, d'où un port FANTÔME chez l'imager
(`work[image]` alors que l'app déclare `reference_image`). Trois mesures indépendantes le
confirment : la card v4 le rend en `data-wama-depot=attache`, `GENERIC_APPS` écrase la
dérivation par `primary_input='prompt'`, et `studio_redundancy('imager')` sort en
`narrowed_by_declaration` avec l'`io_scope` « le port image (i2i/référence) de la card n'est
pas exposé au nœud ».

**L'obligation reste au runtime** : l'union dit quels slots EXISTENT, `wama-input-match` dit
lesquels sont OBLIGATOIRES selon le modèle choisi (`matches_inputs`). Un slot requis par un
seul modèle est OFFERT, pas imposé.

### 6.4 La card v4 implémente déjà la bonne forme

Vérifié au gabarit et au navigateur : section **prompt** au-dessus, hors onglets (`input_slots`
fait `if group == 'prompt': continue`) · un **onglet par port fichier**, chacun portant TOUTES
ses modalités **dont son propre champ URL** — ce qui lève l'ambiguïté « cette URL, c'est un
prompt, un travail ou une référence ? » sans recourir à la chronologie · un onglet **live** ·
la **barre de lot** hors ports. Le studio en fait autant, avec le prompt en socket connectable
(nœud source « Batch de prompts »). **Aucun conflit studio ↔ card v4.**

⚠ **Un seul point du dépôt dit encore le contraire** : `INPUT_TYPES['prompt'].port == 'travail'`.
C'est le vocabulaire qui est en retard sur ses deux consommateurs, pas l'inverse.

### 6.5 Reste à faire — dans cet ordre

| # | geste | preuve attendue |
|---|---|---|
| ~~P0~~ | ~~`prompt_file` → brique de lot commune~~ | ✅ **fait le 2026-09-10** |
| P0′ | séparer les axes restants : `prompt.port` → `prompt`, sortir `url`, classer `negative_prompt` | ports inchangés hors `prompt` ; v4 et studio d'accord |
| P1 | accesseur d'union `app_input_ports(app, domain)` — **réutiliser `input_match.auto_entry()`**, qui en calcule déjà une variante | table des écarts union ↔ ports actuels, sans changer un comportement |
| P2 | `studio_node_ports` le consomme (repli si union vide) | `studio_redundancy` : imager `narrowed_by_declaration` → `derived` ; roundtrip fidèle ; corpus ré-exporté |
| P3 | la card v4 suit seule | batteries `converter_01` et `imager_01` |
| P4 | câblage de l'imager : l'attache d'image devient un dépôt de TRAVAIL | `imager_01.import` : `skip` → OK |

### 6.6 Points ouverts, nommés

- **Aucun jeton de `tasks` ne dit le transfert de style.** `model_registry.py:553-559` dérive
  `inputs_required/optional` des `tasks` et ne sait produire que `work_image` — d'où
  `reference_image` déclaré par **zéro modèle**. Un modèle IP-Adapter/ControlNet verrait son
  image classée « travail » à tort. À ajouter avant d'intégrer un tel modèle.
- **Texte explicatif par entrée** (demande Fabien) : le contrat de port porte DÉJÀ une case
  `description` (rendue par `portEl()` côté studio, peuplée sur les nœuds sources). L'ajouter à
  `INPUT_TYPES` est additif.
- **Seuil d'onglets** : rien ne borne leur nombre. Un modèle multi-entrées type Wan3 en
  produirait beaucoup — reprendre le motif du seuil de 6 avec « … » de la rangée d'actions.
- **`describe2img` (imager)** : rendu superflu par « Envoyer vers » + studio (décision Fabien
  10/09) — c'est aussi ce qui explique que son image n'aille jamais au modèle d'image. Retrait
  à faire, 0 génération dans ce mode en base.
- **`prompt` de l'avatarizer** : ajout personnalisé (TTS+avatar), qu'aucun modèle ne déclare.
  Sous la règle d'union il DISPARAÎT, au profit de la chaîne synthesizer → avatarizer — et il
  reviendra de lui-même le jour où un modèle déclarera le couple. Position Fabien 10/09.
