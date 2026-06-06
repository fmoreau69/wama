# WAMA — Architecture UI « card-centric » (décision projet, 2026-06)

> **Décision** : la **card devient l'unité de travail auto-suffisante** ; le **volet
> droit devient un inspecteur contextuel** de la card/du batch sélectionné. Choisi
> face à l'option incrémentale. Ce document est la spec cible + la feuille de route.
> Voir aussi `WAMA_APP_CONVENTIONS.md §8.X` (staging) et `ROADMAP.md`.

## 1. Problème résolu

Aujourd'hui WAMA sépare « quoi traiter » (volet droit : dépôt + prompt + référence +
réglages) de « la file » (cards). Conséquences : **redondance** des paramètres (volet
droit + modale item + modale batch), **ordre contre-intuitif** (régler avant de
déposer), **prolifération des zones de dépôt** (filemanager, volet droit, file,
AI-assistant).

## 2. Principe

- **La card EST l'unité de travail**, et elle est **auto-suffisante**.
- La zone de staging devient une **« card de composition »** (card vide en attente de
  dépôt) où l'on assemble un item.
- Le **volet droit = inspecteur** : reflète la card/le batch sélectionné (source unique
  de vérité, éditable). Rien sélectionné → affiche les **défauts** (= gabarit de la
  card de composition).

## 3. Carte de composition — zones (déclarées par app)

Partiel commun `common/templates/common/_compose_card.html`, piloté par un descripteur
de capacités par app (`COMPOSE_CAPABILITIES`), n'affichant que les zones pertinentes :

| Zone | Rôle | Apps types |
|------|------|-----------|
| **Fichier de travail** (dépôt) | entrée à traiter | transcriber, describer, enhancer, reader, converter, anonymizer, avatarizer(standalone) |
| **Prompt** | génération **ou** consignes de traitement (ex. SAM3) | imager, composer, synthesizer, avatarizer(pipeline), anonymizer(SAM3) |
| **Référence** (dépôt audio/image) | voix clonage, mélodie, image avatar/style | synthesizer, composer, avatarizer, imager |
| **RAG ponctuel** (par card) | contexte d'enrichissement **isolé par card** (pas de contamination croisée) ; aussi depuis la médiathèque ; ré-éditable dans les réglages | describer, transcriber, reader… |

Stockage des dépôts : **temporaire** (statut `DRAFT`, comme le pilote transcriber)
jusqu'à validation.

## 4. Carte des zones de dépôt (anti-prolifération)

Principe : **1 source + 1 destination par app**, + la surface globale.

- **Filemanager (arbre)** = bibliothèque persistante = **source** (on glisse depuis).
- **Card de composition (dans la file)** = **destination** unique par app (fichier de
  travail + référence). → **on retire la zone de dépôt du volet droit**.
- **AI-assistant (accueil)** = surface conversationnelle, concern distinct.

## 5. Volet droit = inspecteur

- Au clic sur une card → ses paramètres s'affichent dans le volet droit (éditables, live).
- Au clic sur un en-tête de batch → paramètres du batch (appliqués à tous).
- Rien sélectionné → défauts (gabarit).
- **Validation découplée** : peu importe où les paramètres ont été réglés (inspecteur,
  modale item, modale batch), `Ajouter`/`Lancer` agit sur l'état courant (`DRAFT→PENDING`).
- Drag d'une card **vers/depuis un batch** pour réorganiser la file.

## 6. Modales

On **conserve les modales item + batch** pour l'instant (déjà en place, 1 bouton).
À terme, la modale = **le même inspecteur en overlay focalisé** (utile petit écran),
**pas un 2ᵉ jeu de champs**. Pas de retrait tant que l'inspecteur live n'est pas validé.

## 6bis. Vision étendue — templates génériques pilotés par descripteur

> **Idée (à converger entre nous avant implémentation — gros chantier)** : les templates
> **file d'attente + volet droit + card + preview** deviennent **génériques**, générés à
> partir d'un **descripteur d'application**. Le fonctionnement des cards est **identique**
> partout ; seules les **spécificités déclarées** changent d'une app à l'autre.
>
> Avantage : créer une nouvelle app = **renseigner son descripteur** → elle suit
> automatiquement le template commun (file, volet, card, preview, import). Prolonge ce
> qu'on a déjà fait pour l'**import batch générique** (`BATCH_FORMAT.md`).

**Descripteur d'application (`APP_SPEC`) — champs envisagés :**

| Champ | Décrit | Exemple transcriber |
|-------|--------|--------------------|
| `import_methods` | méthodes d'entrée acceptées | multi-fichiers + URL simple + fichier batch (urls+options) |
| `compose_zones` | zones de la card de composition (§3) | fichier de travail + RAG de mise en contexte |
| `params` | champs paramètres → **modale + volet droit** (générés depuis les **modèles de l'app**) | backend, langue, hotwords, diarisation, prétraitement, résumé, cohérence… |
| `output_preview` | aperçu de sortie **spécifique en bas de card** (généralisé, comme imager — **remplace le bouton œil**) | « Transcription 77 mots · Diarisation · Résumé 48 mots · Cohérence 88 mots » |
| `actions` | boutons spécifiques éventuels | (ordre standard §6 sinon) |

**Preview de sortie en bas de card** : à **généraliser** (comme imager) — un résumé
compact des sorties produites directement sous la card, plutôt qu'un bouton œil séparé.
Chaque app déclare son gabarit de preview dans `APP_SPEC.output_preview`.

**Statut** : vision validée sur le principe ; **chantier d'uniformisation à cadrer**
ensemble avant d'écrire le générateur de templates. À faire **après** que la version
card-centric soit éprouvée sur transcriber (cf. phases ci-dessous).

## 7. Feuille de route (phases)

1. ✅ **Staging pilote** (transcriber, statut `DRAFT`).
2. **Généraliser le staging** + extraire `common/.../staging.py` + `wama-staging.js`
   (decriber/enhancer/reader/synthesizer/converter/anonymizer/composer/imager/avatarizer).
3. **Card de composition** : partiel commun + descripteur `COMPOSE_CAPABILITIES` par app
   (zones fichier/prompt/référence/RAG). Retrait progressif des entrées du volet droit.
4. **Volet droit = inspecteur live** de la card/batch sélectionné (source unique).
5. **RAG ponctuel par card** (isolé) + intégration médiathèque.
6. **Rationaliser les modales** (overlay = inspecteur focalisé).
7. **Templates génériques pilotés par descripteur** (§6bis) — gros chantier final
   d'uniformisation, à cadrer ensemble. Généralise file/volet/card/preview depuis
   `APP_SPEC`. Inclut la **généralisation de la preview de sortie en bas de card**.

> Chaque phase reste rétro-compatible ; on valide l'UX app par app avant d'étendre.
>
> **Ordre convenu avec l'utilisateur** : aboutir le **staging transcriber** (en cours) →
> appliquer la version **card-centric au transcriber** → **tester** → **généraliser** aux
> autres apps → puis chantier descripteur (§6bis).
