# WAMA — Format de fichier batch unifié

> Spec du **format batch unique** à balises (ffmpeg-style), commun à toutes les apps.
> Parseur : `wama/common/utils/batch_parsers.py` (`parse_unified_batch`,
> `parse_unified_batch_line`, `is_unified_batch_text`). Voir `WAMA_APP_CONVENTIONS.md §9`.

## Principe

Un fichier batch = **une ligne par item**. Chaque ligne décrit l'item avec des
**balises, dans n'importe quel ordre**. Une URL/un fichier de travail et un prompt
ne sont que des **champs** : chaque app consomme ceux qui la concernent et ignore
les autres. Ajouter un champ ne casse pas les fichiers existants.

```
-i / --input      fichier ou URL de travail (entrée à traiter)
-p / --prompt     texte (génération, TTS, guidage de description…)
-r / --reference  référence (voix de clonage, mélodie, image avatar, image de style…)
-o / --output     nom/chemin de sortie (optionnel ; défaut dérivé de l'entrée/prompt)
--clé valeur      option propre à l'app (voice, speed, model, language, duration…)
-x valeur         option courte → options['x']
```

### ⚠ `-o / --output` : le NOM est honoré, la DESTINATION ne l'est pas encore (mesuré 2026-08-25)

La ligne ci-dessus annonce « nom/**chemin** de sortie ». Le parseur range bien la valeur dans
`output_filename` (`batch_parsers.py:563`), mais **aucune app n'en dérive un dossier** : la sortie
retombe dans le `upload_to` de l'app (`media/<app>/<user>/output/`). Le champ est donc, à ce jour,
un nom — pas une destination. **La doc promettait plus que le code ne fait** ; le noter ici plutôt
que de laisser le prochain le découvrir en le testant.

**Besoin exprimé (Fabien, 2026-08-25), deux cas d'usage qui ne se recouvrent pas :**

| cas | attendu | ce que ça exige |
|---|---|---|
| **À côté de la source** — scanner des dossiers de médias à anonymiser, écrire `<source>_anonymized.<ext>` **dans le dossier d'origine** | destination **relative à l'entrée**, sans écraser l'original | résoudre `-o` par rapport au dossier de `-i`, + un motif de suffixe |
| **Regroupement** — un lot de prompts pour le synthesizer, toutes les voix dans **un dossier dédié** | destination **absolue et commune** au lot | un `-o` de niveau LOT (en-tête de fichier batch), pas seulement par ligne |

### ✅ DÉCISION (Fabien, 2026-08-25) — une COPIE, jamais un déplacement

> Le fichier canonique **reste** dans `media/<app>/<user>/output/`. La destination `-o` reçoit une
> **copie**. C'est la décision, et elle est meilleure que le déplacement que j'avais envisagé
> d'abord — pour une raison qui n'est pas de confort : **elle ne casse aucun invariant.**

`output_video.name`, `safe_delete_file`, la rétention, le miroir de sauvegarde, le tiering et les
previews continuent tous d'opérer sur le fichier canonique, **sans une ligne de changement**. La
copie est une *projection*, jamais une source de vérité.

**Ce que ça règle, point par point :**

| risque du déplacement | ce que la copie en fait |
|---|---|
| sortir de `MEDIA_ROOT` casse rétention/tiering/sauvegarde | ne se pose plus : le canonique n'a pas bougé |
| **previews de card** (question de Fabien) | ne se pose plus : `unified_preview` lit le canonique — **les copies lui sont invisibles**. Avec un déplacement il aurait fallu servir des fichiers hors `MEDIA_ROOT` à travers Django, c'est-à-dire ouvrir une vraie surface de sécurité |
| traversée de chemin | subsiste, mais ne menace plus que la *cible de copie* — le rayon d'action est réduit à une écriture, pas à l'intégrité du modèle média |

**La liste blanche reste nécessaire** — une copie est encore une écriture arbitraire par le
processus serveur. Mais elle **existe déjà** et n'est pas à inventer :
`filemanager.MountedFolder.local_path`, **par utilisateur**, avec sa config SMB. Règle :
*une destination `-o` doit se résoudre sous l'un des `MountedFolder` de l'utilisateur demandeur*
(ou sous son propre `media/<app>/<user>/`).
Deux bénéfices gratuits : ce sont **les mêmes dossiers que l'Explorateur affiche** (l'utilisateur
choisit une destination qu'il voit, aucun concept ni UI en plus), et le cas « à côté de la source »
est automatiquement couvert — un dossier qu'on a scanné pour construire le lot est nécessairement
monté. ⚠ Inventer une seconde notion de « où le serveur a le droit d'écrire » serait la faute :
elle divergerait de celle-ci.

**Quatre règles à acter avant d'implémenter** (non couvertes par la décision, chacune muette si on
l'oublie) :

1. **La copie n'est JAMAIS supprimée automatiquement.** La rétention et la suppression de lot
   n'opèrent que **sous `media/`**. Un fichier déposé dans le dossier de l'utilisateur est *son*
   fichier ; l'effacer de notre propre initiative serait dangereux et surprenant.
2. **Une copie qui échoue ne fait PAS échouer le job.** Partage réseau indisponible, droits
   refusés → le job reste `SUCCESS` avec un avertissement. Sinon un à-coup de montage coûte une
   heure de GPU déjà dépensée.
3. **Relance** : une seconde exécution écrase la copie précédente (destination déclarée = intention
   stable). À défaut, chaque relance sédimenterait des variantes suffixées chez l'utilisateur.
4. Les copies vivant hors `media/`, **`check_media_integrity` ne les voit pas** — c'est cohérent,
   et c'est écrit ici pour que personne ne « corrige » plus tard cette absence.

**Sans `-o`** : rien ne change — le résultat reste dans `media/` et l'utilisateur télécharge la card,
le lot ou la file entière. La destination sert à **redispatcher**, pas à stocker.

- **Guillemets** autour des valeurs contenant des espaces : `-p "upbeat jazz piano"`.
- **Commentaires** : ligne commençant par `#`. Encodage **UTF-8**. Formats acceptés :
  `.txt .md .csv .pdf .docx`.

### Nom du fichier de sortie (`-o` absent)

- **Apps média** (entrée = fichier) : si `-o` absent → la sortie reprend le **nom du
  fichier d'entrée**.
- **Import de plusieurs fichiers de prompt** (1 prompt/fichier, pas un fichier batch) :
  la sortie reprend le **nom du fichier de prompt** (cas identique au précédent).
- **Fichier batch de N prompts sans `-o` par ligne (« Cas 2 »)** : la sortie est
  dérivée du **nom du fichier batch + index** : `poems.csv` → `poems_01.wav`,
  `poems_02.wav`, … (helper commun `apply_indexed_output_names`). Un `-o` explicite
  sur une ligne est toujours respecté. Appliqué à **synthesizer** et **composer** ;
  imager/avatarizer nomment leurs sorties via le worker de génération.

### Exemples

```text
# Transcriber / Describer / Enhancer / Converter / Reader / Anonymizer (apps média)
-i "https://example.com/clip.mp4" -o "resume_1.txt"
-i ./media/photo.jpg --output_format concise --language fr

# Composer (génération) — référence audio ⇒ bascule auto sur un modèle melody
-p "upbeat jazz piano with soft drums" --duration 30 -o "intro.wav"
-p "guitar solo over this melody" -r "theme.wav" -o "solo.wav"

# Synthesizer (TTS) — référence = voix de clonage
-p "Bonjour à tous" --voice ma_voix --speed 1.1 -o "intro.wav"

# Avatarizer standalone — audio en entrée + avatar en référence
-i "discours.wav" -r "avatar.png" -o "avatar_1.mp4"
```

## Variante CSV à en-têtes (« tableur »)

Pour construire un batch **depuis Excel / LibreOffice** sans gérer les balises, on
peut fournir un **CSV dont la 1ʳᵉ ligne nomme les colonnes**. Le résultat est
**strictement le même item normalisé** que le format à balises.

```csv
prompt,voice,speed,output
"Bonjour, tout le monde, ça va ?",fr_female,1.1,intro.wav
"Deuxième ligne",default,1.0,suite.wav
```

- **Virgules dans une cellule** : aucun problème — un tableur met automatiquement
  la cellule entre guillemets (`"Bonjour, ça va ?"`) et le parseur (`csv.DictReader`)
  respecte ces guillemets. Les virgules internes ne cassent donc pas les colonnes.
- **En-têtes reconnus** (insensible casse/accents) → champ canonique :
  - `input` / `file` / `fichier` / `url` / `media` / `path` / `chemin` / `entree` / `source` → **input**
  - `prompt` / `text` / `texte` / `description` / `contenu` → **prompt**
  - `reference` / `ref` / `avatar` / `melody` / `melodie` → **reference**
  - `output` / `sortie` / `name` / `nom` / `filename` → **output**
  - **toute autre colonne** (ex. `voice`, `speed`, `language`, `model`, `steps`, `quality`…)
    → **option** `options[nom_colonne]` (cohérent avec `--clé valeur`).
- ⚠️ `voice`/`voix` sont des **options** (preset), pas la référence : pour une voix de
  **clonage**, utiliser la colonne `reference`.
- Détection : `is_csv_header_batch()` ; parsing : `parse_csv_header_batch()`.
  `is_structured_batch_text()` = CSV à en-têtes **ou** balises ; `parse_unified_batch()`
  et `parse_structured_batch_text()` dispatchent automatiquement.

## Comment sait-on qu'un fichier texte est un LOT ? (règle de décision, 2026-08-22)

C'est LA question qui bloquait, et elle ne se pose que pour le texte : un `.mp4` n'est
jamais un lot. Trois familles d'apps, selon ce qu'un `.txt` déposé peut signifier :

| famille | apps | un `.txt` déposé est |
|---|---|---|
| **A** — sans ambiguïté | anonymizer, enhancer, transcriber, reader, avatarizer | forcément un lot |
| **B** — texte = **contenu** | converter, describer | un document à traiter **ou** un lot |
| **C** — texte = **prompt** | synthesizer, composer, imager | un prompt **ou** un lot de N prompts |

**Règle : on décide par la STRUCTURE, jamais par le sens du texte.** Une ligne est retenue
comme référence si elle est *adressable* — schéma d'URL, extension de fichier en fin de
ligne, ou préfixe de chemin (`/`, `./`, `~/`, `C:\`, UNC). Un fichier n'est une liste que
si **toutes** ses lignes utiles le sont : une seule ligne non adressable suffit à dire
« ce n'est pas une liste », et l'appelant retombe alors sur le traitement en CONTENU.

> **Défaut corrigé le 2026-08-22.** `_parse_media_lines` acceptait TOUTE ligne non vide
> comme un chemin : trois lignes de prose devenaient trois « médias ». Or le front ne
> retombe sur l'upload direct que si le serveur renvoie `count == 0`
> (`batch-import.js:140`) — ce repli ne se déclenchait donc **jamais** pour un fichier
> texte non vide. Conséquence mesurée : déposer un `.txt` sur **converter** ou
> **describer** ouvrait la barre de lot au lieu de créer la card du document à convertir.
> Accessoirement, le `pipe positionnel` rendait 2 items de déchets aux apps média.
> Discriminant : `ligne_est_une_reference()` (`batch_parsers.py`).

Ordre de décision, du plus explicite au plus inféré :
1. **l'intention déclarée** par l'utilisateur (modalité de la card d'entrée) prime ;
2. sinon la **structure** : balises → CSV/à-en-têtes → liste d'adresses ;
3. sinon c'est du **contenu**.

## Le séparateur vertical `|` — sa vraie place

Le pipe est le séparateur **historique** de WAMA (cf. l'en-tête de `batch_parsers.py`).
Il existe sous **deux** formes qu'il ne faut pas confondre :

- **avec en-tête** — `prompt|voice|speed|output` : c'est un **CSV à séparateur `|`**,
  strictement équivalent au CSV à virgules. **Déjà reconnu** par `is_csv_header_batch()`
  (vérifié le 2026-08-22) — la spec ne le disait pas.
- **sans en-tête, positionnel** — `nom|prompt|modèle|durée` : c'est le format **originel**,
  conservé pour la compatibilité des fichiers déjà importés dans le **synthesizer**. Il
  n'est compris que par `parse_pipe_batch()` (composer/synthesizer), et n'est vu ni par
  `is_structured_batch_text()` ni par les apps média.

> **En-tête requis ?** Non, et il ne doit pas le devenir : le positionnel sans en-tête
> reste accepté pour ne pas invalider les fichiers existants. L'en-tête est ce qui rend un
> fichier **auto-descriptif** et donc portable entre apps — à privilégier pour tout
> nouveau fichier, quel que soit le séparateur (`,` `;` `|` tabulation).

## Matrice des champs par application

| App | `-i` input | `-p` prompt | `-r` reference | `-o` output | options usuelles |
|-----|:--:|:--:|:--:|:--:|---|
| anonymizer | **requis** | — | — | opt | (réglages de floutage) |
| converter | **requis** | — | — | opt | `--format`, `--quality` |
| describer | **requis** | opt (guidage) | — | opt | `--output_format`, `--language`, `--max_length` |
| enhancer | **requis** | — | — | opt | `--ai_model`, `--denoise`, `--blend_factor` |
| reader | **requis** | — | — | opt | `--backend` |
| transcriber | **requis** | — | — | opt | `--backend`, `--language`, `--hotwords` |
| synthesizer | — | **requis** (texte) | opt (voix clonage) | opt | `--voice`, `--speed`, `--pitch` |
| composer | — | **requis** (prompt) | opt (mélodie) | opt | `--model`, `--duration` |
| imager | — | **requis** (prompt) | opt (image réf) | opt | `--model` |
| avatarizer (pipeline) | — | **requis** (texte) | **requis** (avatar galerie) | opt | `--voice`, `--language`, `--tts`, `--quality`, `--enhancer`, `--bbox` |
| avatarizer (standalone) | **requis** (audio) | — | **requis** (avatar galerie) | opt | `--quality`, `--bbox` |

**Auto-détection de modèle (composer)** : si `-r` (référence audio) est fourni →
basculer automatiquement sur un modèle qui l'exploite (`musicgen-melody`).

## Rétrocompatibilité

`is_unified_batch_text(text)` détecte le format à balises (1ʳᵉ ligne utile commençant
par une balise). Sinon, on retombe sur les parseurs **legacy** existants :
- liste d'URLs/chemins (1 par ligne) — apps média ;
- pipe positionnel `nom|prompt|modèle|durée` — composer/synthesizer.

Les deux continuent de fonctionner pendant la transition. À terme, le format à
balises devient le format canonique (un CSV à en-têtes pourra être ajouté comme
variante « tableur », produisant le même item normalisé).

## Adoption dans une app (recette)

Dans `batch_create` (ou `batch_preview`) :

```python
from wama.common.utils.batch_parsers import (
    extract_batch_file_text, is_unified_batch_text, parse_unified_batch,
)

text = extract_batch_file_text(tmp_path)
if is_unified_batch_text(text):
    items, warnings = parse_unified_batch(tmp_path)
    # items : [{input, prompt, reference, output, options{}, line_num}, …]
    # → mapper sur le modèle de l'app (valider les champs requis)
else:
    items, warnings = <parseur legacy de l'app>   # liste d'URLs ou pipe positionnel
```

> **État :** ✅ **Câblé partout** (Phase B terminée).
> - **Apps Type A** (anonymizer, converter, describer, enhancer, reader, transcriber) :
>   le câblage est **centralisé** — `parse_media_list_batch()` détecte le format à
>   balises et mappe `-i`→`path` (+ `-o`/`-p`/`--option` transportés). Aucune app
>   à modifier individuellement (règle « zéro duplication »).
> - **imager** : `parse_text_prompts()` balise-aware (`-p`→prompt, `--steps/--cfg/
>   --model/--np`… via `_IMAGER_OPTION_ALIASES`, `-o`→`output_filename`, `-r`→`style_reference`).
> - **synthesizer** : `parse_batch_file()` balise-aware (`-p`→texte, `--voice/--speed`,
>   `-r`→`voice_reference`, `--language`).
> - **composer** : référence + auto-modèle `musicgen-melody` si `-r`.
> - **avatarizer** : `parse_unified_batch` natif (pas de legacy) — `-p`→pipeline,
>   `-i`→standalone, `-r`→avatar galerie (requis), `--voice/--language/--tts/--quality/
>   --enhancer/--bbox` ; group-by-nature par mode (pipeline / standalone).
>
> Le legacy (liste d'URLs / pipe positionnel) reste accepté en parallèle.
> **Variante CSV à en-têtes** : ✅ livrée (détection + parsing centralisés ;
> bénéficie à toutes les apps via `parse_unified_batch` / `parse_media_list_batch`).
