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
| 3 | Dupliquer un **élément** (`.duplicate-btn`) | ❌ | non |
| 3b | Dupliquer un **lot** (`.batch-duplicate-btn`) | ❌ | non |
| 4 | Supprimer un **élément** (`.delete-btn`) | ❌ | non |
| 4b | Supprimer un **lot** (`.batch-delete-btn`) | ❌ | non |
| 5 | Tout effacer | ❌ | non |
| 6 | Sélectionner une card → l'inspecteur se remplit ; désélectionner | ❌ | non |
| 7 | **Créer par le bouton primaire** (apps `data-wama-depot=attache` : avatarizer, imager) | ❌ | non |
| 8 | Démarrer un item → RUNNING → SUCCESS | ❌ | **oui** |
| 9 | Arrêter / relancer (bouton de cycle) | ❌ | **oui** |
| 10 | Progression : % et ETA visibles et qui avancent | ❌ | **oui** |
| 11 | Aperçu du résultat (clic → visionneuse) | ❌ | **oui** |
| 12 | Télécharger le résultat | ❌ | **oui** |
| 13 | Démarrer tout / télécharger tout (lot) | ❌ | **oui** |
| 14 | Import dossier récursif · URL · fichier de lot · « Envoyer vers » | ❌ | non |

**Couverture mesurée le 2026-08-22 : 1 geste sur 16.** Les deux seuls scénarios par app sont
`<app>.ui` (santé de la page : 200 + zéro erreur console — aucun geste) et `<app>.import`.
**Au 2026-08-23 : 3 gestes et demi sur 16** (import ; dupliquer + supprimer ; ouverture des
paramètres). Chaque ajout se paie en minutes de passage nocturne, pas en lignes de code par app :
les trois scénarios partagent le même montage de fixture et le même filet ORM de nettoyage.

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
| **▶ Cycle** | POST via JS | ✅ `wama-cycle-button.js` | `.wama-cycle-btn` | **2/10 adoptée** (anonymizer, imager) |
| **⚙ Paramètres** | ouvre une modale | ✅ *depuis le 2026-08-23* — `queue-actions.js` tient le bouton et la délégation, l'app déclare son ouvreur (`onSettings`) | `.settings-btn[data-id]` | **11/11 porté** (+ le jumeau bac à sable) |
| **⬇ Télécharger** | **lien `<a href>`** | *sans objet* | `href="{% url 'app:download' %}"` partout ; quelques `download-btn` résiduels | n/a |

> ⚠ **La ligne ⚙ ci-dessus a été RÉÉCRITE le 2026-08-23, et son relevé initial était FAUX sur
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
| brique **et** adoptée | **uniformité totale** (dupliquer 12/12 ; paramètres 11/11 le 23/08) |
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
| **1** | Gestes **2 à 7** — paramètres, dupliquer, supprimer, tout effacer, inspecteur, bouton primaire. Purement UI + base. Premier item : **création de l'avatarizer** (geste 7), justement celui qui manquait ce soir | non | 🔄 **geste 2 à moitié (23/08)**, gestes 3-4 faits (22/08) ; restent 5, 6, 7 |
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
