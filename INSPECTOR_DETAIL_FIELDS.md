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

## Chantier lié (à faire pour des propriétés riches partout)
Généraliser `common/utils/media_probe.py::probe_audio` en **`probe_media(path)`** couvrant
image (L×H) / vidéo (L×H·fps·durée) / audio (codec·kHz·canaux) / PDF (N pages) / archive (N entrées),
pour que `source_properties` soit rempli uniformément, pas seulement là où l'app le calcule.

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
