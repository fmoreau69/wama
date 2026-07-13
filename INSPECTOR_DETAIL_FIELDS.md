# Inspecteur — Schéma canonique des infos d'item (`DETAIL_FIELDS`)

> Validé par Fabien 2026-07-07 (audit exhaustif des 10 apps). **Source de vérité** pour la section
> « Infos/État » de l'inspecteur commun : `unified_detail(app, pk)` + adapter par app → `WamaDetails`.
> But : reporter les infos de la card dans l'inspecteur (métadonnée-driven, pérenne) pour pouvoir
> **amincir les cards** ensuite. Labels figés UNE fois ici — ne pas re-labelliser par app.

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
- `common/utils/detail_registry.py` : registre `register_app_detail(app, model, adapter)` (miroir de
  `preview_registry`).
- `unified_detail(app, pk)` (vue commune) → JSON `{fields:[{key,label,icon,value,category}], extra:{…}}`.
- Adapter par app = mapping `champ_modèle → clé_canonique` (+ `extra` tiré de `params.py`).
- Rendu : `WamaDetails.renderSections` dans l'inspecteur (section « Infos »).

## Mapping par app
Voir l'audit (transcriber `backend→engine` `audio→source_file` … ; reader `backend→engine`
`input_file→source_file` `page_count→propriétés` ; composer `model→engine` `audio_output→result_file`
`estimated_seconds→ETA` ; etc.). Pilote = **Reader**, puis rollout 9 apps.

## État de rollout par app (audit empirique 2026-07-11)

| App | `register_app_detail` | preview (registre) | `initFromSchema` | `_inspector_actions` |
|---|---|---|---|---|
| transcriber | ✅ apps.py:68 | ✅ PreviewRegistry direct (apps.py:45) | ✅ index.js:1167 | ✅ index.html:53 |
| describer | ✅ apps.py:43 | ✅ apps.py:19 | ✅ index.html:313 | ✅ index.html:27 |
| composer | ✅ apps.py:46 | ✅ apps.py:27 | ✅ index.html:263 | ✅ index.html:69 |
| reader | ✅ apps.py:42 | ✅ apps.py:20 | ✅ reader.js:632 | ✅ index.html:50 |
| converter | ✅ apps.py:37 | ✅ apps.py:13 | ✅ index.html:345 | ✅ index.html:191 |
| enhancer | ❌ | ✅ ×2 (apps.py:27/37) | ✅ ×2 (index.html:864/879) | ❌ |
| synthesizer | ❌ | ✅ PreviewRegistry (apps.py:25) | ✅ index.html:830 | ❌ |
| anonymizer | ❌ | ✅ PreviewRegistry (apps.py:23) | ❌ | ❌ |
| avatarizer | ❌ | ❌ | ✅ index.html:691 | ❌ |
| imager | ❌ | ❌ | ❌ | ❌ |

> Bilan : detail **5/10** (les 5 apps portées), preview **8/10** (manquent avatarizer, imager),
> câblage complet 4 sous-éléments **5/10**. Prochaines cibles naturelles : enhancer + synthesizer
> (il ne leur manque que detail + actions), puis anonymizer, avatarizer, imager.

## Ajout au schéma canonique (2026-07-13)
- **`result_text`** — résultat TEXTE d'un item (transcriber `text`, describer/reader
  `result_text`). Complète `result_file` pour les apps dont la sortie n'est pas un fichier.
  Consommateurs : runner générique du studio (chaînage texte→synthesizer, nœud Sortie .txt) ;
  l'inspecteur peut l'afficher à terme (aperçu du texte côté Sortie).
