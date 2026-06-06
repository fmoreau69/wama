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
