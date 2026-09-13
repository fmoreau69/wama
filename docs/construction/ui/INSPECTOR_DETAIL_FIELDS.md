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
| `engine_effective` | Moteur effectif | `fa-shield-alt` | Réglages | used_backend |
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

  | Voie | Signature | Adoption (mesurée 2026-08-22) |
  |---|---|---|
  | **Adapter** (fonction) | `register_app_detail(app, model, adapter)` | **9** — anonymizer, avatarizer, composer, describer, enhancer (×2 : `enhancer` + `audio_enhancer`), imager, synthesizer, transcriber |
  | **Spec** (déclarative) | `register_app_detail_spec(app, model, spec)` → `detail_from_spec` | **3** — converter, converter_01, reader |

  > ⚠ La voie **spec** ne figurait pas dans ce document, alors que c'est la plus alignée sur la
  > philosophie (§3 : métadonnée-driven — l'app déclare `aliases` + champs au lieu d'écrire une
  > fonction). Elle est aussi celle que le **codegen** peut produire. À considérer comme la
  > cible ; l'adapter reste nécessaire quand la résolution demande du calcul.

- `unified_detail(app, pk)` (vue commune) → JSON plat `{clé: valeur}` (+ `extra:{label: valeur}`),
  et **non** `{fields:[{key,label,icon,…}]}` : les labels/icônes vivent côté CLIENT (voir ci-dessous).
- Adapter par app = mapping `champ_modèle → clé_canonique` (+ `extra` tiré de `params.py`).
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
| **Aperçu d'entrée** (texte) | `source_text` | `preview_utils.py:113-123` |
| **Geste « Ajouter au RAG »** | `result_text`, sinon `source_text` — **data-gated** : pas de texte ⇒ pas de bouton | `wama-inspector.js` (`_ragChip`) |
| **Ingestion RAG** | `result_text` (sortie) puis `source_text` (entrée) | `common/views.py` — boucle `('result_text','sortie'),('source_text','entrée')` (ancre symbolique : les numéros de ligne de ce fichier dérivent) |
| **Runner du studio** | `result_text` (chaînage texte → synthesizer) | cf. §Ajout 2026-07-13 |

> Le geste RAG vit dans l'inspecteur **parce que** le schéma canonique y est déjà : les 10 apps
> l'obtiennent sans une ligne de code par app. C'est l'argument qui a fait choisir cet
> emplacement (`WAMA_MEMORY.md` §7ter, jalon 14) — il appartient donc à ce document aussi.

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

  > Ne contredit PAS la décision figée n°2 du 2026-07-07 (« `result_file` non distingué par
  > type ») : il ne s'agit pas de distinguer un type de sortie, mais un **cardinal**. Le concept
  > « résultat » reste unique ; on nomme seulement le cas où il y en a N.

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
