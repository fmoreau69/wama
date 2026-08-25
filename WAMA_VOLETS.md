# WAMA_VOLETS.md — Volets gauche et droit : référence unique du domaine

> **Statut : état des lieux MESURÉ au 2026-08-22 ; les TROIS défauts du §4 sont CORRIGÉS le
> même jour** (brique + 2 apps, 2 scénarios nocturnes vérifiés rouges sur le code d'avant),
> **et le chantier de fond — la DÉCLARATION des sections (§8 n°2) — est LIVRÉ** : les 17 pages
> déclarent, les 51 cadres vides sont retirés, 13 tests versionnés couvrent le mécanisme
> (`wama/common/tests_volet.py`). Voir **§3-bis** pour le contrat.
>
> ⚠ Deux diagnostics du §4 étaient FAUX et la confrontation au code les a redressés : le ✕
> cassé n'appelait pas un bandeau à rajouter (§4①) et l'import d'avatarizer n'était pas perdu
> « au premier clic » mais dès le chargement (§4③). Un défaut se mesure au bon maillon.
>
> Ce document
> existe parce qu'aucun ne couvrait le sujet : ni le filemanager (volet gauche), ni
> l'inspecteur (volet droit) n'avaient de référence — seul `INSPECTOR_DETAIL_FIELDS.md`
> traitait du *schéma des champs de détail*, pas de la structure des panneaux.
>
> **UN document pour les DEUX volets**, et non deux : les questions qui décident — masquage
> en mode simplifié, repli à la volée, largeur utile, déclaration par page, place dans
> `base.html` — leur sont **communes**. Deux documents auraient dupliqué ces sections, donc
> divergé. Leurs contenus diffèrent (arborescence de fichiers / inspecteur contextuel) : ce
> sont deux parties, pas deux domaines.

---

## 1. L'ossature — `wama/templates/base.html`

| Élément | Lignes | Fait |
|---|---|---|
| Volet **gauche** | `:128` | `include` de `filemanager/sidebar.html` — arborescence de fichiers |
| Volet **droit** `<aside id="wama-right-panel">` | `:131-200` | ~~Rendu pour **TOUTE** page étendant `base.html`~~ → rendu **si `volet.actif`** (§3-bis, 22/08) ; chaque section est conditionnée par sa clé |
| `right_panel_top` | `:147` | Bloc libre, **vide et sans cadre** — « ni un média, ni un paramètre, ni une action » |
| `#media-section` | `:150-166` | Défaut : placeholder « Sélectionnez un fichier pour l'aperçu » |
| `#info-section` | `:169-174` | **Seule section née masquée**, hôte `#inspectorInfo`, aucun bloc surchargeable |
| `#settings-section` | `:177-186` | Défaut : « Aucun paramètre disponible » |
| `#actions-section` | `:189-198` | Corps **vide** — mais titre et cadre rendus quand même |
| Pont apps | `common/app_modern_base.html:264-286` | Redéclare les blocs et ouvre `app_right_panel_*` |
| Masquage global | `base.html:22` | `body.wama-simple #wama-right-panel { display:none }` — **les deux volets disparaissent en mode simplifié** |
| Scripts inspecteur | `base.html:309-310` | `wama-inspector.js` + `-autofill.js` chargés **globalement** depuis le 2026-08-20 |

⚠ **Le CSS de structure du volet droit vit chez le filemanager** (`filemanager.css:199-254` :
`#wama-right-panel`, `.right-panel-section`, `.right-panel-preview*`), chargé globalement par
`base.html:37`. Erreur de conception connue et **non souhaitée** (Fabien) ; aucun bug
aujourd'hui puisque le CSS est chargé partout, mais un refactoring est prévu.

---

## 2. État des lieux — 35 pages mesurées

| Mesure | Avant (22/08 matin) | Après (22/08 soir) |
|---|---|---|
| Pages rendant le volet droit | **35** (15 via `app_modern_base`, 20 en extension directe) | 18 — les 17 autres n'en rendent plus |
| Pages **déclarant** au moins un bloc `right_panel_*` | 17 / 35 | inchangé |
| Pages au volet **totalement vide de sens** (3 cadres, 0 déclaration, 0 inspecteur) | **17 / 35** | **0** |
| **Cadres vides cumulés** sur ces pages | **51** | **0** |
| Pages appelant l'inspecteur | 14 (**16 instances**) | inchangé |
| Pages **sans aucun** cadre inutile | **2 / 35** | **35 / 35** |

> ⚠ L'accueil comptait EN PLUS 3 cadres sous son avatar (§5) : il déclare désormais `tete=True`
> et garde son volet pour le seul avatar. Il n'était pas dans les 17 — c'est donc **54** cadres
> retirés au total, pas 51.

**Les 17 pages au volet vide** : licences · Mon RAG · **Registres** · médiathèque ·
catalogue de fonctions · catalogue de librairies · profil · préférences (×2) · gestion des
utilisateurs · matrice d'accès · connexion (×2) · validation d'inscription ·
**face_analyzer (×3)**.

### Le mécanisme existe, c'est l'ADOPTION qui manque

| Option de `WamaInspector` | Adoption |
|---|---|
| `hideOnInspect` | 4 / 16 |
| `onDeselect` | 2 / 16 |
| `keepMediaSection` | **2 / 16** (model_manager ; + avatarizer le 22/08, cf. §4③) |
| `showOnInspect` · `settingsTitleInspect` | **1 / 16** chacune |

**Une seule page exploite les quatre leviers : `model_manager/index.html`.** C'est donc
**lui la référence à généraliser**, pas les apps média — elles consomment le socle sans le
contextualiser. Constat qui corrige une intuition naturelle (« aligner sur les apps »).

---

## 3. Les quatre états contextuels — `common/static/common/js/wama-inspector.js`

| État | Déclencheur | Effet | Lignes |
|---|---|---|---|
| **① File entière** (aucune sélection) | `init()`, `deselect()`, `media:processed` | Médias **masquée** ; Infos = agrégat de file lu de `WamaQueueStats` | 718-726, 843-847 |
| **② Item (card)** | clic délégué, ↑/↓ | params reflétés · actions · aperçu · `fillDetail` → `/common/detail/<app>/<pk>/` · Infos visible | 740-753 |
| **③ Batch** | clic sur `.batch-group` | réglages du **1ᵉʳ item** · agrégat `data-batch-*` · **aucun aperçu** | 755-767 |
| **④ Désélection** | croix, **Échap**, clic hors card | restaure les défauts, vide les actions, `onDeselect()` | 769-785 |

⚠ **Ne rien casser ici** : ce comportement file/batch/card est éprouvé et s'accroche aux
**identifiants** (`#media-section`, `#inspectorActions`, `#inspectorInfo`) et aux options de
`init`. Toute évolution doit laisser ids, blocs et JS intacts.

---

## 3-bis. Le volet est DÉCLARATIF — contrat (livré 2026-08-22)

**Référence unique du mécanisme : `wama/common/utils/volet.py`** (le pourquoi y est écrit ; ne
pas le recopier ici). Patron suivi : celui de `_filter_bar.html` — une variable de contexte
déclarée côté vue, consommée par des `{% if %}`, contrat documenté à la source.

```python
from wama.common.utils.volet import volet, VOLET_AUCUN

context['volet'] = VOLET_AUCUN                    # aucun volet (17 pages transversales)
context['volet'] = volet(medias=False)            # retrait CIBLÉ : garde Paramètres + Actions
context['volet'] = volet(tete=True, medias=False, parametres=False, actions=False)   # accueil
```

| Clé | Effet |
|---|---|
| `medias` | section Médias **et** son satellite `#info-section` (hôte de l'inspecteur) |
| `parametres` · `actions` | les sections homonymes |
| `tete` | ne rend rien de plus — **garde le volet ouvert** pour une page qui n'a que `right_panel_top` |
| `actif` | **dérivée** : si fausse, pas d'`<aside>` du tout **et** `<body class="wama-sans-volet">` |

**Trois décisions, et leur raison :**

1. **Le défaut est « les trois sections ».** Les apps ne déclarent RIEN et ne changent pas d'un
   pixel — contrainte n°1 du chantier. C'est le context processor `volet_defaut` qui garantit
   un dict complet ; sans lui, `{% if volet.medias %}` sur une variable absente vaudrait faux
   et masquerait TOUT.
2. **Une déclaration est toujours COMPLÈTE.** Un dict partiel masquerait les clés non citées
   (même cause). `volet()` remplit les quatre. L'alternative — un filtre maison
   `volet|section:'medias'` — a été écartée pour la raison que `_filter_bar.html` donne déjà :
   « un mécanisme de plus à connaître » pour un seul usage.
3. **Retirer l'`<aside>` ne suffit pas.** `body > .container-fluid` porte
   `margin-right: var(--fm-right-panel-width) !important` : sans la classe `wama-sans-volet`,
   on aurait laissé 360 px de bande morte — le décor déplacé, pas supprimé. **Mesuré** :
   corps 860 px → **1220 px** sur `registres`, 860 px inchangé sur `transcriber`.

⚠ **`cam_analyzer` DÉCLARE ses trois sections** au lieu d'en hériter (§5). Le rendu est le même
aujourd'hui ; la déclaration est ce qui garantit qu'un futur changement de défaut ne détruira
pas sa mini-carte Leaflet.

### Preuves — `wama/common/tests_volet.py` (13 tests)

| Classe | Ce qu'elle garde |
|---|---|
| `ContratTest` | dict toujours complet · `actif` dérivée · le défaut EST l'historique |
| `DefautTest` | sans déclaration : les trois sections + `#info-section`, pas de classe |
| `DeclarationTest` | retrait ciblé · retrait total (aside ET classe) · `tete` seule |
| `PagesDAppTest` | **les 11 apps du catalogue** rendues à l'identique (pages réelles) |
| `PagesDeclarantesTest` | 10 pages transversales + connexion en visiteur + accueil + cam_analyzer |

⚠ Le périmètre de `PagesDAppTest` est `APP_CATALOG`, **pas** `discoverable_apps()` : la
médiathèque expose un index mais est une surface transversale qui DÉCLARE. Les confondre
ferait échouer le test au moment même où le chantier avance.

---

## 4. ⚠ Trois défauts MESURÉS — ✅ CORRIGÉS le 2026-08-22

> Les trois énoncés d'origine sont conservés **barrés** quand la confrontation au code les a
> démentis : c'est le diagnostic, pas le symptôme, qui était faux. Chaque correctif est couvert
> par un scénario nocturne dont on a vérifié qu'il **échoue** sur le code d'avant (§4.4).

**① Le ✕ d'un batch ne désélectionne pas — ✅ corrigé (1 ligne dans la brique).**
Symptôme confirmé, ~~cause~~ **corrigée** : ce n'est PAS un bandeau manquant.

- ~~« `#inspectorBanner` n'existe que sur 5 pages, il faut l'inclure sur les 8 autres »~~
  **FAUX, et le rajouter aurait été une régression.** Son retrait est une décision ACTÉE :
  le 2026-07-08, la mini-card « Réglages de l'élément #N » a été **retirée** des apps portées
  au détail parce qu'elle redoublait l'identité déjà portée par la section Infos, et le ✕ des
  Infos est passé à l'appel direct de `deselect` (`PROJECT_STATUS.md:910-913`, §21.3.6). Le
  code le dit aussi, en commentaire, dans `wama-inspector.js` (chemin ITEM).
- **La vraie cause** : ce jour-là le chemin ITEM (`fillDetail`) a été migré, le chemin **BATCH**
  (`showBatchInfo`) a été **oublié** — il proxifiait encore par `$(ids.deselect).click()`. Sans
  bandeau dans la page, `od` vaut `null` : le clic tombait dans le vide. Le proxy n'avait
  d'ailleurs aucune vertu propre (sur les pages AVEC bandeau il déclenchait ce même `deselect`),
  et `showBatchInfo` **masque** le bandeau deux lignes plus haut.
- **Portée réelle : 7 pages, pas 8** — anonymizer, composer, converter, describer, enhancer,
  reader, transcriber. ~~journal~~ n'était **pas** concerné : sa file n'a aucun `.batch-group`
  (vérifié), donc `showBatchInfo` ne s'y exécute jamais.
- Le commentaire mensonger de `transcriber/index.html` (« brique COMMUNE » sans include en
  dessous) est **remplacé** par la raison du retrait — pour que le prochain lecteur ne « répare »
  pas un choix délibéré.

**② Deux instances d'inspecteur sur hôtes partagés — ✅ corrigé (registre inerte).**
Confirmé : `enhancer` (image + audio) et `imager` (image + vidéo) câblent deux instances sur une
page dont les hôtes (`#inspectorInfo`, `#inspectorActions`, `#media-section`…) sont **uniques**
et lus par id fixe. Symptôme précisé par la mesure : ce n'est pas « la seconde réinitialise la
première » mais **deux sélections vivantes à la fois** — volet peuplé par l'une, card de l'autre
toujours surlignée. Correctif : une sélection **chasse** les autres instances de la page
(`_cederLaMain`). **Inerte par construction** là où le défaut n'existe pas : sur une page à
instance unique le registre ne contient que l'instance courante, que la boucle saute — les
14 autres instances ne changent pas de comportement.

**③ Chez `avatarizer`, la zone d'import d'avatar — ✅ corrigé (`keepMediaSection: true`).**
~~« disparaît au premier clic »~~ **Pire que ça, et mesuré** : `#media-section` est
`display:none` **dès le chargement** (`init` → `showQueueInfo` → `setMediaSection(false)`), donc
la zone d'import n'apparaissait **jamais** — elle était dans le DOM, invisible. Le levier de
déclaration existait depuis le 19/08 et une seule page l'utilisait. Avatarizer n'ayant **pas**
de `#preview-container`, sa section Médias ne porte que du contenu permanent : `true` (jamais
masquée) et non `'no-selection'`.

### 4.4 Preuves — scénarios nocturnes versionnés

| Scénario | Ce qu'il exerce | Vérifié **rouge** sur le code d'avant |
|---|---|---|
| `common.volet.deselection` | file **synthétique** (1 batch, 2 cards) injectée dans une page réelle **sans bandeau** ; `selectBatch` puis clic sur le ✕ | oui — « batch 999999 → 999999, surbrillance toujours là » |
| `common.volet.instances` | **deux** files synthétiques, deux instances ; sélection dans l'une puis dans l'autre | oui — « 2 card(s) surlignée(s) au lieu d'une » |

Files **synthétiques** délibérément : le test porte sur la BRIQUE, pas sur les données. Il
tourne donc toutes les nuits sur une file vide, sans rien créer ni supprimer — une variante
« cliquer un vrai batch » aurait SKIPPÉ la plupart des nuits.

### 4.5 ⚠ Angle mort découvert en validant : `<app>.ui` ne s'authentifie pas

`check_app_page` ne pose aucun cookie de session (contrairement à `<app>.import`). Playwright
suit alors la redirection et lit le **200 de l'accueil** : le scénario passe au vert sans avoir
jamais vu l'app. Mesuré le 2026-08-22 sur les 14 apps découvertes :

- **12 pages sont réellement atteintes** sans cookie — le vert y est mérité (c'est ce qui rend
  la non-régression de ce palier valide : transcriber, avatarizer, enhancer, imager en font partie) ;
- **`model_manager` est détourné dans les DEUX cas** (`/?next=/model-manager/`) : `model_manager.ui`
  n'a jamais mesuré cette page. Le compte de test nocturne n'a pas le droit ;
- **`studio`** est détourné sans cookie, atteint avec : `studio.ui` mesure l'accueil ;
- **`converter_01`** est l'inverse — atteint sans cookie, détourné **avec** le compte de test.

> Que 12 index répondent 200 à un visiteur non identifié n'est PAS une découverte : c'est le
> trou de droits déjà consigné (`PROFILES_PERMISSIONS §1.5`, « index non gardés »). Les deux
> constats se recoupent, ils ne se contredisent pas.

**Conséquence pour ce palier** : la modification de `model_manager/index.html` (absorption du
bandeau) est prouvée par **rendu direct du gabarit** (égalité structurelle attributs + texte
avec le markup retiré) et par le bout-en-bout de `/common/apps/`, qui applique le même motif de
paramètres — **pas** par un passage navigateur sur la page elle-même, faute de droits. Corriger
l'angle mort demande de trancher ce qu'on veut mesurer (santé en visiteur ? en utilisateur ?) et
rendrait `model_manager.ui` **rouge** : à décider, pas à glisser dans un palier de volets.

---

## 5. Cas particuliers à NE PAS casser

**`cam_analyzer`** — ce n'est **pas un inspecteur** mais un **panneau de travail permanent** :
les trois sections sont détournées (« Carte & passages » porte une mini-carte Leaflet de
320 px, « Profil actif », « Exports »), pilotées par le JS métier, jamais par `WamaInspector`.
L'unité de sélection est une **session/un passage**, pas une card. ⚠ Lui appliquer un
masquage automatique **détruirait la carte**. Il devra **déclarer**, jamais hériter.

**`face_analyzer`** — à l'inverse, ne déclarait rien : **9 cadres vides** sur ses trois pages.
✅ Ses trois vues déclarent `VOLET_AUCUN` depuis le 2026-08-22 (webcam, graphiques et sessions
occupent toute la largeur).

**`home.html`** — l'avatar vit en `right_panel_top` (`:14-25`), posé `display:none`, chargé
par **import dynamique au clic** (~6 Mo, une seule fois). ⚠ **Il n'est PAS persistant** :
son conteneur n'existe que dans `home.html` (`base.html` ne référence `wama-avatar` nulle
part), donc il **disparaît dès qu'on quitte l'accueil**. Ce qui persiste est son *état*, pas
sa présence. ~~Et il s'ajoute au volet sans rien remplacer : les trois cadres inutiles restent
sous lui.~~ ✅ **Corrigé le 22/08** : l'accueil déclare `tete=True` + les trois sections à
`False` — le volet reste ouvert pour le seul avatar. C'est le cas d'usage qui a rendu la clé
`tete` nécessaire (un gabarit ne peut pas dire si son bloc libre est vide).

**`filemanager`** — n'a **aucune** page étendant `base.html` ; il fournit la sidebar gauche
et, par accident d'histoire, le CSS du volet droit. Son « aperçu global » annoncé en
commentaire (`base.html:156`) **n'est câblé nulle part** : il utilise sa propre modale.

---

## 6. Code mort identifié

| Élément | Chemin | Constat |
|---|---|---|
| `window.WAMA_RIGHT_PANEL` | `base.html:203-256` | API complète (`showPreview`/`updateSettings`/…) — **0 appelant** |
| Copie de l'`<aside>` | `filemanager/templates/filemanager/right_panel.html` (118 l.) | **jamais incluse** |
| Gabarits intermédiaires | `common/app_base.html`, `accounts/base_form.html` | **rien ne les étend** |

---

## 7. Le mode simplifié — la tension non résolue

`body.wama-simple` **masque les deux volets**. Or l'intention d'origine était d'obtenir un
**chatbot** — donc précisément le mode où l'assistant devrait être au centre. Contradiction à
résoudre avant de câbler un assistant persistant.

Différence observée avec un chatbot web du marché (Claude) : celui-ci met **conversations,
projets et skills dans son volet gauche**, là où WAMA les place dans le **menu déroulant
utilisateur**. Deux organisations pour des objets comparables.

**Piste (Fabien, 2026-08-22 — à réfléchir, PAS un plan d'attaque)** : le mode simplifié
garderait ses volets, **repliables** comme les chatbots modernes, mais avec un autre usage —
volet gauche = les entrées du menu utilisateur en accès direct (**sans** le filemanager),
volet droit = **l'AI Assistant seul**. La partie centrale ne changerait pas : dans les apps
tout est déjà **redondant** (les paramètres restent atteignables par la modale).

⚠ **La limite identifiée, et elle est réelle** : cette redondance **n'existe pas pour les
pages de catalogue** — ce qui vit dans leur volet droit n'est accessible **que** par lui.
Aucune solution ne satisfait tous les cas ; et puisque le mode simplifié vise un chatbot sans
navigation, **il n'a peut-être pas à les satisfaire**. Question laissée ouverte, non
prioritaire.

---

## 8. Suites possibles — ordre conseillé, rien d'engagé

| # | Chantier | Pourquoi cet ordre |
|---|---|---|
| 1 | ~~**Bandeau manquant** sur 8 pages~~ → **✅ FAIT autrement (22/08)** | Le diagnostic était faux : pas un `include` à ajouter mais **un chemin oublié** dans la brique. Voir §4① — l'`include` aurait REVERTÉ le retrait décidé le 07/08 |
| 2 | ~~**Déclaration des sections**~~ → **✅ LIVRÉ (22/08)** | Défaut inchangé ⇒ zéro régression pour les apps ; **17 pages et 54 cadres** retirés (§3-bis) |
| 3 | ~~Double instance `enhancer`/`imager`~~ → **✅ FAIT (22/08)** | Traité avec ① : même brique, même passe de validation (§4②) |
| 4 | **Portage depuis `model_manager`** vers la brique | Bandeau paramétrable · restauration du hint · `detailSchema`/`actionsSchema` · `ids.actionButtons` |
| 5 | **Assistant dans le volet** (conteneur en `base.html`, préférence au profil) | Rend l'avatar réellement persistant ; ne pas engager avant 2 |
| 6 | Hygiène : CSS du volet vers `common/`, retrait du code mort (§6) | Mécanique, sans risque, mais sans valeur d'usage |

⚠ **NE PAS réécrire `wama-inspector.js`.** `PROJECT_STATUS.md:1320-1349` documente deux
correctifs de ce fichier **entièrement revertés** — c'est la brique la plus consommée du
dépôt (14 pages), toute modification y est transverse par construction.

---

## 9. Questions ouvertes

1. **Assistant vs inspecteur dans le même volet** — le double usage peut dégrader l'UI/UX.
   Piste de Fabien : n'y garder que **l'avatar en tête** (discussion naturelle + guidage),
   avec une capacité nouvelle — **amener l'utilisateur sur la page qui convient** à sa
   demande. À réfléchir.
2. **Repli élégant des volets à la volée** — souhaité, sans le « gros bouton » déjà essayé
   puis retiré parce qu'il polluait l'UI.
3. **Mode simplifié** — cf. §7.
4. **Trois états plutôt que deux** pour l'assistant (toujours visible / replié quand le
   contexte prime / jamais) — évite de choisir entre « perdu partout » et « encombrant ».

## Voir aussi
- `INSPECTOR_DETAIL_FIELDS.md` — schéma canonique des champs de détail (contenu, pas structure).
- `WAMA_LLM.md §1` — contrat de surface de l'assistant (le tour ne porte jamais d'audio).
- `CARD_DESIGN.md` — anatomie des cards, source de la sélection qui nourrit l'inspecteur.
