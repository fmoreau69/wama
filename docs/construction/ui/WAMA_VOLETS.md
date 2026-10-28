# WAMA_VOLETS.md — Volets gauche et droit : référence unique du domaine

> **Statut : état des lieux MESURÉ au 2026-08-22 ; les TROIS défauts du §4 sont CORRIGÉS le
> même jour** (brique + 2 apps, 2 scénarios nocturnes vérifiés rouges sur le code d'avant),
> **et le chantier de fond — la DÉCLARATION des sections (§8 n°2) — est LIVRÉ** : les 17 pages
> déclarent, les 51 cadres vides sont retirés, 13 tests versionnés couvrent le mécanisme
> (`wama/common/tests/tests_volet.py`). Voir **§3-bis** pour le contrat.
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
| ~~Masquage global~~ | — | ~~`body.wama-simple #wama-right-panel { display:none }`~~ — **retiré le 2026-10-27 avec le mode simplifié** (§7) ; le bouton de l'en-tête replie les deux volets par `WamaPanels.setAll` |
| **Repli par la frontière** (2026-10-10) | `common/js/wama-panel-toggle.js` + `common/css/wama-panel-toggle.css` | `WamaPanels` : un clic sur la frontière d'un volet le replie / le rouvre, sur toute page — voir §9 ② |
| **Place des volets** (2026-10-10) | `wama-panel-toggle.css` | marges dérivées `--wama-left-gutter` / `--wama-right-gutter` (largeur du volet, ou 0 replié / sans volet) : SEULE source que lisent le corps, l'en-tête et les barres fixes — jamais plus `--fm-*-width` (`tests_panel_toggle`) |
| **Contextes de largeur** (2026-10-12) | `base.html` (amorce `WamaPanelsContext`) + `wama-panel-toggle.js` | sous le `lg` de Bootstrap : classe `wama-narrow`, volets repliés d'office, un seul ouvert, mémoire `wama_panel_<côté>_narrow` — voir §9 ⑤ |
| **Barre du haut et pied** (2026-10-12) | `includes/header.html`, `base.html`, `filemanager.css` | grilles `1fr auto 1fr` ; la barre est un CONTENEUR (`wama-header`) dont les libellés `.wama-header-label` s'effacent derrière leur icône — §9 ⑤ |
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

> ⚠ **Constat daté du 22/08, qui a bougé depuis.** Le 2026-09-09, licences, Mon RAG et Registres
> ont RÉCUPÉRÉ un volet pour l'inspecteur de détail. Le 2026-09-15, le **profil** aussi
> (consigne de Fabien) : `volet(medias=False, actions=False)`, et sa section Paramètres porte
> tout ce qui touche aux clés — jeton d'API, clés des fournisseurs LLM, connecteurs de la
> médiathèque. L'invariant gardé par `tests_volet.py` reste le même : aucun cadre VIDE.
>
> ⚠ **2026-10-18 — le journal et le calendrier** (relevé par Fabien sur le calendrier : « Médias /
> Sélectionnez un fichier / Aucun paramètre disponible / Actions » vides). Les deux pages montrent
> la card cliquée par l'inspecteur commun (aperçu + fiche) et déclarent ce qu'elles remplissent :
> journal `volet(parametres=False, actions=False)`, calendrier `volet(parametres=False)` (son action
> « Ouvrir dans <app> » vit au volet, faute de card sur la page). Médias garde une invite PROPRE à
> la page (bloc `right_panel_media_hint` de `base.html`, `keepMediaSection: true`). L'invariant de
> `tests_volet` a été affûté le même jour : Médias se reconnaît à l'invite par défaut, son
> conteneur d'aperçu étant aussi l'hôte de l'inspecteur ; les deux pages y sont mesurées.

### Le mécanisme existe, c'est l'ADOPTION qui manque

| Option de `WamaInspector` | Adoption |
|---|---|
| `hideOnInspect` | 4 / 16 |
| `onDeselect` | 2 / 16 |
| `keepMediaSection` | **2 / 16** (model_manager ; + avatarizer le 22/08, cf. §4③) — + journal et calendrier le 2026-10-18 |
| `showOnInspect` · `settingsTitleInspect` | **1 / 16** chacune — `showOnInspect` + calendrier le 2026-10-18 |

> Chiffres du 22/08, non remesurés depuis : seuls les ajouts du 2026-10-18 sont comptés à la main.

**Une seule page exploite les quatre leviers : `model_manager/index.html`.** C'est donc
**lui la référence à généraliser**, pas les apps média — elles consomment le socle sans le
contextualiser. Constat qui corrige une intuition naturelle (« aligner sur les apps »).

---

## 3. Les quatre états contextuels — `common/static/common/js/wama-inspector.js`

| État | Déclencheur | Effet | Lignes |
|---|---|---|---|
| **① File entière** (aucune sélection) | `init()`, `deselect()`, `media:processed` | Médias **masquée** ; Infos = agrégat de file lu de `WamaQueueStats` | 718-726, 843-847 |
| **② Item (card)** | clic délégué, ↑/↓ | params reflétés · actions · aperçu · `fillDetail` → `/common/detail/<app>/<pk>/` · Infos visible | 740-753 |
| **③ Batch** | clic sur `.batch-group`, ↑/↓ (le lot est un arrêt de la file depuis le 2026-10-14, `queueStops`) | réglages du **1ᵉʳ item** · agrégat `data-batch-*` · **aucun aperçu** | 755-767 |
| **④ Désélection** | croix, **Échap**, clic hors card | restaure les défauts, vide les actions, `onDeselect()` | 769-785 |

⚠ **Ne rien casser ici** : ce comportement file/batch/card est éprouvé et s'accroche aux
**identifiants** (`#media-section`, `#inspectorActions`, `#inspectorInfo`) et aux options de
`init`. Toute évolution doit laisser ids, blocs et JS intacts.

**« Médias » devient « Aperçu » — ✅ 2026-10-28** (Fabien : *« la section Médias n'a plus de
sens […] c'est la preview qui a pris sa place […] une section qui ne charge rien »*). Mesuré
avant d'y toucher — 118 pages sans argument rendues dans la base de test, puis 16 dans le
navigateur sans sélection : dans les 10 apps la section n'était PAS inerte, c'est l'hôte de
l'aperçu de l'inspecteur, déjà masquée hors sélection (état ①) ; trois cadres l'étaient :
- le **journal** et le **calendrier** la gardaient visible sans sélection (`keepMediaSection:
  true`) : 258 px pour une invite. Retiré — l'aperçu s'y montre au clic, comme dans les apps
  (vu à l'écran : masquée avant, l'aperçu du témoin après le clic) ;
- **« Modifier mon compte »** (`accounts:user-edit`) rendait les TROIS cadres vides de
  `base.html` : sa déclaration `VOLET_AUCUN` (2026-10-20) vivait dans une seconde
  `get_context_data` que la suivante remplaçait. Fusionnées ; le défaut (une méthode définie deux
  fois, la première perdue en silence) n'existait nulle part ailleurs — garde générique
  `tests_unbound_names.MethodDefinedTwiceTest`, la page ajoutée à `PagesDeclarantesTest.PAGES`.

Le titre par défaut dit ce qu'est la section : **Aperçu** (`base.html`), identifiants inchangés.
Restent DÉCLARÉS, parce qu'ils y logent un contenu PERMANENT : le cam_analyzer (« Carte &
passages ») et le model manager (ressources système hors sélection, `'no-selection'`). Garde :
`test_the_preview_section_shows_only_what_is_selected` (aucun `keepMediaSection: true` ;
contre-épreuve rouge par un fichier fautif jetable). ⏳ Deux restes dans `wama-inspector.js`, à
solder quand ce fichier, en cours ailleurs, sera libre (relevés à la revérification du même
jour) : la branche `keepMediaSection === true` n'a plus d'appelant ; et le libellé « Aperçu » y est
écrit une seconde fois (`fillPreview(card, 'Aperçu')`, l. 873) — le titre par défaut de la
section le porte déjà (`base.html`), que `_setPreviewTitle(null)` sait reprendre. ⚠ La clé de
déclaration reste `volet(medias=…)` : un identifiant français de l'API du volet (`SECTIONS`), qui
se renommera avec ses ~20 appelants, pas au détour d'un libellé.

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
   ⚠ **Sauf pour une page du COMPTE, depuis le 2026-10-20** (Fabien : *« on met les champs en
   fonction du contenu de la page, pas de champ par défaut »*). Une page déclarée au registre
   des pages du compte (`app_registry.register_account_page`) n'a AUCUNE section sans
   déclaration : elle déclare ce qu'elle remplit. Mesuré le jour même : Partages,
   Notifications, Formats médias et Apps rendaient encore « Médias / Sélectionnez un fichier »,
   « Aucun paramètre disponible » et un cadre Actions vide. Apps déclare ses deux sections
   remplies ; Studio (hors compte) la sienne ; Backends ne déclare plus d'Actions vides. Garde :
   `tests_volet.AccountPagesHaveNoDefaultTest`, sur TOUTES les pages du registre — elle a trouvé
   Backends le jour de son écriture, qu'aucune liste ne citait.
   ⚠ **Et l'autre moitié, apprise le même soir** : le MODEL MANAGER est une page du compte
   (« Modèles ») qui REMPLIT ses trois sections sans les déclarer — il a perdu tout son volet
   (ressources, propositions à valider, actions) une fois le serveur relancé. Il déclare
   désormais `volet(medias=can_manage)`, et le garde vérifie aussi qu'une section qu'un gabarit
   de page du compte remplit est RENDUE (`test_a_section_the_page_fills_is_rendered`). *Retirer
   un défaut, c'est aussi retirer ce que des pages tenaient de lui sans le dire.*
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

### Preuves — `wama/common/tests/tests_volet.py` (13 tests)

| Classe | Ce qu'elle garde |
|---|---|
| `ContratTest` | dict toujours complet · `actif` dérivée · le défaut EST l'historique |
| `DefautTest` | sans déclaration : les trois sections + `#info-section`, pas de classe |
| `DeclarationTest` | retrait ciblé · retrait total (aside ET classe) · `tete` seule |
| `PagesDAppTest` | **les 11 apps du catalogue** rendues à l'identique (pages réelles) |
| `PagesDeclarantesTest` | 10 pages transversales + connexion en visiteur + accueil + cam_analyzer |
| `AccountPagesHaveNoDefaultTest` | (2026-10-20) TOUTES les pages du registre des pages du compte : aucune section rendue avec le contenu par défaut ; une page du compte sans déclaration n'a aucune section |

⚠ Le périmètre de `PagesDAppTest` est `APP_CATALOG`, **pas** `discoverable_apps()` : la
médiathèque expose un index mais est une surface transversale qui DÉCLARE. Les confondre
ferait échouer le test au moment même où le chantier avance.

## 3-ter. Le volet devient une ZONE DE BRIQUES — ✅ étape 1 (les surfaces), 2026-10-21

> Décision de Fabien, le 2026-10-21 : *« on passe tout WAMA progressivement en briques UI »* — le
> volet droit aussi, avec le même fonctionnement que la grille d'une surface : la mise en page
> d'origine **verrouillée par défaut**, le cadenas la rend modifiable, on replace, on relocke.
> Le volet est une **COLONNE**, pas une seconde grille libre (on y réordonne et on y règle la
> hauteur ; il a sa largeur à lui et se replie, `WamaPanels`). Les réglages en **deux colonnes**
> restent : c'est l'intérieur de la brique (`ParamGroup(columns=2)`), que déplacer ou
> redimensionner ne touche pas — et c'est désormais la LARGEUR DE LA BRIQUE qui fait passer à une
> colonne (requête de conteneur, `wama-surface.css`), plus celle de la fenêtre. Pas de repli
> automatique d'une brique au centre en mode Simplifié : la modale règle une card sans le volet,
> l'aperçu est dans la card, chaque volet se replie seul — l'agencement du mode Simplifié viendra
> plus tard (§7).

**Étape 1, livrée : le volet d'une SURFACE.** La page d'une surface déclare `volet(tete=True,
medias=False, parametres=False, actions=False)` (`surface_views.surface_page`) : l'assistant en
tête, puis la colonne `.wama-surface-panel` (`common/surface.html`, bloc `right_panel_top`). Ses
sections par défaut n'y montraient rien. Un emplacement déclare sa zone (`BrickSlot.zone`,
`grid` | `panel`) ; le noyau monte deux grilles gridstack (`acceptWidgets`), une brique glissée de
l'une à l'autre garde son élément — elle n'est jamais remontée — et la disposition gardée par
compte porte la zone de chaque place (`surfaces.clean_layout`). Une surface jamais disposée
s'ouvre **figée pour tous** (`surface_views._layout_of` ; seul le mode Simplifié l'était). Le
transcriber y retrouve son volet : actions, document, intervenants ; le centre au texte et au
temps. Gardes : `tests_surfaces.SurfaceLayoutTest`, scénario `common.surface_layout` (passage
d'un panneau dans la colonne, retour par « Disposition par défaut »).

**Épingler un panneau en haut ou en bas de la fenêtre — ✅ 2026-10-26** (Fabien : *« locker le
transport en bas ou en haut de page pour qu'il ne défile pas avec la page »*). Le geste est au
noyau (`wama-surface.js`, bouton `.wama-brick-dock`), la brique le DÉCLARE (`dockable: true` à son
`registerBrick` — le transport, `media_transport`, est la première). Le choix se garde avec la
disposition du compte (`docked: {emplacement: 'top' | 'bottom'}` — quatre bords le soir même,
ci-dessous —, validé par
`surfaces.clean_layout` : emplacements déclarés seuls, un bord hors `DOCK_EDGES` refusé). Le
panneau épinglé est fixé entre les gouttières des volets (`--wama-left-gutter` /
`--wama-right-gutter`, posées par `wama-panel-toggle.css`) et la page se décale de sa hauteur.
Garde : `tests_surfaces.SurfaceLayoutTest.test_a_docked_panel_is_kept_with_the_layout_of_the_account`.
⚠ Calé à `top: 0`, il passait SOUS l'en-tête fixe (relevé par Fabien le jour même, `95018c69`) :
il se cale entre l'en-tête et le pied, par les hauteurs que lisent déjà les volets
(`--fm-header-height` / `--fm-footer-height`).

**EMPILER des briques en un panneau, ÉPINGLER à QUATRE bords — ✅ 2026-10-26, le soir** (Fabien :
*« tout ce qui est lié au temps et à la lecture devrait pouvoir s'assembler en un module […] la
dissociation doit être dans le code, pas dans la présentation »* ; *« empiler/imbriquer des
briques pour les compacter en une seule, uniquement en affichage »* ; *« pour les zones fixes
latérales, on a qu'à le faire »*). Le noyau seul (`wama-surface.js`), aucune brique touchée :
- **Empiler** : chaque brique apporte une SECTION (titre + corps) ; « Empiler dans ce panneau »
  (icône calques, menu commun `WamaCardMenu`) fait passer un autre panneau — brique ou pile —
  SOUS celui-ci ; chaque section garde son titre, sa part de la hauteur et son état (le même
  élément : rien n'est remonté) ; flèches pour monter / descendre, « Détacher » pour sortir. La
  tête de la pile donne au panneau sa place et son épinglage. Gardé avec la disposition
  (`stacks : {tête: [{id, h}]}`, validé par `surfaces._clean_stacks` : une brique dans un seul
  panneau, un emplacement retiré oublié). Un geste de DISPOSITION : disposition modifiable
  seulement, défait par « Disposition par défaut » (qui garde, elle, l'épinglage : une
  préférence de lecture).
- **Épingler** à un bord : un menu de cinq choix (haut, bas, gauche, droite, « Dans la page »)
  au lieu du bouton qui faisait défiler deux bords — on choisit un BORD, jamais « sur place » au
  milieu de la page. Haut et bas : une bande qui garde sa hauteur dans la grille (≤ 45 % de la
  fenêtre) ; gauche et droite : une COLONNE fixe entre les bandes, sa largeur dans la grille
  (≤ 40 % de la zone centrale) ; deux panneaux sur un même bord se rangent l'un après l'autre.
  Le panneau épinglé QUITTE la grille — la page se referme derrière lui — et y retrouve sa place
  désépinglé (elle reste gardée dans la disposition). Une colonne n'a pas sa place sur une
  fenêtre de téléphone : le panneau y reste dans la page. Tout panneau s'épingle disposition
  modifiable ; figée, l'épingle ne reste que pour une brique qui la DÉCLARE (`dockable` : le
  transport) ou un panneau déjà épinglé — le rendu fini ne se couvre pas d'épingles.
- Ce qui ne change pas : la grille magnétique, la colonne du volet (`zone='panel'`), le centre qui
  défile, la disposition figée par défaut, le repli des volets.
- Gardes : `tests_surfaces` (piles et quatre bords au serveur, poids d'une pile en V8, calage
  sous l'en-tête et au-dessus du pied sur le CSS servi) ; scénario nocturne
  **`common.surface_stack`** (9 gestes sur la page servie : empiler les MÊMES briques, épingler en
  bas puis à gauche mesurés à l'écran, la page qui se referme, rechargement, tête descendue qui
  garde l'épinglage, détacher, désépingler), à côté de `common.surface_layout` (9/9, rien n'a
  reculé) ; trois contre-épreuves rouges (empilement neutralisé, panneau laissé dans la grille,
  colonne calée à 0).
- Revérifié sur le live relancé le 2026-10-27 : le noyau lit ses bornes de la surface
  (`Surface.to_dict` : `max_rows`, `dock_edges` — il recopiait `400` et la liste des bords,
  `test_the_kernel_reads_the_bounds_the_server_applies`) ; `common.surface_stack` passe à
  **12 gestes** — FIGÉE, la pile épinglée reste à son bord sans ses outils d'atelier et
  l'épingle quitte les panneaux ordinaires ; **« Disposition par défaut » défait les piles et
  GARDE l'épinglage** (une préférence de LECTURE, comme figée) ; sur un téléphone la colonne
  reste dans la page sans rien réécrire —, trois contre-épreuves de plus, rouges, jouées dans le
  navigateur du scénario (noyau et feuille réécrits par `page_hook`, rien sur le disque).
- **Le CADRE des bords — ✅ 2026-10-27** (Fabien : *« quand je clique sur un bouton pour
  désempiler, les briques UI fixes se retrouvent de nouveau masquées derrière le pied de page.
  Il faudrait mettre une garde permanente […] trouver une solution universelle »*). Reproduit sur
  le live (correction du transcriber, ligne de temps + transport + écriture épinglés en bas) :
  après « Détacher », et à tout rechargement, la bande retombait à **46 px** collée au pied — sa
  hauteur était MESURÉE (`offsetHeight`) sur un panneau reconstruit à l'instant, qui n'avait encore
  que la hauteur d'une cellule. Deux corrections, au noyau seul :
  1. **un seul élément fixe**, `.wama-dock-frame`, borné par l'en-tête, le pied et les deux volets
     (`--fm-header-height`, `--fm-footer-height`, `--wama-left-gutter`, `--wama-right-gutter` — les
     marges que lit la frontière des volets) ; quatre RÉGIONS (haut, bas, gauche, droite), où un
     panneau épinglé est DÉPLACÉ comme il passe de la grille à la colonne du volet. Recouvrir
     l'en-tête, le pied ou un volet ouvert n'est plus une erreur à éviter : la place n'existe pas.
     Le calcul de décalage panneau par panneau (`--wama-dock-offset`) est retiré ; la page s'écarte
     de la taille des régions (`ResizeObserver`) ;
  2. **la taille se LIT dans la place de grille** (rangées × cellule, colonnes × largeur de
     colonne), jamais mesurée sur l'élément.
  Gardes : la **garde permanente** du scénario `common.surface_stack` mesure la zone sûre sur les
  ÉLÉMENTS RÉELS (l'en-tête, le pied, chaque volet affiché — jamais les variables que le cadre
  lit) après CHAQUE geste et chaque ouverture, et qu'aucune brique épinglée n'est écrasée sous son
  titre ; un geste de plus rejoue le défaut (empiler un 3ᵉ panneau dans une pile épinglée, le
  détacher, recharger) — **14/14** sur le live ; `test_a_docked_panel_stops_at_the_header_and_the_footer`
  (le cadre est le SEUL `position: fixed` de la feuille, la taille lue et non mesurée). Sept
  contre-épreuves rouges : taille remesurée, cadre calé au bas de la fenêtre, cadre calé sous le
  volet (dans le navigateur) ; second élément fixe, cadre non borné, taille mesurée, panneau hors
  de sa région (texte lu muté en mémoire).
- **Des LIGNES de panneaux côte à côte — ✅ 2026-10-27** (Fabien : un petit élément « se placerait
  à côté, collé au transport » ; l'écriture à la lecture reste un OUTIL à part, posée à côté du
  transport — les « quatre niveaux » de `common/surfaces.py`). `docked` devient
  `{bord: [[panneau, …], …]}` (`surfaces._clean_docked`) : en haut et en bas des lignes ordonnées
  de panneaux côte à côte, à gauche et à droite des colonnes — une LISTE, le stockage (jsonb) ne
  gardant pas l'ordre des clés. L'ancienne forme `{id: bord}` est relue côté serveur
  (`_layout_of` passe par `clean_layout`) ; la relecture côté page, tenue le temps de la relance
  du live, est retirée à la revérification du même soir — un seul chemin. Une ligne prend la hauteur de son plus grand panneau,
  lue dans la grille ; une brique DÉCLARE sa largeur de ligne (`rowWidth` à son
  `registerBrick` — l'écriture à la lecture : `17rem`), prise quand elle PARTAGE sa ligne, seule
  elle la remplit. Geste : le menu de l'épingle propose « À côté de « X » » pour chaque panneau
  déjà épinglé (« Dans la colonne de » à gauche et à droite). Gardes :
  `test_pinned_rows_put_a_panel_beside_another` (V8 sur le noyau servi), la forme et l'ancienne
  forme au serveur ; `common.surface_stack` **15/15** (geste « à côté » : même ligne, collé à
  droite, gardé comme une ligne) et `surface_layout` 9/9 sur un serveur jetable (le live sert
  l'ancien Python jusqu'à sa relance) ; deux contre-épreuves rouges de plus (« à côté » ignoré,
  taille remesurée). Vu à l'écran sur la correction du transcriber : ligne de temps, puis transport
  + écriture sur une ligne, au-dessus du pied, rendus tels quels au rechargement.
- **Le GLISSER-DÉPOSER vers les bords — ✅ 2026-10-27** (Fabien : *« par simple drag&drop aux
  extrémités de la zone centrale (haut/bas/gauche/droite), on visualise directement si l'élément
  va se fixer […] et de même pour l'empilement, avec la possibilité d'empiler aussi
  latéralement »*). Pendant qu'on glisse un panneau — de la page (le glisser de gridstack,
  inchangé) ou déjà épinglé (par son titre) —, les bandes des bords s'éclairent (celle qui
  épinglerait plus fort), au-dessus d'un panneau épinglé son CENTRE empile et ses CÔTÉS posent à
  côté (avant ou après lui ; dessus et dessous dans une colonne), et une pastille DIT ce que fera
  le lâcher (« Épingler en bas de la fenêtre », « À côté de « Transport » », « Empiler dans… »,
  « Remettre dans la page »). Lâché ailleurs, un panneau épinglé revient dans la page ; relâché
  sur lui-même, il reste. Le lâcher passe par les MÊMES gestes que les menus (`Docks.put`,
  `join`) ; le pointeur est suivi par la brique commune `WamaGestures.track` (souris, stylet,
  doigt) — l'événement `drag` de gridstack ne part qu'aux changements de cellule, mesuré arrêté à
  200 px du bord visé. Repères et pastille vivent DANS le cadre : ils ne passent pas plus sous
  l'en-tête qu'un panneau. Disposition figée : rien ne se glisse. Dans la page, la grille
  magnétique garde la main. Gardes : `test_dragging_a_panel_to_an_edge_goes_through_the_common_gestures`
  et le « avant » au V8 ; `common.surface_stack` **19/19** — quatre glisser réels à la souris
  (au bord du haut, à côté, rendu à la page, empilé), chacun vérifié sur ce que la page MONTRAIT
  avant le lâcher puis sur ce qui est gardé ; deux contre-épreuves rouges (lâcher ignoré, pointeur
  non suivi). Vu à l'écran sur la correction du transcriber.
- **Une ligne épinglée se retaille sur place, et prend la taille de son PREMIER panneau — ✅
  2026-10-28** (Fabien : « règle les limites 1 et 3 »). La taille du plus GRAND laissait un vide
  sous le transport quand l'écriture à la lecture, plus haute, se posait à côté : ce qu'on pose
  « à côté » s'aligne désormais sur ce qui était là. Une POIGNÉE au bord intérieur de chaque ligne
  (côté page) la retaille : la taille suit le pointeur, s'aligne au lâcher sur la grille (rangées
  pour une bande, colonnes pour une colonne) et se garde dans la place du premier panneau — la
  même source que sa taille, celle qu'il retrouve rendu à la page. Absente d'une disposition
  figée. Code : `wama-brick-layout.js` (`resizeRow`), la brique commune de la disposition depuis
  `4a96042b`. Gardes : `test_a_pinned_row_takes_its_first_panel_size_and_resizes_in_place` ;
  `common.surface_stack` **21/21** sur le live (retailler par la poignée ; à côté d'un panneau plus
  bas) ; deux contre-épreuves rouges dans le navigateur (taille du plus grand, poignée qui ne
  garde rien).
- **Empiler DANS LA PAGE par le titre — ✅ 2026-10-28** (Fabien : « créer un empilement de briques
  UI […] au lieu de figer puis empiler ») : glisser le titre d'un panneau sur celui d'un autre les
  empile dans la page, à la place qu'avait la cible au début du geste ; la pile s'épingle ensuite
  d'un seul geste (vers un bord). Le TITRE et non le corps : la grille écarte le panneau qu'on
  survole. La cible se trouve là où est le titre OU là où il était au début du geste, et reste
  saisie à quelques pixels près (`pageTitleUnder`, `STACK_HOLD`). Ailleurs, la grille garde son
  magnétisme et ses espaces (la limite « à côté seulement dans une bande » est un comportement
  voulu, décision du même jour). Gardes : assertions du noyau (`tests_surfaces`) ;
  `common.surface_stack` **22/22**, cinq passages verts d'affilée ; contre-épreuve rouge (titre
  neutralisé). ⚠ La première version ne visait que le titre à sa position du moment : rouge un
  passage sur deux, la grille poussant la cible avant que le pointeur ne l'atteigne.
- ✅ **Le mode simplifié RETIRÉ — 2026-10-27** : bouton des volets dans l'en-tête, « Joindre »
  dans le chat, accueil à largeur de téléphone mesuré (§7).
- ⏳ **Suite décidée le 2026-10-27** (Fabien) : ④ les boutons d'atelier remplacés par UN menu « ⋯ »
  (gardé pour la disposition figée, le clavier, le tactile et les scénarios) — **après** que Fabien
  a essayé le glisser-déposer : « si on arrive à gérer tout ça en drag&drop, es-tu ok pour retirer
  les boutons qui feraient doublon ? ».
- ✅ Reste de `WAMA_DATA_WORLD §8.2 ⑤` (« layout dockable + détachement en vraie fenêtre ») : un
  panneau DANS UNE AUTRE FENÊTRE — fait le 2026-10-28, voir plus bas.
- **Étape ②, 1ᵉʳ geste — la DISPOSITION devient une brique commune ✅ 2026-10-28.** Les pages
  d'apps ne sont pas des surfaces (on n'y édite pas un élément) mais leur volet doit prendre les
  mêmes gestes : grille et colonne du volet, figer, empiler, épingler, glisser vers les bords,
  disposition gardée par compte. Ce code vivait dans le noyau des surfaces, mêlé à l'édition
  (`wama-surface.js`, 1 374 lignes : l'édition jusqu'à la ligne 500, la disposition ensuite) ; il
  en sort **tel quel** dans `common/js/wama-brick-layout.js` (`WamaBrickLayout.create`, `docks`,
  `scaleWeights`) — seuls changent les noms de ce qu'on lui passe (la surface déclarée devient
  `slots`, `columns`, `maxRows`, `dockEdges`, la route `url`), relevé par un diff du code déplacé.
  Le noyau (511 lignes) lui passe ce que la surface déclare et monte chaque brique dans le cadre
  qu'elle pose (`mount(rec)`) ; la disposition ne connaît ni `ctx`, ni la valeur éditée, ni
  l'enregistrement. Gardes : `test_the_layout_is_a_common_brick_the_kernel_mounts` (une seule
  maison : aucun code de grille dans le noyau, rien de la surface dans la disposition, chargée
  avant le noyau), les gardes existantes repointées sur le nouveau fichier (V8 sur la copie
  servie). Mesuré avant ET après sur un serveur jetable : `common.surface_layout` 9/9,
  `common.surface_stack` 19/19, parité de l'éditeur 71/71. ⚠ À froid, le premier scénario peut
  échouer à l'attente de 20 s (le serveur jetable met ~45 s à servir sa première adresse) :
  rejoué à chaud, il passe — un artefact de démarrage, pas une régression.
- **Étape ②, 2ᵉ geste — les SECTIONS DU VOLET des pages deviennent des panneaux ✅ 2026-10-28**
  (Fabien : « tu peux poursuivre les sections du volet »). L'assistant, le bloc de tête, Aperçu,
  Infos, Paramètres et Actions sont chacun un panneau de la disposition commune : on les réordonne,
  on les retaille, on les empile, on les épingle à un bord de la zone centrale (Paramètres en bas,
  sur toute la largeur, par exemple), et la disposition se garde par compte et PAR PAGE (la clé de
  page est l'espace de noms le plus proche de sa route : l'app, ou `common` pour le journal et le
  calendrier).
  - **Le rendu par défaut ne change pas** : tant que le compte n'a rien disposé, le volet reste
    celui d'avant et la grille n'est même pas chargée. Le cadenas du titre du volet (« Modifier la
    disposition du volet ») la monte ; figée sans geste, la disposition redevient au rechargement
    le volet d'avant. Une page disposée reçoit la grille tout de suite, pour ne pas sauter au
    chargement.
  - **La section est DÉPLACÉE telle quelle** dans son panneau : mêmes éléments, mêmes
    identifiants. L'inspecteur et les apps qui la remplissent n'en savent rien
    (`wama-inspector.js` n'est pas touché). Figée, la colonne garde l'allure du volet d'avant : ni
    fond ni cadre, le titre de la section.
  - **Hauteurs** : chaque section a une hauteur par défaut déclarée (`PANEL_SLOTS`, en rangées de
    46 px) ; son contenu défile dans le panneau, et l'utilisateur le retaille (la règle de toutes
    les briques, §3-ter : pas d'ajustement au contenu).
  - **Une section que la page masque retire son panneau** sans laisser de trou (l'aperçu et les
    infos, tant que rien n'est sélectionné), et il revient à son RANG, quel que soit l'ordre où la
    page montre ses sections (`setShown`). Retiré, il reste dans le document : l'inspecteur le
    retrouve par son identifiant.
  - **Une page qui a sa propre disposition ne reçoit pas celle-ci** : une surface (sa colonne est
    déjà une zone de sa grille) et le cam_analyzer (étape ③, « il déclare, il n'hérite pas »)
    déclarent `volet(…, arrangeable=False)`.
  - **Code** : `common/utils/volet.py` (`PANEL_SLOTS`, `page_key`, `layout_of`, `layout_config`),
    route `common:panel_layout` (`common/panel_views.py`, validée par `surfaces.clean_layout`, la
    règle des surfaces), `common/js/wama-panel-layout.js`. Le module de disposition gagne trois
    choses, sans changer les surfaces : une page SANS grille au centre (la colonne seule), l'endroit
    du cadre des bords (`frameHost`) et `setShown`.
  - **Gardes** : `tests_volet.PanelBricksTest` (11 tests : sections déclarées une fois au serveur,
    défaut sans grille, disposition par compte et par page, validation par la règle des surfaces,
    clé de page, pages exclues, V8), cinq contre-épreuves rouges ; scénario nocturne
    **`common.panel_layout`** (13 gestes sur le journal : ouvert tel qu'avant, colonne de panneaux,
    aperçu et infos retirés puis remis dans l'ordre, card cliquée, épinglé en bas entre le pied et
    le volet, gardé au rechargement et par « Disposition par défaut », rendu à la colonne, figé →
    le volet d'avant), quatre contre-épreuves rouges dans le navigateur (panneau détaché du
    document, rang ignoré, brique qui ne suit plus sa section, grille montée d'office). Non-recul
    des surfaces mesuré après : `common.surface_layout` 9/9, `common.surface_stack` 22/22, parité de
    l'éditeur 71/71.
  - ⚠ **Défauts trouvés en le faisant**, tous deux corrigés avant le commit : un panneau retiré
    sortait du document, et l'inspecteur ne retrouvait plus l'aperçu pour le remontrer ; et les
    infos revenaient AU-DESSUS de l'aperçu (l'inspecteur montre l'un puis l'autre, la grille posait
    le second sous le premier arrivé).
  - **Revérification du même jour** : le module chargeait la grille par son propre `loadScript`,
    la TROISIÈME copie privée du geste (après le chat de l'assistant et l'ajout à la
    médiathèque), et sa feuille comme la main virtuelle. Réunis dans la plomberie commune,
    `WamaApp.loadScript` / `WamaApp.loadStyle` (`wama-app-base.js`), les quatre appelants passés
    par eux, vérifiés au navigateur (le ⚙ du chat sur le journal, l'import de la médiathèque, la
    grille du volet) ; garde `tests_script_loader` (aucun JS de WAMA ne crée sa balise `<script>`
    ou `<link>`), contre-épreuve rouge par un fichier jetable.
  - **Pas fait** : replier une section (l'avatar a son propre repli, qui laisse alors un vide dans
    un panneau de hauteur fixe — on retaille le panneau) ; ouvrir un panneau dans une autre
    fenêtre (`WAMA_DATA_WORLD §8.2 ⑤`, la suite prévue).

- **Un panneau DANS UNE AUTRE FENÊTRE ✅ 2026-10-28** (`WAMA_DATA_WORLD §8.2 ⑤` ; Fabien : « on
  passe à l'ouverture d'un panneau dans une autre fenêtre ») — un second écran porte le transport,
  l'aperçu ou une vue pendant que la page reste sur le premier. Menu de l'épingle, « Dans une autre
  fenêtre » (pas sur un téléphone), pour tout panneau : d'une surface comme du volet.
  - **Le panneau est DÉPLACÉ, pas recréé** : la brique garde son code, son état et l'axe partagé ;
    rien n'est à synchroniser, d'où aucun canal entre fenêtres (le `BroadcastChannel` qu'envisageait
    `WAMA_DATA_WORLD §8.1` n°11 n'a pas servi). La fenêtre reprend le thème et les feuilles de la
    page, une barre la nomme et porte « Remettre dans la page ».
  - **Deux relais** : un geste fait dans la fenêtre (pointeur, clavier) est rejoué sur la page, où
    les briques l'écoutent — sauf une frappe dans un champ, qui reste au champ ; et la page retrouve
    par son identifiant un élément parti dans la fenêtre (l'inspecteur remplit l'aperçu du volet).
  - **Le retour** : fermer la fenêtre, ou « Remettre dans la page », rend le panneau à sa place —
    son rang dans la colonne, son bord s'il était épinglé ; « Disposition par défaut » rappelle
    toutes les fenêtres ; quitter la page les ferme. **Rien ne se garde** : un navigateur n'ouvre une
    fenêtre qu'au geste de l'utilisateur, une fenêtre ne peut donc pas se rouvrir au rechargement.
  - **Code** : `wama-brick-layout.js` (`openWindow`, `closeWindow`, `relay`, `findInWindows`),
    `wama-surface.css` (`body.wama-panel-window`).
  - **Vu au navigateur** : le transport de l'éditeur du transcriber dans une fenêtre — Espace frappé
    dans la fenêtre lance la lecture (horloge 0:01 / 1:00), il revient à la fermeture ; l'aperçu du
    volet du journal dans une fenêtre suit la card cliquée dans la page (un fichier puis l'autre),
    disparaît quand rien n'est sélectionné, revient à son rang (assistant, aperçu, infos).
  - **Gardes** : `PanelBricksTest.test_a_panel_opens_in_another_window_and_keeps_working` ;
    `common.panel_layout` **16/16** (fenêtre ouverte et panneau retrouvé, touche relayée mais pas
    une frappe de champ, retour au rang) ; trois contre-épreuves rouges dans le navigateur (relais
    retiré, identifiant non retrouvé, panneau non rendu). Non-recul : surfaces 9/9 et 22/22, parité
    de l'éditeur intacte.
  - ⚠ **Limites, connues** : un menu ouvert depuis la fenêtre (vitesse, choix d'une brique)
    s'ouvrirait dans la page — les outils de disposition y sont masqués, les menus propres d'une
    brique non ; une brique qui regarde où est le FOCUS dans la page (la liste des segments au
    clavier) ne suit pas le clavier de la fenêtre ; les animations de la fenêtre battent au rythme
    de la page — page réduite ou cachée, le navigateur les ralentit ; sur un écran d'une autre
    densité de pixels, un canevas dessiné pour la page peut paraître flou.

**À venir, dans cet ordre (le plus sûr d'abord)** : ~~② les sections du volet des PAGES D'APPS~~
(✅ ci-dessus) ; ③ le cam_analyzer, élément par élément, chacun en brique UNIVERSELLE (§5 : il
déclare, il n'hérite pas) ; ④ le centre des pages d'apps (card d'entrée, file) sur la même grille ;
~~ouvrir un panneau dans une autre fenêtre~~ (✅ ci-dessus).

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

**`home.html`** — ~~l'avatar vit en `right_panel_top` (`:14-25`), posé `display:none`, chargé
par **import dynamique au clic** (~6 Mo, une seule fois). ⚠ **Il n'est PAS persistant** :
son conteneur n'existe que dans `home.html` (`base.html` ne référence `wama-avatar` nulle
part), donc il **disparaît dès qu'on quitte l'accueil**. Ce qui persiste est son *état*, pas
sa présence.~~ ✅ **LIVRÉ le 2026-09-22 (demande de Fabien)** : le conteneur est dans
**`base.html`** (`common/_assistant_avatar.html`, en tête de **tout** volet, pour tout compte
connecté), la préférence est **DURABLE** (`assistant/params.py` : `avatar` — **actif par
défaut** — et `avatar_collapsed`, persistés par la route commune `ai_chat_settings` → brique
`user_settings`, lus sur chaque page par le context processor `assistant_avatar`), et le
comportement est la brique **`wama-avatar-panel.js`** : chargement à la demande **après** le
rendu de la page (`requestIdleCallback`), **repliable** par le chevron (replié = rien n'est
chargé), masquable par le bouton de l'assistant. `home.html` ne garde que la voix (`speakText`)
et ce bouton. L'importmap three.js est devenue globale du même geste (une par document).
Tenu par `tests_assistant_surfaces.AvatarPersistantTest`. ~~⚠ Il **parle** toujours depuis la
seule surface qui a un texte à dire (l'accueil) : ailleurs il est présent et silencieux.~~
✅ **Le soir même (22/09, demande de Fabien) : l'assistant SE PARLE depuis toute page.**
L'accordéon « Assistant » (le chevron replie **tout** d'un coup — préférence `avatar_collapsed`)
contient l'avatar et, hors accueil, un **mini-chat** (`wama-assistant-chat.js`) : même fil `web`
que l'accueil (`views.ai_chat_thread`, chargé à la demande), champ d'une ligne qui grandit
jusqu'à quatre puis défile, fil borné à 180 px, et un **bouton voix unique** 🔊/🔇/⏹ (brique
commune `wama-assistant-voice.js`, aussi câblé sur l'accueil) : pendant une lecture il
l'**arrête**, sinon il coupe/rétablit la voix — préférence durable `voice`. **Aucun réglage
dans le volet** : modèle, curseur et voix choisie se règlent sur l'accueil et valent partout
(durables) ; le volet n'affiche qu'un rappel en lecture seule de l'étiquette du dernier tour.
Sur l'accueil le partial ne rend que l'avatar (le chat complet est là). Cadrage mesuré : vue
buste, caméra rapprochée et relevée, 200 px. Smoke Playwright 8/8 (envoi réel compris).
Reste (§9 ①) : un seul chat — l'accueil devrait devenir la même brique en mode « complet ».
~~Et il s'ajoute au volet sans rien remplacer : les trois cadres inutiles restent
sous lui.~~ ✅ **Corrigé le 22/08** : l'accueil déclare `tete=True` + les trois sections à
`False` — le volet reste ouvert pour le seul avatar. C'est le cas d'usage qui a rendu la clé
`tete` nécessaire (un gabarit ne peut pas dire si son bloc libre est vide).
✅ **2026-10-18 (décision de Fabien) — les RÉGLAGES de l'assistant passent au volet, comme ceux
d'une app.** Ils encombraient la carte du chat de l'accueil (modèle, curseur, puis les deux pauses
de la voix). L'accueil déclare `parametres=True` : la section « Paramètres de l'assistant » rend
le schéma `assistant/params.py` (contexte `panel`, pauses repliées dans le groupe « Voix »,
`ParamGroup`). Et le mode SIMPLIFIÉ, où le volet est masqué, garde son chemin comme dans toute
app : la ⚙ du chat ouvre la modale COMMUNE (`WamaParams.settingsModal`, contexte `item`), servie
par la route de réglages (GET : schéma, groupes, valeurs ; POST : formulaire). La même ⚙ est sur
le mini-chat du volet, qui n'avait AUCUN accès aux réglages — la phrase « aucun réglage dans le
volet » ci-dessus disait vrai jusqu'à ce jour. Un identifiant par contexte : volet et modale
peuvent être rendus ensemble. Gardes : `tests_assistant_deposit_settings`, `tests_volet`.

**`filemanager`** — n'a **aucune** page étendant `base.html` ; il fournit la sidebar gauche
et, par accident d'histoire, le CSS du volet droit. Son « aperçu global » annoncé en
commentaire (`base.html:156`) **n'est câblé nulle part** : il utilise sa propre modale.

---

## 6. Code mort identifié

| Élément | Chemin | Constat |
|---|---|---|
| ~~`window.WAMA_RIGHT_PANEL`~~ | `base.html:203-256` | API complète (`showPreview`/`updateSettings`/…) — **0 appelant** · ✅ **retirée le 2026-10-20** avec son hôte `#preview-media` (`REMOVAL_LEDGER R31`) |
| ~~Copie de l'`<aside>`~~ | `filemanager/templates/filemanager/right_panel.html` (118 l.) | **jamais incluse** · ✅ **supprimée le 2026-10-20** (R31) |
| Gabarits intermédiaires | `common/app_base.html`, `accounts/base_form.html` | **rien ne les étend** |

---

## 7. Le mode simplifié — la tension non résolue

> ✅ **2026-10-10 (décision de Fabien) — le mode s'applique SUR PLACE.** Il renvoyait à l'accueil
> depuis toute autre page (`wamaToggleMode`, sans raison consignée — introduit dans un commit de
> mars sur un autre sujet), comportement implicite. Il masque désormais les volets là où l'on est
> (l'éditeur du transcriber s'en servait déjà comme « plein écran ») ; l'accueil simplifié reste
> à un clic par le logo WAMA, ce que dit l'infobulle du bouton. Les deux gestes coexistent sans
> se recouvrir : le **repli par la frontière** (§9 ②) est local à un volet et à un navigateur ;
> le **mode simplifié** est une préférence du profil qui change aussi l'accueil (chatbot).

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

⏳ **2026-10-26 — le RETIRER ? (question de Fabien, décision à prendre)** : *« le mode simplifié
masque les volets gauche et droit de façon stricte et ne permet pas de rouvrir un des deux à la
volée — il n'est pas aligné sur le repli des volets […] Je me demande même si à terme, le mode
simplifié ne devrait pas être retiré : il n'apporte plus grand-chose à part masquer les deux
volets d'un coup ; l'assistant permet déjà de glisser des fichiers. »* Constat au code :
`body.wama-simple` met les deux gouttières à 0 (`wama-panel-toggle.css:23`) sans passer par le
repli par la frontière (§9 ②), qui, lui, se rouvre d'un clic. Deux voies : (a) le RETIRER — le
repli des deux volets en tient lieu, l'accueil chatbot devient un choix d'accueil à part ; (b)
l'ALIGNER — « Simplifié » = replier les deux volets par le même mécanisme, chacun se rouvrant à
la volée. Un retrait passe par `REMOVAL_LEDGER` (trois surfaces : code, préférence du profil,
docs). Rien n'est touché avant la décision.

✅ **2026-10-27 — RETIRÉ (décision de Fabien, voie (a) avec ce que (b) gardait)** : *« on remplace
le bouton "Simplifié" par un switch qui masque les volets de chaque côté, juste avec une icône
représentative, aligné sur le fonctionnement de repli des volets latéraux permettant de les
rouvrir et fermer 1 par 1 […] et on ajoute dans l'assistant un bouton permettant d'ajouter des
documents directement […] Comme ça on conserve bien tout le fonctionnement en place, on réduit
l'occupation dans le header, on a plus 2 interfaces concurrentes sur la page d'accueil. »* Ce que
le mode faisait, et où cela vit désormais :
- **masquer les volets** → le bouton de l'en-tête (`[data-wama-panels-switch]`, une icône) :
  `WamaPanels.setAll` replie les deux, chacun se rouvre seul par sa frontière, le bouton reprend
  sa forme quand les deux sont rouverts ; en largeur étroite (un seul ouvert), il rouvre le volet
  droit, celui de l'assistant. L'assistant y passe aussi (`fold_side_panels`, qui remplace
  `switch_ui_mode`). Rien au profil : c'est le repli par navigateur, comme la frontière ;
- **les trois zones de dépôt de l'accueil** → « Joindre » (trombone) dans les DEUX chats : le
  sélecteur du système (galerie et appareil photo sur un téléphone), puis le dépôt commun du
  glisser — l'assistant demande quoi en faire et sait ranger en Médiathèque
  (`tool_api.add_to_media_library`) ou lancer le Reader. C'était le seul geste que le mode
  rendait indispensable : sur un téléphone, ni glisser ni explorateur ;
- **l'usage sur un téléphone** → le contexte étroit (volets repliés d'office, §9 ⑤) : mesuré par
  le scénario nocturne `common.layout.phone` (390 px : saisie utilisable, « Joindre » par le vrai
  sélecteur, envoi intercepté, bouton des volets) ;
- **la préférence** → un navigateur qui l'avait choisie retrouve une fois ses volets repliés
  (amorce de `base.html`, `wama_ui_mode` traduit puis oublié).
Retraits : `REMOVAL_LEDGER R182`. Gardes : `tests_panel_toggle` (`SimplifiedModeRetiredTest` —
aucune trace du mode dans le code —, le bouton et la reprise du mode joués en V8),
`tests_assistant_reach.SidePanelsFromTheAssistantTest` (l'outil, l'action du chat, « Joindre »
en V8), `common.layout.phone` ; huit contre-épreuves rouges. La colonne `ui_mode` est partie en
deux temps : hors du modèle par `accounts/0030` (défaut en base, le serveur en service la lisait
encore), puis supprimée par `accounts/0031` après la relance.

---

## 8. Suites possibles — ordre conseillé, rien d'engagé

| # | Chantier | Pourquoi cet ordre |
|---|---|---|
| 1 | ~~**Bandeau manquant** sur 8 pages~~ → **✅ FAIT autrement (22/08)** | Le diagnostic était faux : pas un `include` à ajouter mais **un chemin oublié** dans la brique. Voir §4① — l'`include` aurait REVERTÉ le retrait décidé le 07/08 |
| 2 | ~~**Déclaration des sections**~~ → **✅ LIVRÉ (22/08)** | Défaut inchangé ⇒ zéro régression pour les apps ; **17 pages et 54 cadres** retirés (§3-bis) |
| 3 | ~~Double instance `enhancer`/`imager`~~ → **✅ FAIT (22/08)** | Traité avec ① : même brique, même passe de validation (§4②) |
| 4 | **Portage depuis `model_manager`** vers la brique | Bandeau paramétrable · restauration du hint · `detailSchema`/`actionsSchema` · `ids.actionButtons` |
| 5 | ~~**Assistant dans le volet** (conteneur en `base.html`, préférence au profil)~~ → **✅ LIVRÉ pour l'AVATAR (22/09)** : conteneur en `base.html`, préférence durable dans les réglages de l'assistant (pas au profil : même chemin que le modèle et le curseur), actif par défaut, repliable — voir §5 `home.html` | Rend l'avatar réellement persistant. ⚠ Ce qui reste : la **conversation** transversale (le chat vit encore dans `home.html` seul), et la tension du mode simplifié (§7) |
| 6 | Hygiène : CSS du volet vers `common/`, retrait du code mort (§6) | Mécanique, sans risque, mais sans valeur d'usage |
| 7 | **Explorateur : regrouper les apps par MONDE** (`media` / `lab` / `data`) + **changer d'app en cliquant son dossier** | Décidé 2026-08-25 avec l'UI du monde Data (`WAMA_DATA_WORLD.md §11.8 ⑦`) ; la catégorie `media` attend que les UI lab/data existent |
| 8 | **Tri / filtrage / recherche dans l'explorateur** | Inexistant aujourd'hui ; ⭐ pour le monde Data c'est un filtrage par **AXES du plan d'expérience** (`WAMA_DATA_WORLD.md §13`) — une seule brique pour les deux mondes, pas deux tris |

⚠ **NE PAS réécrire `wama-inspector.js`.** `PROJECT_STATUS.md:1320-1349` documente deux
correctifs de ce fichier **entièrement revertés** — c'est la brique la plus consommée du
dépôt (14 pages), toute modification y est transverse par construction.

---

## 9. Questions ouvertes

1. **Assistant vs inspecteur dans le même volet** — le double usage peut dégrader l'UI/UX.
   Piste de Fabien : n'y garder que **l'avatar en tête** (discussion naturelle + guidage),
   avec une capacité nouvelle — **amener l'utilisateur sur la page qui convient** à sa
   demande. À réfléchir.
2. ~~**Repli élégant des volets à la volée** — souhaité, sans le « gros bouton » déjà essayé
   puis retiré parce qu'il polluait l'UI.~~ ✅ **LIVRÉ le 2026-10-10 (demande de Fabien)** —
   brique `WamaPanels`, montée par `base.html`, aucune app ne l'appelle. **Le geste est la
   frontière elle-même** : au repos rien de plus que le liseré ; au survol (après 0,12 s, pour
   qu'un pointeur qui passe ne fasse rien clignoter) une ligne et une pastille à chevron qui
   suit le pointeur ; clic = repli animé (0,22 s), la zone centrale et l'en-tête prennent la
   place. Volet replié : une trace fine au bord de la fenêtre le rouvre. Bouton accessible
   (clavier, `aria-expanded`). Au **doigt**, la pastille reste visible (mesure tablette du
   même jour : un geste qui n'existe qu'au survol n'existe pas au doigt). État par
   **navigateur** (localStorage — replier sur la tablette ne replie pas le poste de bureau),
   appliqué avant le premier rendu. Après chaque bascule, `resize` + `wama:panels` : cards v3,
   liens du studio et carte Leaflet se recalent sans rien connaître de la brique. Volet droit
   replié : l'avatar ne se charge pas, et l'indication « Réglages » de la card d'entrée devient
   « Réglages : afficher le volet », qui le rouvre. **Mesuré au navigateur** : zone centrale
   860 → 1500 px (1500 × 1000), canvas du studio 624 → 1264 px, liens à 0,08 px de leurs ports,
   tablette portrait 394 → 834 px. Gardes : `wama/common/tests/tests_panel_toggle.py`.
3. **Mode simplifié** — cf. §7.
4. **Trois états plutôt que deux** pour l'assistant (toujours visible / replié quand le
   contexte prime / jamais) — évite de choisir entre « perdu partout » et « encombrant ».
5. **Les volets à largeur de tablette** — partie mise en page du chantier tablette
   (`ROADMAP §27`, relevé du 2026-10-10, iPad Pro 11 émulé). **Mesuré, volets ouverts** : zone
   centrale 346 à 394 px sur 834 en portrait selon la page, 626 sur 1194 en paysage ; canvas du
   studio 158 px en portrait (438 en paysage), inutilisable. En portrait, la barre du haut se
   chevauche (« WAMA » sur « Simplifié », « Panneau » sur le nom du compte).
   ✅ Le **repli manuel** (question 2) rend 834 px au centre.
   ✅ **LIVRÉ le 2026-10-12** (`ROADMAP §27` étape 2) — le repli d'office et les deux barres :
   - **Deux contextes de largeur.** Sous le point de rupture `lg` de Bootstrap (992 px, lu dans
     sa feuille, `--bs-breakpoint-lg` — pas un nombre à nous) : volets **repliés d'office**,
     **un seul ouvert** (en ouvrir un replie l'autre), **mémoire à part**
     (`wama_panel_<côté>_narrow`). Le choix fait en grand n'est jamais écrit depuis le contexte
     étroit : il revient tel quel à la rotation en paysage, et l'étroit retrouve le sien au
     retour. Une seule écriture de la règle : `WamaPanelsContext`, posé par l'amorce de
     `base.html` avant le premier rendu, que la brique relit quand la largeur change.
     ⚠ La LARGEUR, pas le pointeur : une fenêtre étroite à la souris a le même problème de place
     qu'une tablette ; le pointeur décide de la taille des cibles (`wama-touch.css`), la largeur
     décide de la place des volets.
   - **Pousser, pas recouvrir — décision prise à la conception.** La note d'origine disait
     « volets en tiroir ». Un tiroir recouvre le centre ; or deux gestes centraux exigent un
     centre VIVANT pendant que le volet est ouvert : glisser de l'explorateur vers l'app
     (`filemanager.js:261`), et cliquer une card pour remplir l'inspecteur. Le volet ouvert
     pousse donc la zone centrale, comme en grand, et l'exclusivité garde au centre 594 à 634 px
     (portrait). Aucun voile, aucune fermeture « au clic dehors » : elle aurait refermé le
     panneau à chaque card cliquée.
   - **La barre du haut** était trois blocs, le logo posé en ABSOLU au centre : rien ne
     l'empêchait de recouvrir ses voisins, et il les recouvrait **dès 1 280 px de bureau**
     volets ouverts (« WAMA » sur « Simplifié », 71 px), pas seulement en tablette (la droite y
     débordait de 97 px sur le volet). Désormais une grille `1fr auto 1fr` : le logo reste au
     centre tant que les côtés y tiennent, se décale sinon, ne recouvre jamais. La barre est un
     **conteneur** (sa largeur n'est pas celle de la fenêtre : elle se loge entre les volets) et
     ses libellés s'effacent derrière leur icône, du moins utile au plus utile — le mode
     (720 px), le nom du compte (580), « Applications » (440) —, masqués à l'œil seulement (forme
     `.visually-hidden` de Bootstrap : le lecteur d'écran les lit toujours). Nom du compte borné
     à 16 caractères.
   - **Le pied**, même défaut, même remède : les ressources système, posées en absolu, couvraient
     le titre centré dès 834 px ; grille `1fr minmax(0, auto) 1fr`, le titre s'abrège au besoin.
   **Mesuré**, 6 pages × 6 profils (iPad Pro 11 portrait et paysage, iPad mini portrait,
   bureau 1 280 / 1 024 / 900) : **0 chevauchement** dans la barre (avant : 33 combinaisons sur 36 — seule la médiathèque, sans
   volet droit, y échappait en grand), **0
   recouvrement** au pied, 0 défilement horizontal, 0 erreur console ; centre en portrait **394
   → 834 px** (studio : canvas pleine largeur, il en avait 158). Barre seule balayée de 320 à
   820 px, nom réel puis nom en lettres larges : aucun chevauchement. Gardes :
   `tests_panel_toggle` (l'amorce PUIS la brique, jouées dans V8 sur la même mémoire) et le
   scénario nocturne **`common.layout.tablet`** (`ui_smoke_layout.py` : portrait → paysage →
   portrait, puis bureau), vérifié **rouge** sur l'ancienne mise en page réinjectée (barre 77 px,
   pied 170 px).
   ⏳ Ce qui reste hors de cette étape : un téléphone (sous ~600 px, un volet ouvert laisse peu
   au centre — hors du périmètre tablette), et les gestes (`ROADMAP §27` étape 3).
   ✅ *2026-10-28* : le téléphone et les grands écrans sont mesurés chaque nuit —
   **`common.layout.screens`** (`ui_smoke_layout.py`, 8 écrans de 3 440 px en 21:9 à 390 px ×
   l'accueil, le journal, le calendrier et chaque app découverte), les mesures de
   `common.layout.tablet` plus tout élément VISIBLE hors de l'écran. Au téléphone, le pied ne
   garde que les pourcentages des ressources (son titre laisse sa place). Relevé, défauts trouvés
   et corrigés : `ROADMAP §27`.

## Voir aussi
- `WAMA_DATA_WORLD.md §11.8` — l'UI du monde Data hérite de la file Médias ; les évolutions ⑦ du
  volet gauche (regroupement par monde, clic-pour-changer-d'app) sont décidées là et tracées §8.
- `INSPECTOR_DETAIL_FIELDS.md` — schéma canonique des champs de détail (contenu, pas structure).
- `WAMA_LLM.md §1` — contrat de surface de l'assistant (le tour ne porte jamais d'audio).
- `CARD_DESIGN.md` — anatomie des cards, source de la sélection qui nourrit l'inspecteur.
