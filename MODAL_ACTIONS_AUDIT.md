# Audit — boutons d'action des modales (cards / batch) par application

> Demandé par Fabien (2026-06-30). But : recenser tous les cas, identifier les divergences, proposer
> une convention commune (un minimum de divergences, seulement si assumées). Lié à `CARD_DESIGN.md`
> (schéma couleur des boutons de CARD, déjà adopté) et au chantier schéma-driven (`params.py`).

## 1. Inventaire des pieds de modale « Réglages » (item / batch)

| App | Modale | Bouton annuler | Bouton enregistrer | Enregistrer & démarrer | Boutons en plus |
|-----|--------|----------------|--------------------|------------------------|-----------------|
| **Transcriber** | item | Annuler `secondary` | Enregistrer `primary` | `success` | — |
| **Synthesizer** | item + batch | Annuler `secondary` | Enregistrer `primary` | `success` | — |
| **Describer** | item | Annuler `secondary` | Enregistrer `primary` | `success` | — |
| **Reader** | batch | Annuler `secondary` | `primary` | `success` | — |
| **Converter** | job | **Fermer** `secondary` | **Appliquer `warning`** | — (absent ici) | **Profil `outline-info` (en 1er)** |
| **Converter** | batch | Annuler `secondary` | **Appliquer `warning`** | `success` | — |
| **Composer** | item | Annuler **sans couleur** | Save **sans couleur** (icône ▶) | (fusionné) | — |
| **Anonymizer** | plusieurs | Fermer/Annuler `secondary` | `primary` | — | incohérent entre ses propres modales |
| **Avatarizer** | item | Annuler **`outline-secondary`** | **Save `secondary`** | **Start `warning`** | — |
| **Imager** | image + vidéo | Annuler `secondary` | **save `success` (icône ▶, fusionne save & start)** | (fusionné) | **Force reset `danger` (en 1er)** |
| **Enhancer** | item | **modale construite en JS** (`js-open-settings`) — pas de pied template | — | — | — |

## 2. Divergences identifiées

1. **Libellé annuler** : « Annuler » (majorité) vs « Fermer » (Converter job).
2. **Couleur du bouton enregistrer** : `primary` (Transcriber/Synth/Describer/Reader) · `warning`
   (Converter « Appliquer ») · `secondary` (Avatarizer) · `success` (Imager) · **aucune** (Composer).
3. **« Enregistrer & démarrer »** : présent en `success` (majorité) · **absent** (Converter job) ·
   **fusionné** dans un seul bouton ▶ (Imager, Composer).
4. **Libellé/icône du save** : « Enregistrer » (`fa-save`) vs « Appliquer » (`fa-save`) vs icône ▶ seule.
5. **Boutons spécifiques placés EN PREMIER** (cassent l'ordre « annuler à gauche ») : Profil (Converter),
   Force reset (Imager).
6. **Composer** : aucune classe de couleur (`btn btn-sm` nu) → boutons gris ternes.
7. **Avatarizer** : sémantique inversée (save = `secondary` éteint, start = `warning` au lieu de success).
8. **Enhancer** : modale de réglages construite en JS → pas de pied homogène, à aligner au portage schéma.
9. **Anonymizer** : incohérent entre ses propres modales (Fermer vs Annuler, primary vs secondary).

## 3. Convention commune PROPOSÉE (pied de modale réglages)

Alignée sur le schéma couleur de CARD déjà adopté (▶ = success, ⚙ = secondary) — supprime l'anomalie
« save en warning ». Disposition `d-flex justify-content-between` :

```
[ groupe GAUCHE — actions spécifiques optionnelles ]      [ Annuler ] [ Enregistrer ] [ Enregistrer & démarrer ]
   ⤷ Profil (outline-info), Force reset (outline-danger)        secondary    primary           success
```

- **Annuler** : toujours « Annuler », `btn-secondary`, premier du groupe droit. (Jamais « Fermer ».)
- **Enregistrer** : `btn-primary`, libellé « Enregistrer », `fa-save`.
- **Enregistrer & démarrer** : `btn-success`, libellé « Enregistrer & démarrer », `fa-play`.
- **Actions spécifiques assumées** (Profil, Force reset, etc.) : groupées **à gauche**, en style
  `outline-*` pour les désaccentuer, jamais intercalées dans le groupe droit.
- Fusionner save & start en un seul bouton (Imager/Composer) = divergence **tolérée si assumée** pour
  les apps à traitement immédiat, mais alors couleur = `success` + libellé explicite (pas d'icône seule).

→ Cible : composant commun `common/_settings_modal_footer.html` (slot « actions spécifiques » à gauche),
inclus par toutes les apps une fois la modale passée au schéma. Supprime les divergences 1–9 d'un coup.

## 4. « Sauver comme profil » — quelles apps le méritent ?

Un *profil* = jeu de valeurs NOMMÉ d'un schéma, réappliqué souvent. Pertinent quand les réglages sont
**riches + réutilisés tels quels** sur de nombreux items.

| App | Profil pertinent ? | Pourquoi |
|-----|--------------------|----------|
| **Converter** | ✅ (déjà) | format + qualité + redim/fps/bitrate réutilisés (« web 1080p », « podcast 192k »…) |
| **Imager** | ✅ | modèle + steps + guidance + taille + style = preset de génération |
| **Anonymizer** | ✅ | détecteurs + type/force de floutage = config récurrente par type de média |
| **Enhancer** | ⚠️ utile | modèle + force/upscale ; presets « voix », « musique »… |
| **Composer** | ⚠️ utile | style + durée + modèle (presets de genre) |
| **Synthesizer** | ➖ partiel | la voix est déjà gérée par « Mes voix » ; un profil voix+vitesse+format reste un plus |
| **Transcriber / Describer / Reader** | ❌ | peu de params / auto-détection → faible valeur |

**Recommandation forte (métadonnée-driven)** : ne PAS recoder un bouton Profil par app. En faire une
**capacité COMMUNE du système de schéma** : une app déclare `supports_profiles=True` (+ type d'asset),
et la brique commune fournit le bouton « Profil » (slot gauche du pied) + l'enregistrement/rechargement
des **valeurs WamaParams** sous un nom (réutilise la médiathèque / `UserAsset` comme stockage de presets).
Converter migre alors sur la brique commune au lieu de son `saveProfileModal` bespoke.

## 5. Bugs connexes signalés (à investiguer — hors audit)

- **Converter : l'inspecteur (volet droit) ne se met pas à jour.** Attendu en l'état : le volet droit du
  Converter est la zone de **composition** (pas un inspecteur de card) ; seule la **modale ⚙ per-job** a
  été portée sur le schéma. Rendre le volet contextuel suppose la **séparation du volet droit** (même
  prérequis que Synthesizer/Imager — cf. `project_schema_driven_ports`).
- **Converter (préexistant) : à l'ajout d'un item, les paramètres apparaissent ~0,5 s puis disparaissent.**
  Probable : la card neuve s'insère avec ses champs, puis un re-render / refresh de la file la remplace.
  À tracer (pas lié au portage modale).
