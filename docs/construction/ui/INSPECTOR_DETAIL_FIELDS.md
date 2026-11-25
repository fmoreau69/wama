# Inspecteur — Schéma canonique des infos d'item (`DETAIL_FIELDS`)

> Validé par Fabien 2026-07-07 (audit exhaustif des 10 apps). **Source de vérité du CONTRAT** de
> la section « Infos/État » de l'inspecteur commun : quelles clés, quel sens, quels alias.
> `unified_detail(app, pk)` + adapter/spec par app → `renderDetailChips`.
> But : reporter les infos de la card dans l'inspecteur (métadonnée-driven, pérenne) pour pouvoir
> **amincir les cards** ensuite.
>
> ⚠ **Confronté au code le 2026-08-22** (demande de Fabien — le document avait été oublié lors de
> la session « volets »). Il était juste sur l'essentiel mais **cinq choses manquaient** et une
> affirmation était fausse. Corrigé ici : ① la clé `source_text` (3 consommateurs, absente du
> document) ② les clés dérivées `source_type`/`source_properties_icon` ③ la **seconde voie
> d'enregistrement** `register_app_detail_spec` (3 apps) ④ quatre règles de rendu qui sont des
> DÉCISIONS et non des accidents ⑤ les consommateurs hors affichage (RAG, aperçu, studio).
> ⚠ **L'affirmation « labels figés UNE fois ici » était FAUSSE** — voir §Où vivent réellement les
> labels. Ne pas s'y fier pour changer un libellé.

## Principe

1. **Épine dorsale canonique universelle** (ci-dessous) : labels/icônes définis ici, une fois.
2. **Réglages spécifiques d'app = réutilisés de `params.py`** (déjà label + icône par champ) — AUCUN
   nouveau label pour diarisation, mode, seed, voix, etc. Source unique = `params.py`.
3. Un champ ne s'affiche que s'il a une **valeur** (les optionnels disparaissent sinon).

## Épine dorsale (ordre d'affichage)

| Clé canonique | Label FR | Icône | Catégorie | Alias résolus |
|---|---|---|---|---|
| `id` | # | `fa-hashtag` | Identité | — |
| `created_at` | Créé le | `fa-calendar-alt` | Identité | uploaded_at |
| `source_file` | Fichier source | `fa-file` | Entrée | audio / input_file / file / text_file |
| `source_duration_display` | Durée | `fa-clock` | Entrée | duration_inMinSec |
| `source_properties` | Propriétés | *adaptative* (voir ci-dessous) | Entrée | — |
| `engine` | Moteur / Modèle | `fa-microchip` | Réglages | backend / model / tts_model / ai_model |
| `engine_effective` | *(à la suite du moteur : « demandé → employé » ; seul, « Employé »)* | `fa-shield-alt` | Réglages | used_backend ; sinon le modèle des lignes d'étapes (`employed_models`, 2026-11-23) |
| `engine_label` · `engine_effective_label` | *(pas de chip : ce qui se LIT pour les deux clés ci-dessus)* | — | Réglages | ajoutées 2026-11-23, cf. « Temps 3 » plus bas |
| `result_file` | Résultat | `fa-download` | Sortie | audio_output / output_file / output_video |
| `output_format` | Format | `fa-file-export` | Sortie | — |
| `output_quality` | Qualité | `fa-sliders` | Sortie | quality_preset |
| `status` | Statut | `fa-circle` | État | (normalisé, voir ci-dessous) |
| `error_message` | Erreur | `fa-triangle-exclamation` | État | — |
| `processing_time_display` | Temps de traitement | `fa-stopwatch` | Temps | (déjà via `_processing_time.html`) |
| `source_text` | *(pas de chip — cf. §Consommateurs)* | — | Entrée | ajoutée 2026-08 ; symétrique de `result_text` |
| `source_type` · `source_properties_icon` | *(pas de chip)* | — | Entrée | dérivées, cf. §`source_properties` |

> ⚠ Les trois dernières lignes ont été AJOUTÉES au document le 2026-08-22, après confrontation
> au code : `build_detail` les émet depuis longtemps et elles ont de vrais consommateurs, mais
> le tableau ne les portait pas. `source_text` en particulier n'apparaissait NULLE PART ici
> alors que trois mécanismes en dépendent (voir §Consommateurs du schéma).

### `source_properties` : icône ADAPTATIVE selon le type de média
Ne jamais afficher la vague audio par défaut. Icône dérivée du type d'entrée :
`audio → fa-wave-square` · `image → fa-image` · `video → fa-film` · `document/pdf/text → fa-file-lines`
· `archive → fa-file-zipper` · défaut → `fa-circle-info`.

### `status` : normalisation d'AFFICHAGE (base inchangée)
reader/converter stockent `DONE`/`ERROR` → affichés « Terminé »/« Échec » comme SUCCESS/FAILURE.
Alias : `DONE→SUCCESS`, `ERROR→FAILURE` (uniquement pour le libellé/couleur, pas en base).

## Décisions figées (Fabien 2026-07-07)
1. Collisions résolues vers UN nom : `engine`, `source_file`, `result_file`.
2. `result_file` NON distingué par type (audio/vidéo/image/fichier) — un seul concept.
3. Champs techniques exclus (task_id, user, flags UI internes).

## Chantier lié — ✅ FAIT 2026-07-09
`common/utils/media_probe.py::probe_media(path)` couvre image (format • L×H) / vidéo
(codec • L×H • fps + durée) / audio (codec • kHz • canaux + durée) / PDF (N pages) /
archive (N entrées). **Branché en fallback UNIVERSEL dans `build_detail`** (`detail_registry`) :
si l'app ne fournit ni `properties` ni durée, la sonde remplit `source_properties` /
`source_duration_display` / `source_type` (icône) — via `probe_media_cached` (cache Django
par chemin+mtime : une sonde par fichier, pas par clic). Zéro travail par app.

## Mécanisme

- `common/utils/detail_registry.py` (miroir de `preview_registry`) — **DEUX voies
  d'enregistrement**, pas une :

  | Voie | Signature | Adoption (mesurée 2026-10-05 ; 9 / 2 le 03/10, 9 / 3 le 22/08) |
  |---|---|---|
  | **Spec** (déclarative) — LA voie | `register_app_detail_spec(app, model, spec)` → `detail_from_spec` | **les 11 surfaces** — anonymizer, audio_enhancer, avatarizer, composer, converter, describer, enhancer, imager, reader, synthesizer, transcriber (+ les jumelles générées) |
  | **Adapter** (fonction) — plus aucun | `register_app_detail(app, model, adapter)` | **0** depuis le 2026-10-05 (`imager` et `audio_enhancer` portés, voir ✅ ci-dessous). La signature reste dans la brique ; `tests_detail_spec.CODE_ADAPTERS` est VIDE et un adapter code nouveau fait échouer la suite |

  > ⚠ La voie **spec** ne figurait pas dans ce document, alors que c'est la plus alignée sur la
  > philosophie (§3 : métadonnée-driven — l'app déclare `aliases` + champs au lieu d'écrire une
  > fonction). Elle est aussi celle que le **codegen** peut produire. À considérer comme la
  > cible ; ~~l'adapter reste nécessaire quand la résolution demande du calcul~~ *(périmé depuis le
  > 2026-10-05 : plus aucun adapter code, `tests_detail_spec.py:33` `CODE_ADAPTERS = {}` — vérifié
  > le 2026-10-31)*.

  ### Le langage de la spec (complété le 2026-10-03, décision de Fabien)

  Lus un par un, cinq des six adapters code ne faisaient rien qu'une déclaration ne sache dire —
  à quatre formes près, que chacun écrivait à sa main. Elles sont au commun (`spec_value`,
  `detail_from_spec`) ; le vocabulaire ENTIER de la spec tient dans cette table :

  | Où | Forme | Sens | 1ᵉʳ usage |
  |---|---|---|---|
  | valeur | `'champ'` | le champ du modèle | — |
  | valeur | `{'const': x}` | une constante | reader (`document`) |
  | valeur | `{'field': f, 'map': table, 'default'?: x}` | le champ TRADUIT par une table ; `default` *(2026-11-01)* pour une valeur absente de la table | rôle d'asset (`MEDIA_CATEGORY_ROLE`) ; le schéma d'un élément de l'imager (`generation_mode` : les modes vidéo → `VIDEO_PARAMS_JSON`, le reste → `IMAGE_PARAMS_JSON`) — la forme qui désigne un DOMAINE quand deux domaines partagent un modèle, parce qu'une valeur de champ se cherche aussi en base (`app_modes.domain_filter`) |
  | valeur | `['a', 'b']` *(2026-10-03)* | le PREMIER champ non vide | avatarizer (avatar, sinon audio) |
  | valeur | `{'when_any': [champs], 'then': x, 'else': y}` *(2026-10-03)* | une valeur selon la PRÉSENCE d'un champ | synthesizer (type « texte » dès qu'un texte existe) |
  | `extra` | `{'field', 'label'?, 'display'?}` | un réglage ; `display` = `get_<f>_display()` | reader |
  | `extra` | `'max_chars': n` *(2026-10-03)* | texte TRONQUÉ (`…`) | composer (prompt) |
  | `extra` | entrée SANS `label` *(2026-10-03)* | le libellé est celui du SCHÉMA (`params.py`) — principe 2 ci-dessus, enfin tenu par le code | transcriber |
  | — | `extra_from_params: 'champ JSON'` | le PORTEUR des valeurs. ⚠ Depuis le 2026-11-23 les réglages posés du schéma sont listés pour TOUTE spec, sans le demander (`True` n'ajoute plus rien) ; `extra` ne porte que les faits hors schéma | converter (`options`) |
  | — | `aliases` | alias canoniques | converter |
  | ~~—~~ | ~~`result_tabs`~~ | ~~onglets de résultat texte (R18)~~ — **retiré du vocabulaire le 2026-10-13** (`REMOVAL_LEDGER R127`) : le describer (R125) puis le transcriber (R126) l'avaient quitté, leurs facettes sont les faces de la visionneuse commune ; une spec qui le déclarerait encore rougit `tests_detail_spec` | — |
  | valeur | `'port'` *(2026-11-25)* | un NOM désigne un champ OU un PORT que l'élément garde dans la table commune des entrées (`port_fields.element_value` ; un attribut existant prime) — vaut dans toutes les formes ci-dessus, et pour l'aperçu, la photo des réglages surveillés et l'entrée d'un pipeline. Le nom doit être un champ du modèle ou un port qu'il DÉCLARE dans la table (`table_ports`, tenu par `tests_detail_spec`) | avatarizer (`['work_image', 'work_object3d', 'audio_input']`, `INPUT_MODEL_MATCHING §6.13`) |
  | valeur | `['a', 'b']` sur une LISTE *(2026-10-05)* | dans « premier champ non vide », un champ qui porte une collection rend son PREMIER élément | imager (la vidéo, sinon la 1ʳᵉ image) |
  | valeur | `result_files: 'champ'` *(2026-10-05)* | la COLLECTION de résultats (émise à partir de deux) | imager (`output_images`) |
  | valeur | `content_title: <valeur>` *(2026-11-08)* | le TITRE LU dans le contenu de l'élément (pas son fichier) : il nomme son LOT (`batch_identity`, juste après le nom donné à la main — le titre le plus lu parmi les éléments, quel que soit leur ordre) et l'élément sur sa card | reader (`read_title` : le titre lu sur une partition, tant que la card la porte) |
  | valeur | `content_page: <valeur>` *(2026-11-08)* | le NUMÉRO DE PAGE lu dans le contenu : les éléments d'un lot se RANGENT par lui (`batch_identity.order_by_read_pages` — décision de Fabien, « réordonner seul » ; une page sans numéro qui porte le titre lu ouvre l'œuvre) | reader (`read_page`) |
  | valeur | `params_schema: <valeur>` *(2026-10-05)* | le schéma des réglages CHOISI PAR ÉLÉMENT (`*PARAMS_JSON` du module de l'app PROPRIÉTAIRE du modèle), pour une surface qui sert deux domaines — c'est aussi ce qui désigne le domaine de l'élément (`app_modes.element_domain`) ; absent = le schéma du DOMAINE que sert la surface (`app_modes`, `params_schema` du domaine), sinon le principal. ⚠ Le 2026-10-21, la constante `AUDIO_PARAMS_JSON` d'audio_enhancer est retirée : son domaine `audio` la nomme | imager (image/vidéo) |

  **Un réglage vrai s'affiche « Oui »** — règle d'AFFICHAGE unique (`wama-inspector.js`,
  `_settingValue`), pour toutes les apps : la donnée reste `true`. Avant, le transcriber écrivait
  « Oui » dans son adapter et les apps au détail tiré du schéma affichaient « true ».

  **Un fait rendu UNE fois** (2026-10-03, question de Fabien : « c'est un problème nouveau ? » —
  non : là depuis l'audit du 2026-07-11). Les réglages tirés du schéma (`extra_from_params`,
  et les adapters code par `settings_from_schema`) ne relistent ni le champ que `engine` nomme
  (sinon « Moteur / Modèle kokoro » puis « Modèle TTS kokoro »), ni `output_format` /
  `output_quality`, que `build_detail` rend lui-même en section Sortie depuis l'origine (sinon
  « Format de sortie original » sous Réglages ET « Format original » sous Sortie). Le repli du
  2026-08-13 (converter : un paramètre absent du JSON porteur se lit sur le champ dédié) est
  gardé pour les OPTIONS ; il avait ajouté le format en réglage par effet de bord. Garde :
  `tests_detail_spec.AFactIsShownOnceTest` (les dix apps, les deux voies).

  ✅ **SOLDÉ le 2026-10-05** — les trois formes ci-dessous sont au commun (table plus haut :
  `spec_value`, `spec_schema`, `detail_from_spec`), l'imager et l'audio de l'enhancer sont sur
  la spec. Mesure avant bascule, ancien adapter contre spec, sur TOUS les éléments réels (lecture
  seule) : **31/31 générations de l'imager et 6/6 audios identiques clé pour clé** ; seul l'ORDRE
  des réglages de l'imager change (le prompt en tête, comme au composer). La spec ne nomme un
  schéma que par son nom d'attribut ; le module est celui de l'app Django qui possède le modèle
  (`audio_enhancer` est une surface de l'app `enhancer`) — aucune table de correspondance.
  Gardes : `tests_detail_spec` (formes, schéma nommé déclaré par son app, les deux apps), trois
  mutations tuées. Le paragraphe suivant est le constat du 2026-10-03, gardé tel quel :

  ⏳ **Ce que la spec ne dit PAS ENCORE — à ajouter pour porter les deux derniers adapters**
  (Fabien, 2026-10-03 : « on uniformise et on porte tout », il n'y a pas de choix de ne pas
  porter ; cette ligne disait « à dessein », c'était faux) : ① une COLLECTION de résultats
  (`result_files`, clé canonique que `build_detail` accepte déjà — imager : `output_images`) ;
  ② un SCHÉMA choisi par élément pour `extra_from_params` (imager : `IMAGE_PARAMS_JSON` ou
  `VIDEO_PARAMS_JSON` selon `is_video_generation`) ou NOMMÉ (audio de l'enhancer :
  `AUDIO_PARAMS_JSON`, qui n'est pas le schéma principal de l'app) — `declared_param_schemas`
  connaît déjà tous les schémas d'une app par leur nom d'attribut ; ③ « premier élément d'une
  liste » dans la forme « premier champ non vide » (imager : `output_video`, sinon la première
  des `output_images`). Le rôle selon la sortie et le type selon l'élément sont déjà exprimables
  (`when_any`). Un calcul, lui, n'a pas sa place dans une donnée. Liste tenue par
  `tests_detail_spec.CODE_ADAPTERS`, qui ne peut que descendre.

  Mesure avant bascule (éléments témoins non enregistrés, ancien adapter contre spec candidate) :
  **16 témoins sur 19 identiques clé pour clé** (anonymizer, avatarizer, synthesizer, composer) ;
  les 3 autres sont ceux du transcriber, dont les libellés passent de quatre mots écrits à la main
  (« Diarisation », « Résumé », « Mots-clés », « Cohérence ») à ceux de son schéma, ceux de la
  modale ⚙ (« Identifier les locuteurs », « Générer un résumé », « Mots-clés contextuels »,
  « Vérifier la cohérence ») — changement VISIBLE, voulu.
  Gardes : `tests_detail_spec` (les formes ; toute spec enregistrée contre son modèle — champs
  existants, vocabulaire connu, donnée JSON ; les adapters code restants déclarés).

- `unified_detail(app, pk)` (vue commune) → JSON plat `{clé: valeur}` (+ `extra:{label: valeur}`),
  et **non** `{fields:[{key,label,icon,…}]}` : les labels/icônes vivent côté CLIENT (voir ci-dessous).
- ~~Adapter par app~~ Spec par app (`register_app_detail_spec`) = mapping `champ_modèle → clé_canonique`
  DÉCLARÉ (+ `extra` tiré de `params.py`) ; la voie adapter (`register_app_detail`,
  `detail_registry.py:89`) n'a plus d'appelant depuis le 2026-10-05 *(corrigé le 2026-10-31)*.
- Rendu : `renderDetailChips` (`wama-inspector.js`) dans la section « Infos ».

### ⚠ Où vivent RÉELLEMENT les labels (l'en-tête de ce document était faux)

Ce document affirmait « **Labels figés UNE fois ici** ». **C'est inexact, et le rectifier
importe** : les libellés effectifs vivent dans `DETAIL_META` (`wama-inspector.js`) et n'y
couvrent que **7 clés** — `created_at`, `source_duration_display`, `engine`, `engine_effective`,
`output_format`, `output_quality`, `processing_time_display`. Les autres sont rendues avec des
libellés/icônes **écrits en dur** dans `renderDetailChips` (`source_file`, `source_properties`,
`result_file`) ou n'ont pas de libellé du tout (`id`, `status`, `created_at` : rendus en
**en-tête**, pas en ligne).

Conséquence pratique : modifier un label ici ne change **rien** à l'écran. Le document reste la
référence du CONTRAT (quelles clés, quel sens, quels alias) ; la source du RENDU est le JS.
Les faire diverger est facile — c'est déjà arrivé pour les trois clés ajoutées ci-dessus.

### Rendu — décisions non consignées jusqu'ici (mesurées dans `renderDetailChips`)

1. **En-tête vs lignes.** `id`, `status` (badge coloré), `created_at` et
   `processing_time_display` sont rendus dans une **ligne d'en-tête** avec le ✕ de désélection,
   pas comme des lignes de l'épine dorsale. Le tableau ci-dessus décrit donc le CONTRAT, pas la
   disposition.
2. **L'erreur REMPLACE la section Sortie** (elle ne s'y ajoute pas) : un item en échec n'a pas
   de résultat à montrer.
3. **Une erreur n'est émise que si le statut n'est PAS `SUCCESS`** (`build_detail`). Sur un item
   terminé, `error_message` est un **résidu** d'un run précédent — le champ n'est pas toujours
   purgé au redémarrage. Vécu le 2026-08-13 : une note de smoke du 03/08 s'affichait encore sur
   un item #49 en SUCCESS, faisant passer un succès pour un problème.
4. **Troncature à 280 caractères** (`_short_error`) : une trace complète noierait le volet.

### Consommateurs du schéma (au-delà de l'affichage)

Le schéma canonique n'alimente pas que la section « Infos ». Trois autres mécanismes le lisent —
c'est ce qui rend `source_text` / `result_text` structurants et non décoratifs :

| Consommateur | Ce qu'il lit | Où |
|---|---|---|
| **Aperçu d'entrée** (face Entrée, fichier OU texte — 2026-10-12) | `source_file`, sinon `source_text` (port `prompt` : `source_text` seul) | `preview_utils._input_preview` — symétrique de la face Sortie (`result_file`/`result_text`) ; le `file_field` du registre d'aperçu ne désigne plus l'entrée |
| ~~**Geste « Ajouter au RAG »**~~ | ~~`result_text`, sinon `source_text` — data-gated~~ — **retiré de l'inspecteur le 2026-11-01** (doublon du menu « … », décision de Fabien) : le geste vit dans `wama-card-menu.js`, et le serveur refuse un élément sans texte | ligne suivante |
| **Ingestion RAG** | `result_text` (sortie) puis `source_text` (entrée) | `common/views.py` — boucle `('result_text','sortie'),('source_text','entrée')` (ancre symbolique : les numéros de ligne de ce fichier dérivent) |
| **Runner du studio** | `result_text` (chaînage texte → synthesizer) | cf. §Ajout 2026-07-13 |

> Le geste RAG a vécu dans l'inspecteur (2026-08-22 → 2026-11-01) **parce que** le schéma
> canonique y est déjà : les 10 apps l'obtenaient sans une ligne de code par app (`WAMA_MEMORY.md`
> §7ter, jalon 14). Le menu « … », global lui aussi, l'offre depuis le 2026-09-11 ; le bouton du
> volet, devenu doublon, est retiré (`WAMA_MEMORY.md §9quater`). Le texte reste lu au schéma
> canonique, côté serveur (ligne « Ingestion RAG »).

## Mapping par app
Voir l'audit (transcriber `backend→engine` `audio→source_file` … ; reader `backend→engine`
`input_file→source_file` `page_count→propriétés` ; composer `model→engine` `audio_output→result_file`
`estimated_seconds→ETA` ; etc.). Pilote = **Reader**, puis rollout 9 apps.

## État de rollout par app

> Table figée SUPPRIMÉE (2026-07-25, plan doc B12) : elle annonçait « detail 5/10 » alors que
> `register_app_detail` est présent dans les 10 apps — les tables figées dérivent. **Source
> vivante du suivi d'adoption : `/apps/` (`get_conformity_summary()`), alimentée par la mesure
> réelle `manage.py check_app_conformity` (critère `inspector_adapters`).**

## Ajout au schéma canonique (2026-07-13)
- **`result_text`** — résultat TEXTE d'un item (transcriber `text`, describer/reader
  `result_text`). Complète `result_file` pour les apps dont la sortie n'est pas un fichier.
  Consommateurs : runner générique du studio (chaînage texte→synthesizer, nœud Sortie .txt) ;
  l'inspecteur peut l'afficher à terme (aperçu du texte côté Sortie).

## Ajout au schéma canonique (2026-08-22)

- **`result_role`** (2026-09-18, décision Fabien) — le RÔLE d'asset de la sortie, dans le
  vocabulaire des natures de la médiathèque (`voice`, `audio_music`, `audio_sfx`, `image`,
  `video`, `document`, `avatar`, `object3d`). L'app DÉCLARE ce qu'elle produit ; le geste commun
  « ranger en médiathèque » (`media_library.services.admissible_roles`) ne propose alors que ce
  rôle, après le filtre par extension — et l'ignore s'il n'est pas admis pour l'extension (une
  déclaration fausse ne bloque rien). Non déclaré = l'utilisateur choisit. Formes en spec :
  const, champ, ou champ traduit `{'field': 'media_type', 'map': MEDIA_CATEGORY_ROLE}` (table
  commune image/vidéo/document ; l'audio en est ABSENT à dessein). Déclaré par composer (musique
  ou bruitage selon `generation_type`), imager, avatarizer, anonymizer, enhancer (branche média),
  converter ; pas par la branche audio de l'enhancer ni le synthesizer (une voix synthétisée
  n'est pas une voix de référence). Émis seulement avec une sortie. C'est ce qui a permis de
  retirer la route d'app `composer:export_to_library` (`REMOVAL_LEDGER R65`). ⚠ Ne concerne que
  les apps **early-binding** : pour une app late-binding (`result_text`, pas de `result_file`) le
  geste médiathèque rend un `document` au format choisi, par le builder du ⬇ — il ne lit pas
  `result_role`.
- **`result_files`** — la COLLECTION des sorties d'un même traitement, quand il en produit
  plusieurs (imager : N images par génération). Liste d'URL.

  **`result_file` ne bouge pas et reste le REPRÉSENTANT** — c'est lui que lisent le studio, le
  lien Sortie et la face `?side=output` des apps à sortie unique. `result_files` s'ajoute *à
  côté* : un consommateur qui l'ignore se comporte exactement comme avant. C'est ce qui permet
  de l'introduire sans toucher aux 9 autres apps.

  Émise **à partir de deux entrées** seulement : en dessous, `result_file` dit déjà tout, et une
  collection d'un seul élément ferait rendre une grille d'une case.

  Consommateur : `preview_utils._output_preview_data` la sert sous la clé `files` (en gardant
  `url` = le représentant, pour la rétro-compatibilité), et `renderInlinePreview` en fait une
  **grille de vignettes** dont le clic ouvre la visionneuse commune — la navigation étant
  nourrie par la collection elle-même, jamais par un balayage du DOM.
  ⚠ *Précisé le 2026-10-13* : la visionneuse ne montrait de `files` que le représentant, et le
  clic sur une vignette n'y naviguait qu'entre les fichiers d'UNE card (sans ses faces). Le rendu
  vit désormais dans la brique d'aperçu (`WamaMediaPreview.renderInline`, `media-preview.js`) ;
  la vignette ouvre l'ÉLÉMENT sur SON fichier, et la visionneuse parcourt les fichiers puis les
  cards voisines (`ROUTE §F3b`, bloc « UNE brique d'aperçu »).

  > Ne contredit PAS la décision figée n°2 du 2026-07-07 (« `result_file` non distingué par
  > type ») : il ne s'agit pas de distinguer un type de sortie, mais un **cardinal**. Le concept
  > « résultat » reste unique ; on nomme seulement le cas où il y en a N.

---

## Chips de la card ↔ section INFOS du volet, et format des DURÉES — chantier ouvert le 2026-11-19 ⏳

> Fabien, 2026-11-19 : *« régler les écarts entre les chips affichées sur la card et celles qui
> vivent dans la section INFOS du volet droit […] il faut terminer l'alignement sur ce point. On fait
> ça proprement et en profondeur pour un alignement parfait »* ; et pour les durées : *« une petite
> fonction au commun pour aligner les durées en heures, minutes et secondes […] elle n'est pas
> appliquée partout. Il faudrait qu'elle soit utilisée partout où il y a des durées »*.

**Mesuré le 2026-11-19** (recensement en lecture seule, points clés relus au code) :
- **Deux déclarations** de ce qui se montre : les chips de la card lisent les champs `chip=True` du
  schéma, mis en forme par `display_format` (`card_chips.chips_for` → `param_schema.format_display`) ;
  la section INFOS lit la liste `extra` de la spec de détail (`register_app_detail_spec`) et, pour la
  durée de l'entrée, la chaîne que CHAQUE app met dans `duration_display`
  (`detail_registry.py:375-377`), affichée telle quelle (`wama-inspector.js:138`, `:201`). Card
  témoin : « 1:35 » en chip, « Durée 95s » au volet — et « 95s » aussi sur la card, section Sortie
  (`composer/models.py:312`, `_generation_card.html:72`).
- **La brique commune existe, en jumelles** : `WamaApp.formatDuration` (`wama-app-base.js:1500`,
  « m:ss » / « h:mm:ss ») et `media_probe.format_duration` (`media_probe.py:27`) — mais la JS ARRONDIT
  (`:1503`) quand la Python TRONQUE (`:35`) : 95,6 s = « 1:36 » ici, « 1:35 » là. `WamaAxis.formatTime`
  (`wama-axis.js:125`, horloge du lecteur, dixièmes en option) est une troisième écriture du même
  format.
- **Réécrites ~10 fois** (même calcul, autre nom ; la plupart SANS les heures — « 62:00 ») :
  `wama-audio-player.js:31`, `media_library/models.py:154` et `:210`, `synthesizer/models.py:301`,
  `anonymizer/views.py:308` et `:327`, `describer/views.py:314`, `describer/backends/video_backend.py:382`,
  `document_export.py:443`, `cam_analyzer/…/index.js:5794` (toujours h:mm:ss),
  `face_analyzer/video.html:1671`, `face_analyzer/index.html:226`.
- **Une seconde famille, « 1 min 35 s », sans brique commune** : `ProcessingTimeMixin.processing_display`
  (`common/models.py:185`), `WamaEta` (`wama-eta.js:33-51`), `media-preview.js:699-704` (une durée de
  MÉDIA, là où la card dit « 1:35 »), `gateway/core.py:245`, `composer/models.py:338` (« ~1min35s »).
- **Horodatages techniques dupliqués** : segments (`transcriber/models.py:284`, et
  `process_pipeline.py:64` `_clock` sans les heures) ; SRT ×3 (`transcriber/models.py:293`,
  `transcriber/views.py:931`, `asr_eval_corpus.py:123`).
- **Affichages bruts** : la bande des process « 95 s » (`_card_process_step.html:18`,
  `wama-app-base.js:1582`), un chip numérique sans `display_format` (`card_chips.py:212-216` — seul le
  composer en déclare un), `enhancer/_audio_card.html:33`, `imager/_generation_card.html:73`,
  `media-library.js:890`, cam_analyzer ; `imager.duration_display` est le TEMPS DE TRAITEMENT affiché
  comme « Durée » de l'entrée (`imager/models.py:323-334`).
- Garde existante : `tests_display_format` (les jumelles rendent le même texte sur des entiers ;
  l'écart d'arrondi lui échappe).

**Plan proposé (⏳ deux décisions de Fabien avant d'écrire)** : (1) UNE brique, deux jumelles alignées
(même arrondi), avec les formes que WAMA emploie — horloge (média, position), précision au dixième ou
à la milliseconde (segments, SRT), et la famille « unités » si elle est gardée ; (2) la section INFOS
met en forme par la MÊME déclaration que les chips (`display_format`, champs du schéma), plus aucune
chaîne d'app ; (3) chaque réécriture remplacée par la brique, chaque affichage brut déclaré ; (4) une
garde générique qui relève une mise en forme locale d'une durée, liste de restes qui ne peut que
baisser. *Décisions* : la famille « 1 min 35 s » (temps de traitement, ETA) se garde-t-elle à côté de
l'horloge ? Et la règle d'arrondi (tronquer comme le lecteur et la jumelle Python, ou arrondir).

✅ **Décidé par Fabien le 2026-11-19** : les deux familles se gardent (l'horloge pour un média ou une
position, les unités pour une attente) ; la valeur est TRONQUÉE. ✅ **Livré le même jour (durées,
temps 1 et 3)** — la brique `common/utils/durations.py` (`format_clock` avec dixième ou milliseconde,
`format_duration`, `format_elapsed`, `srt_timestamp`) et sa jumelle autonome `WamaDurations`
(`common/js/wama-durations.js`, chargée par `base.html` avant ses consommateurs) ; portés sur elle :
`WamaApp.formatDuration`, `WamaAxis.formatTime`, le lecteur audio commun, `WamaEta`, l'aperçu (une
durée reçue en secondes OU déjà écrite), le chronomètre d'enregistrement, l'attente de l'assistant,
`ProcessingTimeMixin.processing_display`, `media_probe.format_duration` (réexport), la note de durée de
la bande des étapes (UNE écriture serveur, `card_rows → duration_text`, que le gabarit et le JS
affichent), les tours de parole (`_clock`, `format_time_range`), les trois écritures SRT (à l'octet de
celle d'`asr_eval_corpus`), l'export de documents, le pied de réponse Discord, les délais du Studio ;
composer (« 95s » → `MediaDurationMixin`, « ~1min35s » → unités), synthesizer, anonymizer, describer
(card et rapport vidéo), médiathèque (modèles et recherche), enhancer (card audio), face_analyzer,
cam_analyzer. L'imager perd son ALIAS `duration_display` du temps de traitement, que le volet lisait
comme la durée de l'entrée. Garde : `tests_display_format.OneWritingOfADurationTest` (jumelles côte à
côte, troncature, SRT à l'octet, aucune durée écrite à la main hors de la brique — restes déclarés :
aucun ; les jumelles de bac à sable suivent à leur régénération).
✅ **Temps 2, l'alignement card ↔ volet — livré le même jour** : la mise en forme d'une valeur de
réglage, qui vivait DANS `card_chips.chips_for`, en est sortie en une fonction commune,
`card_chips.display_value` (libellé de l'option — plaques, catalogue, voix —, format déclaré, unité) ;
les chips ET la liste « Réglages » de la section INFOS (`detail_registry.settings_from_schema`) la
lisent. Seul écart VOULU : un nombre sans unité se préfixe de son libellé sur la card (« Étapes 30 »),
le volet ayant déjà le libellé en regard. Garde : `tests_detail_spec.AFactIsShownOnceTest.
test_a_setting_reads_in_the_panel_as_on_the_card` (contre-épreuve : valeurs brutes au volet → rouge).
~~⏳ La liste `extra` d'une spec de détail (`register_app_detail_spec`) reste une seconde déclaration
de CE QUI se montre (pas de sa forme) : à confronter aux champs `chip=True` du schéma, app par app.~~
*(soldé le 2026-11-23, temps 3 ci-dessous)* ⏳ Les textes de console (« 12.3s » des tâches) et la page
d'administration des apps (`apps.html`, médiane en secondes) restent à porter.

✅ **Temps 3, la LISTE elle-même et le modèle employé — 2026-11-23.** Fabien, après essai : *« le
volet droit était plus complet. Tu as bien gardé la source la plus complète des 2 ? C'est
parfaitement aligné, universel, uniforme et schéma-driven ? De mon côté, je ne vois pas de différence
avec avant […] j'ai toujours auto:text-to-music, ce qui n'est pas le modèle mais la tâche. Il faut
peut-être donner les 2 infos »*. Mesuré avant d'écrire (les deux dernières cards de chaque app, en
lecture seule) : le temps 2 n'avait aligné que la FORME d'une valeur, et seulement pour les sept
surfaces dont la spec demandait `extra_from_params` ; **quatre apps listaient encore leurs réglages
à la main** — composer (type, prompt), transcriber (quatre cases), describer (trois), reader (deux) —
donc rien n'y avait changé. Le volet affichait par ailleurs la clé technique du modèle, le curseur
« Rapide ↔ Qualité » d'un modèle désigné, « Ce qu'on floute : [] », un texte à dire en entier.

- **Une source, pour toute app** : la liste « Réglages » est celle des réglages POSÉS du SCHÉMA
  (`detail_from_spec`, sans que la spec le demande). La card en montre le sous-ensemble `chip=True`,
  le volet le tout : la source la plus complète est gardée, c'est celle du schéma. `extra` ne porte
  plus que les faits HORS schéma (le type d'une génération, un nombre de pages) ; ce qu'il nomme
  n'est pas répété. Les quatre listes à la main sont retirées.
- **Ce qui ne s'y lit pas** : un réglage que sa condition masque dans la ⚙ (`show_if`, même
  vocabulaire, `param_schema._show_if_met`) ; un réglage que ne lisent que des étapes qui n'ont pas
  lieu — coupées ou sans objet (`process_pipeline.unread_settings`, la règle de la card « pas de puce
  pour un réglage d'un process éteint ») ; une valeur composée vide. Un texte long se coupe à 60
  caractères (`LONG_TEXT`, ce que deux specs écrivaient à la main) ; une liste et une table se lisent
  en clair.
- **Demandé → employé** : `engine` et `engine_effective` gardent la VALEUR (la médiathèque en fait
  une étiquette) ; `engine_label` et `engine_effective_label` portent ce qui se lit. Un « auto » se
  lit « Automatique », celui d'un groupe avec sa tâche — « Automatique (Texte → musique) »
  (`card_chips.auto_choice_label`, donc sur la card aussi). Le modèle EMPLOYÉ, quand la spec ne nomme
  aucun champ pour lui, est celui des lignes des étapes qui lisent le sélecteur
  (`process_pipeline.employed_models` — ce que la bande écrit à côté de chaque étape). Le volet écrit
  les deux en une lecture, « Automatique (Texte → musique) → ACE-Step 1.5 », et de même pour tout
  autre sélecteur de modèle laissé à « Automatique » (« Automatique → MuScriptor large »). Un modèle
  qu'aucune étape ne lit sur la card (un cover dont on ne tire que les partitions) ne s'y dit pas.

Gardes, dans les modules existants : `tests_detail_spec` (`ExtraSettingsTest` — la liste entière, une
entrée nommée non répétée, aucune spec ne liste à la main un réglage de son schéma ;
`RequestedAndEmployedModelTest` ; `ShownSettingsTest`) et `tests_process_pipeline`
(`test_the_panel_reads_what_no_step_reads_and_the_models_the_steps_kept`).

---

## Voir aussi — la frontière avec `WAMA_VOLETS.md` (ajouté 2026-08-22)

Les deux documents décrivent **deux couches** de la même région d'écran, et ne se recouvrent pas
(vérifié dans les deux sens le 2026-08-22) :

| | `WAMA_VOLETS.md` | **ce document** |
|---|---|---|
| Objet | le **CONTENANT** — ossature `base.html`, quelles sections existent et quand | le **CONTENU** d'une seule section : « Infos » |
| Couvre | 4 états contextuels (file/item/batch/désélection), contrat déclaratif `volet.py`, 35 pages mesurées, mode simplifié | quelles clés, quel sens, quels alias, quelles règles de rendu |

**La couture est `#inspectorInfo` + `fillDetail`.** `WAMA_VOLETS` §3 décrit l'état ② : un clic sur
une card appelle `fillDetail` → `/common/detail/<app>/<pk>/` et remplit `#inspectorInfo`. **Ce
document reprend exactement là.** Les deux pointent vers `wama-inspector.js`, mais vers des
fonctions distinctes — `init`/`deselect`/machine à états là-bas, `renderDetailChips`/`DETAIL_META` ici.

**Qui modifier :** l'hôte, le moment de l'appel ou la visibilité de la section → `WAMA_VOLETS`.
Ce que l'appel RENVOIE et comment c'est rendu → ici.

> Ce renvoi est ajouté parce que le lien était **unidirectionnel** : `WAMA_VOLETS` citait ce
> document, l'inverse n'existait pas. C'est ainsi que deux références divergent — et
> vraisemblablement pourquoi ce fichier a été oublié pendant la session « volets ».
