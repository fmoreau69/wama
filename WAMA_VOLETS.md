# WAMA_VOLETS.md — Volets gauche et droit : référence unique du domaine

> **Statut : ÉTAT DES LIEUX MESURÉ au 2026-08-22, aucun refactoring engagé.** Ce document
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
| Volet **droit** `<aside id="wama-right-panel">` | `:131-200` | Rendu pour **TOUTE** page étendant `base.html` |
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

| Mesure | Nombre |
|---|---|
| Pages rendant le volet droit | **35** (15 via `app_modern_base`, 20 en extension directe) |
| Pages **déclarant** au moins un bloc `right_panel_*` | 17 / 35 |
| Pages au volet **totalement vide de sens** (3 cadres, 0 déclaration, 0 inspecteur) | **17 / 35** |
| **Cadres vides cumulés** sur ces pages | **51** |
| Pages appelant l'inspecteur | 14 (**16 instances**) |
| Pages **sans aucun** cadre inutile | **2 / 35** — `model_manager/index` et `transcriber/edit` |

**Les 17 pages au volet vide** : licences · Mon RAG · **Registres** · médiathèque ·
catalogue de fonctions · catalogue de librairies · profil · préférences (×2) · gestion des
utilisateurs · matrice d'accès · connexion (×2) · validation d'inscription ·
**face_analyzer (×3)**.

### Le mécanisme existe, c'est l'ADOPTION qui manque

| Option de `WamaInspector` | Adoption |
|---|---|
| `hideOnInspect` | 4 / 16 |
| `onDeselect` | 2 / 16 |
| `showOnInspect` · `keepMediaSection` · `settingsTitleInspect` | **1 / 16** chacune |

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

## 4. ⚠ Trois défauts MESURÉS — ce ne sont pas des cadres vides

**① La croix ✕ d'un batch ne désélectionne pas, sur 8 pages.** `#inspectorBanner` n'existe
que sur 5 pages (`_inspector_banner.html` inclus par avatarizer, imager, synthesizer + 2
copies inline dans `apps.html` et `model_manager`). Ailleurs `ids.deselect` vaut `null` et
`showBatchInfo` appelle `od.click()` sur un élément inexistant → **seul Échap fonctionne**.
Concerne : anonymizer, composer, converter, describer, enhancer, reader, **transcriber**,
journal. ⚠ Le commentaire de transcriber affirme que le bandeau est « centralisé » alors que
le partial **n'est pas inclus** — une doc qui ment sur son propre fichier.

**② Deux instances d'inspecteur sur hôtes partagés.** `enhancer` (image + audio) et `imager`
(image + vidéo) appellent `init` deux fois sur la même page ; les hôtes (`#inspectorActions`,
`#media-section`…) étant **uniques par page**, la seconde réinitialise l'état de la première.

**③ Chez `avatarizer`, l'import d'avatar disparaît au premier clic.** Sa zone d'upload vit
dans `#media-section` — précisément la section que la brique masque à la sélection d'une card.

---

## 5. Cas particuliers à NE PAS casser

**`cam_analyzer`** — ce n'est **pas un inspecteur** mais un **panneau de travail permanent** :
les trois sections sont détournées (« Carte & passages » porte une mini-carte Leaflet de
320 px, « Profil actif », « Exports »), pilotées par le JS métier, jamais par `WamaInspector`.
L'unité de sélection est une **session/un passage**, pas une card. ⚠ Lui appliquer un
masquage automatique **détruirait la carte**. Il devra **déclarer**, jamais hériter.

**`face_analyzer`** — à l'inverse, ne déclare rien : **9 cadres vides** sur ses trois pages.

**`home.html`** — l'avatar vit en `right_panel_top` (`:14-25`), posé `display:none`, chargé
par **import dynamique au clic** (~6 Mo, une seule fois). ⚠ **Il n'est PAS persistant** :
son conteneur n'existe que dans `home.html` (`base.html` ne référence `wama-avatar` nulle
part), donc il **disparaît dès qu'on quitte l'accueil**. Ce qui persiste est son *état*, pas
sa présence. Et il **s'ajoute** au volet sans rien remplacer : les trois cadres inutiles
restent sous lui.

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
| 1 | **Bandeau manquant** sur 8 pages | Un `include` répare une **croix cassée** — c'est un bug, pas de l'esthétique |
| 2 | **Déclaration des sections** (`volet = {...}` côté vue, comme `facettes`) | Défaut inchangé ⇒ **zéro régression** pour les apps ; corrige 17 pages et 51 cadres |
| 3 | Double instance `enhancer`/`imager` | Bug latent, indépendant du reste |
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
- `WAMA_IA_TRANSVERSE.md §1` — contrat de surface de l'assistant (le tour ne porte jamais d'audio).
- `CARD_DESIGN.md` — anatomie des cards, source de la sélection qui nourrit l'inspecteur.
