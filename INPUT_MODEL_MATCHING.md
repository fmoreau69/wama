# INPUT_MODEL_MATCHING.md — Card d'entrée ↔ modèles : le mécanisme d'appariement

> **Le nœud (Fabien, 2026-07-03)** : la card d'entrée doit porter TOUTES les entrées possibles de
> l'app (prompt — vide = génération aléatoire —, fichiers batch, fichier de référence, médiathèque).
> Question stratégique : le CHOIX DU MODÈLE pilote-t-il les entrées affichées, ou les ENTRÉES
> FOURNIES filtrent-elles les modèles ? Exigences : global (toutes apps + studio), naturel, guidé
> sans bloquer, réversible et COMPRÉHENSIBLE (retirer la référence doit visiblement « rouvrir »
> les modèles).

## 1. Ce que font les meilleures apps du domaine (état de l'art)

| App | Pattern |
|---|---|
| **Suno / Udio** (musique) | UNE box de composition ; **ajouter un audio** (cover/extend) **reconfigure les options** — l'entrée pilote. L'audio ajouté = vignette retirable. |
| **Midjourney** | prompt + refs d'images GLISSÉES = enrichissement ; le « modèle » (version) est un réglage séparé jamais bloquant. |
| **Kling / Pika / Runway** (vidéo) | déposer une image **bascule automatiquement** en image-to-video, avec feedback visible du mode. Entrée-d'abord. |
| **ComfyUI** (nœuds) | **typage par connexion** : brancher un type d'entrée filtre les nœuds compatibles — exactement le choix déjà acté pour le studio WAMA. |
| **ChatGPT / Claude** (pièces jointes) | on attache n'importe quoi, le système s'adapte ; les capacités gatent les traitements. |
| **Canva / CapCut** | partir de l'asset → les outils proposés se filtrent. |

**Constat** : l'industrie a convergé vers **« entrée-d'abord »** (*bring your stuff, the tool adapts*),
MAIS jamais en **cachant** les options — en les **désactivant avec explication**.

## 2. LA DÉCISION : bidirectionnel, ancré entrée-d'abord

Ni (A) pur ni (B) pur — les deux directions se rencontrent, avec une dominante :

### Direction principale — les ENTRÉES filtrent les modèles (B)
- Chaque entrée fournie apparaît en **CHIP retirable** (vignette + ✕) dans la card.
- Un modèle incompatible avec les entrées fournies n'est **PAS caché** : il est **désactivé avec la
  raison** (option grisée + tooltip « Incompatible avec votre fichier de référence »).
- Une ligne d'état explicite la causalité : *« 3 modèles désactivés par la mélodie de référence —
  retirez-la (✕) pour les retrouver »* → **réversibilité comprise d'un coup d'œil**.

### Direction complémentaire — le MODÈLE éclaire les entrées (A)
- Sélectionner un modèle qui **attend** une entrée (Melody → mélodie) ne bloque pas : le **slot
  correspondant s'allume** (badge « requis »/« recommandé », pulse discret) avec le texte déclaré
  (« Ce modèle suit une mélodie de référence — ajoutez un audio »).
- Le lancement sans l'entrée requise = bouton désactivé avec la raison (jamais d'échec silencieux).

### Invariants UX (les garde-fous du « guidé sans bloquer »)
1. **Ne jamais cacher, désactiver + expliquer** (statut visible, pas d'impasse).
2. **Cause → effet visible** : chaque restriction pointe l'entrée qui la cause ; le ✕ de la chip
   est l'annulation évidente.
3. **Divulgation progressive** : la card montre les *affordances* (prompt, + fichier, référence,
   médiathèque) légères — pas tous les champs conditionnels dépliés.
4. **Prompt vide = explicite** : placeholder « Vide = génération aléatoire (le modèle improvise) ».

## 3. Architecture déclarative (globale — rien par app)

Tout existe déjà en germe ; il manque UNE couche d'appariement :

| Élément | Où (existant) | Ajout |
|---|---|---|
| **Slots d'entrée** d'une app | `APP_MODES` + `INPUT_TYPES` (ports work/reference/prompt — déjà consommés par `studio_node_ports`) | déclarer composer (prompt, batch, `reference_melody`: accept audio, port reference) |
| **Besoins des modèles** | `AIModel.capabilities` (canonique) | nouveau vocabulaire : `inputs_required` / `inputs_optional` (ids d'INPUT_TYPES). Ex. musicgen-melody : `inputs_optional: ['reference_melody']`… ou `required` selon le comportement réel |
| **Rendu des slots** | `_new_item_card` | slot « référence » paramétrable (chip + accept + médiathèque) |
| **Appariement** | — | **nouvelle brique `wama-input-match.js`** : état = {entrées fournies} × {modèle choisi} → désactive/raisonne les options (extension du pattern `WamaModelCaps`), allume les slots, gère la ligne d'état |
| Studio | `studio_node_ports` (typage par connexion) | consomme les MÊMES déclarations — cohérence card ↔ nœud garantie |

**Chaîne** : INPUT_TYPES/APP_MODES (slots) + capabilities (besoins) → `wama-input-match` (logique) →
card commune + select modèle (surfaces). Zéro hardcode par app ; composer = pilote.

## 4. Plan d'implémentation (pilote composer)
1. Vocabulaire : `inputs_required/optional` ajoutés à `CANONICAL_CAPABILITIES` + déclarés sur les
   4 modèles composer (melody seul avec référence). `INPUT_TYPES` += `reference_melody`.
2. `APP_MODES['composer']` déclaré (slots : prompt, batch_file, reference_melody).
3. `_new_item_card` : slot référence (chip/accept/médiathèque) piloté par paramètre.
4. Brique `wama-input-match.js` (désactiver+raison, allumer slot, ligne d'état, réversibilité).
5. Composer : retirer le `melodyGroup` hardcodé du volet (remplacé par le slot de card déclaré) —
   la « disparition » actuelle devient sans objet.
6. Étendre : imager (image de référence img2img — même mécanique), puis studio (mêmes ports).
