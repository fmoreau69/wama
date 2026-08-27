# WAMA — Vérification : grille d'ADOPTION et grille FONCTIONNELLE

> **Référence unique du domaine « comment on sait que ça marche ».** Décidé avec Fabien le
> 2026-08-22. Ne PAS créer de document concurrent : la grille de conformité est décrite dans
> `WAMA_APP_CONVENTIONS.md` (ses critères), la charpente nocturne dans `PROJECT_STATUS.md §Tests
> fonctionnels nocturnes` (son runner) — **ce fichier-ci tient la DOCTRINE** : qui prouve quoi,
> ce qui reste non prouvé, et dans quel ordre on comble.

---

## 1. Le constat qui a déclenché ce document

Le 2026-08-22, deux défauts ont été trouvés **le même jour**, tous deux invisibles à la grille :

| Défaut | Ce que la grille en disait | Ce que le clic a dit |
|---|---|---|
| **anonymizer** — `paramName` absent : le fichier n'arrivait jamais, **400 pour tous les utilisateurs** | verte sur ses critères d'import : le markup était là, la brique était là | scénario `.import` ROUGE — rien n'était créé |
| **converter_01** — bloc `app_scripts` non émis : aucun JS chargé, aucun écouteur | verte (et de toute façon **jamais notée** : les jumelles bac à sable sont exclues du run global) | 0 card créable par 5 voies, **zéro erreur console** |

**La grille n'avait pas tort — elle mesurait autre chose.** Elle atteste que l'app a *adopté* la
brique commune. C'est une propriété réelle et utile (l'homogénéité est un objectif de design,
philosophie §2), mais ce n'est **pas** une preuve de fonctionnement. Confondre les deux, c'est
lire « vert » là où l'utilisateur voit un écran mort.

> ⚠ Corollaire opérationnel, appris le même jour : **la grille ne note jamais une app de bac à
> sable** dans un run global (`non_sandbox_apps`). Un critère écrit pour attraper le défaut de
> converter_01 ne pouvait donc structurellement pas l'attraper. On peut la noter explicitement —
> `check_app_conformity --app converter_01` fonctionne (mesuré : 39✅/3🔶/21❌ sur 63 → 64 %) —
> mais il faut le vouloir.

---

## 2. Deux grilles, deux prétentions — à ne jamais confondre

| | **Grille d'ADOPTION** (existante) | **Grille FONCTIONNELLE** (à bâtir) |
|---|---|---|
| Question | « cette app utilise-t-elle la brique commune ? » | « ce geste utilisateur produit-il l'effet attendu ? » |
| Instrument | `check_app_conformity` — analyse statique du code | scénarios nocturnes — Playwright, clics réels |
| Coût | secondes, aucun service requis | minutes, exige serveur + base (+ parfois GPU) |
| Source | `common/services/conformity_checker.py` | `common/services/nightly_tests.py` + `ui_smoke.py` |
| Sortie | `logs/conformity_report.json` → `/apps/` | `logs/nightly_tests/nightly_*.json` → **à câbler** |
| Prouve | l'homogénéité | le fonctionnement |
| Ne prouve PAS | que ça marche | que le code est homogène |

**Règle de lecture, à appliquer partout :** *un critère de grille atteste une ADOPTION, jamais un
FONCTIONNEMENT ; seul un scénario qui exécute le geste le prouve.* Quand on annonce un résultat,
préciser lequel des deux on cite.

---

## 3. Catalogue des gestes — il existe déjà, il n'est pas exécutable

Le catalogue n'est **pas à inventer** : c'est la table des composants obligatoires de
`CLAUDE.md` (§Conventions UI) + les voies d'import. Il faut le rendre *exécutable*.

| # | Geste utilisateur | Scénario aujourd'hui | Traitement requis |
|---|---|---|---|
| 1 | Déposer un fichier → une card apparaît | ✅ `<app>.import` | non |
| 2 | Ouvrir les paramètres d'un item, modifier, enregistrer, relire | ⚠️ **MOITIÉ** — `<app>.settings` (23/08) prouve l'OUVERTURE ; modifier/enregistrer/relire reste dû | non |
| 3 | Dupliquer un **élément** (`.duplicate-btn`) | ✅ `<app>.duplicate_delete` | non |
| 3b | Dupliquer un **lot** (`.batch-duplicate-btn`) | ✅ `<app>.batch_actions` (23-24/08) | non |
| 4 | Supprimer un **élément** (`.delete-btn`) | ✅ `<app>.duplicate_delete` | non |
| 4b | Supprimer un **lot** (`.batch-delete-btn`) | ✅ `<app>.batch_actions` (23-24/08) | non |
| 5 | Tout effacer | ❌ | non |
| 6 | Sélectionner une card → l'inspecteur se remplit | ✅ **ENTIER** — `<app>.inspector_actions` (28/08) : remplissage du volet Actions **et** refermeture par le ✕, sur les deux portées (card **et** card mère de lot), **20 chemins / 20** sur 10 apps | non |
| 7 | **Créer par le bouton primaire** (apps `data-wama-depot=attache` : avatarizer, imager) | ❌ | **oui sauf imager** — mesuré 27/08 : composer expédie la tâche DANS sa vue de création (`composer/views.py:235`) et avatarizer enchaîne `createJob()` puis `startJob()` (`avatarizer/js/index.js:253-254`) |
| 8 | Démarrer un item → RUNNING → SUCCESS | ❌ | **oui** |
| 9 | Arrêter / relancer (bouton de cycle) | ❌ | **oui** |
| 10 | Progression : % et ETA visibles et qui avancent | ❌ | **oui** |
| 11 | Aperçu du résultat (clic → visionneuse) | ❌ | **oui** |
| 12 | Télécharger le résultat | ❌ — ⚠ le MARKUP est prouvé (critère `download_wiring` 12/12 + pages 200), le TRANSFERT non : le compte de test ne possède aucun élément traité, donc `download/<pk>/` lui répond 404 — **le scoping qui fonctionne**, pas une panne | **oui** |
| 13 | Démarrer tout / télécharger tout (lot) | ❌ | **oui** |
| 14 | Import dossier récursif · URL · **fichier de lot** · « Envoyer vers » | ⚠️ **QUART** — `<app>.batch_import` (27/08) prouve le **fichier de lot** ; récursif, URL et « Envoyer vers » restent dus | non |

**Couverture mesurée le 2026-08-22 : 1 geste sur 16.** Les deux seuls scénarios par app sont
`<app>.ui` (santé de la page : 200 + zéro erreur console — aucun geste) et `<app>.import`.
**Au 2026-08-23 : 3 gestes et demi sur 16** (import ; dupliquer + supprimer ; ouverture des
paramètres). Chaque ajout se paie en minutes de passage nocturne, pas en lignes de code par app :
les trois scénarios partagent le même montage de fixture et le même filet ORM de nettoyage.
**Au 2026-08-27 : 6 gestes et demi sur 16** — les actions de LOT (3b/4b, `<app>.batch_actions`)
et la SÉLECTION (6, `<app>.inspector_actions`) s'y ajoutent. La table ci-dessus portait encore
❌ sur 3/3b/4/4b alors que le paragraphe juste en dessous les comptait : une table et sa prose
qui divergent dans le MÊME fichier, c'est le mode de dérive que ce document est censé traquer.
**Au 2026-08-27 (soir) : 6 gestes trois quarts sur 16** — le FICHIER DE LOT (quart du geste 14,
`<app>.batch_import`) s'ajoute. Fraction assumée : trois des quatre voies d'import du geste 14
restent dues, et les annoncer couvertes serait le faux vert que ce document traque.

> ⚠ **`<app>.settings` mesure la MOITIÉ du geste 2, et le dit dans son propre détail** (« MOITIÉ
> DU GESTE — modifier/enregistrer/relire n'est PAS mesuré ici »). Ce n'est pas de la modestie :
> enregistrer déclenche selon les apps une **relance de traitement**, donc du GPU — ce qui range
> la seconde moitié avec les gestes 8-13, à traiter sur le converter en CPU (§4). Un scénario qui
> promet plus qu'il ne mesure est pire qu'absent : il éteint la question.

> ⚠ **Élément et lot sont DEUX gestes, pas un** (précision de Fabien, 22/08 — la première version
> de cette table les confondait). Ils n'ont pas la même difficulté, et c'est ce qui les rend
> tous deux intéressants :
> - le **lot** est uniforme *par construction* — ses boutons vivent dans le partial commun
>   `_batch_card.html` (`.batch-duplicate-btn`, `.batch-delete-btn`, `data-batch-id`) ;
> - l'**élément** repose sur une **convention de nommage tenue par discipline** — `.duplicate-btn`
>   et `.delete-btn` sont réécrits dans le gabarit de card de CHAQUE app (`anonymizer/_media_card.html`,
>   `transcriber/_transcript_card.html`, `converter/_job_card.html`…). Vérifié identique sur ces
>   trois, mais rien ne le garantit : c'est exactement l'homogénéité qu'aucune analyse statique
>   ne prouve et qu'un clic mesure.
>
> **À ne pas confondre avec le geste n°7.** Le « bouton primaire » (`primary_btn_id`, déclaré dans
> l'include de la card d'entrée — `btn-generate` avatarizer, `generateBtn` composer,
> `imgGenerateBtn`/`vidGenerateBtn` imager) sert à **créer** un élément quand le dépôt ne suffit
> pas. Dupliquer et supprimer agissent sur un élément **déjà créé**. Trois gestes indépendants.

> Illustration prise sur le vif le même soir : la normalisation `job_id`→`id` de l'**avatarizer**
> n'a **pas pu être prouvée**, parce que `avatarizer.import` SKIPPE (son dépôt joint le fichier,
> c'est le bouton primaire qui crée — geste n°7) et que `avatarizer.ui` n'atteste que la page.
> Le correctif est sûr, il n'est pas *mesuré*. C'est le geste n°7 qui manque, pas le correctif.

### Geste 6 — la SÉLECTION, angle mort du nocturne jusqu'au 2026-08-27

> **Six scénarios coexistaient sans qu'aucun n'emprunte le chemin de la sélection.** `batch_actions`
> clique les **boutons** de la card ; or ce sont `selectItem` / `selectBatch` qui appellent
> `renderItemActions` / `renderBatchActions` et remplissent le volet. Deux défauts sont donc passés
> au travers, **tous deux MUETS** :
> - le contrat **inversé** de `renderBatchActions` — `TypeError` au clic sur une card mère, dans
>   4 apps, **atteint sur le compte de Fabien** (26/08) ;
> - l'**imager** ne déclarait AUCUN des deux rappels : `fillActions` fait `if (renderFn)`, donc le
>   volet restait **vide sans erreur ni journal**.
>
> **Un volet vide ne plante pas** — ce qui ne plante pas ne se signale pas : ni erreur, ni journal,
> ni page rouge. Seule une assertion peut le voir.

**Ce que `<app>.inspector_actions` mesure** — sélectionner une card, puis une card **mère de lot**,
et exiger que `#inspectorActions` porte **au moins un bouton**. Les deux portées sont mesurées
séparément et rapportées séparément : un chemin non mesurable est écrit « NON MESURÉ — *raison* »
et n'emporte jamais l'autre.

**Couverture mesurée le 2026-08-27** (14 apps) : **7 mesurées** (anonymizer, converter, describer,
enhancer, reader, synthesizer, transcriber) ; **3 non mesurables** (avatarizer, composer, imager —
file vide pour le compte de test **et** l'app ne sait pas grouper : c'est le geste n°7 qui manque
là aussi) ; **4 hors périmètre** (converter_01, media_library, model_manager, studio — pas de volet
`#inspectorActions`, apps non portées ou non-files).

**Contre-mesure APRÈS commit** (`--id .inspector_actions,.batch_actions`, 28 scénarios →
**12 OK / 0 échec / 16 skips**, rapport `logs/nightly_tests/nightly_20260827_171014.json`) :
`batch_actions` est mesuré sur **5** apps (anonymizer, converter, describer, reader, synthesizer),
**non mesurable** sur **6** (les 3 ci-dessus + enhancer, transcriber, converter_01) et **hors
périmètre** sur 3.

**Reprise du même relevé le 2026-08-27 au soir, une fois le montage de fixture passé par la voie
de LOT** (§ geste 14 ci-dessous) : **17 OK / 3 échecs / 8 skips** sur les mêmes 28 scénarios —
`.inspector_actions` **10 OK / 0 échec / 4 skips** (`nightly_20260827_190935.json`),
`.batch_actions` **7 OK / 3 échecs / 4 skips** (`nightly_20260827_190507.json`). Les skips sont
**divisés par deux** (16 → 8) et les 8 restants ne disent plus que « surface absente ».
⚠ **Les 3 échecs sont un GAIN, pas une régression** : avatarizer, enhancer et imager n'émettent
pas `['del','dup','start']` sur leur card mère — `actions_communes=True` n'y est pas adopté.
C'était déjà vrai ; c'était seulement **invisible**, caché derrière un skip. Un skip qui devient
un échec est la mesure qui progresse, pas l'app qui recule.

**Les 3 échecs sont SOLDÉS le 2026-08-27 (nuit)** — `actions_communes=True` adopté sur les trois :
`.batch_actions` **10 OK / 0 échec / 4 skips** (`nightly_20260827_235842.json`) et `.batch_import`
inchangé à **9 / 0 / 5** (`nightly_20260827_235409.json`). Les 4 skips restants sont **structurels**
(converter_01, media_library, model_manager, studio — aucune surface de lot), pas des trous d'app.
Le portage a été atomique par app : la card mère émet `data-batch-{delete,duplicate,start}-url`
et les handlers locaux disparaissent dans le MÊME geste, faute de quoi chaque clic postait deux fois.

> ⚠⚠ **Une correction de portage a produit un message d'erreur qui désignait le mauvais maillon.**
> `enhancer.batch_import`, vert une heure plus tôt, est tombé sur
> « *Unexpected token '<', "<!DOCTYPE "... is not valid JSON* ». Le message accuse un **endpoint**
> qui rendrait du HTML — 302 de login, page 500. La cause était **trois lignes de commentaire** :
> `{# … #}` posé sur **deux lignes**. Le lexer de Django n'est pas en DOTALL, donc ce n'est pas un
> commentaire : le texte est **émis littéralement**, ici au milieu de `window.ENHANCER_APP = {…}`
> → `SyntaxError` → l'objet de config n'existe jamais → `fetch(undefined)` retombe sur la page
> courante, qui répond du HTML. Aucun endpoint n'était en cause. **Un message d'erreur nomme le
> lieu où le symptôme SORT, jamais le lieu où la cause ENTRE** — et un défaut de gabarit peut
> ressortir en erreur réseau.
>
> C'est la **8ᵉ récidive** du commentaire multi-ligne. La contre-mesure du jour a fonctionné :
> `manage.py check_templates` a nommé les 3 défauts, fichier et ligne, en une commande — là où les
> sept précédentes se sont payées en heures de diagnostic. Une règle qui demande de se souvenir
> n'est pas un contrôle ; celle-ci l'est devenue.

> ⚠ **Zéro échec ne veut pas dire couvert : 16 des 28 scénarios SAUTENT.** C'est précisément ce
> que ce document appelle prendre une adoption pour un fonctionnement — sauf qu'ici le skip est
> **explicite** : il nomme le maillon manquant (« deux dépôts n'ont créé aucun LOT », « aucune en
> file ») et renvoie à `<app>.import`. Un skip qui dit pourquoi est une **liste de travail** ;
> un skip muet serait un faux vert.

> ⚠ **Le chemin « card mère » n'existe pas sans lot multi-éléments**, et le compte de test n'en
> possédait presque aucun (relevé : **4 lots multi sur 10 apps, tous comptes confondus**). Premier
> passage : 3 OK / 7 « file vide » — le chemin qui portait le contrat inversé restait **non mesuré
> dans un scénario écrit pour lui**. Le scénario monte donc son lot quand il manque, sous une garde
> qui retire en sortie **ce qu'il a créé et rien d'autre** (différence d'ids). Un scénario vert sur
> un chemin non emprunté est exactement ce que ce document appelle une adoption prise pour un
> fonctionnement.

> ⚠ **Cinq défauts d'INSTRUMENT ont été trouvés avant d'accuser une seule app** — trois sur
> `batch_actions` (URLs cherchées sur la mère et non sur les boutons…), deux sur celui-ci :
> les cards filles vivent dans un `.collapse` **replié** (taille nulle → « aucune card en file »
> sur des apps qui en avaient) ; et sur le **reader**, la file **se re-rend seule** (~1 requête/s
> tant qu'un élément est PENDING — 19 requêtes en 4 s au relevé), ce qui **efface le marqueur** posé
> sur la cible et fait reparaître le nœud en pleine animation `wama-fan-in` : Playwright, qui exige
> un élément « stable », tournait jusqu'à expiration. Le scénario tente donc le **clic réel**
> d'abord et, à défaut, un **clic DOM** qui bouillonne jusqu'à la délégation — en le **disant dans
> son détail** (`[clic DOM — …]`). Une mesure faible qui se présente comme forte serait pire que
> pas de mesure.

**La seconde moitié du geste 6 — la DÉSÉLECTION — est mesurée depuis le 2026-08-28** :
**10 OK / 0 échec / 4 skips**, **20 chemins sur 20** (10 apps × card + card mère),
`nightly_20260828_010227.json`. Elle est **greffée** sur `<app>.inspector_actions` et non écrite en
scénario jumeau : le coût d'un scénario de file est le **montage du lot** (10–25 s), jamais les
clics. Ce qui est exigé après le ✕ : volet Actions **vidé** ET surbrillance **retirée** — les deux,
car un seul des deux nettoyages suffit à laisser une **sélection fantôme** (défaut du 22/08), où les
actions du volet désignent un élément que l'utilisateur ne voit plus sélectionné.

> ⚠⚠ **Deux défauts d'instrument de plus — 7 en tout dans cette famille, et toujours avant
> d'accuser une app.**
> - **6ᵉ — un clic réel atterrit au CENTRE de l'élément marqué, pas sur l'élément marqué.** La
>   cible « lot » pouvait être un **conteneur** dont le centre est occupé par un enfant que la
>   délégation IGNORE (bouton, aperçu) : le clic part, rien ne se passe, et l'instrument écrivait
>   « le volet reste VIDE — callback absent » sur le **converter**, seule app à écrire son propre
>   emballage `.batch-group` autour de l'en-tête ET du repli des filles (partout ailleurs,
>   `.batch-group` **est** la card mère). L'app n'avait rien : un clic sur son en-tête remplissait
>   le volet, console vide. `CIBLE` vérifie désormais par `elementFromPoint` que le point de clic
>   résout bien l'hôte visé — on mesure le contrat au lieu de le supposer.
> - **7ᵉ — chercher le ✕ juste après le clic mesure la LATENCE de la requête de détail.** Le ✕ de
>   l'item n'est pas rendu par le clic mais par `fillDetail`, à l'arrivée de
>   `/common/detail/<app>/<pk>/`. On attend son apparition, bornée à 4 s ; l'absence reste un vrai
>   constat.
>
> **Et un vrai défaut d'app, que ces deux-là masquaient** : sur le **transcriber**, un élément créé
> par **fichier de lot** naît `audio=''` (`views.py:1339` — le fichier n'est téléchargé qu'au
> lancement), or sa card ne portait `data-preview-url` que `{% if elem.audio %}`. Sans cette URL,
> `fillDetail` abandonne **avant même d'émettre la requête** : ni volet Infos, ni ✕. Ces éléments
> étaient **sélectionnables et non inspectables**, dans l'app de référence. L'URL est désormais
> portée par la card elle-même. ⚠ **Indexer le DÉTAIL sur une affordance d'APERÇU le rend absent
> partout où il n'y a pas encore de fichier** — c'est la brique commune qui le décide
> (`wama-inspector.js:571`), donc le piège attend chaque app qui diffère son téléchargement.

### Geste 14 (fichier de lot) — il a pris la place du geste 7, qui s'est révélé être un geste GPU

> **Le plan annonçait le geste n°7.** Il devait débloquer d'un coup `batch_actions` et
> `inspector_actions` sur les trois apps à file vide (avatarizer, composer, imager). En le
> préparant, on a mesuré qu'il **déclenche un traitement** : le composer expédie la tâche DANS sa
> vue de création (`composer/views.py:235`) et l'avatarizer enchaîne `createJob()` puis
> `startJob()` (`avatarizer/js/index.js:253-254`). Seul l'imager crée sans lancer. Le geste 7
> rejoint donc la famille 8-13 — **jamais exécutée par une session** (§4) — et c'est le **fichier
> de lot** qui atteint le même but par la seule voie dont le CONTRAT sépare créer et démarrer :
> `#batchCreateOnlyBtn` crée des éléments PENDING, `#batchCreateAndStartBtn` est l'autre bouton et
> n'est jamais cliqué. ⚠ **Un substitut ne vaut que si son CONTRAT, et pas seulement son effet
> observé, exclut le traitement.**

**Ce que `<app>.batch_import` mesure** — télécharger le gabarit que l'app **publie**, le déposer,
cliquer « Ajouter », et exiger qu'un lot apparaisse en file sans qu'aucun démarrage soit émis. Le
gabarit n'est jamais fabriqué par le scénario : un fichier inventé mesurerait *notre* lecture du
formalisme — trois syntaxes coexistent (balises CLI, tableur à en-têtes, positionnel `|`) — au lieu
de ce que l'app propose réellement à ses utilisateurs.

**Couverture mesurée le 2026-08-27** (14 apps, `nightly_20260827_190038.json`) : **9 OK / 0 échec /
5 skips**. Les 9 apps qui exposent la surface passent (anonymizer, avatarizer, composer, converter,
describer, enhancer, imager, reader, transcriber) ; les 5 skips nomment l'absence de surface —
`show_batch_bar` non déclaré (converter_01, media_library, model_manager, studio), pas de
`batch_template_url` publié (synthesizer).

> ⚠ **Six défauts ont été trouvés en exerçant ce SEUL geste, et aucun n'était visible par lecture :
> tous étaient MUETS à l'écran.**
> 1. **La brique commune ne s'initialisait pas** quand une app l'instancie depuis son propre
>    `DOMContentLoaded` — l'événement était déjà émis et ne repasse jamais. « Ajouter » et
>    « Démarrer » étaient **morts sans une seule erreur console**, sur toutes les apps de cette
>    forme. Corrigé dans la brique (garde `readyState`), jamais dans les apps.
> 2. **La brique jetait le diagnostic du serveur** : un lot refusé ligne à ligne répond
>    `success: true, count: 0, warnings[]` — la page se rechargeait à l'identique, sans un mot.
> 3. **avatarizer** appelait `/avatarizer/undefinedpreview/` (404) et déclarait `batchExts` là où
>    la brique lit `batchExtensions`.
> 4. **anonymizer** routait le `.txt` de lot vers son téléverseur de médias, qui répondait 200 avec
>    une erreur par ligne — dans un `console.warn`.
> 5. **converter** publiait un gabarit dont les cinq lignes d'exemple étaient **commentées** :
>    inerte par construction.
> 6. **`build_batch_template`** posait une ligne d'en-têtes même à UN seul champ — or
>    `_parse_media_lines` ABANDONNE le fichier entier à la première ligne non conforme, et
>    l'en-tête est la première.

> ⚠ **Et trois défauts de l'INSTRUMENT, chacun accusant une app à tort** — les compter à part n'est
> pas une coquetterie : c'est ce qui sépare « l'app est cassée » de « ma mesure est cassée ».
> - La card d'entrée est servie **repliée** par 6 apps sur 9 (`[data-nic-toggle]`) : bouton
>   invisible → lu comme « l'app refuse le lot ».
> - `get_test_user()` appelé sous `sync_playwright` lève `SynchronousOnlyOperation` (la boucle
>   d'événements est installée dans le thread courant) : le montage retombait **en silence** sur le
>   placeholder du gabarit. L'ORM est donc lu depuis un thread ordinaire.
> - La garde « source nue » prenait la syntaxe **à balises** de l'avatarizer pour une colonne unique
>   et détruisait sa ligne d'exemple. Tester les seuls délimiteurs ne suffit pas ; un chemin ne
>   porte jamais de jeton commençant par `-`.

> ⭐ **Une source d'exemple est un PLACEHOLDER, et un placeholder ne mesure qu'à moitié.**
> `https://example.com/photo.png` n'existe pas : les apps qui se contentent de **stocker** la source
> créent quand même l'élément, celles qui la **résolvent à la création** n'en créent aucun (le
> converter télécharge et récolte un 404). Le maillon « un lot apparaît en file » n'y était donc pas
> mesuré — et le verdict aveugle « aucun lot nouveau » ne distinguait pas cette chaîne **saine**
> d'une chaîne cassée. Le montage dépose donc de vrais médias dans le domicile déclaré des entrées
> de l'app, et **des sources DISTINCTES** : deux lignes identiques ne rendent qu'un élément
> (l'aperçu déduplique) — donc un lot unitaire, donc **pas de card mère**, donc l'app accusée à tort.

> ⚠ **Le nettoyage doit retirer les FICHIERS avant les lignes.** `QuerySet.delete()` ne touche aucun
> `FileField` : l'app copie la source dans son dossier d'entrée et cette copie **survit à l'objet**
> — 6 `.wav` retrouvés dans `media/converter/…` avant correction. Un harnais qui laisse des déchets
> dans `media/` finit par mesurer ses propres résidus.

---

## 3bis. Matrice des ACTIONS DE CARD — relevé exhaustif (2026-08-23)

> Demandée par Fabien après une soirée de découvertes au coup par coup : « établir la liste
> exhaustive de toutes les actions communes ou proposables au commun ». Elle remplace
> l'archéologie — un bouton, un test rouge, une enquête — par **une passe unique**. Hors
> périmètre pour l'instant, à sa demande : modales de réglages et inspecteur.

| Action | Nature | Brique commune | Graphies relevées | Uniformité |
|---|---|---|---|---|
| **⧉ Dupliquer** | POST via JS | ✅ `queue-actions.js` | `.duplicate-btn[data-duplicate-url]` | **12/12** |
| **🗑 Supprimer** | POST via JS | ✅ *depuis le 2026-08-22* | `delete-btn` (6) · `job-delete-btn` (converter ×2) · `btn-delete-job` (avatarizer) · `js-audio-delete` + `js-delete-enhancement` (enhancer) · `video-delete-btn` (imager vidéo) · `data-action="delete"` (reader) | **6/11 porté** (23/08 : converter, synthesizer, transcriber, enhancer ×2, reader) |
| **▶ Cycle** | POST via JS | ✅ `wama-cycle-button.js` | `.wama-cycle-btn` | **12/12** — re-mesuré le 2026-08-23 |
| **⚙ Paramètres** | ouvre une modale | ✅ *depuis le 2026-08-23* — `queue-actions.js` tient le bouton et la délégation, l'app déclare son ouvreur (`onSettings`) | `.settings-btn[data-id]` | **11/11 porté** (+ le jumeau bac à sable) |
| **⬇ Télécharger** | lien, **ou split ▾ si N formats** | ✅ *depuis le 2026-08-23* — `common/_download_button.html` + tag `bouton_telecharger` ; la FORME se déduit de `export_formats` déclaré au catalogue | `.download-btn` dans le partial commun | **12/12** |
| **✏ Éditer** | ouvre une page/vue | ❌ *aucune* — **1 seule implémentation** | `.edit-btn` (transcriber) | 1/12 — à généraliser |

> ⚠⚠ **CE TABLEAU S'EST TROMPÉ QUATRE FOIS, TOUJOURS DANS LE MÊME SENS — il SOUS-ESTIME.**
> ⚙ : avatarizer donné pour « rien » alors qu'il avait `btn-settings-job`, et enhancer absent de
> la table avec ses DEUX graphies. ▶ Cycle : annoncé **2/10**, mesuré **12/12** — les douze cards
> incluent le partial commun ET appellent `WamaCycleButton`. La cause est commune aux quatre :
> **un relevé par motif de texte hérite des angles morts du motif choisi**, et un chiffre bas
> n'attire pas la contradiction alors qu'un chiffre haut l'attirerait. Corollaire de méthode :
> **ne jamais planifier depuis cette table sans re-mesurer la ligne qu'on s'apprête à traiter** —
> c'est ce qui a failli faire porter une brique de cycle déjà adoptée partout.
>
> ⚠ **La ligne ⚙ a été RÉÉCRITE le 2026-08-23, et son relevé initial était FAUX sur
> deux points** — les deux dans le même sens, celui qui sous-estime la divergence :
> - **avatarizer n'avait pas « rien »** : il avait `btn-settings-job`, seule graphie des six à
>   inverser l'ordre des mots (`btn-settings-*` au lieu de `*-settings-btn`). Un relevé qui
>   cherche un suffixe ne la voit pas — et c'est ainsi qu'elle a été classée « absence ».
> - **enhancer manquait entièrement de la table** : ses DEUX familles de cards portaient
>   `js-open-settings` et `js-audio-settings`.
>
> Total réel : **six graphies pour dix apps** — exactement le compte de la suppression, pour
> exactement la même raison. La leçon n'est pas « le relevé était bâclé » : c'est qu'**un relevé
> par motif de texte hérite des angles morts du motif choisi**. Ce qui a corrigé la table n'est
> pas une relecture, c'est le scénario `<app>.settings` qui ÉNUMÈRE les classes réellement
> présentes dans la page et les rapporte à chaque passage.

**Le motif est sans exception, et c'est le résultat principal de ce relevé :**

| état de la brique | conséquence observée |
|---|---|
| brique **et** adoptée | **uniformité totale** (dupliquer, paramètres, supprimer, télécharger : 12/12 le 23/08) |
| brique mais **non adoptée** | l'adoption est le chantier, le nommage tient (cycle, 2/10) |
| **pas de brique** | **divergence** (supprimer et paramètres : 6 graphies chacun, avant leur brique) |
| l'action est un **lien** | aucune brique n'est requise — un `<a href>` n'a rien à déléguer |

> **La divergence n'est jamais une négligence de style : c'est la trace d'une brique absente.**
> Corollaire pratique — on ne « corrige pas un nommage », on crée la brique qui le rend inutile
> à discuter.

### Ce que la brique ⚙ a coûté au commun AVANT d'exister (mesuré le 2026-08-23)

La divergence ne reste pas dans les apps : **elle est facturée au substrat**. Le `cardSettings`
par défaut de `wama-inspector.js` devait porter en dur l'UNION des graphies —

```js
card.querySelector('.settings-btn, [data-action="settings"], .btn-settings-job, .job-settings-btn')
```

— une **liste de noms d'apps écrite dans une brique commune**, qu'il fallait allonger à chaque
app qui inventait la sienne (et qui, de fait, était déjà incomplète : `video-settings-btn` et
`js-audio-settings` n'y figuraient pas). Après portage elle se lit `.settings-btn,
[data-action="settings"]`. **C'est le meilleur indicateur qu'une brique manque** : quand le
commun se met à énumérer des apps, il compense une brique absente.

### Ce que la brique ⚙ partage, et ce qu'elle ne partage pas

⚙ n'est **pas** un POST : dupliquer et supprimer SONT l'action (une URL, un POST), ⚙ ne fait
qu'ouvrir une modale dont le contenu appartient à l'app. La brique prend donc exactement ce qui
divergeait — **la graphie du bouton et la délégation du clic** — et l'app déclare son ouvreur en
une ligne, comme `wama-cycle-button.js` le fait déjà pour ▶. Deux hooks déclarés couvrent les
spécificités légitimes sans une seule condition d'app dans la brique :

| hook | pourquoi il existe |
|---|---|
| `onSettings(fn, {within})` | `within` scope l'ouvreur à un type de card — c'est ce qui permet aux **deux familles de cards de l'enhancer** (audio / amélioration) de partager `.settings-btn` sans se marcher dessus |
| `onDeleted(fn)` | suite après suppression **au lieu du rechargement** — sans lui, porter le transcriber aurait été une RÉGRESSION (il retire la card sans recharger, désélectionne l'inspecteur, arrête le polling) |

### Nommage canonique retenu

`.<action>-btn` + `data-<action>-url` pour l'élément, `.batch-<action>-btn` pour le lot — c'est
déjà ce que fait le couple `duplicate-btn`/`batch-duplicate-btn`, seul modèle qui ait produit de
l'homogénéité. On généralise le précédent qui marche, on n'invente pas une convention de plus.

⚠ **Une tension à trancher** : le bouton de cycle s'appelle `.wama-cycle-btn`, préfixé du nom de
sa brique, là où la famille dit `.<action>-btn`. Le renommer touche une brique **déjà adoptée**
par 2 apps ; ne pas le renommer laisse une exception dans la convention. À décider — ne pas
laisser dériver par défaut.

---

## 4. Contrainte qui dicte l'ordre : le GPU

Les gestes 8–13 exigent un **traitement réel**. Or la règle est absolue ici : **jamais de charge
GPU en WSL2 déclenchée par l'assistant, ni de job GPU nocturne** (crashs hôte répétés,
`reference_wsl_gpu_windows_update_regression`). Deux issues, aucune n'est un détail :

1. **Commencer par les apps sans GPU** — le **converter** tourne sur ffmpeg/pandoc, en CPU. Il
   sert de patron pour toute la famille « avec traitement ».
2. **Traitement-jouet** pour les autres (entrée minuscule, modèle le plus léger), à n'activer que
   sur décision explicite de Fabien.

### 4bis. La pyramide des niveaux est DÉSÉQUILIBRÉE — et c'est une DÉCISION, pas un trou

> Relevé mesuré le 2026-08-25 (`nightly_tests.REGISTRY`, 89 scénarios, 0 désactivé). Écrit ici
> **parce qu'un prochain relevé lirait ces chiffres comme un défaut** et « corrigerait » une
> priorité que Fabien a délibérément posée ailleurs.

Les niveaux prévus existent tous — `STAGES = ("wired", "ui", "consistency", "model_loaded", "output")`,
soit exactement la gradation « sans GPU → chargement de modèle → génération ». Leur occupation :

| niveau | scénarios | qui |
|---|---|---|
| `ui` | **72** (81 %) | les 15 apps |
| `consistency` | 9 | `common` seul |
| `wired` | 5 | common, synthesizer, transcriber |
| `model_loaded` | **2** | enhancer, transcriber |
| `output` | **1** | studio |

**Pourquoi c'est ainsi (Fabien, 2026-08-25) — deux raisons, aucune n'est un oubli :**
1. **Les crashs hôte interdisent de laisser tourner une charge GPU** (1 à 2 arrêts non prévus par
   jour, cf. §4 ci-dessus). Les étages `model_loaded` et `output` sont donc *bloqués par l'infra*,
   pas par un manque d'écriture de tests.
2. **Les tests servent aujourd'hui à TERMINER LE PORTAGE des apps** — éprouver la chaîne
   d'auto-génération et clore cette marche est la priorité en cours. Or c'est précisément ce que
   le niveau `ui` mesure. Le déséquilibre est donc l'image fidèle de l'objectif du moment.

**Ce qui est acté** : alimenter les étages hauts se fera **progressivement, sans priorité**, une
fois le portage clos et l'infra stabilisée. ⚠ Ne pas en faire un critère ni une alerte : un
indicateur qu'on « corrige » par réflexe déplacerait l'effort hors de la priorité réelle.

⚠ Et l'idée de scénarios pilotés par des **tâches types données à l'AI-Assistant** n'est pas à
créer : elle existe déjà partiellement — `common/nightly_scenarios.py` exerce `tool_api`
(`_run_tool_api_inventaire`, `_run_tool_api_lectures`). C'est le point d'accroche à réutiliser le
jour où on montera d'un étage, pas un chantier neuf.

---

## 5. Le second chantier : la grille d'adoption ne couvre pas tous les mécanismes

Demande de Fabien (2026-08-22) : « mettre à jour la grille de conformité pour qu'elle reflète
tous les mécanismes ». Ce n'est pas à estimer — **c'est mesuré** par
`mecanismes_scan.mecanismes_sans_critere()`, qui exploite le champ `mecanisme` des critères.

**Relevé du 2026-08-22 : 20 mécanismes ne sont vérifiés par AUCUN critère**, et 0 critère
orphelin (aucune liaison morte — le point positif).

| Mécanisme | Apps consommatrices | Mécanisme | Apps |
|---|---|---|---|
| `media_paths` | 10 | `output_formats` | 5 |
| `rag_geste` | 10 | `video_utils` | 5 |
| `gateway_identity` | 10 | `audio_decode` | 4 |
| `manifests` | 8 | `document_export` | 3 |
| `notifications` | 8 | `llm` | 3 |
| `ffmpeg` | 5 | `audio_player` · `media_picker` · `media_probe` · `nightly_tests` · `task_skeleton` | 2 chacun |
| | | `model_coverage` · `provenance` · `resource_governor` · `run_outcome` | 1 chacun |

**Priorité par cardinalité** : un mécanisme adopté par 10 apps et vérifié par rien est le plus
coûteux à laisser dériver. `media_paths`, `rag_geste`, `gateway_identity`, `manifests`,
`notifications` d'abord.

### ⚠ Le scan a une MAILLE TROP GROSSIÈRE (constat de Fabien, 2026-08-23)

Question posée : « si les mécanismes de suppression/duplication sont au registre, comment
peut-on être vert partout alors que les noms diffèrent ? ».

Réponse vérifiée : **la grille n'est pas GÉNÉRÉE depuis le registre.** Le champ `mecanisme` d'un
critère est un simple *lien*, servant à repérer les mécanismes que rien ne vérifie. Or ce scan
travaille à la maille du **mécanisme**, alors qu'un mécanisme héberge **plusieurs comportements**.

Cas mesuré : `queue_front` héberge `queue-actions.js` (dupliquer **et** supprimer), le collapse
de lot, le focus de card et les `data-wama-*`. Il porte **deux** critères — il n'a donc JAMAIS
été signalé comme non couvert, pendant que **personne ne vérifiait la suppression**. Un mécanisme
à cinq comportements avec un seul critère compte comme « couvert » ; les quatre autres sont
invisibles.

**Ce n'est pas un défaut de génération, c'est un défaut de granularité.** La correction est la
matrice du §3bis : elle énumère des **actions**, pas des mécanismes — et une action se vérifie
ou ne se vérifie pas, sans moyenne possible.

**Application concrète (2026-08-23)** : `queue_front` porte désormais **trois** critères —
`duplicate_wiring`, `delete_wiring`, `settings_wiring` — un par ACTION, jamais un pour le
mécanisme. C'est la forme que doit prendre la réponse au relevé ci-dessus : découper par
comportement là où le mécanisme en héberge plusieurs, et non ajouter un critère par ligne du
tableau des 20.

> ⚠ **Et un critère par action ne suffit toujours pas.** `settings_wiring` est passé **vert sur
> 10/10 le jour de son écriture** — parce qu'il mesure ce qu'il peut mesurer : deux présences
> dans le code (le bouton au contrat, l'ouvreur déclaré). Il ne voit pas un ouvreur qui lève, une
> modale qui s'ouvre vide, un second handler qui la referme. **Le vert d'un critère neuf n'est
> pas une bonne nouvelle, c'est le moment où il faut aller cliquer** — c'est exactement pourquoi
> `<app>.settings` a été écrit dans la même passe, et non « plus tard quand on aura le temps ».

⚠ Ne PAS écrire un critère par mécanisme mécaniquement : certains (`resource_governor`,
`provenance`) sont des briques de niveau **système**, pas d'app — un critère par app n'y aurait
pas de sens. Le scan signale un manque de couverture, il ne dicte pas la réponse.

---

## 6. Ordre d'exécution retenu

| Phase | Contenu | GPU | État |
|---|---|---|---|
| **1** | Gestes **2 à 6** + geste 14 — paramètres, dupliquer, supprimer, tout effacer, inspecteur, fichier de lot. Purement UI + base. ⚠ Le geste 7 (création par le bouton primaire) a été **requalifié geste GPU** le 27/08 (§3) : hors session, remplacé en phase 1 par le geste 14 | non | 🔄 **geste 2 à moitié (23/08)**, gestes 3-4 faits (22/08), **geste 6 ENTIER (28/08, `inspector_actions` — sélection *et* désélection, 20/20)**, geste 14 mesuré (27/08) ; **reste 5** (+ 7 côté Fabien, GPU) |
| **2** | Câbler les résultats nocturnes en **grille fonctionnelle** : `nightly_*.json` → agrégat geste × app, rendu comme `/apps/` le fait pour l'adoption | non | ⏳ |
| **3** | Gestes **8 à 13** sur le **converter** (CPU) comme patron, puis extension | CPU d'abord | ⏳ |
| **4** | Critères pour les **20 mécanismes non couverts**, par cardinalité décroissante | non | ⏳ |
| **5** | Voies d'import restantes (geste 14) | non | ⏳ |

---

## Voir aussi

- `WAMA_APP_CONVENTIONS.md` — les critères de la grille d'adoption + la table des composants
  obligatoires (= le catalogue des gestes, sous sa forme non exécutable).
- `WAMA_MECANISMES.md` — index généré des mécanismes transversaux ; c'est lui qui alimente le
  scan de couverture du §5.
- `WAMA_APP_GENERATION_ROUTE.md §11` — les trous de la route ; #26 y est reclassé : il demandait
  un critère de grille pour un défaut que la grille ne peut pas voir (§1).
- `PROJECT_STATUS.md §Tests fonctionnels nocturnes` — le runner, le registre, la sérialisation
  VRAM-aware.
